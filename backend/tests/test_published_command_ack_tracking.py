"""
Tests de regresión para C36 — backend-command-ack-consumer (slice 1: modelo,
migración, publicadores y fix D5/RN-106 en la publicación).

Cubre:
  - update_config: NO avanza ruleset_version_applied al publicar; sí crea
    PublishedCommand con command_id y ack_status=pending.
  - rule_sync: persiste con ack_status=NULL (excluido del barrido de timeout,
    que se agrega en slice 2).
  - Regresión del bug de commit faltante en publish_* post-commit (FIX C36):
    publish_restore_file/publish_baseline_update/publish_quarantine_file y
    publish_update_config/publish_rescan_baseline se llaman post-commit del
    caller real y deben persistir su PublishedCommand sin depender de un
    commit posterior del caller.

Usa SQLite in-memory. Salta si psycopg/libpq no está disponible.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, EventStatus
from app.modules.rules.models import PublishedCommand


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
def agent_online(mem_engine) -> Agent:
    a = Agent(
        agent_id="agent-ack-001",
        status=AgentStatus.online,
        shared_secret_hex="aa" * 32,
        ruleset_version_applied=5,
    )
    with Session(mem_engine) as s:
        s.add(a)
        s.commit()
        s.refresh(a)
    return a


# ── update_config: no avanza al publicar, sí registra PublishedCommand ───────


def test_publish_update_config_creates_pending_command_without_advancing_version(mem_engine, agent_online):
    from app.modules.agents.streams import publish_update_config

    mock_valkey = MagicMock()
    with Session(mem_engine) as s:
        agent = s.get(Agent, agent_online.agent_id)
        publish_update_config(s, mock_valkey, agent, ["/etc"], ruleset_version=42)

    with Session(mem_engine) as s:
        cmds = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == "update_config")).all()
        assert len(cmds) == 1
        assert cmds[0].ack_status == "pending"
        assert cmds[0].command_id is not None

        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 5, "publicar NO debe avanzar ruleset_version_applied (D5/RN-106)"


def test_update_agent_config_service_does_not_advance_ruleset_version_applied(mem_engine, agent_online):
    from app.modules.agents.service import update_agent_config

    mock_valkey = MagicMock()
    with Session(mem_engine) as s:
        update_agent_config(
            db=s,
            valkey_client=mock_valkey,
            agent_id=agent_online.agent_id,
            watch_paths=["/var/log"],
            user_id=1,
        )

    with Session(mem_engine) as s:
        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 5


def test_publish_rescan_baseline_creates_pending_command(mem_engine, agent_online):
    from app.modules.agents.streams import publish_rescan_baseline

    mock_valkey = MagicMock()
    with Session(mem_engine) as s:
        agent = s.get(Agent, agent_online.agent_id)
        publish_rescan_baseline(s, mock_valkey, agent)

    with Session(mem_engine) as s:
        cmds = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == "rescan_baseline")).all()
        assert len(cmds) == 1
        assert cmds[0].ack_status == "pending"
        assert cmds[0].command_id is not None


# ── rule_sync: ack_status NULL, excluido del barrido ─────────────────────────


def test_rule_sync_persists_with_null_ack_status(mem_engine, agent_online):
    from app.modules.rules.service import publish_rule_sync

    mock_valkey = MagicMock()
    with Session(mem_engine) as s:
        publish_rule_sync(s, mock_valkey, new_version=3)

    with Session(mem_engine) as s:
        cmd = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == "rule_sync")).first()
        assert cmd is not None
        assert cmd.ack_status is None


# ── Regresión del bug de commit faltante (fix C36) ───────────────────────────


def test_publish_restore_file_persists_without_caller_commit(mem_engine, agent_online):
    """
    Regresión del bug descubierto en el apply de C36: publish_restore_file se
    invoca post-commit del caller real (actions/service.py) y NO debe
    depender de un session.commit() posterior para persistir PublishedCommand.
    """
    from app.modules.actions.streams import publish_restore_file

    ev = Event(
        event_id="evt-commit-fix-001",
        agent_id=agent_online.agent_id,
        path="/etc/commit-fix-test",
        hash_detected="deadbeef",
        status=EventStatus.rejected,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    with Session(mem_engine) as s:
        s.add(ev)
        s.commit()
        s.refresh(ev)

    mock_valkey = MagicMock()
    with Session(mem_engine) as s:
        event = s.get(Event, ev.id)
        publish_restore_file(s, mock_valkey, event)
        # NO se llama session.commit() acá — simula el caller real (post-commit, sin comitear de nuevo)

    # Sesión NUEVA e independiente: si el fix no persistió, esto falla.
    with Session(mem_engine) as s:
        cmds = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == "restore_file")).all()
        assert len(cmds) == 1
        assert cmds[0].command_id is not None
        assert cmds[0].ack_status == "pending"
        assert cmds[0].event_id == ev.id
