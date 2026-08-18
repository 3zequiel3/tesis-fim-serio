"""
Tests del outbox transaccional de comandos de decisión y de agente
(D37/RN-131, change stream-ack-durability):

  14.9  La fila pending nace en la MISMA transacción; Valkey caído deja el
        evento terminal y la fila pending; el despachador la publica después.
  14.10 Una transacción que falla no deja fila PublishedCommand.
  14.11 Un agente sin shared_secret_hex hace fallar approve/reject/
        update_config/rescan, con la mutación revertida en los cuatro.
  14.12 El no-op de baseline absent (RN-74) no encola comando.

Usa SQLite in-memory. Salta si psycopg no está disponible (Windows sin PostgreSQL).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from valkey.exceptions import ValkeyError

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.agents.models import Agent, AgentStatus, BaselineEntry, BaselineStatus
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import PublishedCommand
from app.modules.rules.service import publish_pending_commands
from app.modules.actions.schemas import RejectAction
from app.modules.actions.service import _approve_single, _reject_single


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
    agent = Agent(agent_id="agent-outbox", status=AgentStatus.online, shared_secret_hex=secret.hex())
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent, secret


@pytest.fixture()
def agent_without_secret(session) -> Agent:
    agent = Agent(agent_id="agent-no-secret", status=AgentStatus.online, shared_secret_hex=None)
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent


def _make_pending_event(session: Session, agent_id: str, path: str = "/etc/passwd", hash_detected: str = "abc123") -> Event:
    event = Event(
        event_id=f"evt-{path}-{id(session)}",
        agent_id=agent_id,
        path=path,
        hash_detected=hash_detected,
        status=EventStatus.pending,
        version=0,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _flaky_valkey() -> MagicMock:
    client = MagicMock()
    client.xadd = MagicMock(side_effect=ValkeyError("connection refused"))
    return client


def _working_valkey() -> MagicMock:
    client = MagicMock()
    client.xadd = MagicMock()
    return client


# ── 14.9 — outbox: pending nace en la transacción, Valkey caído no pierde nada ─


def test_approve_pending_row_born_in_same_transaction(session, admin_user, agent_with_secret):
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent.agent_id)

    _approve_single(
        db=session, valkey_client=_working_valkey(), event_id=event.id,
        version=0, confirm_absent=False, user_id=admin_user.id,
    )

    cmd = session.exec(
        select(PublishedCommand).where(PublishedCommand.command_type == "baseline_update")
    ).first()
    assert cmd is not None
    assert cmd.status == "published"  # el intento inmediato best-effort tuvo éxito


def test_approve_valkey_down_leaves_event_approved_and_command_pending(session, admin_user, agent_with_secret):
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent.agent_id)

    result = _approve_single(
        db=session, valkey_client=_flaky_valkey(), event_id=event.id,
        version=0, confirm_absent=False, user_id=admin_user.id,
    )

    assert result.status == EventStatus.approved

    cmd = session.exec(
        select(PublishedCommand).where(PublishedCommand.command_type == "baseline_update")
    ).first()
    assert cmd is not None
    assert cmd.status == "pending"

    # El despachador, corrido después con Valkey ya arriba, lo publica y marca published.
    working_client = _working_valkey()
    published = publish_pending_commands(session, working_client)
    assert published == 1
    working_client.xadd.assert_called_once()

    session.refresh(cmd)
    assert cmd.status == "published"


def test_reject_valkey_down_leaves_event_rejected_and_command_pending(session, admin_user, agent_with_secret):
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent.agent_id)

    result, _ = _reject_single(
        db=session, valkey_client=_flaky_valkey(), event_id=event.id,
        version=0, action=RejectAction.restore, user_id=admin_user.id,
    )

    assert result.status == EventStatus.rejected
    cmd = session.exec(
        select(PublishedCommand).where(PublishedCommand.command_type == "restore_file")
    ).first()
    assert cmd is not None
    assert cmd.status == "pending"


# ── 14.10 — rollback: transacción que falla no deja fila PublishedCommand ─────


def test_approve_rollback_leaves_no_published_command_row(session, admin_user, agent_with_secret, monkeypatch):
    """
    Simula un fallo justo en el `db.commit()` — DESPUÉS de que
    `enqueue_baseline_update` ya agregó la fila PublishedCommand a la sesión
    (flush pendiente). El caller real (router/bulk) haría `db.rollback()`
    ante cualquier excepción no capturada; acá se hace explícito para
    observar que la fila insertada-pero-no-comiteada desaparece, igual que
    test_bulk_approve_rollback_isolates_failed_item en test_actions.py.
    """
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent.agent_id)

    def _boom():
        raise RuntimeError("simulated_commit_failure")

    monkeypatch.setattr(session, "commit", _boom)

    with pytest.raises(RuntimeError):
        _approve_single(
            db=session, valkey_client=_working_valkey(), event_id=event.id,
            version=0, confirm_absent=False, user_id=admin_user.id,
        )

    monkeypatch.undo()
    session.rollback()

    cmds = session.exec(select(PublishedCommand)).all()
    assert cmds == []
    session.refresh(event)
    assert event.status == EventStatus.pending


# ── 14.11 — agente sin shared_secret_hex: falla y revierte los cuatro ─────────


def test_approve_without_secret_reverts_and_raises(session, admin_user, agent_without_secret):
    event = _make_pending_event(session, agent_without_secret.agent_id)

    with pytest.raises(ValueError):
        _approve_single(
            db=session, valkey_client=_working_valkey(), event_id=event.id,
            version=0, confirm_absent=False, user_id=admin_user.id,
        )
    session.rollback()

    session.refresh(event)
    assert event.status == EventStatus.pending
    assert session.exec(select(PublishedCommand)).all() == []


def test_reject_without_secret_reverts_and_raises(session, admin_user, agent_without_secret):
    event = _make_pending_event(session, agent_without_secret.agent_id)

    with pytest.raises(ValueError):
        _reject_single(
            db=session, valkey_client=_working_valkey(), event_id=event.id,
            version=0, action=RejectAction.restore, user_id=admin_user.id,
        )
    session.rollback()

    session.refresh(event)
    assert event.status == EventStatus.pending
    assert session.exec(select(PublishedCommand)).all() == []


def test_update_config_without_secret_reverts_and_raises(session, admin_user, agent_without_secret):
    from app.modules.agents.service import update_agent_config

    with pytest.raises(ValueError):
        update_agent_config(
            db=session, valkey_client=_working_valkey(), agent_id=agent_without_secret.agent_id,
            watch_paths=["/etc"], user_id=admin_user.id,
        )
    session.rollback()

    session.refresh(agent_without_secret)
    assert agent_without_secret.watch_paths == []
    assert session.exec(select(PublishedCommand)).all() == []


def test_rescan_without_secret_reverts_and_raises(session, admin_user, agent_without_secret):
    from app.modules.agents.service import rescan_agent

    event = _make_pending_event(session, agent_without_secret.agent_id)

    with pytest.raises(ValueError):
        rescan_agent(
            db=session, valkey_client=_working_valkey(), agent_id=agent_without_secret.agent_id,
            force=True, user_id=admin_user.id,
        )
    session.rollback()

    session.refresh(event)
    assert event.status == EventStatus.pending
    assert session.exec(select(PublishedCommand)).all() == []


# ── 14.12 — no-op de baseline absent no encola comando ─────────────────────────


def test_reject_baseline_absent_noop_enqueues_no_command(session, admin_user, agent_with_secret):
    agent, _ = agent_with_secret
    event = _make_pending_event(session, agent.agent_id, hash_detected="ccc333")

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
        db=session, valkey_client=_working_valkey(), event_id=event.id,
        version=0, action=RejectAction.restore, user_id=admin_user.id,
    )

    assert result.status == EventStatus.rejected
    assert baseline_absent is True
    assert session.exec(select(PublishedCommand)).all() == []
