"""
Regression tests C22/C8 — Result taxonomy in the event consumer.

Verifica:
- Éxito → XACK + event_ack publicado.
- Dedup/supersede-race → XACK sin re-insert (event_ack para dedup).
- InvalidTransitionError → XACK + audit en rejected_events_audit, sin event_ack.
- SQLAlchemyError → NO XACK, mensaje queda en PEL.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool
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

from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, RejectedEventAudit, RejectionReason
from app.modules.events.service import InvalidTransitionError, EventStatus


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
def shared_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def agent(mem_engine, shared_secret: bytes) -> Agent:
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


def _run_handle(mem_engine, payload: dict, mock_client=None):
    if mock_client is None:
        mock_client = AsyncMock()
        mock_client.xack = AsyncMock()
        mock_client.xadd = AsyncMock()

    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod
    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(service_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))
    return mock_client


# ── Éxito → XACK + event_ack ─────────────────────────────────────────────────


def test_success_path_xack_and_publishes_event_ack(mem_engine, agent, shared_secret) -> None:
    payload = _make_valid_payload("agent-test", shared_secret)
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 1

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_called_once()

    ack_data = json.loads(mock_client.xadd.call_args[0][1]["data"])
    assert ack_data["type"] == "event_ack"
    assert ack_data["event_id"] == payload["event_id"]


# ── Dedup → XACK sin re-insert ────────────────────────────────────────────────


def test_dedup_path_xack_without_reinsert(mem_engine, agent, shared_secret) -> None:
    payload = _make_valid_payload("agent-test", shared_secret)
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod

    # Primera entrega
    mock1 = AsyncMock()
    mock1.xack = AsyncMock()
    mock1.xadd = AsyncMock()
    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(service_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(mock1, "1-0", _make_msg_data(payload)))

    # Segunda entrega del mismo event_id
    mock2 = AsyncMock()
    mock2.xack = AsyncMock()
    mock2.xadd = AsyncMock()
    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(service_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(mock2, "2-0", _make_msg_data(payload)))

    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 1  # sin re-insert

    mock2.xack.assert_called_once()  # ack igual
    mock2.xadd.assert_called_once()  # event_ack re-publicado (dedup legítimo)


# ── Supersede race → XACK sin event_ack ─────────────────────────────────────


def test_supersede_race_xack_no_event_ack(mem_engine, agent, shared_secret) -> None:
    """mark_superseded retorna False (carrera) → _ingest retorna None → solo XACK."""
    payload = _make_valid_payload("agent-test", shared_secret)
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(service_mod, "engine", mem_engine), \
         patch.object(service_mod, "mark_superseded", return_value=False):
        # Primero creamos un evento pending para que mark_superseded sea llamado
        from app.modules.events.models import EventStatus as ES
        with Session(mem_engine) as s:
            existing = Event(
                event_id="existing-pending",
                agent_id="agent-test",
                path=payload["path"],
                hash_detected="oldhash",
                status=ES.pending,
                detected_at=datetime.now(timezone.utc),
                received_at=datetime.now(timezone.utc),
            )
            s.add(existing)
            s.commit()
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()  # sin event_ack en race


# ── InvalidTransitionError → XACK + audit ────────────────────────────────────


def test_invalid_transition_xack_and_audits(mem_engine, agent, shared_secret) -> None:
    payload = _make_valid_payload("agent-test", shared_secret)
    import app.modules.events.consumer as consumer_mod

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    with patch.object(consumer_mod, "engine", mem_engine):
        with patch.object(
            consumer_mod,
            "ingest_event",
            side_effect=InvalidTransitionError(EventStatus.approved, EventStatus.pending),
        ):
            asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()  # sin event_ack

    with Session(mem_engine) as session:
        audits = session.exec(select(RejectedEventAudit)).all()
    assert len(audits) == 1


# ── SQLAlchemyError → NO XACK ─────────────────────────────────────────────────


def test_sqlalchemy_error_no_xack_stays_in_pel(mem_engine, agent, shared_secret) -> None:
    payload = _make_valid_payload("agent-test", shared_secret)
    import app.modules.events.consumer as consumer_mod

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    with patch.object(consumer_mod, "engine", mem_engine):
        with patch.object(
            consumer_mod,
            "ingest_event",
            side_effect=SQLAlchemyError("connection refused"),
        ):
            asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))

    mock_client.xack.assert_not_called()  # mensaje queda en PEL
    mock_client.xadd.assert_not_called()

    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 0
