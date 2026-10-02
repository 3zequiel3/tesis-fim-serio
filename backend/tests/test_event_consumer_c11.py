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

class _FakeClock:
    """Injectable monotonic clock: tests advance time explicitly, no sleeping."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_rate_limiter_check_under_limit() -> None:
    from app.modules.events.consumer import _RateLimiter
    rl = _RateLimiter(rate_per_s=1.0, burst=3, clock=_FakeClock())
    assert rl.check("a1") is True
    assert rl.check("a1") is True
    assert rl.check("a1") is True


def test_rate_limiter_check_over_limit() -> None:
    from app.modules.events.consumer import _RateLimiter
    rl = _RateLimiter(rate_per_s=1.0, burst=3, clock=_FakeClock())
    rl.check("a1")
    rl.check("a1")
    rl.check("a1")
    assert rl.check("a1") is False


def test_rate_limiter_refill_admits_one_event_per_token() -> None:
    """D85/RN-179: with an empty bucket, advancing 1/rate seconds enables exactly one event."""
    from app.modules.events.consumer import _RateLimiter
    clock = _FakeClock()
    rl = _RateLimiter(rate_per_s=2.0, burst=2, clock=clock)
    rl.check("a1")
    rl.check("a1")
    assert rl.check("a1") is False
    clock.advance(1 / 2.0)
    assert rl.check("a1") is True  # the refilled token
    assert rl.check("a1") is False  # and only one


def test_rate_limiter_defaults_match_d85_rn179() -> None:
    """D85/RN-179: sustained 100 events/min (100/60 tokens per second), burst of 3,000."""
    from app.core.config import Settings

    assert Settings.model_fields["rate_limit_ingest_rate_per_s"].default == 100 / 60
    assert Settings.model_fields["rate_limit_ingest_burst"].default == 3000


def test_rate_limiter_honours_configured_burst(monkeypatch) -> None:
    """`_RateLimiter()` without arguments takes the burst from Settings, not a hardcoded value."""
    import app.modules.events.consumer as consumer_mod

    monkeypatch.setattr(consumer_mod.settings, "rate_limit_ingest_burst", 3)
    monkeypatch.setattr(consumer_mod.settings, "rate_limit_ingest_rate_per_s", 1.0)

    rl = consumer_mod._RateLimiter(clock=_FakeClock())
    assert [rl.check("a1") for _ in range(4)] == [True, True, True, False]


def test_rate_limiter_honours_configured_rate_in_retry_after(monkeypatch) -> None:
    """
    D37/RN-131: when the rate is reconfigured, the derived `retry_after` comes
    from the SAME rate (not a hardcoded 100/60).
    """
    import app.modules.events.consumer as consumer_mod

    monkeypatch.setattr(consumer_mod.settings, "rate_limit_ingest_burst", 2)
    monkeypatch.setattr(consumer_mod.settings, "rate_limit_ingest_rate_per_s", 0.1)

    rl = consumer_mod._RateLimiter(clock=_FakeClock())
    rl.check("a1")
    rl.check("a1")
    assert rl.check("a1") is False

    assert rl.seconds_until_available("a1") == pytest.approx(10.0)


def test_reset_rate_limiter_clears_state(monkeypatch) -> None:
    import app.modules.events.consumer as consumer_mod

    monkeypatch.setattr(consumer_mod, "_rate_limiter", consumer_mod._RateLimiter(
        rate_per_s=1.0, burst=5, clock=_FakeClock(),
    ))
    for _ in range(5):
        consumer_mod._rate_limiter.check("x")
    assert consumer_mod._rate_limiter.check("x") is False
    consumer_mod.reset_rate_limiter()
    assert consumer_mod._rate_limiter.check("x") is True


def test_consumer_rate_limited_event_audited(mem_engine, agent, shared_secret, monkeypatch) -> None:
    """
    El primer evento con el balde vacío de un agente genera RejectedEventAudit(rate_limited) y hace XACK.

    D37/RN-131: rate_limited ahora publica un event_nack con retry_after
    numérico (derivado del rate limiter) — el evento se conserva del lado
    del agente, ya no es mudo.
    """
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as svc_mod

    # Small bucket, drained explicitly, independent of the default burst.
    monkeypatch.setattr(consumer_mod, "_rate_limiter", consumer_mod._RateLimiter(
        rate_per_s=1.0, burst=3, clock=_FakeClock(),
    ))
    for _ in range(3):
        consumer_mod._rate_limiter.check("agent-test")

    # The next event must be rejected
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


def test_consumer_token_bucket_admits_burst_then_nacks_with_retry_after(
    mem_engine, shared_secret, monkeypatch
) -> None:
    """
    D85/RN-179 integration: with burst=3, an agent's first three new events are
    persisted; the fourth is XACKed, audited as rate_limited and gets an
    event_nack whose retry_after is the one computed by the limiter. An event
    from another agent in the same run is persisted.
    """
    import app.modules.events.consumer as consumer_mod

    limiter = consumer_mod._RateLimiter(rate_per_s=1.0, burst=3, clock=_FakeClock())
    monkeypatch.setattr(consumer_mod, "_rate_limiter", limiter)
    with Session(mem_engine) as session:
        session.add(Agent(agent_id="agent-a", status=AgentStatus.offline,
                          shared_secret_hex=shared_secret.hex()))
        session.add(Agent(agent_id="agent-b", status=AgentStatus.offline,
                          shared_secret_hex=shared_secret.hex()))
        session.commit()

    for i in range(3):
        client = _run_handle(mem_engine, _make_valid_payload("agent-a", shared_secret, f"/etc/f{i}"))
        client.xack.assert_called_once()
    with Session(mem_engine) as session:
        assert len(session.exec(select(Event).where(Event.agent_id == "agent-a")).all()) == 3

    expected_retry_after = limiter.seconds_until_available("agent-a")
    client = _run_handle(mem_engine, _make_valid_payload("agent-a", shared_secret, "/etc/f3"))
    client.xack.assert_called_once()
    nack = json.loads(client.xadd.call_args[0][1]["data"])
    assert nack["type"] == "event_nack"
    assert nack["reason"] == "rate_limited"
    assert nack["retry_after"] == pytest.approx(expected_retry_after)
    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
        assert [r.reason for r in rejections] == [RejectionReason.rate_limited]
        assert len(session.exec(select(Event).where(Event.agent_id == "agent-a")).all()) == 3

    client = _run_handle(mem_engine, _make_valid_payload("agent-b", shared_secret))
    client.xack.assert_called_once()
    with Session(mem_engine) as session:
        assert len(session.exec(select(Event).where(Event.agent_id == "agent-b")).all()) == 1


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
         patch.object(consumer_mod, "_ingest",
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
