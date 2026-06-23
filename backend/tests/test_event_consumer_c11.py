"""
Tests de los features de C11 en el consumer de eventos: rate limit e InvalidTransitionError.

Usa SQLite in-memory. Salta si psycopg no está disponible (Windows sin PostgreSQL).
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

from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, RejectedEventAudit, RejectionReason


@pytest.fixture()
def mem_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def shared_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def agent(mem_engine, shared_secret: bytes) -> Agent:
    a = Agent(agent_id="agent-test", status=AgentStatus.offline, shared_secret_hex=shared_secret.hex())
    with Session(mem_engine) as session:
        session.add(a)
        session.commit()
        session.refresh(a)
    return a


def _make_valid_payload(agent_id: str, shared_secret: bytes, path: str = "/etc/passwd") -> dict:
    from app.core.streams import SCHEMA_VERSION, sign_payload
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": path,
        "hash_detected": "abc123",
    }
    payload["signature"] = sign_payload(shared_secret, payload)
    return payload


def _make_msg_data(payload: dict) -> dict:
    return {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}


def _run_handle(mem_engine, payload: dict) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as svc_mod

    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(svc_mod, "engine", mem_engine):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))
    return mock_client


# ── Rate limit ─────────────────────────────────────────────────────────────────

def test_rate_limiter_check_under_limit() -> None:
    from app.modules.events.consumer import _RateLimiter
    rl = _RateLimiter(limit=3)
    assert rl.check("a1") is True
    assert rl.check("a1") is True
    assert rl.check("a1") is True


def test_rate_limiter_check_over_limit() -> None:
    from app.modules.events.consumer import _RateLimiter
    rl = _RateLimiter(limit=3)
    rl.check("a1")
    rl.check("a1")
    rl.check("a1")
    assert rl.check("a1") is False


def test_rate_limiter_sliding_window_expires() -> None:
    import time
    from app.modules.events.consumer import _RateLimiter
    rl = _RateLimiter(limit=2, window_s=0.05)  # ventana de 50ms
    rl.check("a1")
    rl.check("a1")
    assert rl.check("a1") is False
    time.sleep(0.1)
    assert rl.check("a1") is True  # ventana expiró


def test_reset_rate_limiter_clears_state() -> None:
    from app.modules.events.consumer import reset_rate_limiter, _rate_limiter
    for _ in range(100):
        _rate_limiter.check("x")
    assert _rate_limiter.check("x") is False
    reset_rate_limiter()
    assert _rate_limiter.check("x") is True


def test_consumer_rate_limited_event_audited(mem_engine, agent, shared_secret) -> None:
    """El evento 101 de un agente genera RejectedEventAudit(rate_limited) y hace XACK."""
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as svc_mod

    consumer_mod.reset_rate_limiter()

    # Saturar el rate limiter directamente
    for _ in range(100):
        consumer_mod._rate_limiter.check("agent-test")

    # El evento 101 debe ser rechazado
    payload = _make_valid_payload("agent-test", shared_secret)
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert any(r.reason == RejectionReason.rate_limited for r in rejections)
    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()  # sin event_ack

    consumer_mod.reset_rate_limiter()


# ── InvalidTransitionError en consumer ────────────────────────────────────────

def test_consumer_invalid_transition_xacks_and_does_not_persist(mem_engine, agent, shared_secret) -> None:
    """Si ingest_event lanza InvalidTransitionError el consumer hace XACK y no persiste."""
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as svc_mod
    from app.modules.events.service import InvalidTransitionError, EventStatus

    consumer_mod.reset_rate_limiter()

    payload = _make_valid_payload("agent-test", shared_secret)
    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()

    with patch.object(consumer_mod, "engine", mem_engine), \
         patch.object(svc_mod, "engine", mem_engine), \
         patch.object(consumer_mod, "ingest_event",
                      side_effect=InvalidTransitionError(EventStatus.approved, EventStatus.pending)):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))

    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 0
    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()
