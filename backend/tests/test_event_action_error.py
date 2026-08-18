"""
Tests de regresión para C41 — action_error en el modelo Event, la ingesta y
la migración 008 (D36/RN-130). Compone con action_failed (D35/RN-129, C40)
sin alterarlo.

Cubre (tasks.md sección 12.1 / 12.2 / 12.3):
  - ingest_event persiste action_error tal cual, truncado a 64 caracteres.
  - Un valor desconocido no invalida el evento (tolerancia hacia adelante).
  - Ausente → None (agente viejo, o ruta de éxito donde el agente no
    escribe la clave).
  - action_error no influye en la derivación de status ni en la
    supersesión.
  - EventOut expone action_error en GET /events y GET /events/{id}.
  - La migración 008 es idempotente.

Sigue el mismo patrón que test_event_symlink_metadata.py: SQLite in-memory
para ingest_event, Session real contra Postgres para EventOut/migración.
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


# ── ingest_event ────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_ingest_event_persists_known_action_error(mem_engine) -> None:
    now = _now()
    payload = {
        "event_id": "uuid-action-error-001",
        "agent_id": "agent-test",
        "path": "/usr/bin/su",
        "hash_detected": "deadbeef",
        "action": "auto_restore",
        "action_failed": True,
        "action_error": "read_only_mount",
    }
    import app.modules.events.service as svc

    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(payload, now, now)

    assert event is not None
    assert event.action_failed is True
    assert event.action_error == "read_only_mount"
    assert event.status == EventStatus.pending


def test_ingest_event_stores_unknown_action_error_without_rejecting(mem_engine) -> None:
    """Un agente más nuevo que el backend manda una causa que este no reconoce.

    Debe persistirse tal cual — nunca invalidar el evento (D-8)."""
    now = _now()
    payload = {
        "event_id": "uuid-action-error-002",
        "agent_id": "agent-test",
        "path": "/etc/shadow",
        "hash_detected": "deadbeef",
        "action": "quarantine",
        "action_failed": True,
        "action_error": "some_future_cause_v2",
    }
    import app.modules.events.service as svc

    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(payload, now, now)

    assert event is not None
    assert event.action_error == "some_future_cause_v2"
    assert event.status == EventStatus.pending


def test_ingest_event_truncates_action_error_to_64_chars(mem_engine) -> None:
    now = _now()
    long_cause = "x" * 200
    payload = {
        "event_id": "uuid-action-error-003",
        "agent_id": "agent-test",
        "path": "/etc/passwd",
        "hash_detected": "deadbeef",
        "action": "auto_restore",
        "action_failed": True,
        "action_error": long_cause,
    }
    import app.modules.events.service as svc

    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(payload, now, now)

    assert event is not None
    assert event.action_error == long_cause[:64]
    assert len(event.action_error) == 64


def test_ingest_event_without_action_error_key_is_none(mem_engine) -> None:
    """Payload de un agente viejo, o ruta de éxito: sin la clave → None."""
    now = _now()
    payload = {
        "event_id": "uuid-action-error-004",
        "agent_id": "agent-test",
        "path": "/etc/hosts",
        "hash_detected": "deadbeef",
        "action": "auto_restore",
        "action_failed": False,
    }
    import app.modules.events.service as svc

    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(payload, now, now)

    assert event is not None
    assert event.action_error is None
    assert event.status == EventStatus.auto_restored


def test_action_error_does_not_affect_status_derivation(mem_engine) -> None:
    """Dos eventos idénticos salvo action_error deben derivar el mismo status."""
    now = _now()
    base = {
        "agent_id": "agent-test",
        "path": "/etc/derivation-check",
        "hash_detected": "deadbeef",
        "action": "auto_restore",
        "action_failed": True,
    }
    import app.modules.events.service as svc

    with patch.object(svc, "engine", mem_engine):
        e1 = ingest_event({**base, "event_id": "uuid-deriv-1"}, now, now)
        e2 = ingest_event(
            {**base, "event_id": "uuid-deriv-2", "action_error": "permission_denied"}, now, now
        )

    assert e1 is not None and e2 is not None
    assert e1.status == e2.status == EventStatus.pending


# ── EventOut ────────────────────────────────────────────────────────────────


@pytest.fixture()
def session():
    with Session(engine) as s:
        yield s
        s.rollback()


@pytest.fixture()
def agent(session: Session) -> Agent:
    a = Agent(agent_id=f"agent-evt-action-error-{uuid.uuid4().hex[:8]}", status=AgentStatus.online)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_event_out_serializes_action_error(session: Session, agent: Agent) -> None:
    event = Event(
        event_id=f"evt-action-error-{uuid.uuid4().hex[:8]}",
        agent_id=agent.agent_id,
        path="/usr/bin/sudo",
        hash_detected="deadbeef",
        status=EventStatus.pending,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
        action_failed=True,
        action_error="permission_denied",
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)

    assert out.action_error == "permission_denied"
    assert out.action_failed is True


def test_event_out_defaults_action_error_none(session: Session, agent: Agent) -> None:
    event = Event(
        event_id=f"evt-action-error-none-{uuid.uuid4().hex[:8]}",
        agent_id=agent.agent_id,
        path="/etc/ordinary",
        hash_detected="feedface",
        status=EventStatus.auto_restored,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    ack_map = _get_ack_status_map(session, [event.id])
    out = _to_event_out(event, ack_map)

    assert out.action_error is None


# ── Migración 008 — idempotencia ────────────────────────────────────────────


def test_migration_008_is_idempotent() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1] / "db" / "migrations" / "008_add_event_action_error.sql"
    )
    sql = migration_path.read_text()

    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
        # Segunda ejecución: no debe lanzar (ADD COLUMN IF NOT EXISTS).
        conn.execute(text(sql))
        conn.commit()


def test_events_table_has_action_error_column_after_migration() -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'events' AND column_name = 'action_error'"
            )
        ).all()
    assert {r[0] for r in rows} == {"action_error"}
