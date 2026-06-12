"""Tests del consumer de eventos (Change 08, task 9.4).

Usa SQLite in-memory para aislar la DB.
Cubre: rechazos por clock_skew / invalid_schema / invalid_signature / unknown_agent,
dedup idempotente, y camino feliz (Event persistido + event_ack).

Los tests se saltan si psycopg/libpq no está disponible (ej. Windows sin PostgreSQL).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

# Saltar si psycopg/libpq no está disponible en este entorno (patrón idéntico a
# los tests Linux-only del agente — se ejecutan en CI/Docker pero no en Windows)
try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

# Env mínimo para importar app sin error de config
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, RejectedEventAudit, RejectionReason


@pytest.fixture()
def mem_engine():
    """Motor SQLite in-memory con todas las tablas creadas."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def shared_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def agent(mem_engine, shared_secret: bytes) -> Agent:
    """Agente pre-registrado con shared_secret_hex."""
    a = Agent(
        agent_id="agent-test",
        status=AgentStatus.offline,
        shared_secret_hex=shared_secret.hex(),
    )
    with Session(mem_engine) as session:
        session.add(a)
        session.commit()
        session.refresh(a)
    return a


def _make_msg_data(payload: dict) -> dict:
    return {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}


def _make_valid_payload(agent_id: str, shared_secret: bytes, path: str = "/etc/passwd") -> dict:
    from app.core.streams import SCHEMA_VERSION, sign_payload
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": path,
        "hash_detected": "abc123",
        "process_pid": 1234,
        "process_uid": 0,
        "process_exe": "/usr/bin/test",
    }
    payload["signature"] = sign_payload(shared_secret, payload)
    return payload


# ── helpers de test que usan el engine de test ─────────────────────────────────

def _run_handle(mem_engine, payload: dict, mock_client=None) -> None:
    """Ejecuta _handle_message contra el engine de test."""
    if mock_client is None:
        mock_client = AsyncMock()
        mock_client.xack = AsyncMock()
        mock_client.xadd = AsyncMock()

    import app.modules.events.consumer as consumer_mod
    with patch.object(consumer_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))
    return mock_client


# ── Rechazos ───────────────────────────────────────────────────────────────────

def test_reject_invalid_schema(mem_engine, agent) -> None:
    from app.core.streams import SCHEMA_VERSION, sign_payload
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "agent-test",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION + 99,  # demasiado alto
        "path": "/etc/passwd",
        "hash_detected": "h",
    }
    payload["signature"] = sign_payload(os.urandom(32), payload)
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert len(rejections) == 1
    assert rejections[0].reason == RejectionReason.invalid_schema
    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()


def test_reject_unknown_agent(mem_engine) -> None:
    from app.core.streams import SCHEMA_VERSION, sign_payload
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "ghost-agent",  # no existe en DB
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/passwd",
        "hash_detected": "h",
    }
    payload["signature"] = sign_payload(os.urandom(32), payload)
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert any(r.reason == RejectionReason.unknown_agent for r in rejections)


def test_reject_invalid_signature(mem_engine, agent, shared_secret) -> None:
    from app.core.streams import SCHEMA_VERSION
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "agent-test",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/passwd",
        "hash_detected": "h",
        "signature": "badbadbadbad",  # firma inválida
    }
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert any(r.reason == RejectionReason.invalid_signature for r in rejections)


def test_reject_clock_skew(mem_engine, agent, shared_secret) -> None:
    from app.core.streams import SCHEMA_VERSION, sign_payload
    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "agent-test",
        "detected_at": old_time,
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/passwd",
        "hash_detected": "h",
    }
    payload["signature"] = sign_payload(shared_secret, payload)
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert any(r.reason == RejectionReason.clock_skew for r in rejections)


# ── Dedup idempotente ──────────────────────────────────────────────────────────

def test_dedup_idempotent(mem_engine, agent, shared_secret) -> None:
    payload = _make_valid_payload("agent-test", shared_secret)
    import app.modules.events.consumer as consumer_mod

    # Primera entrega
    mock_client1 = AsyncMock()
    mock_client1.xack = AsyncMock()
    mock_client1.xadd = AsyncMock()
    with patch.object(consumer_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(mock_client1, "1-0", _make_msg_data(payload)))

    # Segunda entrega del mismo event_id
    mock_client2 = AsyncMock()
    mock_client2.xack = AsyncMock()
    mock_client2.xadd = AsyncMock()
    with patch.object(consumer_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(mock_client2, "2-0", _make_msg_data(payload)))

    # Solo un Event en la DB
    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 1

    # Pero el segundo también hizo XACK + event_ack
    mock_client2.xack.assert_called_once()
    mock_client2.xadd.assert_called_once()  # event_ack re-publicado


# ── Camino feliz ──────────────────────────────────────────────────────────────

def test_happy_path_persists_event_and_sends_ack(mem_engine, agent, shared_secret) -> None:
    payload = _make_valid_payload("agent-test", shared_secret)
    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    import app.modules.events.consumer as consumer_mod
    with patch.object(consumer_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))

    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 1
    assert events[0].event_id == payload["event_id"]
    assert events[0].agent_id == "agent-test"

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_called_once()

    # El event_ack lleva el event_id y target_agent_id
    ack_call = mock_client.xadd.call_args
    ack_data = json.loads(ack_call[0][1]["data"])
    assert ack_data["event_id"] == payload["event_id"]
    assert ack_data["target_agent_id"] == "agent-test"
    assert ack_data["type"] == "event_ack"
