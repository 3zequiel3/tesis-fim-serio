"""
Tests de regresión para C39 — metadato de symlink (is_symlink/symlink_target)
en el modelo Event, EventOut y la migración 005 (D33/RN-127).

Cubre:
  - ingest_event persiste is_symlink/symlink_target desde el payload.
  - Payload de agente viejo (sin las keys) ingiere con defaults false/None.
  - EventOut expone el metadato para eventos de symlink y con defaults para
    archivos regulares.
  - La migración 005 es idempotente (aplicarla dos veces no falla).

Sigue el mismo patrón que test_event_ack_status_field.py (Session real contra
Postgres) y test_event_service.py (SQLite in-memory para ingest_event).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.database import engine
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus
from app.modules.events.router import _get_ack_status_map, _to_event_out
from app.modules.events.service import ingest_event


# ── ingest_event — 8.1 / 8.2 ──────────────────────────────────────────────────

@pytest.fixture()
def mem_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_ingest_event_persists_symlink_metadata(mem_engine) -> None:
    now = _now()
    payload = {
        "event_id": "uuid-symlink-001",
        "agent_id": "agent-test",
        "path": "/etc/evil",
        "hash_detected": "deadbeef",
        "is_symlink": True,
        "symlink_target": "/root/.ssh/authorized_keys",
    }
    import app.modules.events.service as svc
    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(payload, now, now)

    assert event is not None
    assert event.is_symlink is True
    assert event.symlink_target == "/root/.ssh/authorized_keys"


def test_ingest_event_without_symlink_keys_defaults(mem_engine) -> None:
    """Payload de un agente viejo, sin is_symlink/symlink_target: ingiere sin error."""
    now = _now()
    payload = {
        "event_id": "uuid-old-agent-001",
        "agent_id": "agent-test",
        "path": "/etc/passwd",
        "hash_detected": "deadbeef",
    }
    import app.modules.events.service as svc
    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(payload, now, now)

    assert event is not None
    assert event.is_symlink is False
    assert event.symlink_target is None


# ── EventOut — 8.3 ────────────────────────────────────────────────────────────

@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def agent(session: Session) -> Agent:
    a = Agent(agent_id=f"agent-evt-symlink-{uuid.uuid4().hex[:8]}", status=AgentStatus.online)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_event_out_serializes_symlink_metadata(session: Session, agent: Agent) -> None:
    event = Event(
        event_id=f"evt-symlink-{uuid.uuid4().hex[:8]}",
        agent_id=agent.agent_id,
        path="/etc/evil",
        hash_detected="deadbeef",
        status=EventStatus.pending,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        is_symlink=True,
        symlink_target="/root/.ssh/authorized_keys",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)

    assert out.is_symlink is True
    assert out.symlink_target == "/root/.ssh/authorized_keys"


def test_event_out_defaults_for_regular_file(session: Session, agent: Agent) -> None:
    event = Event(
        event_id=f"evt-regular-{uuid.uuid4().hex[:8]}",
        agent_id=agent.agent_id,
        path="/etc/passwd",
        hash_detected="feedface",
        status=EventStatus.pending,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)

    assert out.is_symlink is False
    assert out.symlink_target is None


# ── Migración 005 — 8.4 idempotencia ─────────────────────────────────────────

def test_migration_005_is_idempotent() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1] / "db" / "migrations" / "005_add_event_symlink_metadata.sql"
    )
    sql = migration_path.read_text()

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
        # Segunda ejecución: no debe lanzar (ADD COLUMN IF NOT EXISTS).
        conn.execute(text(sql))
        conn.commit()


def test_events_table_has_symlink_columns_after_migration() -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'events' AND column_name IN ('is_symlink', 'symlink_target')"
            )
        ).all()
    columns = {r[0] for r in rows}
    assert columns == {"is_symlink", "symlink_target"}
