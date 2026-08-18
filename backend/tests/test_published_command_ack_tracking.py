"""
Tests de regresión para C36 — backend-command-ack-consumer (slice 1: modelo,
migración, publicadores y fix D5/RN-106 en la publicación).

Cubre:
  - update_config: NO avanza ruleset_version_applied al publicar; sí crea
    PublishedCommand con command_id y ack_status=pending.
  - rule_sync: persiste con ack_status=NULL (excluido del barrido de timeout,
    que se agrega en slice 2).
  - enqueue_restore_file/enqueue_baseline_update/enqueue_quarantine_file y
    enqueue_update_config/enqueue_rescan_baseline (D37/RN-131 — renombradas
    desde publish_*, ver módulo actions/streams.py y agents/streams.py):
    insertan PublishedCommand `pending` en la sesión SIN hacer XADD ni commit
    propio. El caller decide cuándo comitea (misma transacción que su
    mutación) — a diferencia del contrato anterior (C36), donde estas
    funciones corrían post-commit y comiteaban ellas mismas tras el XADD.

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


def test_enqueue_update_config_creates_pending_command_without_advancing_version(mem_engine, agent_online):
    from app.modules.agents.streams import enqueue_update_config

    with Session(mem_engine) as s:
        agent = s.get(Agent, agent_online.agent_id)
        enqueue_update_config(s, agent, ["/etc"], ruleset_version=42)
        s.commit()  # D37/RN-131: enqueue_* ya no comitea — lo hace el caller

    with Session(mem_engine) as s:
        cmds = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == "update_config")).all()
        assert len(cmds) == 1
        assert cmds[0].status == "pending"  # nace pending, el XADD lo hace el despachador
        assert cmds[0].ack_status == "pending"
        assert cmds[0].command_id is not None

        agent = s.get(Agent, agent_online.agent_id)
        assert agent.ruleset_version_applied == 5, "encolar NO debe avanzar ruleset_version_applied (D5/RN-106)"


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


def test_enqueue_rescan_baseline_creates_pending_command(mem_engine, agent_online):
    from app.modules.agents.streams import enqueue_rescan_baseline

    with Session(mem_engine) as s:
        agent = s.get(Agent, agent_online.agent_id)
        enqueue_rescan_baseline(s, agent)
        s.commit()

    with Session(mem_engine) as s:
        cmds = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == "rescan_baseline")).all()
        assert len(cmds) == 1
        assert cmds[0].status == "pending"
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


# ── D37/RN-131: enqueue_* persiste en la sesión, el caller decide el commit ──


def test_enqueue_restore_file_requires_caller_commit(mem_engine, agent_online):
    """
    D37/RN-131 invierte el contrato de C36: antes, `publish_restore_file`
    corría post-commit del caller y comiteaba ella misma tras el XADD (no
    dependía de un commit posterior). Ahora `enqueue_restore_file` NO hace
    XADD ni commit — es el caller quien debe comitear, en la MISMA
    transacción que su propia mutación. Sin ese commit, la fila no persiste.
    """
    from app.modules.actions.streams import enqueue_restore_file

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

    with Session(mem_engine) as s:
        event = s.get(Event, ev.id)
        enqueue_restore_file(s, event)
        # Sin commit acá: la sesión se cierra sin comitear (simula un caller
        # que aborta antes de su propio db.commit()).

    # Sesión NUEVA e independiente: sin el commit del caller, no debe existir.
    with Session(mem_engine) as s:
        cmds = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == "restore_file")).all()
        assert cmds == []


def test_enqueue_restore_file_persists_once_caller_commits(mem_engine, agent_online):
    """Contraparte del test anterior: SI el caller comitea, la fila persiste pending."""
    from app.modules.actions.streams import enqueue_restore_file

    ev = Event(
        event_id="evt-commit-fix-002",
        agent_id=agent_online.agent_id,
        path="/etc/commit-fix-test-2",
        hash_detected="deadbeef",
        status=EventStatus.rejected,
        detected_at=datetime.now(timezone.utc),
        received_at=datetime.now(timezone.utc),
    )
    with Session(mem_engine) as s:
        s.add(ev)
        s.commit()
        s.refresh(ev)

    with Session(mem_engine) as s:
        event = s.get(Event, ev.id)
        enqueue_restore_file(s, event)
        s.commit()

    with Session(mem_engine) as s:
        cmds = s.exec(select(PublishedCommand).where(PublishedCommand.command_type == "restore_file")).all()
        assert len(cmds) == 1
        assert cmds[0].status == "pending"
        assert cmds[0].command_id is not None
        assert cmds[0].ack_status == "pending"
        assert cmds[0].event_id == ev.id
