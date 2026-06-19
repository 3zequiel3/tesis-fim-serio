"""
Consumer del stream 'events' para el backend FIM Platform.

Consumer group: fim-backend (RN-56).
Validación en orden barato→caro:
  1. schema_version   → invalid_schema  (RN-91)
  2. agent_id existe  → unknown_agent
  3. HMAC-SHA256      → invalid_signature (RN-79)
  4. clock skew ≤5min → clock_skew      (RN-90)
  5. rate limit       → rate_limited    (RN-88, D7)
  6. dedup event_id   → XACK + event_ack sin re-insertar (RN-73)

Camino feliz: ingest_event (service), XACK, publica event_ack firmado (RN-73, D5).
Rechazos: inserta RejectedEventAudit, XACK, sin event_ack (D4, RN-105).
Al arrancar releer pendientes con id '0' antes de nuevos '>' (RN-76).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlmodel import Session, select

from app.core.database import engine
from app.core.streams import (
    CONSUMER_GROUP,
    CONSUMER_NAME,
    SCHEMA_VERSION,
    STREAM_COMMANDS,
    STREAM_EVENTS,
    check_schema_version,
    sign_payload,
    verify_payload,
)
from app.modules.agents.models import Agent
from app.modules.alerts.service import notify_if_applicable
from app.modules.events.models import Event, EventStatus, RejectedEventAudit, RejectionReason
from app.modules.events.service import InvalidTransitionError, ingest_event

log = structlog.get_logger()

_CLOCK_SKEW_S = 300  # 5 minutos (RN-90)
_MAX_PAYLOAD_DUMP = 4 * 1024  # 4 KB (RN-105)
_BLOCK_MS = 2000
_BATCH_SIZE = 50


# ── Rate limiter ──────────────────────────────────────────────────────────────

class _RateLimiter:
    """Ventana deslizante 60s por agent_id (RN-88). Single-threaded asyncio."""

    def __init__(self, limit: int = 100, window_s: float = 60.0) -> None:
        self._limit = limit
        self._window_s = window_s
        self._buckets: dict[str, deque[float]] = {}

    def check(self, key: str) -> bool:
        """Retorna True si está dentro del límite (registra el timestamp). False si excede."""
        now = time.monotonic()
        cutoff = now - self._window_s
        bucket = self._buckets.setdefault(key, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._limit:
            return False
        bucket.append(now)
        return True

    def reset(self) -> None:
        self._buckets.clear()


_rate_limiter = _RateLimiter()


def reset_rate_limiter() -> None:
    """Limpia todos los contadores. Usado en tests."""
    _rate_limiter.reset()


# ── Consumer loop ─────────────────────────────────────────────────────────────

async def run_consumer(client: Any, stop_event: asyncio.Event) -> None:
    """Tarea asyncio principal del consumer de eventos."""
    await _ensure_group(client)
    # Releer pendientes al arrancar (RN-76)
    await _process_batch(client, "0")
    log.info("consumer.started", group=CONSUMER_GROUP)

    while not stop_event.is_set():
        try:
            await _process_batch(client, ">")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("consumer.loop_error", error=str(exc))
            await asyncio.sleep(1)


async def _ensure_group(client: Any) -> None:
    try:
        await client.xgroup_create(STREAM_EVENTS, CONSUMER_GROUP, id="0", mkstream=True)
        log.info("consumer.group_created", group=CONSUMER_GROUP)
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            pass  # group ya existe
        else:
            raise


async def _process_batch(client: Any, start_id: str) -> None:
    """Lee un batch del stream y procesa cada mensaje."""
    results = await client.xreadgroup(
        CONSUMER_GROUP,
        CONSUMER_NAME,
        {STREAM_EVENTS: start_id},
        count=_BATCH_SIZE,
        block=(_BLOCK_MS if start_id == ">" else None),
    )
    if not results:
        return
    for _stream, messages in results:
        for msg_id, msg_data in messages:
            await _handle_message(client, msg_id, msg_data)


async def _handle_message(client: Any, msg_id: str, msg_data: dict[str, Any]) -> None:
    received_at = datetime.now(timezone.utc)
    raw = msg_data.get("data", "{}")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        log.warning("consumer.unparseable_message", msg_id=msg_id)
        await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        return

    payload_dump = raw[:_MAX_PAYLOAD_DUMP]
    agent_id = payload.get("agent_id", "")
    event_id = payload.get("event_id")

    # ── 1. schema_version ────────────────────────────────────────────────────
    if not check_schema_version(payload):
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.invalid_schema, received_at, payload, payload_dump)
        return

    # ── 2. unknown_agent ─────────────────────────────────────────────────────
    shared_secret = _get_shared_secret(agent_id)
    if shared_secret is None:
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.unknown_agent, received_at, payload, payload_dump)
        return

    # ── 3. HMAC ───────────────────────────────────────────────────────────────
    if not verify_payload(shared_secret, payload):
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.invalid_signature, received_at, payload, payload_dump)
        return

    # ── 4. clock skew ─────────────────────────────────────────────────────────
    detected_at = _parse_datetime(payload.get("detected_at"))
    if detected_at is None or abs((received_at - detected_at).total_seconds()) > _CLOCK_SKEW_S:
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.clock_skew, received_at, payload, payload_dump)
        return

    # ── 5. rate limit ─────────────────────────────────────────────────────────
    if not _rate_limiter.check(agent_id):
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.rate_limited, received_at, payload, payload_dump)
        log.warning("consumer.rate_limited", agent_id=agent_id)
        return

    # ── 6. dedup ──────────────────────────────────────────────────────────────
    if event_id and _event_exists(event_id):
        # Re-entrega legítima: XACK + event_ack, no re-insertar, no auditar
        await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        if event_id:
            await _publish_event_ack(client, event_id, agent_id, shared_secret)
        log.info("consumer.event_dedup", event_id=event_id)
        return

    # ── camino feliz ───────────────────────────────────────────────────────────
    event = _ingest(payload, received_at, detected_at)
    await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
    if event is not None and event_id:
        await _publish_event_ack(client, event_id, agent_id, shared_secret)
        log.info("consumer.event_persisted", event_id=event_id, agent_id=agent_id)
        # Notificación asincrónica post-ingesta — fire-and-forget (D-C15-02)
        asyncio.create_task(notify_if_applicable(event))
    elif event is None:
        log.warning("consumer.event_ingest_skipped", event_id=event_id, reason="race_or_invalid_transition")


# ── helpers de ingesta ────────────────────────────────────────────────────────

def _ingest(payload: dict[str, Any], received_at: datetime, detected_at: datetime) -> Event | None:
    """Llama service.ingest_event; captura InvalidTransitionError."""
    try:
        return ingest_event(payload, received_at, detected_at)
    except InvalidTransitionError as exc:
        log.warning(
            "consumer.invalid_transition",
            from_status=str(exc.from_status),
            to_status=str(exc.to_status),
        )
        return None


# ── helpers de base de datos ─────────────────────────────────────────────────

def _get_shared_secret(agent_id: str) -> bytes | None:
    """Busca el agente en DB y retorna su shared_secret como bytes. None si no existe."""
    with Session(engine) as session:
        agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if agent is None:
        return None
    if not agent.shared_secret_hex:
        return None
    try:
        return bytes.fromhex(agent.shared_secret_hex)
    except ValueError:
        return None


def _event_exists(event_id: str) -> bool:
    with Session(engine) as session:
        existing = session.exec(select(Event).where(Event.event_id == event_id)).first()
    return existing is not None


# ── helpers de rechazo ────────────────────────────────────────────────────────

async def _reject(
    client: Any,
    msg_id: str,
    event_id: str | None,
    agent_id: str,
    reason: RejectionReason,
    received_at: datetime,
    payload: dict[str, Any],
    payload_dump: str,
) -> None:
    detected_at = _parse_datetime(payload.get("detected_at"))
    audit = RejectedEventAudit(
        event_id=event_id,
        agent_id=agent_id,
        reason=reason,
        received_at=received_at,
        detected_at=detected_at,
        payload_dump=payload_dump,
    )
    with Session(engine) as session:
        session.add(audit)
        session.commit()
    await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
    log.warning("consumer.event_rejected", event_id=event_id, agent_id=agent_id, reason=reason)


# ── helpers de publicación ────────────────────────────────────────────────────

async def _publish_event_ack(client: Any, event_id: str, agent_id: str, shared_secret: bytes) -> None:
    payload: dict[str, Any] = {
        "type": "event_ack",
        "event_id": event_id,
        "target_agent_id": agent_id,
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload["signature"] = sign_payload(shared_secret, payload)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    await client.xadd(STREAM_COMMANDS, {"data": data})


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
