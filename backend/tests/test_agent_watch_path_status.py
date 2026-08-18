"""
Tests de regresión para C41 — watch_path_status en el modelo Agent, el
consumer de heartbeat y la migración 009 (D36/RN-130).

Cubre (tasks.md sección 12):
  12.2  Idempotencia de la migración 009 y presencia de la columna.
  12.4  El consumer de heartbeat persiste watch_path_status; clave ausente
        no borra el valor previo; valor malformado se ignora con warning y
        el heartbeat se procesa igual (el agente no pasa a offline).
  12.5  GET /agents y GET /agents/{id} (via list_agents/get_agent) exponen
        el mapa; un agente que nunca reportó lo tiene en None.

Sigue el mismo patrón que test_heartbeat_consumer.py (mem_engine SQLite +
patch.object del engine del módulo) y test_event_symlink_metadata.py
(migración contra Postgres real vía app.core.database.engine).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.agents.models import Agent, AgentStatus


@pytest.fixture()
def mem_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def shared_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def agent(mem_engine, shared_secret) -> Agent:
    a = Agent(agent_id="wps-agent", status=AgentStatus.offline, shared_secret_hex=shared_secret.hex())
    with Session(mem_engine) as session:
        session.add(a)
        session.commit()
        session.refresh(a)
    return a


def _make_hb(agent_id: str, secret: bytes, **extra) -> dict:
    from app.core.streams import sign_payload

    payload = {
        "agent_id": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queue_size": 0,
        "queue_pressure": 0.1,
        "ruleset_version": 0,
        "shutdown": False,
        "schema_version": 1,
        **extra,
    }
    payload["signature"] = sign_payload(secret, payload)
    return {"data": json.dumps(payload)}


# ── 12.4 — el consumer persiste watch_path_status ──────────────────────────────


def test_heartbeat_persists_watch_path_status(mem_engine, agent, shared_secret) -> None:
    import app.modules.agents.heartbeat_consumer as hc

    status_map = {"/etc": "writable", "/usr/bin": "read_only_mount"}
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("wps-agent", shared_secret, watch_path_status=status_map))

    with Session(mem_engine) as session:
        a = session.get(Agent, "wps-agent")
    assert a.watch_path_status == status_map
    assert a.status == AgentStatus.online


def test_heartbeat_without_key_does_not_erase_previous_status(mem_engine, agent, shared_secret) -> None:
    """Agente viejo — sin la clave — no borra el último mapa conocido."""
    import app.modules.agents.heartbeat_consumer as hc

    status_map = {"/etc": "permission_denied"}
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("wps-agent", shared_secret, watch_path_status=status_map))
        # Segundo heartbeat sin la clave (agente viejo, o versión sin el campo)
        hc._handle_heartbeat(_make_hb("wps-agent", shared_secret))

    with Session(mem_engine) as session:
        a = session.get(Agent, "wps-agent")
    assert a.watch_path_status == status_map
    assert a.status == AgentStatus.online  # el heartbeat se procesó igual


def test_heartbeat_with_malformed_status_is_ignored(mem_engine, agent, shared_secret) -> None:
    """Un valor que no es mapa de strings se ignora con warning y no rompe el heartbeat."""
    import app.modules.agents.heartbeat_consumer as hc

    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(
            _make_hb("wps-agent", shared_secret, watch_path_status=["not", "a", "mapping"])
        )

    with Session(mem_engine) as session:
        a = session.get(Agent, "wps-agent")
    assert a.watch_path_status is None
    assert a.status == AgentStatus.online
    assert a.last_heartbeat is not None


def test_heartbeat_with_non_string_values_is_ignored(mem_engine, agent, shared_secret) -> None:
    import app.modules.agents.heartbeat_consumer as hc

    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(
            _make_hb("wps-agent", shared_secret, watch_path_status={"/etc": 1})
        )

    with Session(mem_engine) as session:
        a = session.get(Agent, "wps-agent")
    assert a.watch_path_status is None
    assert a.status == AgentStatus.online


# ── 12.5 — list_agents/get_agent exponen el mapa ────────────────────────────────


def test_list_agents_exposes_watch_path_status(mem_engine) -> None:
    from app.modules.agents.service import list_agents

    with Session(mem_engine) as session:
        a = Agent(
            agent_id="wps-list-agent",
            status=AgentStatus.online,
            watch_path_status={"/etc": "writable", "/bin": "missing"},
        )
        session.add(a)
        session.commit()

        result = list_agents(session)

    assert len(result) == 1
    assert result[0].watch_path_status == {"/etc": "writable", "/bin": "missing"}


def test_get_agent_exposes_watch_path_status(mem_engine) -> None:
    from app.modules.agents.service import get_agent

    with Session(mem_engine) as session:
        a = Agent(
            agent_id="wps-detail-agent",
            status=AgentStatus.online,
            watch_path_status={"/usr/sbin": "permission_denied"},
        )
        session.add(a)
        session.commit()

        result = get_agent(session, "wps-detail-agent")

    assert result.watch_path_status == {"/usr/sbin": "permission_denied"}


def test_agent_that_never_reported_has_null_status_map(mem_engine) -> None:
    """Un agente registrado antes de esta change (o que nunca mandó heartbeat) → None, no {}."""
    from app.modules.agents.service import get_agent

    with Session(mem_engine) as session:
        a = Agent(agent_id="wps-never-reported", status=AgentStatus.offline)
        session.add(a)
        session.commit()

        result = get_agent(session, "wps-never-reported")

    assert result.watch_path_status is None


# ── 12.2 — migración 009: idempotencia y presencia de la columna ──────────────


def test_migration_009_is_idempotent() -> None:
    from sqlalchemy import text

    from app.core.database import engine

    migration_path = (
        Path(__file__).resolve().parents[1] / "db" / "migrations" / "009_add_agent_watch_path_status.sql"
    )
    sql = migration_path.read_text()

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
        # Segunda ejecución: no debe lanzar (ADD COLUMN IF NOT EXISTS).
        conn.execute(text(sql))
        conn.commit()


def test_agents_table_has_watch_path_status_column_after_migration() -> None:
    from sqlalchemy import text

    from app.core.database import engine

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'agents' AND column_name = 'watch_path_status'"
            )
        ).all()
    assert {r[0] for r in rows} == {"watch_path_status"}
