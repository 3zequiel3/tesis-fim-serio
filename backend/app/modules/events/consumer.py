"""
Consumer del stream 'events' para el backend FIM Platform.

Consumer group: fim-backend (RN-56).
Validación en orden barato→caro (FIX-06, FIX-07, FIX-08):
  1. schema_version     → invalid_schema   (RN-91)
  2. agent_id existe    → unknown_agent
  3. HMAC-SHA256        → invalid_signature (RN-79)
  4. clock skew ≤5min   → clock_skew       (RN-90); distingue unparseable vs out_of_range
  5. event_id non-empty → invalid_schema   (FIX-07)
  6. dedup event_id     → XACK + event_ack sin re-insertar ni consumir rate (RN-73, FIX-06)
  7. rate limit         → rate_limited     (RN-88, D7; solo eventos genuinamente nuevos)

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
from sqlalchemy.exc import SQLAlchemyError
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

_background_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
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
    while True:
        try:
            await _ensure_group(client)
            # Releer pendientes al arrancar (RN-76)
            try:
                await _process_batch(client, "0")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("consumer.startup_pending_error", error=str(exc))
            break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("consumer.startup_error", error=str(exc))
            await asyncio.sleep(1)
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
    loop = asyncio.get_running_loop()
    shared_secret = await loop.run_in_executor(None, _get_shared_secret, agent_id)
    if shared_secret is None:
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.unknown_agent, received_at, payload, payload_dump)
        return

    # ── 3. HMAC ───────────────────────────────────────────────────────────────
    if not verify_payload(shared_secret, payload):
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.invalid_signature, received_at, payload, payload_dump)
        return

    # ── 4. clock skew ─────────────────────────────────────────────────────────
    # FIX-08: _parse_datetime siempre retorna UTC-aware o None; distinguir los dos sub-casos
    detected_at = _parse_datetime(payload.get("detected_at"))
    if detected_at is None:
        log.warning(
            "consumer.clock_skew.unparseable",
            event_id=event_id,
            agent_id=agent_id,
            detected_at=payload.get("detected_at"),
        )
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.clock_skew, received_at, payload, payload_dump)
        return
    if abs((received_at - detected_at).total_seconds()) > _CLOCK_SKEW_S:
        log.warning(
            "consumer.clock_skew.out_of_range",
            event_id=event_id,
            agent_id=agent_id,
        )
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.clock_skew, received_at, payload, payload_dump)
        return

    # ── 5. event_id non-empty ─────────────────────────────────────────────────
    # FIX-07: validar explícitamente que event_id sea una cadena no-vacía
    if not event_id:
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.invalid_schema, received_at, payload, payload_dump)
        return

    # ── 6. dedup ──────────────────────────────────────────────────────────────
    # FIX-06: dedup ANTES del rate limit — re-entregas no consumen presupuesto
    event_exists = await loop.run_in_executor(None, _event_exists, event_id)
    if event_exists:
        # Re-entrega legítima: XACK + event_ack, no re-insertar, no auditar, no consumir rate
        await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        await _publish_event_ack(client, event_id, agent_id, shared_secret)
        log.info("consumer.event_dedup", event_id=event_id)
        return

    # ── 7. rate limit ─────────────────────────────────────────────────────────
    # FIX-06: rate limit DESPUÉS del dedup — solo para eventos genuinamente nuevos
    if not _rate_limiter.check(agent_id):
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.rate_limited, received_at, payload, payload_dump)
        log.warning("consumer.rate_limited", agent_id=agent_id)
        return

    # ── camino feliz ───────────────────────────────────────────────────────────
    try:
        event = _ingest(payload, received_at, detected_at)
    except InvalidTransitionError as exc:
        # Dato inválido, no reintentable → XACK + audit log
        await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        log.warning(
            "consumer.invalid_transition",
            event_id=event_id,
            from_status=str(exc.from_status),
            to_status=str(exc.to_status),
        )
        audit = RejectedEventAudit(
            event_id=event_id,
            agent_id=agent_id,
            reason=RejectionReason.invalid_schema,
            received_at=received_at,
            detected_at=detected_at,
            payload_dump=payload_dump,
        )
        await loop.run_in_executor(None, _write_rejection_audit, audit)
        return
    except SQLAlchemyError:
        # Error transitorio de DB → NO XACK, dejar en PEL para reintento
        log.error("consumer.db_error", event_id=event_id, exc_info=True)
        return

    if event is not None:
        # Éxito → XACK + event_ack + notificación
        await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        if event_id:
            await _publish_event_ack(client, event_id, agent_id, shared_secret)
        log.info("consumer.event_persisted", event_id=event_id, agent_id=agent_id)
        _fire_and_forget(notify_if_applicable(event))
    else:
        # Skip legítimo (carrera en mark_superseded) → XACK sin re-insert
        await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        log.info("consumer.event_ingest_skipped", event_id=event_id, reason="supersede_race")


# ── helpers de ingesta ────────────────────────────────────────────────────────

def _ingest(payload: dict[str, Any], received_at: datetime, detected_at: datetime) -> Event | None:
    """
    Llama service.ingest_event y surfacea los outcomes con taxonomía explícita:
    - Retorna Event  → éxito
    - Retorna None   → skip legítimo (carrera en mark_superseded)
    - Lanza InvalidTransitionError → dato inválido, no reintentable
    - Lanza SQLAlchemyError        → error transitorio, el caller NO hace XACK
    """
    return ingest_event(payload, received_at, detected_at)


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


def _write_rejection_audit(audit: RejectedEventAudit) -> None:
    with Session(engine) as session:
        session.add(audit)
        session.commit()


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
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write_rejection_audit, audit)
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
    """
    Parsea un valor como ISO-8601 y siempre retorna un datetime UTC-aware o None.

    FIX-08: si el parsed datetime tiene tzinfo se convierte a UTC; si es naive se
    asume UTC y se agrega tzinfo=timezone.utc. Esto evita TypeError al restar
    datetimes con distintas awareness.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
