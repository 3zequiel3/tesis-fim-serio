"""Tests del heartbeat consumer (Change 08, task 9.5).

Cubre: online/draining por heartbeat, offline por barrido a 30 s.

Los tests se saltan si psycopg/libpq no está disponible.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
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
    import os
    return os.urandom(32)


@pytest.fixture()
def agent(mem_engine, shared_secret) -> Agent:
    a = Agent(agent_id="hb-agent", status=AgentStatus.offline, shared_secret_hex=shared_secret.hex())
    with Session(mem_engine) as session:
        session.add(a)
        session.commit()
        session.refresh(a)
    return a


def _make_hb(
    agent_id: str,
    secret: bytes,
    shutdown: bool = False,
    queue_pressure: float = 0.1,
    discarded_events: object = None,
) -> dict:
    from app.core.streams import sign_payload
    payload = {
        "agent_id": agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queue_size": 0,
        "queue_pressure": queue_pressure,
        "ruleset_version": 0,
        "shutdown": shutdown,
        "schema_version": 1,
    }
    if discarded_events is not None:
        payload["discarded_events"] = discarded_events
    payload["signature"] = sign_payload(secret, payload)
    return {"data": json.dumps(payload)}


# ── Heartbeat marca online ────────────────────────────────────────────────────

def test_heartbeat_marks_online(mem_engine, agent, shared_secret) -> None:
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, shutdown=False, queue_pressure=0.4))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.online
    assert a.queue_pressure == pytest.approx(0.4)
    assert a.last_heartbeat is not None


# ── Heartbeat con shutdown=true → draining ────────────────────────────────────

def test_heartbeat_shutdown_marks_draining(mem_engine, agent, shared_secret) -> None:
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, shutdown=True))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.draining


# ── Barrido a 30 s marca offline ──────────────────────────────────────────────

def test_sweep_marks_offline_after_30s(mem_engine, agent) -> None:
    # Poner el agente online con last_heartbeat en el pasado
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.online
        a.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=35)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._sweep_offline()

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.offline


def test_sweep_does_not_mark_offline_if_recent(mem_engine, agent) -> None:
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
        a.status = AgentStatus.online
        a.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=10)  # reciente
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._sweep_offline()

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.status == AgentStatus.online


# ── 14.13 discarded_events (D37/RN-131) ───────────────────────────────────────


def test_discarded_events_persisted(mem_engine, agent, shared_secret) -> None:
    """Heartbeat con discarded_events=3 → se persiste en Agent.discarded_events."""
    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, discarded_events=3))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.discarded_events == 3


def test_discarded_events_absent_does_not_reset(mem_engine, agent, shared_secret) -> None:
    """Un heartbeat sin la clave NO pisa el valor guardado (tolerancia hacia adelante)."""
    import app.modules.agents.heartbeat_consumer as hc

    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, discarded_events=3))
        # Segundo heartbeat, agente sin actualizar a D37: sin la clave.
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.discarded_events == 3


def test_discarded_events_non_numeric_ignored(mem_engine, agent, shared_secret) -> None:
    """Un valor no numérico se ignora sin romper el resto del heartbeat."""
    import app.modules.agents.heartbeat_consumer as hc

    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(_make_hb("hb-agent", shared_secret, discarded_events="not-a-number"))

    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    # El heartbeat se procesó igual (status/last_heartbeat avanzaron) pese al valor inválido.
    assert a.status == AgentStatus.online
    assert a.last_heartbeat is not None
    assert a.discarded_events is None


def test_discarded_events_never_reported_reads_as_null(mem_engine, agent) -> None:
    """Un agente que nunca envió discarded_events expone None, no 0."""
    with Session(mem_engine) as session:
        a = session.get(Agent, "hb-agent")
    assert a.discarded_events is None
