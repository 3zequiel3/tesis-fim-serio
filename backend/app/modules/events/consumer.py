"""
Consumer del stream 'events' para el backend FIM Platform.

Consumer group: fim-backend (RN-56).
Validación en orden barato→caro (FIX-06, FIX-07, FIX-08):
  1. schema_version      → invalid_schema | schema_version_unsupported (RN-91,
                            enmendada por D37/RN-131 — ver check_schema_version)
  2. agent_id existe y no
     está revocado       → unknown_agent | descarte revocado
  3. HMAC-SHA256         → invalid_signature (RN-79)
  4. clock skew sobre
     sent_at (fallback
     a detected_at)      → clock_skew (RN-90, enmendada por D37/RN-131); distingue
                            unparseable / unparseable_sent_at / out_of_range
  5. event_id non-empty  → invalid_schema   (FIX-07)
  6. ingesta transaccional: dedup event_id antes de supersesión y rate limit
                          → XACK + event_ack sin re-insertar ni consumir rate (RN-73, FIX-06)

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
import functools
import inspect
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.core.config import settings
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
from app.modules.events.models import EventStatus, RejectedEventAudit, RejectionReason
from app.modules.events.service import (
    IngestDisposition,
    IngestOutcome,
    InvalidTransitionError,
    _ingest_event_outcome,
)

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
_DIFF_TEXT_REDACTION_MARKER = "[REDACTED:diff_text]"
_HEX_DUMP_REDACTION_MARKER = "[REDACTED:hex_dump]"
# US-09: hex_dump_before/hex_dump_after carry the same kind of bounded file
# content sample as diff_text — redacted the same way before ever touching
# the rejected-events audit trail.
_REDACTED_PAYLOAD_KEYS: dict[str, str] = {
    "diff_text": _DIFF_TEXT_REDACTION_MARKER,
    "hex_dump_before": _HEX_DUMP_REDACTION_MARKER,
    "hex_dump_after": _HEX_DUMP_REDACTION_MARKER,
}
_BLOCK_MS = 2000
_BATCH_SIZE = 50


def _build_payload_dump(raw: str, payload: dict[str, Any]) -> str:
    """Construye payload_dump para RejectedEventAudit, redactando diff_text.

    `payload` ya es el dict resultado de `json.loads(raw)` (ver
    _handle_message) — si trae alguna de _REDACTED_PAYLOAD_KEYS se
    re-serializa con esos valores reemplazados por su marcador antes de
    truncar a _MAX_PAYLOAD_DUMP (privacy hardening, evita que un diff o
    hex dump sensible quede en texto plano en la auditoría de rechazos). Si
    por algún motivo `payload` no es un dict (no debería ocurrir en este call
    site, ya que _handle_message ya validó que raw parsea), se conserva el
    comportamiento anterior de truncar el raw tal cual.
    """
    if isinstance(payload, dict) and any(k in payload for k in _REDACTED_PAYLOAD_KEYS):
        redacted = dict(payload)
        for key, marker in _REDACTED_PAYLOAD_KEYS.items():
            if key in redacted:
                redacted[key] = marker
        raw = json.dumps(redacted, sort_keys=True, separators=(",", ":"))
    return raw[:_MAX_PAYLOAD_DUMP]


# ── Rate limiter ──────────────────────────────────────────────────────────────

class _RateLimiter:
    """
    Ventana deslizante por agent_id (RN-88).

    Thread-safe (D75/RN-169, D-6 del design de `ingest-offload-blocking-db`):
    desde que `_get_agent_auth` e `_ingest` corren en `run_in_executor`
    (D-1 del design), `check()` se invoca desde un hilo del executor —llega
    por el `accept_new=lambda: _rate_limiter.check(agent_id)` que `_ingest`
    pasa a `_ingest_event_outcome`— mientras `seconds_until_available()` se
    invoca desde el event loop, vía `_reject` en el camino de rechazo. Las
    dos hacen lectura-modificación-escritura sobre el mismo `deque` del mismo
    bucket (`popleft` en la purga, `append` en el alta), así que un
    `threading.Lock` envuelve el cuerpo de `check()`, `seconds_until_available()`
    y `reset()`. Ya NO vale la premisa histórica "single-threaded asyncio":
    con el despacho secuencial (D-2 del design) no hay solapamiento efectivo
    hoy porque `_handle_message` espera a que `_ingest` termine antes de
    llegar a `_reject`, pero el invariante pasaría a depender de una
    propiedad no local del bucle de despacho, y un refactor futuro del
    despacho volvería esa dependencia una carrera real. El costo del lock es
    despreciable (sin contención real) y el algoritmo NO cambia: mismos
    `popleft`/`append`, mismo `_MIN_RETRY_AFTER_S`, mismo `retry_after`
    derivado de RN-88 / D37/RN-131.

    Límite y ventana salen de `Settings` (`rate_limit_ingest_events` /
    `rate_limit_ingest_window_seconds`, defaults 100 / 60.0 = comportamiento
    histórico). Los argumentos explícitos siguen existiendo para los tests que
    necesitan una ventana chica; `_RateLimiter()` sin argumentos lee la config.
    """

    # D37/RN-131: piso positivo pequeño para el retry_after derivado — un
    # remanente <=0 por una carrera entre check() y seconds_until_available()
    # nunca se expone tal cual, para no inducir un busy-loop en el agente.
    _MIN_RETRY_AFTER_S = 0.5

    def __init__(self, limit: int | None = None, window_s: float | None = None) -> None:
        self._limit = limit if limit is not None else settings.rate_limit_ingest_events
        self._window_s = (
            window_s if window_s is not None else settings.rate_limit_ingest_window_seconds
        )
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """Retorna True si está dentro del límite (registra el timestamp). False si excede."""
        with self._lock:
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
        with self._lock:
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
        with self._lock:
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
    # Despacho SECUENCIAL por contrato (D-2 del design de
    # `ingest-offload-blocking-db`, D75/RN-169): sin `gather`, sin
    # `TaskGroup`, sin `create_task` por mensaje. En todo momento hay un
    # solo `_handle_message` en vuelo — el orden FIFO (ítem 40) y la
    # ausencia de duplicados (ítem 41) del protocolo dependen de este mismo
    # bucle. La ganancia que D75 busca es de SOLAPAMIENTO: mientras el hilo
    # del executor resuelve la ingesta del evento N, el loop queda libre
    # para retomar la cadena de notificación fire-and-forget del evento
    # N-1 — no de paralelismo entre eventos del lote.
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

    payload_dump = _build_payload_dump(raw, payload)
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
    # D75/RN-169 deroga la premisa previa ("resolver la única fila de
    # autenticación evita un cambio de executor redundante"): el carril
    # ordenado es precisamente donde el bloqueo se acumula, porque cada
    # evento espera a que el anterior termine su viaje a la base. Medido:
    # `_get_agent_auth` real cuesta 1,329 ms — sobre 2.893 eventos eso es
    # ~3,8 s de event loop bloqueado sólo en esta llamada. El carril de
    # rechazo del mismo archivo ya usaba `run_in_executor` (`:420`, `:554`,
    # `:563`); este call site replica exactamente ese patrón.
    agent_auth = await loop.run_in_executor(None, _get_agent_auth, agent_id)
    if agent_auth.shared_secret is None:
        await _reject(client, msg_id, event_id, agent_id, RejectionReason.unknown_agent, received_at, payload, payload_dump)
        return

    # ── 2.5 revoked agent — FIX-02 / RN-122 ──────────────────────────────────
    # D-4/D37: sin respuesta, igual que invalid_signature/unknown_agent — un
    # agente revocado no es un destinatario válido para un mensaje firmado.
    if agent_auth.revoked:
        log.info("consumer.agent_revoked.discard", agent_id=agent_id, event_id=event_id)
        await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        return

    shared_secret = agent_auth.shared_secret

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


    # ── camino feliz ───────────────────────────────────────────────────────────
    try:
        # D75/RN-169: `_ingest` abre una `Session` bloqueante (`SELECT` de
        # dedup + `INSERT` + `commit`, medidos en ~1,564 ms el INSERT+commit)
        # y corría síncrona dentro de la corrutina — el mismo cuello de
        # botella que `_get_agent_auth` arriba. `_ingest` NO cambia de
        # interfaz (D-1 del design): mismo cuerpo, misma firma, mismas
        # excepciones. `run_in_executor` re-lanza en el `await`, así que el
        # `try/except InvalidTransitionError / SQLAlchemyError` de abajo
        # sigue capturando exactamente lo mismo, en el mismo lugar, con la
        # misma semántica de XACK / no-XACK que antes del cambio.
        outcome = await loop.run_in_executor(
            None, functools.partial(_ingest, payload, received_at, detected_at, agent_id)
        )
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

    # Compatibilidad con dobles de prueba anteriores al resultado tipado.
    if outcome is None:
        outcome = IngestOutcome(IngestDisposition.supersede_race)

    if outcome.disposition == IngestDisposition.rate_limited:
        await _reject(
            client, msg_id, event_id, agent_id, RejectionReason.rate_limited,
            received_at, payload, payload_dump, shared_secret=shared_secret,
        )
        log.warning("consumer.rate_limited", agent_id=agent_id)
        return

    if outcome.disposition == IngestDisposition.duplicate:
        await _ack_with_event_ack(client, msg_id, event_id, agent_id, shared_secret)
        log.info("consumer.event_dedup", event_id=event_id)
        return

    if outcome.disposition == IngestDisposition.persisted and outcome.event is not None:
        await _ack_with_event_ack(client, msg_id, event_id, agent_id, shared_secret)
        log.info("consumer.event_persisted", event_id=event_id, agent_id=agent_id)
        _fire_and_forget(notify_if_applicable(outcome.event))
    else:
        # Una transición concurrente dejó otro pending como representación
        # activa. Resolver esta entrega con el mismo ACK atómico.
        log.info("consumer.event_ingest_skipped", event_id=event_id, reason="supersede_race")
        await _ack_with_event_ack(client, msg_id, event_id, agent_id, shared_secret)


# ── helpers de ingesta ────────────────────────────────────────────────────────

def _ingest(
    payload: dict[str, Any], received_at: datetime, detected_at: datetime, agent_id: str,
) -> IngestOutcome:
    """
    Llama service.ingest_event y devuelve una taxonomía explícita:
    - persisted       → inserción confirmada
    - duplicate       → reentrega sin reinserción ni consumo de rate limit
    - supersede_race  → descarte legítimo por carrera
    - rate_limited    → evento nuevo sin cupo
    - Lanza InvalidTransitionError → dato inválido, no reintentable
    - Lanza SQLAlchemyError        → error transitorio, el caller NO hace XACK
    """
    return _ingest_event_outcome(
        payload,
        received_at,
        detected_at,
        accept_new=lambda: _rate_limiter.check(agent_id),
    )


# ── helpers de base de datos ─────────────────────────────────────────────────

@dataclass(frozen=True)
class _AgentAuth:
    shared_secret: bytes | None
    revoked: bool


def _get_agent_auth(agent_id: str) -> _AgentAuth:
    """Resuelve credencial HMAC y revocación con una sola consulta."""
    with Session(engine) as session:
        agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if agent is None:
        return _AgentAuth(None, False)
    if not agent.shared_secret_hex:
        return _AgentAuth(None, agent.status == AgentStatus.revoked)
    try:
        secret = bytes.fromhex(agent.shared_secret_hex)
    except ValueError:
        secret = None
    return _AgentAuth(secret, agent.status == AgentStatus.revoked)


def _get_shared_secret(agent_id: str) -> bytes | None:
    """Helper compatible para rechazos y consumidores focales."""
    return _get_agent_auth(agent_id).shared_secret


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
    data = _build_event_ack(event_id, agent_id, shared_secret)
    await client.xadd(STREAM_COMMANDS, {"data": data})


def _build_event_ack(event_id: str, agent_id: str, shared_secret: bytes) -> str:
    payload: dict[str, Any] = {
        "type": "event_ack",
        "event_id": event_id,
        "target_agent_id": agent_id,
        "schema_version": SCHEMA_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload["signature"] = sign_payload(shared_secret, payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


async def _ack_with_event_ack(
    client: Any,
    msg_id: str,
    event_id: str,
    agent_id: str,
    shared_secret: bytes,
) -> None:
    """Publica el ACK firmado y elimina el evento de la PEL atómicamente."""
    data = _build_event_ack(event_id, agent_id, shared_secret)
    pipeline_factory = getattr(client, "pipeline", None)
    if pipeline_factory is not None and not inspect.iscoroutinefunction(pipeline_factory):
        pipe = pipeline_factory(transaction=True)
        pipe.xadd(STREAM_COMMANDS, {"data": data})
        pipe.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)
        await pipe.execute()
        return

    # Los fakes asyncio mínimos no exponen el factory sincrónico de redis-py.
    # Publicar primero evita un XACK parcial cuando falla la respuesta.
    await client.xadd(STREAM_COMMANDS, {"data": data})
    await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)


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
