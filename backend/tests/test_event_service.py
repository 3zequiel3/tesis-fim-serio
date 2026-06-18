"""
Tests para el service de eventos (Change 11).

Cubre: validate_transition, ingest_event, compact_chain, retention_task.
Usa SQLite in-memory para aislar la DB.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

# Env mínimo para importar app
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from app.modules.agents.models import Agent, AgentStatus
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus
from app.modules.events.service import (
    InvalidTransitionError,
    VALID_TRANSITIONS,
    compact_chain,
    get_pending_event_for_path,
    ingest_event,
    mark_superseded,
    validate_transition,
)


@pytest.fixture()
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_event(session: Session, path: str, status: EventStatus, minutes_ago: int = 0) -> Event:
    created = datetime.utcnow() - timedelta(minutes=minutes_ago)
    e = Event(
        event_id=f"eid-{path}-{status}-{minutes_ago}",
        agent_id="agent-test",
        path=path,
        hash_detected="abc",
        status=status,
        detected_at=created,
        received_at=created,
        created_at=created,
    )
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


# ── validate_transition ────────────────────────────────────────────────────────

def test_validate_valid_pending_to_superseded() -> None:
    validate_transition(EventStatus.pending, EventStatus.superseded)


def test_validate_valid_pending_to_approved() -> None:
    validate_transition(EventStatus.pending, EventStatus.approved)


def test_validate_valid_pending_to_rejected() -> None:
    validate_transition(EventStatus.pending, EventStatus.rejected)


def test_validate_invalid_terminal_to_pending() -> None:
    with pytest.raises(InvalidTransitionError) as exc_info:
        validate_transition(EventStatus.approved, EventStatus.pending)
    assert exc_info.value.from_status == EventStatus.approved
    assert exc_info.value.to_status == EventStatus.pending


def test_validate_invalid_pending_to_alert_only() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(EventStatus.pending, EventStatus.alert_only)


def test_validate_all_terminals_have_no_out_edges() -> None:
    terminals = [EventStatus.approved, EventStatus.rejected, EventStatus.auto_restored,
                 EventStatus.quarantined, EventStatus.alert_only, EventStatus.superseded]
    for s in terminals:
        assert VALID_TRANSITIONS[s] == set()


# ── ingest_event ──────────────────────────────────────────────────────────────

def test_ingest_no_pending_creates_event_without_parent(mem_engine) -> None:
    now = _now()
    payload = {
        "event_id": "uuid-001",
        "agent_id": "agent-test",
        "path": "/etc/passwd",
        "hash_detected": "deadbeef",
    }
    import app.modules.events.service as svc
    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(payload, now, now)

    assert event is not None
    assert event.parent_event_id is None
    assert event.status == EventStatus.pending
    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 1


def test_ingest_with_pending_creates_chain(mem_engine) -> None:
    now = _now()
    with Session(mem_engine) as session:
        old = _make_event(session, "/etc/hosts", EventStatus.pending)
        old_id = old.id

    payload = {
        "event_id": "uuid-002",
        "agent_id": "agent-test",
        "path": "/etc/hosts",
        "hash_detected": "newdeadbeef",
    }
    import app.modules.events.service as svc
    with patch.object(svc, "engine", mem_engine):
        event = ingest_event(payload, now, now)

    assert event is not None
    assert event.parent_event_id == old_id

    with Session(mem_engine) as session:
        old_refreshed = session.exec(select(Event).where(Event.id == old_id)).first()
        assert old_refreshed is not None
        assert old_refreshed.status == EventStatus.superseded


def test_ingest_race_condition_returns_none(mem_engine) -> None:
    """Simula carrera: mark_superseded retorna False → ingest retorna None."""
    now = _now()
    with Session(mem_engine) as session:
        _make_event(session, "/etc/shadow", EventStatus.pending)

    payload = {
        "event_id": "uuid-003",
        "agent_id": "agent-test",
        "path": "/etc/shadow",
        "hash_detected": "h",
    }
    import app.modules.events.service as svc
    with patch.object(svc, "engine", mem_engine), \
         patch("app.modules.events.service.mark_superseded", return_value=False):
        result = ingest_event(payload, now, now)

    assert result is None


# ── compact_chain ──────────────────────────────────────────────────────────────

def test_compact_chain_under_limit_no_delete(mem_engine) -> None:
    with Session(mem_engine) as session:
        for i in range(8):
            _make_event(session, "/var/log/app.log", EventStatus.superseded, minutes_ago=i)
        compact_chain(session, "/var/log/app.log")
        remaining = session.exec(
            select(Event).where(Event.path == "/var/log/app.log")
        ).all()
    assert len(remaining) == 8


def test_compact_chain_at_limit_plus_one_deletes_oldest(mem_engine) -> None:
    with Session(mem_engine) as session:
        for i in range(11):  # 11 superseded → debe quedar 10
            _make_event(session, "/var/www/index.html", EventStatus.superseded, minutes_ago=i)
        compact_chain(session, "/var/www/index.html")
        session.commit()
        remaining = session.exec(
            select(Event).where(Event.path == "/var/www/index.html")
        ).all()
    assert len(remaining) == 10


def test_compact_chain_respects_audit_log_references(mem_engine) -> None:
    with Session(mem_engine) as session:
        # Crear usuario dummy para FK de audit_log
        user = User(username="admin", password_hash="x", role="admin")
        session.add(user)
        session.commit()
        session.refresh(user)

        events = []
        for i in range(11):
            e = _make_event(session, "/etc/cron.d/test", EventStatus.superseded, minutes_ago=i + 1)
            events.append(e)

        # El más antiguo (último de la lista, minutes_ago más alto) es el que se eliminaría normalmente
        oldest = events[-1]  # minutes_ago=11
        # Protegerlo con audit_log
        audit = AuditLog(
            user_id=user.id,
            action="review",
            target_type="event",
            target_id=oldest.id,
        )
        session.add(audit)
        session.commit()

        compact_chain(session, "/etc/cron.d/test")
        session.commit()

        remaining_ids = {e.id for e in session.exec(
            select(Event).where(Event.path == "/etc/cron.d/test")
        ).all()}

    assert oldest.id in remaining_ids
    assert len(remaining_ids) == 10


# ── mark_superseded ────────────────────────────────────────────────────────────

def test_mark_superseded_success(mem_engine) -> None:
    with Session(mem_engine) as session:
        e = _make_event(session, "/tmp/test", EventStatus.pending)
        result = mark_superseded(session, e.id, e.version)
        session.commit()
        refreshed = session.exec(select(Event).where(Event.id == e.id)).first()

    assert result is True
    assert refreshed.status == EventStatus.superseded
    assert refreshed.version == 1


def test_mark_superseded_wrong_version_returns_false(mem_engine) -> None:
    with Session(mem_engine) as session:
        e = _make_event(session, "/tmp/test2", EventStatus.pending)
        result = mark_superseded(session, e.id, version=99)  # versión incorrecta
        session.commit()
        refreshed = session.exec(select(Event).where(Event.id == e.id)).first()

    assert result is False
    assert refreshed.status == EventStatus.pending  # no cambió


# ── get_pending_event_for_path ─────────────────────────────────────────────────

def test_get_pending_returns_most_recent(mem_engine) -> None:
    with Session(mem_engine) as session:
        e1 = _make_event(session, "/app/config.yml", EventStatus.pending, minutes_ago=5)
        e2 = _make_event(session, "/app/config.yml", EventStatus.pending, minutes_ago=1)
        result = get_pending_event_for_path(session, "/app/config.yml")

    assert result is not None
    assert result.id == e2.id  # el más reciente


def test_get_pending_returns_none_when_no_pending(mem_engine) -> None:
    with Session(mem_engine) as session:
        _make_event(session, "/app/db.yml", EventStatus.approved)
        result = get_pending_event_for_path(session, "/app/db.yml")
    assert result is None
