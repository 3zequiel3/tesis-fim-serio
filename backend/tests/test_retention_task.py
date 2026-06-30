"""
Tests para retention_task (Change 11).

Usa SQLite in-memory + asyncio para testear la tarea de retención sin
esperar la hora real — parcheamos asyncio.sleep para ejecutar solo una iteración.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus


@pytest.fixture()
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _old_event(session: Session, path: str, status: EventStatus, days_old: int = 31) -> Event:
    created = datetime.utcnow() - timedelta(days=days_old)
    e = Event(
        event_id=f"eid-{path}-{days_old}",
        agent_id="agent-x",
        path=path,
        hash_detected="h",
        status=status,
        detected_at=created,
        received_at=created,
        created_at=created,
    )
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


async def _run_retention_once(mem_engine) -> None:
    """Ejecuta una iteración de retention_task parcheando asyncio.sleep."""
    import app.modules.events.service as svc

    call_count = 0

    async def sleep_once(seconds: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise asyncio.CancelledError()

    with patch.object(svc, "engine", mem_engine), \
         patch("app.modules.events.service.asyncio.sleep", side_effect=sleep_once):
        try:
            await svc.retention_task()
        except asyncio.CancelledError:
            pass


def test_retention_deletes_old_terminal(mem_engine) -> None:
    with Session(mem_engine) as session:
        e = _old_event(session, "/var/tmp/old.log", EventStatus.approved, days_old=31)
        eid = e.id

    asyncio.run(_run_retention_once(mem_engine))

    with Session(mem_engine) as session:
        result = session.exec(select(Event).where(Event.id == eid)).first()
    assert result is None


def test_retention_preserves_referenced_in_audit_log(mem_engine) -> None:
    with Session(mem_engine) as session:
        user = User(username="admin2", password_hash="x", role="admin")
        session.add(user)
        session.commit()
        session.refresh(user)

        e = _old_event(session, "/etc/cron.d/old", EventStatus.rejected, days_old=31)
        audit = AuditLog(
            user_id=user.id,
            action="review",
            target_type="event",
            target_id=e.id,
        )
        session.add(audit)
        session.commit()
        eid = e.id

    asyncio.run(_run_retention_once(mem_engine))

    with Session(mem_engine) as session:
        result = session.exec(select(Event).where(Event.id == eid)).first()
    assert result is not None


def test_retention_preserves_recent_terminal(mem_engine) -> None:
    with Session(mem_engine) as session:
        e = _old_event(session, "/tmp/recent.log", EventStatus.approved, days_old=10)
        eid = e.id

    asyncio.run(_run_retention_once(mem_engine))

    with Session(mem_engine) as session:
        result = session.exec(select(Event).where(Event.id == eid)).first()
    assert result is not None


def test_retention_does_not_delete_pending(mem_engine) -> None:
    with Session(mem_engine) as session:
        e = _old_event(session, "/etc/old_pending", EventStatus.pending, days_old=31)
        eid = e.id

    asyncio.run(_run_retention_once(mem_engine))

    with Session(mem_engine) as session:
        result = session.exec(select(Event).where(Event.id == eid)).first()
    assert result is not None
