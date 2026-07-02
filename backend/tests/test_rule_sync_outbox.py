"""
H6 — regression test: outbox para publish_rule_sync sobrevive una caída de Valkey (C34).

Antes del fix, `publish_rule_sync` corría post-commit y publicaba de forma
síncrona: si Valkey estaba caído en ese momento, el XADD lanzaba una excepción
sin capturar (500 en el endpoint) y el comando rule_sync se perdía para
siempre — la versión ya había avanzado pero ningún agente se enteraba.

El fix persiste el payload firmado como PublishedCommand `pending` en la
MISMA transacción que Rule + RulesetVersion, y separa la publicación
efectiva (best-effort inmediato + background task de retry).
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from valkey.exceptions import ConnectionError as ValkeyConnectionError

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.core.streams import verify_payload
from app.modules.agents.models import Agent, AgentStatus
from app.modules.auth.models import User
from app.modules.rules.models import PublishedCommand
from app.modules.rules.service import create_rule, publish_pending_commands


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
    agent = Agent(
        agent_id="agent-outbox-001",
        status=AgentStatus.online,
        shared_secret_hex=secret.hex(),
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)
    return agent, secret


@pytest.fixture()
def down_valkey() -> MagicMock:
    """Simula Valkey caído: cualquier XADD lanza ConnectionError."""
    client = MagicMock()
    client.xadd.side_effect = ValkeyConnectionError("Connection refused")
    return client


def test_create_rule_with_valkey_down_persists_pending_command(
    session, down_valkey, admin_user, agent_with_secret
) -> None:
    """
    H6: crear una regla con Valkey caído no falla, avanza ruleset_version, y
    deja el comando rule_sync persistido como `pending` (no se pierde).
    """
    rule = create_rule(
        session,
        down_valkey,
        admin_user.id,
        {"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"},
    )
    assert rule.id is not None

    cmds = session.exec(
        select(PublishedCommand).where(PublishedCommand.command_type == "rule_sync")
    ).all()
    assert len(cmds) == 1
    assert cmds[0].status == "pending"
    assert cmds[0].published_at is None
    assert cmds[0].payload  # payload firmado ya persistido, listo para reintentar
    assert cmds[0].ruleset_version == 1


def test_pending_command_redelivered_when_valkey_recovers(
    session, down_valkey, admin_user, agent_with_secret
) -> None:
    """
    H6: al recuperarse Valkey, publish_pending_commands (background task)
    publica el comando pendiente sin intervención manual — sin duplicar filas.
    """
    agent, secret = agent_with_secret

    create_rule(
        session,
        down_valkey,
        admin_user.id,
        {"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"},
    )
    cmds = session.exec(
        select(PublishedCommand).where(PublishedCommand.command_type == "rule_sync")
    ).all()
    assert len(cmds) == 1
    assert cmds[0].status == "pending"

    # Valkey se recupera.
    healthy_valkey = MagicMock()
    published = publish_pending_commands(session, healthy_valkey)

    assert published == 1
    healthy_valkey.xadd.assert_called_once()
    call_args = healthy_valkey.xadd.call_args
    payload = json.loads(call_args[0][1]["data"])
    assert payload["type"] == "rule_sync"
    assert payload["target_agent_id"] == agent.agent_id
    assert verify_payload(secret, payload)

    cmds = session.exec(
        select(PublishedCommand).where(PublishedCommand.command_type == "rule_sync")
    ).all()
    assert len(cmds) == 1, "no debe duplicarse la fila de comando persistida"
    assert cmds[0].status == "published"
    assert cmds[0].published_at is not None


def test_transient_failure_stops_batch_without_losing_pending_rows(
    session, admin_user, agent_with_secret
) -> None:
    """
    H6: si el XADD falla a mitad de un barrido con varios pendientes, el resto
    queda `pending` (no se pierde ni se marca published incorrectamente).
    """
    failing_valkey = MagicMock()
    failing_valkey.xadd.side_effect = ValkeyConnectionError("still down")

    create_rule(
        session,
        failing_valkey,
        admin_user.id,
        {"pattern": "/etc/*", "severity": "critical", "action": "auto_restore"},
    )
    create_rule(
        session,
        failing_valkey,
        admin_user.id,
        {"pattern": "/var/*", "severity": "high", "action": "alert_only"},
    )

    cmds = session.exec(
        select(PublishedCommand).where(PublishedCommand.command_type == "rule_sync")
    ).all()
    assert len(cmds) == 2
    assert all(c.status == "pending" for c in cmds)
