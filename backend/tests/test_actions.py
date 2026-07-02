"""
Tests del módulo actions (C13 — approve/reject).

Cubre:
  12.1  test_approve_success
  12.2  test_approve_conflict
  12.3  test_approve_absent_no_confirm
  12.4  test_approve_absent_confirmed
  12.5  test_reject_restore
  12.6  test_reject_quarantine
  12.7  test_reject_absent_baseline_noop
  12.8  test_bulk_approve_partial
  12.9  test_bulk_reject_partial
  12.10 test_baseline_update_hmac_valid
  12.11 test_no_get_file_hash_published
  12.12 test_audit_log_on_approve
  12.13 test_audit_log_on_reject

Usa SQLite in-memory. Salta si psycopg no está disponible (Windows sin PostgreSQL).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.core.streams import verify_payload
from app.modules.agents.models import Agent, AgentStatus, BaselineEntry, BaselineStatus
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import RulesetVersion
from app.modules.actions.service import (
    AbsentConfirmationRequired,
    ConflictError,
    _approve_single,
    _reject_single,
    approve_bulk,
    reject_bulk,
)
from app.modules.actions.schemas import RejectAction


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session(mem_engine):
    with Session(mem_engine) as s:
        yield s


@pytest.fixture()
def mock_valkey() -> MagicMock:
    client = MagicMock()
    client.xadd = MagicMock()
    return client


@pytest.fixture()
def admin_user(session) -> User:
    user = User(
        id=1,
        username="admin",
        email="admin@fim.local",
        password_hash="hashed",
        role="admin",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture()
def agent_with_secret(session) -> tuple[Agent, bytes]:
    secret = os.urandom(32)
    agent = Agent(
        agent_id="agent-001",
        status=AgentStatus.online,
        shared_secret_hex=secret.hex(),
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent, secret


def _make_pending_event(
    session: Session,
    agent_id: str = "agent-001",
    path: str = "/etc/passwd",
    hash_detected: str = "abc123def456",
    version: int = 0,
) -> Event:
    event = Event(
        event_id=f"evt-{hash_detected[:6]}-{id(session)}",
        agent_id=agent_id,
        path=path,
        hash_detected=hash_detected,
        status=EventStatus.pending,
        version=version,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


# ── 12.1 test_approve_success ─────────────────────────────────────────────────


def test_approve_success(session, mock_valkey, admin_user, agent_with_secret):
    """Evento pending aprobado: status→approved, baseline_entries upserted, baseline_update publicado."""
    agent, secret = agent_with_secret
    event = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="deadbeef1234")

    result = _approve_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event.id,
        version=0,
        confirm_absent=False,
        user_id=admin_user.id,
    )

    # Evento aprobado
    assert result.status == EventStatus.approved
    assert result.resolved_by == admin_user.id
    assert result.resolved_at is not None

    # baseline_entries upserted
    entry = session.exec(
        select(BaselineEntry).where(
            BaselineEntry.path == event.path,
            BaselineEntry.agent_id == agent.agent_id,
        )
    ).first()
    assert entry is not None
    assert entry.status == BaselineStatus.present
    assert entry.hash == "deadbeef1234"

    # baseline_update publicado
    mock_valkey.xadd.assert_called_once()
    call_args = mock_valkey.xadd.call_args
    payload = json.loads(call_args[0][1]["data"])
    assert payload["type"] == "baseline_update"
    assert payload["target_agent_id"] == agent.agent_id
    assert payload["hash"] == "deadbeef1234"
    assert payload["baseline_status"] == "present"


# ── 12.2 test_approve_conflict ────────────────────────────────────────────────


def test_approve_conflict(session, mock_valkey, admin_user, agent_with_secret):
    """Versión incorrecta → ConflictError (HTTP 409)."""
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent_id=agent.agent_id, version=0)

    with pytest.raises(ConflictError):
        _approve_single(
            db=session,
            valkey_client=mock_valkey,
            event_id=event.id,
            version=99,  # versión incorrecta
            confirm_absent=False,
            user_id=admin_user.id,
        )

    # Estado del evento sin cambios
    session.refresh(event)
    assert event.status == EventStatus.pending
    mock_valkey.xadd.assert_not_called()


# ── 12.3 test_approve_absent_no_confirm ───────────────────────────────────────


def test_approve_absent_no_confirm(session, mock_valkey, admin_user, agent_with_secret):
    """hash vacío (ausente) sin confirm_absent → AbsentConfirmationRequired (HTTP 422)."""
    agent, _ = agent_with_secret
    event = _make_pending_event(
        session, agent_id=agent.agent_id, hash_detected=""  # vacío = ausente
    )

    with pytest.raises(AbsentConfirmationRequired):
        _approve_single(
            db=session,
            valkey_client=mock_valkey,
            event_id=event.id,
            version=0,
            confirm_absent=False,
            user_id=admin_user.id,
        )

    session.refresh(event)
    assert event.status == EventStatus.pending
    mock_valkey.xadd.assert_not_called()


# ── 12.4 test_approve_absent_confirmed ────────────────────────────────────────


def test_approve_absent_confirmed(session, mock_valkey, admin_user, agent_with_secret):
    """hash vacío con confirm_absent=True → 200, baseline_entries con status='absent'."""
    agent, secret = agent_with_secret
    event = _make_pending_event(
        session, agent_id=agent.agent_id, hash_detected=""
    )

    result = _approve_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event.id,
        version=0,
        confirm_absent=True,
        user_id=admin_user.id,
    )

    assert result.status == EventStatus.approved

    entry = session.exec(
        select(BaselineEntry).where(
            BaselineEntry.path == event.path,
            BaselineEntry.agent_id == agent.agent_id,
        )
    ).first()
    assert entry is not None
    assert entry.status == BaselineStatus.absent
    assert entry.hash is None

    # baseline_update publicado con baseline_status=absent y hash=null
    mock_valkey.xadd.assert_called_once()
    payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert payload["baseline_status"] == "absent"
    assert payload["hash"] is None


# ── 12.5 test_reject_restore ──────────────────────────────────────────────────


def test_reject_restore(session, mock_valkey, admin_user, agent_with_secret):
    """Evento pending rechazado con action=restore: restore_file publicado, baseline no modificado."""
    agent, secret = agent_with_secret
    event = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="aaa111")

    result, baseline_absent = _reject_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event.id,
        version=0,
        action=RejectAction.restore,
        user_id=admin_user.id,
    )

    assert result.status == EventStatus.rejected
    assert baseline_absent is False

    # restore_file publicado
    mock_valkey.xadd.assert_called_once()
    payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert payload["type"] == "restore_file"
    assert payload["target_agent_id"] == agent.agent_id

    # baseline_entries NO modificada (no existe)
    entry = session.exec(
        select(BaselineEntry).where(
            BaselineEntry.path == event.path,
            BaselineEntry.agent_id == agent.agent_id,
        )
    ).first()
    assert entry is None


# ── 12.6 test_reject_quarantine ───────────────────────────────────────────────


def test_reject_quarantine(session, mock_valkey, admin_user, agent_with_secret):
    """Evento pending rechazado con action=quarantine: quarantine_file publicado."""
    agent, secret = agent_with_secret
    event = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="bbb222")

    result, baseline_absent = _reject_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event.id,
        version=0,
        action=RejectAction.quarantine,
        user_id=admin_user.id,
    )

    assert result.status == EventStatus.rejected
    assert baseline_absent is False

    mock_valkey.xadd.assert_called_once()
    payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert payload["type"] == "quarantine_file"


# ── 12.7 test_reject_absent_baseline_noop ─────────────────────────────────────


def test_reject_absent_baseline_noop(session, mock_valkey, admin_user, agent_with_secret):
    """Baseline absent → reject OK, sin comando publicado, baseline_absent=True (M8)."""
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="ccc333")

    # Crear baseline_entry con status=absent
    entry = BaselineEntry(
        path=event.path,
        agent_id=agent.agent_id,
        hash=None,
        status=BaselineStatus.absent,
        last_updated=datetime.now(timezone.utc),
        ruleset_version=1,
    )
    session.add(entry)
    session.commit()

    result, baseline_absent = _reject_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event.id,
        version=0,
        action=RejectAction.restore,
        user_id=admin_user.id,
    )

    assert result.status == EventStatus.rejected
    # Sin comando publicado (no-op)
    mock_valkey.xadd.assert_not_called()
    # M8: el flag baseline_absent hace observable el no-op sin cambiar el comportamiento.
    assert baseline_absent is True


# ── 12.8 test_bulk_approve_partial ────────────────────────────────────────────


def test_bulk_approve_partial(session, mock_valkey, admin_user, agent_with_secret):
    """3 ítems, 1 con conflicto → succeeded 2, failed 1."""
    agent, _ = agent_with_secret
    e1 = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="111aaa", path="/etc/a")
    e2 = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="222bbb", path="/etc/b")
    e3 = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="333ccc", path="/etc/c")

    items = [
        {"event_id": e1.id, "version": 0, "confirm_absent": False},
        {"event_id": e2.id, "version": 99, "confirm_absent": False},  # conflicto
        {"event_id": e3.id, "version": 0, "confirm_absent": False},
    ]

    result = approve_bulk(session, mock_valkey, items, admin_user.id)

    assert len(result["succeeded"]) == 2
    assert len(result["failed"]) == 1
    assert result["failed"][0]["event_id"] == e2.id
    assert result["failed"][0]["reason"] == "conflict"


# ── 12.9 test_bulk_reject_partial ─────────────────────────────────────────────


def test_bulk_reject_partial(session, mock_valkey, admin_user, agent_with_secret):
    """2 ítems, 1 con conflicto → succeeded 1, failed 1."""
    agent, _ = agent_with_secret
    e1 = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="444ddd", path="/etc/d")
    e2 = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="555eee", path="/etc/e")

    items = [
        {"event_id": e1.id, "version": 0, "action": "restore"},
        {"event_id": e2.id, "version": 99, "action": "quarantine"},  # conflicto
    ]

    result = reject_bulk(session, mock_valkey, items, admin_user.id)

    assert len(result["succeeded"]) == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["event_id"] == e2.id
    assert result["failed"][0]["reason"] == "conflict"
    # M8: baseline_absent mapea cada evento exitoso; e1 tiene baseline presente.
    assert result["baseline_absent"] == {e1.id: False}


# ── 12.10 test_baseline_update_hmac_valid ────────────────────────────────────


def test_baseline_update_hmac_valid(session, mock_valkey, admin_user, agent_with_secret):
    """El payload del comando baseline_update tiene firma HMAC verificable con shared_secret del agente."""
    agent, secret = agent_with_secret
    event = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="ff00ff")

    _approve_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event.id,
        version=0,
        confirm_absent=False,
        user_id=admin_user.id,
    )

    payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert verify_payload(secret, payload), "HMAC signature should be valid"


# ── 12.11 test_no_get_file_hash_published ────────────────────────────────────


def test_no_get_file_hash_published(session, mock_valkey, admin_user, agent_with_secret):
    """Ningún flujo de approve/reject publica get_file_hash (D2)."""
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="cafebabe")

    # Aprobar
    _approve_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event.id,
        version=0,
        confirm_absent=False,
        user_id=admin_user.id,
    )

    # Rechazar otro evento
    event2 = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="abcdef12", path="/etc/other")
    _reject_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event2.id,
        version=0,
        action=RejectAction.restore,
        user_id=admin_user.id,
    )

    # Verificar que ningún mensaje publicado es get_file_hash
    for call in mock_valkey.xadd.call_args_list:
        payload = json.loads(call[0][1]["data"])
        assert payload.get("type") != "get_file_hash"


# ── 12.12 test_audit_log_on_approve ──────────────────────────────────────────


def test_audit_log_on_approve(session, mock_valkey, admin_user, agent_with_secret):
    """Fila en audit_log con action='approve' tras aprobar evento."""
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="112233")

    _approve_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event.id,
        version=0,
        confirm_absent=False,
        user_id=admin_user.id,
    )

    logs = session.exec(
        select(AuditLog).where(
            AuditLog.action == "approve",
            AuditLog.target_id == event.id,
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].user_id == admin_user.id


# ── 12.13 test_audit_log_on_reject ───────────────────────────────────────────


def test_audit_log_on_reject(session, mock_valkey, admin_user, agent_with_secret):
    """Fila en audit_log con action='reject' y details.action tras rechazar evento."""
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent_id=agent.agent_id, hash_detected="445566")

    _reject_single(
        db=session,
        valkey_client=mock_valkey,
        event_id=event.id,
        version=0,
        action=RejectAction.quarantine,
        user_id=admin_user.id,
    )

    logs = session.exec(
        select(AuditLog).where(
            AuditLog.action == "reject",
            AuditLog.target_id == event.id,
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].user_id == admin_user.id
    detail = json.loads(logs[0].detail)
    assert detail["action"] == "quarantine"
