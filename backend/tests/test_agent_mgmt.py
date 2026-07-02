"""
Tests de gestión de agentes (C14, tasks 12.1–12.13).

Cubre:
  12.1  test_get_agents_list — lista con todos los agentes y sus campos
  12.2  test_get_agent_detail — detalle con watch_paths
  12.3  test_get_agent_not_found → 404
  12.4  test_agent_config_updates_watch_paths — watch_paths persiste + update_config publicado
  12.5  test_agent_config_hmac_valid — payload tiene firma HMAC verificable
  12.6  test_agent_config_not_found → 404
  12.7  test_rescan_no_pending_succeeds — sin pending → rescan_baseline publicado
  12.8  test_rescan_with_pending_no_force → 409 con count
  12.9  test_rescan_with_pending_force — pending superseded + rescan_baseline publicado
  12.10 test_dead_transition — agente offline > 5min → status=dead en sweep
  12.11 test_dead_to_online_on_heartbeat — agente dead vuelve a online al recibir heartbeat
  12.12 test_audit_log_on_config — fila en audit_log con action="agent_config"
  12.13 test_audit_log_on_rescan — fila en audit_log con action="agent_rescan"

Usa SQLite in-memory. Salta si psycopg no está disponible (Windows sin PostgreSQL).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.core.streams import verify_payload
from app.modules.agents.models import Agent, AgentStatus
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import RulesetVersion


# ── Fixtures ──────────────────────────────────────────────────────────────────


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
        agent_id="agent-mgmt-001",
        status=AgentStatus.online,
        shared_secret_hex=secret.hex(),
        watch_paths=[],
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent, secret


def _make_pending_event(
    session: Session,
    agent_id: str,
    path: str = "/etc/passwd",
    hash_detected: str = "abc123",
) -> Event:
    import uuid
    event = Event(
        event_id=str(uuid.uuid4()),
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


# ── 12.1 test_get_agents_list ─────────────────────────────────────────────────


def test_get_agents_list(session, agent_with_secret):
    """Lista de agentes retorna todos los registrados con sus campos."""
    from app.modules.agents.service import list_agents

    agent, _ = agent_with_secret
    result = list_agents(session)

    assert len(result) == 1
    assert result[0].agent_id == agent.agent_id
    assert result[0].status == AgentStatus.online
    assert isinstance(result[0].watch_paths, list)


# ── 12.2 test_get_agent_detail ────────────────────────────────────────────────


def test_get_agent_detail(session, agent_with_secret):
    """Detalle retorna el agente con watch_paths."""
    from app.modules.agents.service import get_agent

    agent, _ = agent_with_secret
    # Actualizar watch_paths
    agent.watch_paths = ["/etc", "/usr/bin"]
    session.add(agent)
    session.commit()

    result = get_agent(session, agent.agent_id)
    assert result.agent_id == agent.agent_id
    assert result.watch_paths == ["/etc", "/usr/bin"]
    assert result.status == AgentStatus.online


# ── 12.3 test_get_agent_not_found ─────────────────────────────────────────────


def test_get_agent_not_found(session):
    """Agente inexistente → 404."""
    from fastapi import HTTPException
    from app.modules.agents.service import get_agent

    with pytest.raises(HTTPException) as exc_info:
        get_agent(session, "nonexistent-agent")
    assert exc_info.value.status_code == 404


# ── 12.4 test_agent_config_updates_watch_paths ────────────────────────────────


def test_agent_config_updates_watch_paths(session, mock_valkey, admin_user, agent_with_secret):
    """watch_paths persiste en DB y comando update_config publicado."""
    from app.modules.agents.service import update_agent_config

    agent, _ = agent_with_secret
    result = update_agent_config(
        db=session,
        valkey_client=mock_valkey,
        agent_id=agent.agent_id,
        watch_paths=["/etc", "/usr/bin"],
        user_id=admin_user.id,
    )

    # watch_paths persistidos
    assert result.watch_paths == ["/etc", "/usr/bin"]
    session.refresh(agent)
    assert agent.watch_paths == ["/etc", "/usr/bin"]

    # Comando publicado
    mock_valkey.xadd.assert_called_once()
    call_args = mock_valkey.xadd.call_args
    payload = json.loads(call_args[0][1]["data"])
    assert payload["type"] == "update_config"
    assert payload["target_agent_id"] == agent.agent_id
    assert payload["watch_paths"] == ["/etc", "/usr/bin"]


# ── 12.5 test_agent_config_hmac_valid ────────────────────────────────────────


def test_agent_config_hmac_valid(session, mock_valkey, admin_user, agent_with_secret):
    """El payload del comando update_config tiene firma HMAC verificable."""
    from app.modules.agents.service import update_agent_config

    agent, secret = agent_with_secret
    update_agent_config(
        db=session,
        valkey_client=mock_valkey,
        agent_id=agent.agent_id,
        watch_paths=["/var/log"],
        user_id=admin_user.id,
    )

    payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert verify_payload(secret, payload), "HMAC signature should be valid"


# ── 12.6 test_agent_config_not_found ─────────────────────────────────────────


def test_agent_config_not_found(session, mock_valkey, admin_user):
    """Agente inexistente → 404."""
    from fastapi import HTTPException
    from app.modules.agents.service import update_agent_config

    with pytest.raises(HTTPException) as exc_info:
        update_agent_config(
            db=session,
            valkey_client=mock_valkey,
            agent_id="unknown-agent",
            watch_paths=["/etc"],
            user_id=admin_user.id,
        )
    assert exc_info.value.status_code == 404
    mock_valkey.xadd.assert_not_called()


# ── 12.7 test_rescan_no_pending_succeeds ─────────────────────────────────────


def test_rescan_no_pending_succeeds(session, mock_valkey, admin_user, agent_with_secret):
    """Sin pending → rescan_baseline publicado correctamente."""
    from app.modules.agents.service import rescan_agent

    agent, _ = agent_with_secret
    rescan_agent(
        db=session,
        valkey_client=mock_valkey,
        agent_id=agent.agent_id,
        force=False,
        user_id=admin_user.id,
    )

    mock_valkey.xadd.assert_called_once()
    payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert payload["type"] == "rescan_baseline"
    assert payload["target_agent_id"] == agent.agent_id


# ── 12.8 test_rescan_with_pending_no_force ────────────────────────────────────


def test_rescan_with_pending_no_force(session, mock_valkey, admin_user, agent_with_secret):
    """Pending existentes + force=False → PendingEventsExist (HTTP 409 con count)."""
    from app.modules.agents.service import PendingEventsExist, rescan_agent

    agent, _ = agent_with_secret
    # Crear 3 eventos pending
    for i in range(3):
        _make_pending_event(session, agent.agent_id, path=f"/etc/file{i}")

    with pytest.raises(PendingEventsExist) as exc_info:
        rescan_agent(
            db=session,
            valkey_client=mock_valkey,
            agent_id=agent.agent_id,
            force=False,
            user_id=admin_user.id,
        )

    assert exc_info.value.count == 3
    # No se publicó nada
    mock_valkey.xadd.assert_not_called()

    # Los eventos siguen pending
    pending = session.exec(
        select(Event).where(
            Event.agent_id == agent.agent_id,
            Event.status == EventStatus.pending,
        )
    ).all()
    assert len(pending) == 3


# ── 12.9 test_rescan_with_pending_force ──────────────────────────────────────


def test_rescan_with_pending_force(session, mock_valkey, admin_user, agent_with_secret):
    """force=True: pending superseded + rescan_baseline publicado."""
    from app.modules.agents.service import rescan_agent

    agent, _ = agent_with_secret
    # Crear 2 eventos pending
    for i in range(2):
        _make_pending_event(session, agent.agent_id, path=f"/etc/file_f{i}")

    rescan_agent(
        db=session,
        valkey_client=mock_valkey,
        agent_id=agent.agent_id,
        force=True,
        user_id=admin_user.id,
    )

    # Eventos superseded
    superseded = session.exec(
        select(Event).where(
            Event.agent_id == agent.agent_id,
            Event.status == EventStatus.superseded,
        )
    ).all()
    assert len(superseded) == 2

    # rescan_baseline publicado
    mock_valkey.xadd.assert_called_once()
    payload = json.loads(mock_valkey.xadd.call_args[0][1]["data"])
    assert payload["type"] == "rescan_baseline"


# ── 12.10 test_dead_transition ────────────────────────────────────────────────


def test_dead_transition(mem_engine, agent_with_secret):
    """Agente offline > 5min → status=dead en sweep."""
    agent, _ = agent_with_secret

    # Poner el agente offline con last_heartbeat hace 6 minutos
    with Session(mem_engine) as session:
        a = session.get(Agent, agent.agent_id)
        a.status = AgentStatus.offline
        a.last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=6)
        session.add(a)
        session.commit()

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._sweep_offline()

    with Session(mem_engine) as session:
        a = session.get(Agent, agent.agent_id)
    assert a.status == AgentStatus.dead


# ── 12.11 test_dead_to_online_on_heartbeat ────────────────────────────────────


def test_dead_to_online_on_heartbeat(mem_engine, agent_with_secret):
    """Agente dead vuelve a online al recibir heartbeat."""
    from app.core.streams import sign_payload
    agent, secret = agent_with_secret

    # Poner el agente dead
    with Session(mem_engine) as session:
        a = session.get(Agent, agent.agent_id)
        a.status = AgentStatus.dead
        session.add(a)
        session.commit()

    hb_payload = {
        "agent_id": agent.agent_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "queue_size": 0,
        "queue_pressure": 0.1,
        "ruleset_version": 0,
        "shutdown": False,
        "schema_version": 1,
    }
    hb_payload["signature"] = sign_payload(secret, hb_payload)
    hb_msg = {"data": json.dumps(hb_payload)}

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(hb_msg)

    with Session(mem_engine) as session:
        a = session.get(Agent, agent.agent_id)
    assert a.status == AgentStatus.online
    assert a.last_heartbeat is not None


# ── 12.12 test_audit_log_on_config ───────────────────────────────────────────


def test_audit_log_on_config(session, mock_valkey, admin_user, agent_with_secret):
    """Fila en audit_log con action='agent_config' tras actualizar config."""
    from app.modules.agents.service import update_agent_config

    agent, _ = agent_with_secret
    update_agent_config(
        db=session,
        valkey_client=mock_valkey,
        agent_id=agent.agent_id,
        watch_paths=["/etc"],
        user_id=admin_user.id,
    )

    logs = session.exec(
        select(AuditLog).where(AuditLog.action == "agent_config")
    ).all()
    assert len(logs) == 1
    assert logs[0].user_id == admin_user.id
    assert logs[0].target_type == "agent"


# ── 12.13 test_audit_log_on_rescan ───────────────────────────────────────────


def test_audit_log_on_rescan(session, mock_valkey, admin_user, agent_with_secret):
    """Fila en audit_log con action='agent_rescan' tras rescan."""
    from app.modules.agents.service import rescan_agent

    agent, _ = agent_with_secret
    rescan_agent(
        db=session,
        valkey_client=mock_valkey,
        agent_id=agent.agent_id,
        force=False,
        user_id=admin_user.id,
    )

    logs = session.exec(
        select(AuditLog).where(AuditLog.action == "agent_rescan")
    ).all()
    assert len(logs) == 1
    assert logs[0].user_id == admin_user.id
    assert logs[0].target_type == "agent"
