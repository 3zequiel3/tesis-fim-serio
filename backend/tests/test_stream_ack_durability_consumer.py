"""
Tests del contrato de durabilidad del transporte (D37/RN-131, change
stream-ack-durability), lado backend/consumer:

  14.1  Ventana de skew sobre sent_at — detected_at viejo + sent_at reciente se acepta
  14.2  sent_at fuera de rango / futuro / no parseable → clock_skew
  14.3  Sin sent_at: fallback íntegro al comportamiento anterior sobre detected_at
  14.4  La firma cubre sent_at
  14.5  Matriz de respuestas completa (seis motivos, incluidos los mudos)
  14.6  invalid_schema / schema_version_unsupported: agente conocido firma, desconocido calla
  14.7  InvalidTransitionError → nack terminal; supersede-race → event_ack; SQLAlchemyError → silencio
  14.8  retry_after derivado del rate limiter, nunca cero ni negativo

Mismo patrón de fixtures que test_consumer.py (SQLite in-memory, salta si
psycopg/libpq no está disponible).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
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
    a = Agent(
        agent_id="agent-durability",
        status=AgentStatus.offline,
        shared_secret_hex=shared_secret.hex(),
    )
    with Session(mem_engine) as session:
        session.add(a)
        session.commit()
        session.refresh(a)
    return a


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Aísla el estado del rate limiter global entre tests (8.3)."""
    import app.modules.events.consumer as consumer_mod
    consumer_mod.reset_rate_limiter()
    yield
    consumer_mod.reset_rate_limiter()


def _make_msg_data(payload: dict) -> dict:
    return {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}


def _base_payload(agent_id: str, event_id: str | None = None, **overrides) -> dict:
    from app.core.streams import SCHEMA_VERSION
    payload = {
        "event_id": event_id if event_id is not None else str(uuid.uuid4()),
        "agent_id": agent_id,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": "/etc/passwd",
        "hash_detected": "abc123",
    }
    payload.update(overrides)
    return payload


def _sign(payload: dict, secret: bytes) -> dict:
    from app.core.streams import sign_payload
    payload["signature"] = sign_payload(secret, payload)
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


def _xadd_payloads(mock_client) -> list[dict]:
    return [json.loads(call.args[1]["data"]) for call in mock_client.xadd.call_args_list]


# ── 14.1 — detected_at viejo + sent_at reciente se acepta ─────────────────────


def test_detected_at_old_sent_at_recent_is_accepted(mem_engine, agent, shared_secret) -> None:
    """El defecto que motivó la change: una cola de horas debe drenar completa."""
    old_detected = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    payload = _sign(
        _base_payload("agent-durability", detected_at=old_detected, sent_at=datetime.now(timezone.utc).isoformat()),
        shared_secret,
    )
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert len(events) == 1
    assert not rejections
    # detected_at persistido es el original de hace seis horas
    persisted = events[0].detected_at
    if persisted.tzinfo is None:
        persisted = persisted.replace(tzinfo=timezone.utc)
    assert abs((persisted - datetime.fromisoformat(old_detected)).total_seconds()) < 1
    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_called_once()  # event_ack


# ── 14.2 — sent_at fuera de rango / futuro / no parseable ─────────────────────


def test_sent_at_out_of_range_rejected(mem_engine, agent, shared_secret) -> None:
    old_sent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    payload = _sign(_base_payload("agent-durability", sent_at=old_sent), shared_secret)
    _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert len(rejections) == 1
    assert rejections[0].reason == RejectionReason.clock_skew


def test_sent_at_in_future_rejected(mem_engine, agent, shared_secret) -> None:
    future_sent = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    payload = _sign(_base_payload("agent-durability", sent_at=future_sent), shared_secret)
    _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert len(rejections) == 1
    assert rejections[0].reason == RejectionReason.clock_skew


def test_sent_at_unparseable_rejected(mem_engine, agent, shared_secret) -> None:
    payload = _sign(_base_payload("agent-durability", sent_at="not-a-date"), shared_secret)
    _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert len(rejections) == 1
    assert rejections[0].reason == RejectionReason.clock_skew


def test_sent_at_naive_interpreted_as_utc(mem_engine, agent, shared_secret) -> None:
    """sent_at sin tzinfo, dentro de la ventana → se acepta (sin TypeError)."""
    naive_sent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    payload = _sign(_base_payload("agent-durability", sent_at=naive_sent), shared_secret)
    _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 1


# ── 14.3 — sin sent_at: fallback íntegro al comportamiento anterior ───────────


def test_no_sent_at_within_window_accepted(mem_engine, agent, shared_secret) -> None:
    payload = _sign(_base_payload("agent-durability"), shared_secret)
    _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 1


def test_no_sent_at_old_detected_at_rejected(mem_engine, agent, shared_secret) -> None:
    old_detected = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    payload = _sign(_base_payload("agent-durability", detected_at=old_detected), shared_secret)
    _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert len(rejections) == 1
    assert rejections[0].reason == RejectionReason.clock_skew


# ── 14.4 — la firma cubre sent_at ──────────────────────────────────────────────


def test_sent_at_altered_after_signing_is_invalid_signature(mem_engine, agent, shared_secret) -> None:
    payload = _sign(_base_payload("agent-durability"), shared_secret)
    payload["sent_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()  # alterado post-firma
    _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert len(rejections) == 1
    # invalid_signature, NO clock_skew — la ventana ni se evalúa
    assert rejections[0].reason == RejectionReason.invalid_signature


# ── 14.5 — matriz de respuestas completa ───────────────────────────────────────


def test_response_matrix_clock_skew_terminal_nack(mem_engine, agent, shared_secret) -> None:
    old_detected = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    payload = _sign(_base_payload("agent-durability", detected_at=old_detected), shared_secret)
    mock_client = _run_handle(mem_engine, payload)

    mock_client.xadd.assert_called_once()
    nack = _xadd_payloads(mock_client)[0]
    assert nack["type"] == "event_nack"
    assert nack["reason"] == "clock_skew"
    assert "retry_after" not in nack


def test_response_matrix_rate_limited_nack_with_retry_after(mem_engine, agent, shared_secret) -> None:
    import app.modules.events.consumer as consumer_mod
    for _ in range(100):
        consumer_mod._rate_limiter.check("agent-durability")

    payload = _sign(_base_payload("agent-durability"), shared_secret)
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert rejections[0].reason == RejectionReason.rate_limited

    mock_client.xadd.assert_called_once()
    nack = _xadd_payloads(mock_client)[0]
    assert nack["type"] == "event_nack"
    assert nack["reason"] == "rate_limited"
    assert isinstance(nack["retry_after"], (int, float))
    assert nack["retry_after"] > 0


def test_response_matrix_invalid_signature_is_silent(mem_engine, agent) -> None:
    payload = _base_payload("agent-durability")
    payload["signature"] = "0" * 64  # inválida
    mock_client = _run_handle(mem_engine, payload)

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()


def test_response_matrix_unknown_agent_is_silent(mem_engine) -> None:
    payload = _sign(_base_payload("ghost-agent"), os.urandom(32))
    mock_client = _run_handle(mem_engine, payload)

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()


def test_response_matrix_revoked_agent_is_silent(mem_engine, shared_secret) -> None:
    revoked = Agent(agent_id="agent-revoked", status=AgentStatus.revoked, shared_secret_hex=shared_secret.hex())
    with Session(mem_engine) as session:
        session.add(revoked)
        session.commit()

    payload = _sign(_base_payload("agent-revoked"), shared_secret)
    mock_client = _run_handle(mem_engine, payload)

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()


def test_response_matrix_empty_event_id_is_silent(mem_engine, agent, shared_secret) -> None:
    payload = _sign(_base_payload("agent-durability", event_id=""), shared_secret)
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert rejections[0].reason == RejectionReason.invalid_schema
    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()


# ── 14.6 — invalid_schema / schema_version_unsupported: firma vs. silencio ────


def test_schema_version_unsupported_known_agent_gets_signed_nack(mem_engine, agent, shared_secret) -> None:
    from app.core.streams import SCHEMA_VERSION
    payload = _base_payload("agent-durability", schema_version=SCHEMA_VERSION + 99)
    # No hace falta firmar: el rechazo ocurre antes del HMAC.
    mock_client = _run_handle(mem_engine, payload)

    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert rejections[0].reason == RejectionReason.schema_version_unsupported

    mock_client.xadd.assert_called_once()
    nack = _xadd_payloads(mock_client)[0]
    assert nack["reason"] == "schema_version_unsupported"
    assert isinstance(nack["retry_after"], (int, float))
    assert nack["retry_after"] > 0

    from app.core.streams import verify_payload
    assert verify_payload(shared_secret, nack)


def test_schema_version_unsupported_unknown_agent_is_silent(mem_engine) -> None:
    from app.core.streams import SCHEMA_VERSION
    payload = _base_payload("ghost-agent", schema_version=SCHEMA_VERSION + 99)
    mock_client = _run_handle(mem_engine, payload)

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()


def test_invalid_schema_unparseable_known_agent_gets_signed_terminal_nack(mem_engine, agent, shared_secret) -> None:
    payload = _base_payload("agent-durability", schema_version="garbage")
    mock_client = _run_handle(mem_engine, payload)

    mock_client.xadd.assert_called_once()
    nack = _xadd_payloads(mock_client)[0]
    assert nack["reason"] == "invalid_schema"
    assert "retry_after" not in nack

    from app.core.streams import verify_payload
    assert verify_payload(shared_secret, nack)


def test_invalid_schema_unknown_agent_is_silent(mem_engine) -> None:
    payload = _base_payload("ghost-agent", schema_version="garbage")
    mock_client = _run_handle(mem_engine, payload)

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_not_called()


# ── 14.7 — InvalidTransitionError / supersede-race / SQLAlchemyError ──────────


def test_invalid_transition_error_terminal_nack(mem_engine, agent, shared_secret) -> None:
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod

    payload = _sign(_base_payload("agent-durability"), shared_secret)

    def _raise(*_args, **_kwargs):
        from app.modules.events.service import InvalidTransitionError
        from app.modules.events.models import EventStatus
        raise InvalidTransitionError(EventStatus.approved, EventStatus.pending)

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()
    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine), \
            patch.object(consumer_mod, "_ingest", side_effect=_raise):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))

    mock_client.xack.assert_called_once()
    with Session(mem_engine) as session:
        rejections = session.exec(select(RejectedEventAudit)).all()
    assert rejections[0].reason == RejectionReason.invalid_schema

    mock_client.xadd.assert_called_once()
    nack = _xadd_payloads(mock_client)[0]
    assert nack["type"] == "event_nack"
    assert nack["reason"] == "invalid_schema"
    assert "retry_after" not in nack


def test_supersede_race_skip_gets_event_ack(mem_engine, agent, shared_secret) -> None:
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod

    payload = _sign(_base_payload("agent-durability"), shared_secret)

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()
    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine), \
            patch.object(consumer_mod, "_ingest", return_value=None):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))

    mock_client.xack.assert_called_once()
    mock_client.xadd.assert_called_once()
    ack = _xadd_payloads(mock_client)[0]
    assert ack["type"] == "event_ack"
    assert ack["event_id"] == payload["event_id"]


def test_sqlalchemy_error_no_xack_no_response(mem_engine, agent, shared_secret) -> None:
    import app.modules.events.consumer as consumer_mod
    import app.modules.events.service as service_mod
    from sqlalchemy.exc import SQLAlchemyError

    payload = _sign(_base_payload("agent-durability"), shared_secret)

    mock_client = AsyncMock()
    mock_client.xack = AsyncMock()
    mock_client.xadd = AsyncMock()
    with patch.object(consumer_mod, "engine", mem_engine), \
            patch.object(service_mod, "engine", mem_engine), \
            patch.object(consumer_mod, "_ingest", side_effect=SQLAlchemyError("db down")):
        asyncio.run(consumer_mod._handle_message(mock_client, "1-0", _make_msg_data(payload)))

    mock_client.xack.assert_not_called()
    mock_client.xadd.assert_not_called()
    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert not events


# ── 14.8 — retry_after derivado del rate limiter ───────────────────────────────


def test_retry_after_budget_just_filled_close_to_full_window() -> None:
    from app.modules.events.consumer import _RateLimiter
    limiter = _RateLimiter(limit=100, window_s=60.0)
    now = time.monotonic()
    limiter._buckets["a1"] = deque([now] * 100)

    retry = limiter.seconds_until_available("a1")
    assert retry == pytest.approx(60.0, abs=1.0)


def test_retry_after_window_almost_expired_waits_briefly() -> None:
    from app.modules.events.consumer import _RateLimiter
    limiter = _RateLimiter(limit=100, window_s=60.0)
    now = time.monotonic()
    limiter._buckets["a1"] = deque([now - 58.0] + [now] * 99)

    retry = limiter.seconds_until_available("a1")
    assert retry == pytest.approx(2.0, abs=1.0)


def test_retry_after_never_zero_or_negative() -> None:
    from app.modules.events.consumer import _RateLimiter
    limiter = _RateLimiter(limit=100, window_s=60.0)
    now = time.monotonic()
    # Remanente calculado ~0 (o levemente negativo por el tiempo transcurrido
    # entre construir el bucket y llamar al método) — nunca se expone tal cual.
    limiter._buckets["a1"] = deque([now - 60.0 + 0.0005] + [now] * 99)

    retry = limiter.seconds_until_available("a1")
    assert retry > 0
    assert retry >= limiter._MIN_RETRY_AFTER_S


def test_retry_after_zero_when_budget_available() -> None:
    from app.modules.events.consumer import _RateLimiter
    limiter = _RateLimiter(limit=100, window_s=60.0)
    assert limiter.seconds_until_available("never-used") == 0.0

    limiter.check("a1")  # solo 1 de 100
    assert limiter.seconds_until_available("a1") == 0.0


def test_reset_rate_limiter_clears_state() -> None:
    import app.modules.events.consumer as consumer_mod
    consumer_mod._rate_limiter.check("agent-x")
    consumer_mod.reset_rate_limiter()
    assert consumer_mod._rate_limiter.seconds_until_available("agent-x") == 0.0
