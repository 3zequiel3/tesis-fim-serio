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
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event, RejectedEventAudit, RejectionReason


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


def test_rate_limiter_defaults_preserve_legacy_behaviour() -> None:
    """P1: parametrizar no cambia producción — los defaults son los históricos 100/60s."""
    from app.core.config import Settings

    assert Settings.model_fields["rate_limit_ingest_events"].default == 100
    assert Settings.model_fields["rate_limit_ingest_window_seconds"].default == 60.0


def test_rate_limiter_honours_configured_limit(monkeypatch) -> None:
    """P1: `_RateLimiter()` sin argumentos toma el límite de Settings, no el 100 hardcodeado."""
    import app.modules.events.consumer as consumer_mod

    monkeypatch.setattr(consumer_mod.settings, "rate_limit_ingest_events", 3)
    monkeypatch.setattr(consumer_mod.settings, "rate_limit_ingest_window_seconds", 60.0)

    rl = consumer_mod._RateLimiter()
    assert [rl.check("a1") for _ in range(4)] == [True, True, True, False]


def test_rate_limiter_honours_configured_window_in_retry_after(monkeypatch) -> None:
    """
    P1 + D37/RN-131: al reconfigurar la ventana, el `retry_after` derivado sigue
    saliendo de la MISMA ventana (no de un 60.0 hardcodeado).
    """
    import app.modules.events.consumer as consumer_mod

    monkeypatch.setattr(consumer_mod.settings, "rate_limit_ingest_events", 2)
    monkeypatch.setattr(consumer_mod.settings, "rate_limit_ingest_window_seconds", 10.0)

    rl = consumer_mod._RateLimiter()
    rl.check("a1")
    rl.check("a1")
    assert rl.check("a1") is False

    retry = rl.seconds_until_available("a1")
    assert 9.0 < retry <= 10.0, f"retry_after debe derivar de la ventana de 10s, dio {retry}"


def test_reset_rate_limiter_clears_state() -> None:
    from app.modules.events.consumer import reset_rate_limiter, _rate_limiter
    for _ in range(100):
        _rate_limiter.check("x")
    assert _rate_limiter.check("x") is False
    reset_rate_limiter()
    assert _rate_limiter.check("x") is True


def test_consumer_rate_limited_event_audited(mem_engine, agent, shared_secret) -> None:
    """
    El evento 101 de un agente genera RejectedEventAudit(rate_limited) y hace XACK.

    D37/RN-131: rate_limited ahora publica un event_nack con retry_after
    numérico (derivado del rate limiter) — el evento se conserva del lado
    del agente, ya no es mudo.
    """
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
    mock_client.xadd.assert_called_once()  # D37/RN-131: event_nack con retry_after
    nack = json.loads(mock_client.xadd.call_args[0][1]["data"])
    assert nack["type"] == "event_nack"
    assert nack["reason"] == "rate_limited"
    assert isinstance(nack["retry_after"], (int, float))
    assert nack["retry_after"] > 0

    consumer_mod.reset_rate_limiter()


# ── InvalidTransitionError en consumer ────────────────────────────────────────

def test_consumer_invalid_transition_xacks_and_does_not_persist(mem_engine, agent, shared_secret) -> None:
    """
    Si ingest_event lanza InvalidTransitionError el consumer hace XACK, no
    persiste, y (D37/RN-131) publica un event_nack terminal reason=invalid_schema.
    """
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
    mock_client.xadd.assert_called_once()
    nack = json.loads(mock_client.xadd.call_args[0][1]["data"])
    assert nack["type"] == "event_nack"
    assert nack["reason"] == "invalid_schema"
    assert "retry_after" not in nack
