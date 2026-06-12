"""Test de integración del done criterion del Change 08.

Done criterion:
  Evento publicado → consumido → XACK → event_ack → agente borra de cola.
  Heartbeat visible con status = online.

Usa SQLite in-memory + mocks de Valkey para correr sin infraestructura real.
Los tests se saltan si psycopg/libpq no está disponible.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

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

from app.core.streams import SCHEMA_VERSION, sign_payload, verify_payload
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event


@pytest.fixture()
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def shared_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def registered_agent(mem_engine, shared_secret: bytes) -> Agent:
    a = Agent(
        agent_id="integration-agent",
        status=AgentStatus.offline,
        shared_secret_hex=shared_secret.hex(),
    )
    with Session(mem_engine) as session:
        session.add(a)
        session.commit()
        session.refresh(a)
    return a


def test_event_lifecycle(mem_engine, registered_agent, shared_secret: bytes) -> None:
    """
    Evento publicado → consumer persiste → XACK → event_ack firmado válido.
    El event_ack lleva target_agent_id para que el agente borre la cola.
    """
    event_id = str(uuid.uuid4())
    payload = {
        "event_id": event_id,
        "agent_id": "integration-agent",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/passwd",
        "hash_detected": "sha256hexhere",
        "process_pid": 100,
        "process_uid": 0,
        "process_exe": "/usr/bin/vim",
    }
    payload["signature"] = sign_payload(shared_secret, payload)

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    import app.modules.events.consumer as consumer_mod
    with patch.object(consumer_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(
            mock_client,
            "1-0",
            {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))},
        ))

    # 1. Event persistido en DB
    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 1
    assert events[0].event_id == event_id
    assert events[0].received_at is not None

    # 2. XACK enviado
    mock_client.xack.assert_called_once()

    # 3. event_ack publicado en commands con firma válida
    mock_client.xadd.assert_called_once()
    ack_call = mock_client.xadd.call_args
    ack_data = json.loads(ack_call[0][1]["data"])
    assert ack_data["type"] == "event_ack"
    assert ack_data["event_id"] == event_id
    assert ack_data["target_agent_id"] == "integration-agent"
    assert verify_payload(shared_secret, ack_data)


def test_heartbeat_marks_agent_online(mem_engine, registered_agent) -> None:
    """Heartbeat procesado → agente queda online."""
    hb_data = {
        "data": json.dumps({
            "agent_id": "integration-agent",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "queue_size": 2,
            "queue_pressure": 0.05,
            "ruleset_version": 0,
            "shutdown": False,
            "schema_version": SCHEMA_VERSION,
        })
    }

    import app.modules.agents.heartbeat_consumer as hc
    with patch.object(hc, "engine", mem_engine):
        hc._handle_heartbeat(hb_data)

    with Session(mem_engine) as session:
        a = session.get(Agent, "integration-agent")
    assert a.status == AgentStatus.online
    assert a.queue_pressure == pytest.approx(0.05)
