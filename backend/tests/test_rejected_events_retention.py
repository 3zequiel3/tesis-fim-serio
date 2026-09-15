"""
Tests de Change 54 (backend-privacy-hardening) — retención de
rejected_events_audit (D65/RN-159), audit_log sin purga (W18/RN-94), y la
migración idempotente del índice sobre received_at.

Usa SQLite in-memory + asyncio, mismo patrón que test_retention_task.py
(parchea asyncio.sleep para correr N iteraciones sin esperar la hora real).
Salta si psycopg/libpq no está disponible (patrón C08+ del resto de la suite).
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.events.models import RejectedEventAudit, RejectionReason
from app.modules.events.service import purge_rejected_events_audit


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _make_rejected(session: Session, *, days_old: int, agent_id: str = "agent-x") -> RejectedEventAudit:
    received_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    row = RejectedEventAudit(
        event_id=f"evt-{agent_id}-{days_old}-{id(session)}",
        agent_id=agent_id,
        reason=RejectionReason.invalid_signature,
        received_at=received_at,
        payload_dump="{}",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _make_user(session: Session, username: str = "retention_admin") -> User:
    user = User(username=username, email=f"{username}@fim.local", password_hash="x", role="admin")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ── 5.8: purge_rejected_events_audit ──────────────────────────────────────────


def test_row_older_than_period_is_deleted(mem_engine):
    with Session(mem_engine) as session:
        old = _make_rejected(session, days_old=91)
        old_id = old.id

    deleted = purge_rejected_events_audit(
        lambda: Session(mem_engine), datetime.now(timezone.utc), days=90
    )

    assert deleted == 1
    with Session(mem_engine) as session:
        assert session.get(RejectedEventAudit, old_id) is None


def test_recent_row_is_preserved(mem_engine):
    with Session(mem_engine) as session:
        recent = _make_rejected(session, days_old=89)
        recent_id = recent.id

    deleted = purge_rejected_events_audit(
        lambda: Session(mem_engine), datetime.now(timezone.utc), days=90
    )

    assert deleted == 0
    with Session(mem_engine) as session:
        assert session.get(RejectedEventAudit, recent_id) is not None


def test_configurable_period_7_days(mem_engine):
    with Session(mem_engine) as session:
        old = _make_rejected(session, days_old=8)
        old_id = old.id
        recent = _make_rejected(session, days_old=6)
        recent_id = recent.id

    deleted = purge_rejected_events_audit(
        lambda: Session(mem_engine), datetime.now(timezone.utc), days=7
    )

    assert deleted == 1
    with Session(mem_engine) as session:
        assert session.get(RejectedEventAudit, old_id) is None
        assert session.get(RejectedEventAudit, recent_id) is not None


def test_batched_deletion_2500_rows_in_three_batches(mem_engine):
    with Session(mem_engine) as session:
        for i in range(2500):
            _make_rejected(session, days_old=100 + i % 5, agent_id=f"agent-{i}")

    call_count = 0

    def counting_session_factory():
        nonlocal call_count
        call_count += 1
        return Session(mem_engine)

    deleted = purge_rejected_events_audit(
        counting_session_factory, datetime.now(timezone.utc), days=90, batch_size=1000
    )

    assert deleted == 2500
    assert call_count == 3, "2500 filas / batch_size=1000 ⇒ 3 lotes (1000, 1000, 500)"

    with Session(mem_engine) as session:
        remaining = session.exec(select(RejectedEventAudit)).all()
    assert remaining == []


def test_audit_log_row_count_unchanged(mem_engine):
    with Session(mem_engine) as session:
        user = _make_user(session)
        old_audit = AuditLog(
            user_id=user.id,
            action="review",
            target_type="event",
            target_id=1,
            created_at=datetime.now(timezone.utc) - timedelta(days=400),
        )
        session.add(old_audit)
        session.commit()
        _make_rejected(session, days_old=91)
        _make_rejected(session, days_old=10)

    with Session(mem_engine) as session:
        audit_count_before = len(session.exec(select(AuditLog)).all())

    purge_rejected_events_audit(lambda: Session(mem_engine), datetime.now(timezone.utc), days=90)

    with Session(mem_engine) as session:
        audit_count_after = len(session.exec(select(AuditLog)).all())
        rejected_remaining = session.exec(select(RejectedEventAudit)).all()

    assert audit_count_after == audit_count_before == 1
    assert len(rejected_remaining) == 1, "solo la fila de 10 días debe sobrevivir"


def test_invalid_retention_days_zero_raises_validation_error():
    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(rejected_events_retention_days=0)


# ── Tarea periódica: error transitorio no mata la tarea ───────────────────────


async def _run_rejected_retention_iterations(iterations: int) -> None:
    """Corre rejected_events_retention_task() N iteraciones, parcheando
    asyncio.sleep para no esperar la hora real (mismo patrón que
    test_retention_task.py::_run_retention_once)."""
    import app.modules.events.service as svc

    call_count = 0

    async def sleep_n(seconds: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count > iterations:
            raise asyncio.CancelledError()

    with patch("app.modules.events.service.asyncio.sleep", side_effect=sleep_n):
        try:
            await svc.rejected_events_retention_task()
        except asyncio.CancelledError:
            pass


def test_db_error_during_run_does_not_kill_task():
    import app.modules.events.service as svc

    with patch.object(
        svc, "purge_rejected_events_audit", side_effect=[RuntimeError("db down"), 0]
    ), patch.object(svc, "log") as mock_log:
        asyncio.run(_run_rejected_retention_iterations(iterations=2))

    mock_log.error.assert_called_once()
    assert mock_log.error.call_args[0][0] == "service.rejected_retention_error"
    # info solo se llama si deleted > 0 — acá la segunda corrida borra 0, no llama info.
    mock_log.info.assert_not_called()


def test_successful_run_logs_deleted_count_only_when_positive():
    import app.modules.events.service as svc

    with patch.object(svc, "purge_rejected_events_audit", side_effect=[5]), patch.object(
        svc, "log"
    ) as mock_log:
        asyncio.run(_run_rejected_retention_iterations(iterations=1))

    mock_log.info.assert_called_once_with("service.rejected_retention_run", deleted=5)
    mock_log.error.assert_not_called()


# ── 5.8b: migración 017 — idempotencia contra Postgres real ───────────────────


def test_migration_017_is_idempotent_and_index_exists_once():
    from app.core.database import engine
    import sqlalchemy

    migration_path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "db"
        / "migrations"
        / "017_add_rejected_events_audit_received_at_index.sql"
    )
    sql = migration_path.read_text()

    with engine.connect() as conn:
        conn.execute(sqlalchemy.text(sql))
        conn.commit()
        # Segunda ejecución: no debe fallar (CREATE INDEX IF NOT EXISTS).
        conn.execute(sqlalchemy.text(sql))
        conn.commit()

        rows = conn.execute(
            sqlalchemy.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'rejected_events_audit' "
                "AND indexname = 'ix_rejected_events_audit_received_at'"
            )
        ).all()

    assert len(rows) == 1


# ── 5.9: lifespan crea y cancela la tarea de retención de rechazos ────────────


@pytest.mark.asyncio
async def test_lifespan_creates_and_cancels_rejected_retention_task(monkeypatch):
    import app.main as main_module

    started = asyncio.Event()
    task_ref: dict[str, asyncio.Task] = {}

    async def fake_rejected_retention_forever():
        task_ref["task"] = asyncio.current_task()
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    async def fake_noop_forever(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    class _FakeAsyncValkey:
        async def aclose(self) -> None:
            return None

    class _FakeServer:
        async def serve(self) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise

    # Evitar todo lo pesado del lifespan real (Valkey, CA, mTLS, DB, consumers)
    # — mismo criterio que test_auth_cookie_console_mode.py: no levantar el
    # lifespan completo solo para observar el ciclo de vida de una tarea.
    monkeypatch.setattr(main_module, "init_valkey", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "init_async_valkey", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "ensure_ca", lambda *a, **k: None)
    monkeypatch.setattr(main_module.SQLModel.metadata, "create_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "seed_admin", lambda: None)
    monkeypatch.setattr(main_module, "start_mtls_server", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "start_bootstrap_server", lambda *a, **k: None)
    monkeypatch.setattr(
        main_module, "build_async_valkey_client", lambda *a, **k: _FakeAsyncValkey()
    )
    monkeypatch.setattr(main_module, "close_async_valkey", AsyncMock())
    monkeypatch.setattr(main_module, "close_valkey", lambda: None)
    monkeypatch.setattr(main_module, "run_consumer", fake_noop_forever)
    monkeypatch.setattr(main_module, "run_heartbeat_consumer", fake_noop_forever)
    monkeypatch.setattr(main_module, "run_command_ack_consumer", fake_noop_forever)
    monkeypatch.setattr(main_module, "retention_task", lambda: fake_noop_forever())
    monkeypatch.setattr(main_module, "outbox_publisher_task", lambda: fake_noop_forever())
    monkeypatch.setattr(main_module, "recover_pending_notifications", lambda: fake_noop_forever())
    monkeypatch.setattr(
        main_module, "rejected_events_retention_task", fake_rejected_retention_forever
    )

    async with main_module.lifespan(main_module.app):
        await asyncio.wait_for(started.wait(), timeout=2)
        task = task_ref["task"]
        assert not task.done(), "la tarea de retención de rechazos debe seguir corriendo tras el startup"

    # Tras salir del context manager (shutdown), la tarea quedó cancelada.
    await asyncio.sleep(0)
    assert task.cancelled() or task.done()
