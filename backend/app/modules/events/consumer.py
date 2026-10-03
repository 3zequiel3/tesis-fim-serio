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
import contextvars
import functools
import inspect
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
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
from app.modules.agents.secret_wrap import unwrap_agent_secret
from app.modules.alerts.service import notify_if_applicable
from app.modules.events.models import EventStatus, RejectedEventAudit, RejectionReason
from app.modules.events.service import (
    IngestBatchItem,
    IngestDisposition,
    IngestOutcome,
    InvalidTransitionError,
    _ingest_batch,
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

# D87/RN-181: ACK accumulator of the batch being dispatched by `_process_batch`.
# Carried in a ContextVar and not as a parameter of `_handle_message` because
# `test_batch_dispatch_is_strictly_sequential` substitutes `_handle_message` with a
# three-argument double whose assertions must stay untouched. It is safe because
# dispatch is strictly sequential (D75/RN-169): at most one batch is in flight per
# task. `None` outside a batch, which keeps the immediate emission.
_ack_batch_var: contextvars.ContextVar[list[tuple[str, str]] | None] = contextvars.ContextVar(
    "consumer_ack_batch", default=None
)


# Change `ingest-batched-persistence` (amplification of 2026-10-03 of D87/RN-181): the
# validated candidates of the batch being dispatched by `_process_batch`. Same reason as
# `_ack_batch_var`: `_handle_message` keeps its three-argument signature (the double of
# `test_batch_dispatch_is_strictly_sequential`). `None` outside a batch, which keeps the
# per-event ingest of the direct call.
@dataclass(slots=True)
class _IngestCandidate:
    msg_id: str
    payload: dict[str, Any]
    received_at: datetime
    detected_at: datetime
    agent_id: str
    event_id: str
    shared_secret: bytes
    payload_dump: str
    auth_ms: float
    auth_cache_hit: bool
    t_start: float  # perf_counter at the start of `_handle_message`
    validated_at: float  # perf_counter when the candidate cleared validation


_ingest_batch_var: contextvars.ContextVar[list[_IngestCandidate] | None] = contextvars.ContextVar(
    "consumer_ingest_batch", default=None
)


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

@dataclass(slots=True)
class _TokenBucket:
    """Mutable per-agent bucket state: available tokens and last refill instant."""

    tokens: float
    updated_at: float


class _RateLimiter:
    """
    Token bucket per agent_id (RN-88, D85/RN-179).

    Each agent has a bucket of capacity `burst` that refills lazily at
    `rate_per_s` tokens per second; a new event consumes one token. An agent
    never seen before starts with a full bucket, so the replay that follows a
    reconnection is admitted without rejections. Sustained regime: 100
    events/min; burst: 3,000 events (see `Settings`).

    Thread-safe (D75/RN-169, D-6 of the design of `ingest-offload-blocking-db`,
    kept by D-7 of `ingest-token-bucket-rate-limit`): `check()` runs in a
    thread of the executor — it arrives through the
    `accept_new=lambda: _rate_limiter.check(agent_id)` that `_ingest` passes to
    `_ingest_event_outcome` — while `seconds_until_available()` runs in the
    event loop, through `_reject` on the rejection path. Both do
    read-modify-write on the same token record of the same agent, so a single
    `threading.Lock` wraps the body of `check()`, `seconds_until_available()`
    and `reset()`. With the sequential dispatch there is no effective overlap
    today, but the invariant would depend on a non-local property of the
    dispatch loop, and a future refactor would turn that dependency into a
    real race. The lock cost is negligible (no real contention).

    The clock is injectable (`clock`, monotonic by default) so tests advance
    time explicitly instead of sleeping. `retry_after` semantics (D37/RN-131):
    `seconds_until_available()` is the time until the agent accumulates the
    missing token, never below `_MIN_RETRY_AFTER_S`. State lives in process
    memory and is lost on restart (RN-76).

    Rate and burst come from `Settings` (`rate_limit_ingest_rate_per_s` /
    `rate_limit_ingest_burst`); explicit arguments exist for tests that need a
    small bucket. `_RateLimiter()` without arguments reads the config.
    """

    # D37/RN-131: small positive floor for the derived retry_after — a
    # remainder <=0 caused by a race between check() and seconds_until_available()
    # is never exposed as is, to avoid inducing a busy-loop in the agent.
    _MIN_RETRY_AFTER_S = 0.5

    def __init__(
        self,
        rate_per_s: float | None = None,
        burst: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate_per_s = (
            rate_per_s if rate_per_s is not None else settings.rate_limit_ingest_rate_per_s
        )
        self._burst = burst if burst is not None else settings.rate_limit_ingest_burst
        self._clock = clock
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = threading.Lock()

    def _refill(self, bucket: _TokenBucket, now: float) -> None:
        """Lazy refill, capped at `burst`. Must be called with the lock held."""
        elapsed = now - bucket.updated_at
        bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rate_per_s)
        bucket.updated_at = now

    def check(self, key: str) -> bool:
        """Return True and consume one token if available; False (tokens untouched) otherwise."""
        with self._lock:
            now = self._clock()
            bucket = self._buckets.get(key)
            if bucket is None:
                # D-2: an unseen agent starts with a full bucket.
                bucket = self._buckets[key] = _TokenBucket(tokens=float(self._burst), updated_at=now)
            else:
                self._refill(bucket, now)
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return True
            return False

    def refund(self, key: str, n: int) -> None:
        """
        Give back `n` tokens to `key`, never above `burst` (D-6 of
        `ingest-batched-persistence`): a batch whose transaction rolled back spent
        tokens on events that were not persisted, and its PEL re-delivery would spend
        them again. An unknown key has no state to restore and none is created.
        """
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return
            self._refill(bucket, self._clock())
            bucket.tokens = min(float(self._burst), bucket.tokens + n)

    def seconds_until_available(self, key: str) -> float:
        """
        Seconds until `key` has a token again (D37/RN-131, RN-88): used to derive
        the `retry_after` of the rate_limited nack. It does not expose the
        bucket — this is the only point through which the consumer knows the
        limiter state for that purpose.

        0.0 if a token is available or the key has no state (no record is
        created). Otherwise the time to accumulate the missing token, never
        below `_MIN_RETRY_AFTER_S`.
        """
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return 0.0
            self._refill(bucket, self._clock())
            if bucket.tokens >= 1:
                return 0.0
            return max((1 - bucket.tokens) / self._rate_per_s, self._MIN_RETRY_AFTER_S)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_rate_limiter = _RateLimiter()


def reset_rate_limiter() -> None:
    """Clears all agent buckets. Used in tests."""
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
            # D87/RN-181: if Valkey came back without the consumer group, every
            # read fails with NOGROUP forever. Recreate it in place instead of
            # waiting for a restart of the backend. The group is recreated from
            # id "0" (same as at startup), NOT "$": with "$" the entries published
            # between Valkey coming back and the recreation would never be read;
            # with "0" nothing in the stream is skipped (entries already
            # persisted end in dedup, stale ones in a clock_skew rejection).
            if "NOGROUP" in str(exc):
                try:
                    await _ensure_group(client)
                    log.warning("consumer.group_recreated", group=CONSUMER_GROUP)
                    await _process_batch(client, "0")
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception as recreate_exc:
                    # Valkey not answering yet (or the PEL re-read failed): same
                    # treatment as any other error; the next iteration retries
                    # and sees NOGROUP again if the group is still missing.
                    exc = recreate_exc
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
    # D87/RN-181: `event_ack` + `XACK` of every event resolved with an
    # `event_ack` are accumulated here and emitted together once the batch is
    # done, in a single transactional pipeline. An entry is appended only after
    # the `COMMIT` that persisted its event returned (see `_persist_batch`).
    acks: list[tuple[str, str]] = []
    batch_token = _ack_batch_var.set(acks)
    # Amplification of 2026-10-03 of D87/RN-181 (change `ingest-batched-persistence`):
    # the messages that clear validation are collected here and persisted together,
    # in one transaction, after the loop. Validation rejections stay immediate.
    candidates: list[_IngestCandidate] = []
    candidates_token = _ingest_batch_var.set(candidates)
    batch_size = 0
    batch_stats: dict[str, Any] = {}
    # Despacho SECUENCIAL por contrato (D-2 del design de
    # `ingest-offload-blocking-db`, D75/RN-169): sin `gather`, sin
    # `TaskGroup`, sin `create_task` por mensaje. En todo momento hay un
    # solo `_handle_message` en vuelo — el orden FIFO (ítem 40) y la
    # ausencia de duplicados (ítem 41) del protocolo dependen de este mismo
    # bucle. La ganancia que D75 busca es de SOLAPAMIENTO: mientras el hilo
    # del executor resuelve la ingesta, el loop queda libre para retomar la
    # cadena de notificación fire-and-forget del lote anterior — no de
    # paralelismo entre eventos del lote. La persistencia del lote hace UNA
    # sola salida al executor (D-2 de `ingest-batched-persistence`), después
    # del bucle.
    try:
        try:
            for _stream, messages in results:
                for msg_id, msg_data in messages:
                    batch_size += 1
                    await _handle_message(client, msg_id, msg_data)
        finally:
            _ingest_batch_var.reset(candidates_token)
        if candidates:
            await _run_to_completion(_persist_batch(client, candidates, acks, batch_stats))
    finally:
        _ack_batch_var.reset(batch_token)
        # Flush even if a later message of the batch raised: the events already
        # persisted must not wait in the PEL for nothing. If the flush itself
        # fails the entries stay in the PEL (re-delivery is idempotent: dedup by
        # event_id) and the error propagates to the loop, without retrying here.
        ack_count = len(acks)
        flush_started = time.perf_counter()
        await _flush_acks(client, acks)
        if settings.fim_profile_ingest:
            log.info(
                "consumer.timing",
                scope="batch",
                batch_size=batch_size,
                acks=ack_count,
                ack_flush_ms=round((time.perf_counter() - flush_started) * 1000, 3),
                **batch_stats,
            )


# Upper bound for finishing a batch whose consumer task was cancelled (shutdown).
_PERSIST_CANCEL_GRACE_S = 10.0


async def _run_to_completion(coro: Any) -> None:
    """
    Run the persist + effects section of a batch so a cancellation (backend shutdown) cannot
    cut it in half: the executor commits the whole batch even after the awaiting coroutine is
    cancelled, and without its effects up to 50 committed events would never be acknowledged
    nor notified. On cancellation, wait (bounded) for the section to finish, then re-raise.
    """
    task = asyncio.ensure_future(coro)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        if not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), _PERSIST_CANCEL_GRACE_S)
            except asyncio.TimeoutError:
                log.warning("consumer.persist_cancel_timeout", grace_s=_PERSIST_CANCEL_GRACE_S)
            except BaseException:  # noqa: BLE001 - a second cancel or a failure: give up waiting
                pass
        if task.done() and not task.cancelled():
            task.exception()  # retrieved, so it is not reported as never-retrieved
        raise


async def _persist_batch(
    client: Any,
    candidates: list[_IngestCandidate],
    acks: list[tuple[str, str]],
    batch_stats: dict[str, Any],
) -> None:
    """
    Persist the validated candidates of a batch in ONE transaction and, once the
    `COMMIT` returned, apply the effects in stream order (D-2, D-4, D-5 of
    `ingest-batched-persistence`; amplification of 2026-10-03 of D87/RN-181).

    One call to the ingest executor per batch, no concurrency between candidates
    (D75/RN-169). Every effect that depends on the outcome of the ingest
    (`event_ack` + `XACK`, the `rate_limited` and `InvalidTransitionError` replies,
    the scheduling of the notification) runs after the `COMMIT`: before it nothing is
    known to be durable, and a rolled-back batch must leave every candidate in the PEL.
    """
    loop = asyncio.get_running_loop()
    items = [IngestBatchItem(c.payload, c.received_at, c.detected_at, c.agent_id) for c in candidates]
    try:
        result = await loop.run_in_executor(
            None,
            functools.partial(
                _ingest_batch,
                items,
                lambda agent_id: functools.partial(_rate_limiter.check, agent_id),
                _rate_limiter.refund,
            ),
        )
    except SQLAlchemyError as exc:
        if not isinstance(exc, (IntegrityError, DataError)):
            # Transient error: nothing is acknowledged or answered, the whole batch stays in
            # the PEL and the agent republishes after 60 s (dedup makes the re-delivery safe).
            log.error("consumer.batch_db_error", candidates=len(candidates), exc_info=True)
            return
        await _replay_per_event(client, candidates, acks)
        return
    except Exception:
        # Not a database error (e.g. a TypeError on an unexpected payload shape): the batch
        # rolled back and refunded its tokens like for a deterministic error. Replay one by
        # one so the offending event cannot stall its neighbours.
        await _replay_per_event(client, candidates, acks)
        return

    batch_stats.update(
        candidates=len(candidates),
        ingest_db_ms=round(result.ingest_db_ms, 3),
        commit_ms=round(result.commit_ms, 3),
    )
    # The batch is durable. The effects of each candidate are independent of the others: a
    # failure of one (a Valkey error on its XACK, its rejection audit write...) is logged and
    # leaves only that message un-acked in the PEL; it MUST NOT stop the notifications of the
    # events that are already committed (their re-delivery would resolve as a duplicate and
    # the alert would be lost for good).
    for candidate, outcome, candidate_ms in zip(candidates, result.outcomes, result.candidate_ms):
        try:
            if outcome.disposition == IngestDisposition.invalid_transition:
                # The only transition the ingest can reject is superseding a pending event.
                await _reject_invalid_transition(
                    client, candidate, EventStatus.pending, EventStatus.superseded
                )
            else:
                _log_event_timing(candidate, candidate_ms, outcome=None)
                await _apply_outcome(client, acks, candidate, outcome, result.removed_event_ids)
        except Exception:
            log.error(
                "consumer.effect_error", event_id=candidate.event_id, msg_id=candidate.msg_id,
                disposition=outcome.disposition.value, exc_info=True,
            )


async def _replay_per_event(
    client: Any, candidates: list[_IngestCandidate], acks: list[tuple[str, str]]
) -> None:
    """
    Replay a rolled-back batch one candidate at a time through the per-event path, so only
    the offending event stays in the PEL (as before the batched persistence). The batch
    already rolled back and refunded its tokens, which the replay decides again.
    """
    log.warning("consumer.batch_replayed_per_event", candidates=len(candidates), exc_info=True)
    for candidate in candidates:
        try:
            await _ingest_one(client, acks, candidate)
        except Exception:
            log.error("consumer.replay_error", event_id=candidate.event_id, msg_id=candidate.msg_id, exc_info=True)


async def _handle_message(client: Any, msg_id: str, msg_data: dict[str, Any]) -> None:
    # D87/RN-181: inside `_process_batch` (`_ack_batch_var` set), the `event_ack` +
    # `XACK` of events resolved with an `event_ack` are appended to the batch
    # accumulator instead of being emitted one by one. Outside a batch (direct call)
    # the immediate emission is preserved.
    ack_batch = _ack_batch_var.get()
    received_at = datetime.now(timezone.utc)
    # Profiling (D87/RN-181), only when `settings.fim_profile_ingest` is on.
    # `consumer.timing` is emitted only for events that reach the ingest stage;
    # early rejections and transient DB errors are omitted (no log with unmeasured
    # stages). `total_ms` runs until the ingest outcome is known: with the batched
    # ACK the `XACK` is not part of the per-event path (see the `scope="batch"` log).
    t_start = time.perf_counter()
    auth_ms = 0.0
    auth_cache_hit = False
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
    #
    # D87/RN-181: the result is cached in memory for 5 s (`_resolve_agent_auth`);
    # a miss still resolves in the executor, as D75/RN-169 requires, and a hit
    # touches neither the `Session` nor the executor.
    t_auth = time.perf_counter()
    agent_auth, auth_cache_hit = await _resolve_agent_auth_with_hit(agent_id)
    auth_ms = (time.perf_counter() - t_auth) * 1000
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

    # ── 5.5 field types the ingest relies on ──────────────────────────────────
    # An HMAC-valid payload can still carry a `path` / `event_id` of the wrong type
    # (an agent bug, or a compromised agent). They would raise a TypeError deep inside
    # the batch transaction; reject the event here, isolated, with an existing reason.
    path_value = payload.get("path")
    if (path_value is not None and not isinstance(path_value, str)) or not isinstance(event_id, str):
        await _reject(
            client, msg_id, event_id if isinstance(event_id, str) else None, agent_id,
            RejectionReason.invalid_schema, received_at, payload, payload_dump,
            shared_secret=shared_secret,
        )
        return

    # ── camino feliz ───────────────────────────────────────────────────────────
    candidate = _IngestCandidate(
        msg_id=msg_id,
        payload=payload,
        received_at=received_at,
        detected_at=detected_at,
        agent_id=agent_id,
        event_id=event_id,
        shared_secret=shared_secret,
        payload_dump=payload_dump,
        auth_ms=auth_ms,
        auth_cache_hit=auth_cache_hit,
        t_start=t_start,
        validated_at=time.perf_counter(),
    )
    batch = _ingest_batch_var.get()
    if batch is not None:
        # Inside `_process_batch`: collected and persisted with the rest of the batch.
        batch.append(candidate)
        return
    await _ingest_one(client, ack_batch, candidate)


async def _ingest_one(client: Any, ack_batch: list[tuple[str, str]] | None, c: _IngestCandidate) -> None:
    """
    Per-event ingest of one validated candidate, in its own transaction. Used when
    `_handle_message` runs outside a batch and to replay, one by one, a batch that
    failed with a deterministic database error.
    """
    loop = asyncio.get_running_loop()
    try:
        # D75/RN-169: `_ingest` abre una `Session` bloqueante (`SELECT` de
        # dedup + `INSERT` + `commit`, medidos en ~1,564 ms el INSERT+commit)
        # y corría síncrona dentro de la corrutina — el mismo cuello de
        # botella que `_get_agent_auth`. `_ingest` NO cambia de interfaz
        # (D-1 del design): mismo cuerpo, misma firma, mismas excepciones.
        # `run_in_executor` re-lanza en el `await`, así que el `try/except
        # InvalidTransitionError / SQLAlchemyError` de abajo captura
        # exactamente lo mismo, en el mismo lugar, con la misma semántica de
        # XACK / no-XACK que antes del cambio.
        t_ingest = time.perf_counter()
        outcome = await loop.run_in_executor(
            None, functools.partial(_ingest, c.payload, c.received_at, c.detected_at, c.agent_id)
        )
        ingest_ms = (time.perf_counter() - t_ingest) * 1000
    except InvalidTransitionError as exc:
        # Dato inválido, no reintentable → XACK + audit log + nack terminal
        # (D-3 del design): sin la respuesta, el agente republica para
        # siempre un evento que nunca va a entrar.
        await _reject_invalid_transition(client, c, exc.from_status, exc.to_status)
        return
    except SQLAlchemyError:
        # Error transitorio de DB → NO XACK, dejar en PEL para reintento
        log.error("consumer.db_error", event_id=c.event_id, exc_info=True)
        return

    _log_event_timing(c, ingest_ms, outcome=outcome)

    # Compatibilidad con dobles de prueba anteriores al resultado tipado.
    if outcome is None:
        outcome = IngestOutcome(IngestDisposition.supersede_race)
    await _apply_outcome(client, ack_batch, c, outcome, frozenset())


def _log_event_timing(c: _IngestCandidate, ingest_ms: float, outcome: IngestOutcome | None) -> None:
    """
    `consumer.timing` of one event, only under `fim_profile_ingest`. In the batch the
    `ingest_ms` is the time of the candidate inside the batch transaction and the log
    is emitted after the `COMMIT`; on the per-event path it also carries `commit_ms`.
    """
    if not settings.fim_profile_ingest:
        return
    validation_ms = (c.validated_at - c.t_start) * 1000 - c.auth_ms
    timing: dict[str, Any] = dict(
        scope="event",
        event_id=c.event_id,
        agent_id=c.agent_id,
        auth_ms=round(c.auth_ms, 3),
        auth_cache_hit=c.auth_cache_hit,
        validation_ms=round(validation_ms, 3),
        ingest_ms=round(ingest_ms, 3),
        total_ms=round(c.auth_ms + validation_ms + ingest_ms, 3),
    )
    # `ingest-batched-persistence` task 1.4: share of `ingest_ms` spent in the
    # `COMMIT` of the per-event path (absent when the outcome carries none).
    if outcome is not None and getattr(outcome, "commit_ms", None) is not None:
        timing["commit_ms"] = round(outcome.commit_ms, 3)
    log.info("consumer.timing", **timing)


async def _reject_invalid_transition(
    client: Any, c: _IngestCandidate, from_status: EventStatus, to_status: EventStatus
) -> None:
    await client.xack(STREAM_EVENTS, CONSUMER_GROUP, c.msg_id)
    log.warning(
        "consumer.invalid_transition",
        event_id=c.event_id,
        from_status=str(from_status),
        to_status=str(to_status),
    )
    audit = RejectedEventAudit(
        event_id=c.event_id,
        agent_id=c.agent_id,
        reason=RejectionReason.invalid_schema,
        received_at=c.received_at,
        detected_at=c.detected_at,
        payload_dump=c.payload_dump,
    )
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write_rejection_audit, audit)
    if c.event_id:
        await _publish_event_nack(client, c.event_id, c.agent_id, c.shared_secret, RejectionReason.invalid_schema)


async def _apply_outcome(
    client: Any,
    ack_batch: list[tuple[str, str]] | None,
    c: _IngestCandidate,
    outcome: IngestOutcome,
    removed_event_ids: set[int] | frozenset[int],
) -> None:
    """Effects of an ingest outcome. Only called once the `COMMIT` that decided it returned."""
    if outcome.disposition == IngestDisposition.rate_limited:
        await _reject(
            client, c.msg_id, c.event_id, c.agent_id, RejectionReason.rate_limited,
            c.received_at, c.payload, c.payload_dump, shared_secret=c.shared_secret,
        )
        log.warning("consumer.rate_limited", agent_id=c.agent_id)
        return

    if outcome.disposition == IngestDisposition.duplicate:
        await _ack_or_defer(client, ack_batch, c.msg_id, c.event_id, c.agent_id, c.shared_secret)
        log.info("consumer.event_dedup", event_id=c.event_id)
        return

    if outcome.disposition == IngestDisposition.persisted and outcome.event is not None:
        try:
            await _ack_or_defer(client, ack_batch, c.msg_id, c.event_id, c.agent_id, c.shared_secret)
            log.info("consumer.event_persisted", event_id=c.event_id, agent_id=c.agent_id)
        finally:
            # The notification depends on the commit, not on the ACK: it is scheduled
            # right away, never deferred to the end of the batch (D76/RN-170), and even when
            # the ACK failed (the committed event would otherwise lose its alert). An event
            # the compaction of the same batch deleted before the COMMIT has no row to alert on.
            if outcome.event.id in removed_event_ids:
                log.info("consumer.notification_skipped_compacted", event_id=c.event_id)
            else:
                _fire_and_forget(notify_if_applicable(outcome.event))
    else:
        # Una transición concurrente dejó otro pending como representación
        # activa. Resolver esta entrega con el mismo ACK atómico.
        log.info("consumer.event_ingest_skipped", event_id=c.event_id, reason="supersede_race")
        await _ack_or_defer(client, ack_batch, c.msg_id, c.event_id, c.agent_id, c.shared_secret)


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
        secret = unwrap_agent_secret(agent.agent_id, agent.shared_secret_hex)
    except ValueError:
        secret = None
    return _AgentAuth(secret, agent.status == AgentStatus.revoked)


# D87/RN-181: in-memory cache of `_get_agent_auth`, per agent_id, TTL 5 s on the
# monotonic clock. Invalidated ONLY by TTL because there is no agent revocation
# (`AgentStatus.revoked` is never assigned, D86/RN-180) and no secret rotation in
# `v5.0-tesis`; if either is added, this window must be documented with it.
# Only successes (a resolved secret) are cached, on purpose: (1) a stream of fake
# agent_ids would grow the cache without bound, and (2) a cached negative would
# reject, silently and with an XACK, an event of a freshly enrolled agent as
# `unknown_agent`. The cost is that an unknown agent_id still hits the DB per
# event, as before. The cache holds the already unwrapped `_AgentAuth` produced by
# `_get_agent_auth` (which reads the secret through `unwrap_agent_secret`, the
# single helper of D86/RN-180); it never stores the wrapped value nor re-reads
# `shared_secret_hex`. Read and written only from the event loop: no lock needed.
_AUTH_CACHE_TTL_S = 5.0
_auth_clock: Callable[[], float] = time.monotonic
_agent_auth_cache: dict[str, tuple[_AgentAuth, float]] = {}


def reset_agent_auth_cache() -> None:
    """Clears the agent authentication cache. Used in tests."""
    _agent_auth_cache.clear()


async def _resolve_agent_auth_with_hit(agent_id: str) -> tuple[_AgentAuth, bool]:
    """Cached `_get_agent_auth`: returns (auth, cache_hit). See the cache comment above."""
    entry = _agent_auth_cache.get(agent_id)
    if entry is not None and entry[1] > _auth_clock():
        return entry[0], True
    loop = asyncio.get_running_loop()
    auth = await loop.run_in_executor(None, _get_agent_auth, agent_id)
    if auth.shared_secret is not None:
        _agent_auth_cache[agent_id] = (auth, _auth_clock() + _AUTH_CACHE_TTL_S)
    else:
        _agent_auth_cache.pop(agent_id, None)
    return auth, False


async def _resolve_agent_auth(agent_id: str) -> _AgentAuth:
    auth, _hit = await _resolve_agent_auth_with_hit(agent_id)
    return auth


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
        # Same cache as the happy path (D87/RN-181).
        secret = (await _resolve_agent_auth(agent_id)).shared_secret
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


async def _ack_or_defer(
    client: Any,
    ack_batch: list[tuple[str, str]] | None,
    msg_id: str,
    event_id: str,
    agent_id: str,
    shared_secret: bytes,
) -> None:
    """Defer the signed `event_ack` + `XACK` to the batch flush, or emit now without a batch."""
    if ack_batch is None:
        await _ack_with_event_ack(client, msg_id, event_id, agent_id, shared_secret)
        return
    ack_batch.append((msg_id, _build_event_ack(event_id, agent_id, shared_secret)))


async def _flush_acks(client: Any, acks: list[tuple[str, str]]) -> None:
    """
    Emit the accumulated `event_ack` + `XACK` of a batch (D87/RN-181): one
    transactional pipeline with an `XADD commands` per entry and a single
    `XACK events` with every id. Nothing is emitted for an empty batch. A failure
    is logged and propagated, with no retry here: the entries stay in the PEL.
    """
    if not acks:
        return
    msg_ids = [msg_id for msg_id, _data in acks]
    try:
        pipeline_factory = getattr(client, "pipeline", None)
        if pipeline_factory is not None and not inspect.iscoroutinefunction(pipeline_factory):
            pipe = pipeline_factory(transaction=True)
            for _msg_id, data in acks:
                pipe.xadd(STREAM_COMMANDS, {"data": data})
            pipe.xack(STREAM_EVENTS, CONSUMER_GROUP, *msg_ids)
            await pipe.execute()
        else:
            # Minimal asyncio fakes do not expose redis-py's sync pipeline factory:
            # publish first, then ACK (same order as `_ack_with_event_ack`).
            for _msg_id, data in acks:
                await client.xadd(STREAM_COMMANDS, {"data": data})
            await client.xack(STREAM_EVENTS, CONSUMER_GROUP, *msg_ids)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.error("consumer.ack_flush_error", count=len(acks), error=str(exc))
        raise
    finally:
        acks.clear()


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
