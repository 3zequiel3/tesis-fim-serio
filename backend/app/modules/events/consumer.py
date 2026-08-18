"""
Consumer del stream 'events' para el backend FIM Platform.

Consumer group: fim-backend (RN-56).
Validación en orden barato→caro (FIX-06, FIX-07, FIX-08):
  1. schema_version      → invalid_schema | schema_version_unsupported (RN-91,
                            enmendada por D37/RN-131 — ver check_schema_version)
  2. agent_id existe     → unknown_agent
  3. HMAC-SHA256         → invalid_signature (RN-79)
  4. clock skew sobre
     sent_at (fallback
     a detected_at)      → clock_skew (RN-90, enmendada por D37/RN-131); distingue
                            unparseable / unparseable_sent_at / out_of_range
  5. event_id non-empty  → invalid_schema   (FIX-07)
  6. dedup event_id      → XACK + event_ack sin re-insertar ni consumir rate (RN-73, FIX-06)
  7. rate limit          → rate_limited     (RN-88, D7; solo eventos genuinamente nuevos)

Camino feliz: ingest_event (service), XACK, publica event_ack firmado (RN-73, D5).

Respuesta tipada a todo evento (D37/RN-131 — enmienda D4/RN-105, prevalece
sobre la frase "sin event_ack" que documentaba el rechazo):

  | Motivo                                        | Respuesta              |
  |------------------------------------------------|-------------------------|
  | ingesta exitosa · duplicate_event · superseded-race | event_ack          |
  | invalid_schema · clock_skew · InvalidTransitionError | event_nack terminal (sin retry_after) |
  | rate_limited · schema_version_unsupported     | event_nack con retry_after (evento se conserva) |
  | invalid_signature · unknown_agent · agente revocado | sin respuesta (D-4: no hay a quién firmarle una respuesta verificable) |

Todo rechazo sigue insertando RejectedEventAudit y ejecutando XACK, sin excepción.
El SQLAlchemyError transitorio sigue sin XACK y sin respuesta (queda en la PEL).
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
from app.modules.agents.models import Agent, AgentStatus
from app.modules.alerts.service import notify_if_applicable
from app.modules.events.models import Event, EventStatus, RejectedEventAudit, RejectionReason
from app.modules.events.service import InvalidTransitionError, ingest_event

log = structlog.get_logger()

# RN-90, enmendada por D37/RN-131: la ventana de 5 minutos se evalúa sobre
# `sent_at` cuando el payload lo trae (sellado al publicar/republicar); si no
# lo trae (agente anterior a D37) se evalúa sobre `detected_at`, comportamiento
# previo íntegro. `detected_at` en sí mismo dejó de tener ventana: es verdad
# forense, no señal de replay.
_CLOCK_SKEW_S = 300  # 5 minutos

# D37/RN-131: retry_after fijo para el nack retenible de schema_version_unsupported.
# No se deriva del rate limiter — no hay relación con el presupuesto de eventos,
# es "el backend todavía no se actualizó", así que un valor fijo del orden del
# techo que el agente acepta (D37, config.publisher.max_retry_after_s = 60 s
# por defecto) es tan bueno como cualquier otro.
_SCHEMA_VERSION_UNSUPPORTED_RETRY_S = 60.0

# D37/RN-131: motivos para los que NUNCA se firma una respuesta. Ninguno de
# los dos permite identificar de forma segura al destinatario o firmarle una
# respuesta verificable (D-4 del design): invalid_signature no prueba que el
# remitente sea quien dice ser, y unknown_agent no tiene shared_secret que
# usar. Responder convertiría al backend en un oráculo de agent_id existentes.
_SILENT_REJECTION_REASONS = frozenset({RejectionReason.invalid_signature, RejectionReason.unknown_agent})

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

    # D37/RN-131: piso positivo pequeño para el retry_after derivado — un
    # remanente <=0 por una carrera entre check() y seconds_until_available()
    # nunca se expone tal cual, para no inducir un busy-loop en el agente.
    _MIN_RETRY_AFTER_S = 0.5

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

    def seconds_until_available(self, key: str) -> float:
        """
        Segundos hasta que se libere cupo para `key` (D37/RN-131, RN-88): usado
        para derivar el `retry_after` del nack de rate_limited. NO expone el
        `deque` — este es el único punto por el que el consumer conoce el
        estado del limiter para ese fin.

        0.0 si ya hay cupo. Si la ventana está llena, el remanente hasta que
        el timestamp más viejo salga de la ventana, nunca por debajo de
        `_MIN_RETRY_AFTER_S`.
        """
        now = time.monotonic()
        cutoff = now - self._window_s
        bucket = self._buckets.get(key)
        if not bucket:
            return 0.0
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) < self._limit:
            return 0.0
        remaining = self._window_s - (now - bucket[0])
        return max(remaining, self._MIN_RETRY_AFTER_S)

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

    # ── 1. schema_version (D37/RN-131: distingue payload ilegible de versión
    #      adelantada — ver check_schema_version) ────────────────────────────
    schema_check = check_schema_version(payload)
    if schema_check != "ok":
        schema_reason = (
            RejectionReason.invalid_schema
            if schema_check == "invalid"
            else RejectionReason.schema_version_unsupported
        )
        # D-4: acá todavía no se resolvió el shared_secret (eso pasa en el
        # paso 2) — _reject lo resuelve internamente y solo firma el nack si
        # el agente existe; si no, colapsa en silencio como unknown_agent.
        await _reject(client, msg_id, event_id, agent_id, schema_reason, received_at, payload, payload_dump)
        return

    # ── 2. unknown_agent ─────────────────────────────────────────────────────
    loop = asyncio.get_running_loop()
    shared_secret = await loop.run_in_executor(None, _get_shared_secret, agent_id)
    if shared_secret is None:
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.unknown_agent, received_at, payload, payload_dump)
        return

    # ── 2.5 revoked agent — FIX-02 / RN-122 ──────────────────────────────────
    # D-4/D37: sin respuesta, igual que invalid_signature/unknown_agent — un
    # agente revocado no es un destinatario válido para un mensaje firmado.
    is_revoked = await loop.run_in_executor(None, _is_agent_revoked, agent_id)
    if is_revoked:
        log.info("consumer.agent_revoked.discard", agent_id=agent_id, event_id=event_id)
        await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        return

    # ── 3. HMAC ───────────────────────────────────────────────────────────────
    if not verify_payload(shared_secret, payload):
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.invalid_signature, received_at, payload, payload_dump)
        return

    # ── 4. clock skew (D37/RN-131: ventana sobre sent_at, detected_at sin ventana) ──
    # FIX-08: _parse_datetime siempre retorna UTC-aware o None; distinguir los sub-casos.
    # detected_at MUST seguir siendo parseable (verdad forense, se persiste tal cual),
    # pero deja de tener ventana: un detected_at de hace horas es exactamente lo que
    # produce una cola que sobrevivió un corte largo, y MUST aceptarse por este criterio.
    detected_at = _parse_datetime(payload.get("detected_at"))
    if detected_at is None:
        log.warning(
            "consumer.clock_skew.unparseable",
            event_id=event_id,
            agent_id=agent_id,
            detected_at=payload.get("detected_at"),
        )
        await _reject(
            client, msg_id, event_id, agent_id, RejectionReason.clock_skew, received_at, payload, payload_dump,
            shared_secret=shared_secret,
        )
        return

    sent_at_raw = payload.get("sent_at")
    if sent_at_raw is not None:
        sent_at = _parse_datetime(sent_at_raw)
        if sent_at is None:
            log.warning(
                "consumer.clock_skew.unparseable_sent_at",
                event_id=event_id,
                agent_id=agent_id,
                sent_at=sent_at_raw,
            )
            await _reject(
                client, msg_id, event_id, agent_id, RejectionReason.clock_skew, received_at, payload, payload_dump,
                shared_secret=shared_secret,
            )
            return
        if abs((received_at - sent_at).total_seconds()) > _CLOCK_SKEW_S:
            log.warning(
                "consumer.clock_skew.out_of_range",
                event_id=event_id,
                agent_id=agent_id,
            )
            await _reject(
                client, msg_id, event_id, agent_id, RejectionReason.clock_skew, received_at, payload, payload_dump,
                shared_secret=shared_secret,
            )
            return
    else:
        # Ausencia = comportamiento anterior (D33/D35/D36): agente sin actualizar
        # a D37 todavía. La ventana se evalúa sobre detected_at, tal como antes.
        log.debug("consumer.clock_skew.sent_at_absent_fallback", event_id=event_id, agent_id=agent_id)
        if abs((received_at - detected_at).total_seconds()) > _CLOCK_SKEW_S:
            log.warning(
                "consumer.clock_skew.out_of_range",
                event_id=event_id,
                agent_id=agent_id,
            )
            await _reject(
                client, msg_id, event_id, agent_id, RejectionReason.clock_skew, received_at, payload, payload_dump,
                shared_secret=shared_secret,
            )
            return

    # ── 5. event_id non-empty ─────────────────────────────────────────────────
    # FIX-07: validar explícitamente que event_id sea una cadena no-vacía.
    # D-4: sin event_id no hay a qué dirigir un nack — este es el único
    # invalid_schema mudo; _reject lo detecta y no responde.
    if not event_id:
        await _reject(
            client, msg_id, event_id, agent_id, RejectionReason.invalid_schema, received_at, payload, payload_dump,
            shared_secret=shared_secret,
        )
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
        await _reject(
            client, msg_id, event_id, agent_id, RejectionReason.rate_limited, received_at, payload, payload_dump,
            shared_secret=shared_secret,
        )
        log.warning("consumer.rate_limited", agent_id=agent_id)
        return

    # ── camino feliz ───────────────────────────────────────────────────────────
    try:
        event = _ingest(payload, received_at, detected_at)
    except InvalidTransitionError as exc:
        # Dato inválido, no reintentable → XACK + audit log + nack terminal
        # (D-3 del design): sin la respuesta, el agente republica para
        # siempre un evento que nunca va a entrar.
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
        if event_id:
            await _publish_event_nack(client, event_id, agent_id, shared_secret, RejectionReason.invalid_schema)
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
        # Skip legítimo (carrera en mark_superseded, sigue habiendo un pending
        # activo) → XACK sin re-insert, y event_ack (D-3): para el agente el
        # evento está resuelto — el pending activo ya lo representa — y sin
        # respuesta reintentaría para siempre.
        await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        log.info("consumer.event_ingest_skipped", event_id=event_id, reason="supersede_race")
        if event_id:
            await _publish_event_ack(client, event_id, agent_id, shared_secret)


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


def _is_agent_revoked(agent_id: str) -> bool:
    """Retorna True si el agente existe y su status es revoked. FIX-02 / RN-122."""
    with Session(engine) as session:
        agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if agent is None:
        return False
    return agent.status == AgentStatus.revoked


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
    shared_secret: bytes | None = None,
) -> None:
    """
    Persiste el rechazo en `rejected_events_audit`, ejecuta `XACK` (sin
    excepción, siempre) y, después, emite la respuesta tipada que le
    corresponda al `reason` según la matriz de D37/RN-131:

      - `invalid_signature` / `unknown_agent` → nunca responde
        (_SILENT_REJECTION_REASONS, D-4).
      - sin `event_id` → nunca responde (no hay a quién dirigirla).
      - `rate_limited` / `schema_version_unsupported` → nack con
        `retry_after` (el evento se conserva del lado del agente).
      - el resto (`invalid_schema`, `clock_skew`) → nack terminal, sin
        `retry_after`.

    `shared_secret` es opcional: para los rechazos que ocurren ANTES de
    resolver el secreto (schema_version, paso 1) se resuelve acá mismo, y la
    ausencia de agente colapsa en silencio — mismo criterio que unknown_agent
    (D-4 del design).
    """
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

    if reason in _SILENT_REJECTION_REASONS or not event_id:
        return

    secret = shared_secret
    if secret is None:
        secret = await loop.run_in_executor(None, _get_shared_secret, agent_id)
    if secret is None:
        # D-4: sin agente conocido no hay secreto con el que firmar una
        # respuesta verificable. Colapsa en el mismo silencio que unknown_agent.
        return

    retry_after: float | None = None
    if reason == RejectionReason.rate_limited:
        retry_after = _rate_limiter.seconds_until_available(agent_id)
    elif reason == RejectionReason.schema_version_unsupported:
        retry_after = _SCHEMA_VERSION_UNSUPPORTED_RETRY_S

    await _publish_event_nack(client, event_id, agent_id, secret, reason, retry_after)


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


async def _publish_event_nack(
    client: Any,
    event_id: str,
    agent_id: str,
    shared_secret: bytes,
    reason: RejectionReason,
    retry_after: float | None = None,
) -> None:
    """
    Publica `event_nack` firmado al stream `commands` (D37/RN-131). Calcado
    de `_publish_event_ack`. `retry_after` (segundos, float) SOLO se incluye
    cuando no es None — su ausencia es lo que hace terminal al nack.
    """
    payload: dict[str, Any] = {
        "type": "event_nack",
        "event_id": event_id,
        "target_agent_id": agent_id,
        "reason": reason.value if isinstance(reason, RejectionReason) else reason,
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if retry_after is not None:
        payload["retry_after"] = retry_after
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
