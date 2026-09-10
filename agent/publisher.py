"""
Publisher de eventos FIM al stream Valkey 'events' con cola offline durable.

Flujo por evento (D37/RN-131 — cuatro desenlaces, no "esperar ack o
reintentar para siempre"):
  1. Encolar (queue.enqueue) — siempre primero, incluso si el publisher está
     en backpressure (D-6). El payload en cola NO lleva 'signature' ni
     'sent_at': ambos se calculan en _stamp_and_sign, justo antes de cada
     XADD — primer envío, reintento y drenaje (D-1).
  2. XADD al stream 'events', salvo que el publisher esté pausado.
  3. Esperar respuesta tipada en 'commands' (event_ack / event_nack):
     - event_ack: borrar de la cola (queue.remove) — desenlace feliz.
     - event_nack CON retry_after (retenible: rate_limited,
       schema_version_unsupported): conservar el evento, NO contar el
       intento, aplicar backpressure agente-wide (D-6).
     - event_nack SIN retry_after (terminal: invalid_schema, clock_skew):
       borrar de la cola y archivar en el directorio de descarte con el
       motivo (queue.discard).
     - sin respuesta en 60 s: reintentar (_retry_loop), acotado por
       max_publish_attempts. Al agotarse, descartar con
       'max_attempts_exceeded' (D-7).
  Toda respuesta (ack o nack) para un event_id que no está en la cola local
  se ignora — D-4: contención ante un nack inducido por un tercero antes de
  la verificación HMAC en el backend.

Drenaje al arrancar: re-publica toda la cola local en orden FIFO antes de
procesar eventos nuevos (RN-39), respetando backpressure.

Listener de commands: filtra target_agent_id == agent_id | null (D5, RN-106).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

import structlog

from agent.experiment_trace import ExperimentTrace
from agent.queue import EventQueue
from agent.state import save_state
from agent.streams import SCHEMA_VERSION, load_shared_secret, sign_payload, verify_payload

if TYPE_CHECKING:
    import valkey.asyncio as avalkey

    from agent.baseline import BaselineEngine
    from agent.config import AgentConfig
    from agent.detector import FanotifyDetector
    from agent.journal import JournalManager
    from agent.preflight import PreflightRegistry
    from agent.state import AgentState

log = structlog.get_logger()

STREAM_EVENTS = "events"
STREAM_COMMANDS = "commands"
_ACK_TIMEOUT_S = 60.0
# D37/RN-131 (D-6 del design): piso de retry_after — un valor ausente, no
# numérico o negativo en un event_nack retenible se trata como este mínimo,
# nunca como cero (busy-loop) ni como el techo (castigo de más).
_MIN_RETRY_AFTER_S = 1.0


class Publisher:
    """Gestiona la publicación de eventos firmados y la confirmación bidireccional."""

    def __init__(
        self,
        config: "AgentConfig",
        queue: EventQueue,
        client: "avalkey.Valkey",
        experiment_trace: ExperimentTrace | None = None,
    ) -> None:
        self._config = config
        self._queue = queue
        self._client = client
        # Opt-in evidence only. Publisher owns transmission and ACK facts.
        self._experiment_trace = experiment_trace or ExperimentTrace.from_environment()
        self._trace_events: dict[str, dict[str, Any]] = {}
        self._shared_secret = load_shared_secret(config.storage.secrets_dir)
        # event_id → (loop_time_published, payload)
        self._pending: dict[str, tuple[float, dict[str, Any]]] = {}
        self._shutdown = False
        # D37/RN-131 (D-6): reloj monotónico hasta el cual está suspendida la
        # transmisión (backpressure agente-wide). 0.0 == sin pausa.
        self._paused_until: float = 0.0
        # D37/RN-131 (D-8): contador acumulativo de eventos descartados desde
        # el arranque del proceso, expuesto en el heartbeat.
        self._discarded_events: int = 0
        self._on_ack_cb: Callable[[str], None] | None = None
        self._on_update_config_cb: Callable[[list[str]], None] | None = None
        self._on_rule_sync_cb: Callable[[list, int], None] | None = None
        # C13/C14: referencias opcionales para dispatch de comandos del agente
        self._baseline_engine: "BaselineEngine | None" = None
        self._agent_state: "AgentState | None" = None
        self._journal: "JournalManager | None" = None
        self._quarantine_dir: str | None = None
        self._quarantine_store: Any | None = None
        self._detector: "FanotifyDetector | None" = None
        self._preflight_registry: "PreflightRegistry | None" = None

    @staticmethod
    def _trace_reason(reason: Any) -> str:
        """Keep trace reasons in a closed vocabulary, never arbitrary command text."""
        allowed = {
            "rate_limited", "schema_version_unsupported", "invalid_schema", "clock_skew",
            "max_attempts_exceeded", "queue_capacity", "queue_absent", "backpressure",
        }
        return str(reason) if reason in allowed else "other"

    def _trace_record(self, stage: str, payload: dict[str, Any] | None = None, **fields: Any) -> None:
        """Record only publisher-observed facts; never affect transport control flow."""
        payload = payload or {}
        try:
            self._experiment_trace.record(
                stage,
                event_id=payload.get("event_id"),
                path=payload.get("path"),
                operation=payload.get("operation_type") or payload.get("event_type") or "publish",
                hash_before=payload.get("hash_expected"),
                hash_after=payload.get("hash_detected"),
                **fields,
            )
        except Exception:
            return

    async def _xadd_with_trace(self, payload: dict[str, Any], *, source: str) -> None:
        """Trace each actual Valkey attempt, including failures swallowed by callers."""
        attempt = self._queue.get_attempts(payload["event_id"]) + 1
        try:
            await self._xadd(payload)
        except Exception as exc:
            self._trace_record(
                "xadd_failed", payload, source=source, attempt=attempt,
                reason=type(exc).__name__, outcome="failed",
            )
            raise
        self._trace_record(
            "xadd_succeeded", payload, source=source, attempt=attempt, outcome="published",
        )

    # ── public ───────────────────────────────────────────────────────────────

    async def run(self, stop_event: asyncio.Event) -> None:
        """Lanza flush de comandos, drenaje de eventos y listeners; termina cuando stop_event se activa."""
        await self._flush_commands()
        # Consume acknowledgements while the initial disk queue is being
        # published. Starting this listener only after _drain_queue meant a
        # large drain could exceed _ACK_TIMEOUT_S before one ACK was applied;
        # the subsequent retry loop then republished the whole tail.
        ack_task = asyncio.create_task(self._ack_listener(stop_event))
        try:
            await self._drain_queue()
            # Keep retries disabled during the initial FIFO drain. Once it
            # completes, the listener is current and _pending contains only
            # genuinely unacknowledged entries.
            await asyncio.gather(ack_task, self._retry_loop(stop_event))
        finally:
            if not ack_task.done():
                ack_task.cancel()
            await asyncio.gather(ack_task, return_exceptions=True)

    async def publish(self, event_data: dict[str, Any]) -> None:
        """Encola y publica un evento. event_data son los campos del cambio detectado.

        Encolar SIEMPRE ocurre, incluso si el publisher está en backpressure
        (D-6 del design): la detección no se suspende, solo la transmisión.
        """
        payload = self._build_payload(event_data)
        try:
            self._queue.enqueue(payload, on_evict=self._forget_evicted_event)
        except Exception as exc:
            self._trace_record("queue_enqueue_failed", payload, reason=type(exc).__name__, outcome="failed")
            raise
        self._trace_events[payload["event_id"]] = payload
        self._trace_record("queue_enqueue_persisted", payload, outcome="enqueued")
        # Register in _pending BEFORE xadd so _retry_loop can pick it up if xadd fails.
        self._pending[payload["event_id"]] = (
            asyncio.get_running_loop().time(),
            payload,
        )
        if self._is_paused():
            self._trace_record("xadd_deferred", payload, source="initial", reason="backpressure", outcome="deferred")
            log.debug("publisher.publish_paused", event_id=payload["event_id"])
        else:
            try:
                await self._xadd_with_trace(payload, source="initial")
                self._queue.bump_attempts(payload["event_id"])
            except Exception:
                pass  # event stays in _pending; _retry_loop will retry
        log.info("publisher.event_published", event_id=payload["event_id"])

    def _forget_evicted_event(self, event_id: str) -> None:
        """Retire an event synchronously when queue capacity evicts it."""
        payload = self._trace_events.pop(event_id, None)
        self._pending.pop(event_id, None)
        self._trace_record("queue_evicted", payload or {"event_id": event_id}, reason="queue_capacity", outcome="dropped")

    def register_callbacks(
        self,
        on_ack: Callable[[str], None] | None = None,
        on_update_config: Callable[[list[str]], None] | None = None,
        on_rule_sync: Callable[[list, int], None] | None = None,
    ) -> None:
        """Registra callbacks opcionales invocados al procesar comandos del stream."""
        self._on_ack_cb = on_ack
        self._on_update_config_cb = on_update_config
        self._on_rule_sync_cb = on_rule_sync

    def register_command_handlers(
        self,
        baseline_engine: "BaselineEngine",
        state: "AgentState",
        journal: "JournalManager",
        quarantine_dir: str | None = None,
        quarantine_store: Any | None = None,
        detector: "FanotifyDetector | None" = None,
        preflight_registry: "PreflightRegistry | None" = None,
    ) -> None:
        """
        Registra las instancias necesarias para despachar comandos C13/C14
        (baseline_update, restore_file, quarantine_file, update_config, rescan_baseline).
        Debe llamarse desde bootstrap después de inicializar baseline, state y detector.
        """
        self._baseline_engine = baseline_engine
        self._agent_state = state
        self._journal = journal
        self._quarantine_dir = quarantine_dir
        self._quarantine_store = quarantine_store
        self._detector = detector
        self._preflight_registry = preflight_registry

    def set_shutdown(self, value: bool) -> None:
        """Marca el estado de drenaje graceful para que el heartbeat lo vea."""
        self._shutdown = value

    @property
    def shutdown(self) -> bool:
        return self._shutdown

    @property
    def discarded_events(self) -> int:
        """Contador acumulativo de eventos descartados desde el arranque (D-8).

        Incluye los descartes terminales del publicador y las expulsiones por
        capacidad de la cola. Antes, drop-oldest eliminaba eventos sin que el
        heartbeat pudiera hacer visible esa pérdida.
        """
        return self._discarded_events + self._queue.evicted_events

    def _is_paused(self) -> bool:
        """True si el publisher está en backpressure (D-6). Nunca lanza fuera
        de un loop corriendo: si no hay loop, se asume sin pausa."""
        if self._paused_until <= 0:
            return False
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return False
        return now < self._paused_until

    def _apply_backpressure(self, retry_after: Any) -> float:
        """Fija _paused_until a partir de un retry_after no confiable (D-5, D-6).

        Acota por abajo (_MIN_RETRY_AFTER_S, nunca cero ni negativo) y por
        arriba (config.publisher.max_retry_after_s — un valor firmado prueba
        origen, no sensatez). Retorna el valor efectivo aplicado.
        """
        try:
            value = float(retry_after)
        except (TypeError, ValueError):
            value = _MIN_RETRY_AFTER_S
        if value <= 0:
            value = _MIN_RETRY_AFTER_S
        ceiling = self._config.publisher.max_retry_after_s
        effective = min(value, ceiling)
        loop = asyncio.get_running_loop()
        self._paused_until = loop.time() + effective
        return effective

    # ── helpers de construcción ───────────────────────────────────────────────

    def _build_payload(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Payload ESTABLE del evento — sin 'signature' ni 'sent_at' (D-1).

        Este es exactamente el payload que se persiste en la cola. `sent_at`
        y `signature` se producen por transmisión en _stamp_and_sign, no acá.
        """
        return {
            "event_id": str(uuid.uuid4()),
            "agent_id": self._config.agent_id,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            **event_data,
        }

    def _stamp_and_sign(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Único punto de firma de eventos del agente (D-1 del design).

        Sella sent_at con la hora UTC actual y firma sobre el canonical JSON
        que incluye ese sent_at, para que quede cubierto por el HMAC. Se
        invoca en cada transmisión: primer envío, reintento y drenaje.
        """
        stamped = {**payload, "sent_at": datetime.now(timezone.utc).isoformat()}
        stamped["signature"] = sign_payload(self._shared_secret, stamped)
        return stamped

    async def _xadd(self, payload: dict[str, Any]) -> None:
        """Sella y firma el payload estable, y lo publica al stream events."""
        stamped = self._stamp_and_sign(payload)
        data = json.dumps(stamped, sort_keys=True, separators=(",", ":"))
        await self._client.xadd(STREAM_EVENTS, {"data": data})

    # ── drenaje de cola ───────────────────────────────────────────────────────

    async def _drain_queue(self) -> None:
        """Publica en FIFO todos los eventos pendientes en cola (RN-39).

        Consume iter_entries() (no iter_fifo()) para sembrar _pending con el
        payload estable del sobre y respeta backpressure (D-6): si el
        publisher está pausado, el evento se registra en _pending pero no se
        transmite hasta que la pausa termine.
        """
        for entry in self._queue.iter_entries():
            payload = entry.get("payload") or {}
            event_id = payload.get("event_id")
            if not event_id or event_id in self._pending:
                continue
            self._trace_events[event_id] = payload
            self._pending[event_id] = (asyncio.get_running_loop().time(), payload)
            if self._is_paused():
                self._trace_record("xadd_deferred", payload, source="drain", reason="backpressure", outcome="deferred")
                log.debug("publisher.drain_paused", event_id=event_id)
                continue
            try:
                await self._xadd_with_trace(payload, source="drain")
                self._queue.bump_attempts(event_id)
                log.info("publisher.queue_drained", event_id=event_id)
            except Exception as exc:
                log.warning("publisher.drain_error", event_id=event_id, error=str(exc))

    # ── flush de comandos pendientes al arrancar ──────────────────────────────

    async def _flush_commands(self) -> None:
        """
        Procesa los comandos pendientes del stream 'commands' desde el cursor
        persistido antes de drenar la cola de eventos (RN-109, D11, D-D).

        Lee en rondas de XREAD COUNT 100 con BLOCK acotado al budget restante.
        Termina al recibir una ronda vacía o al superar command_flush_timeout_s.
        Si se agota el timeout con mensajes pendientes, emite warning y continúa.
        """
        if self._agent_state is None:
            log.warning(
                "publisher.flush_commands.no_state",
                reason="agent_state not injected; skipping flush (legacy mode)",
            )
            return

        timeout_s = self._config.publisher.command_flush_timeout_s
        deadline = time.monotonic() + timeout_s
        cursor = self._agent_state.last_stream_command_id

        while True:
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                log.warning(
                    "publisher.flush_commands.timeout",
                    cursor=cursor,
                    timeout_s=timeout_s,
                )
                break

            block_ms = max(1, int(min(remaining_s, 0.5) * 1000))
            try:
                results = await self._client.xread(
                    {STREAM_COMMANDS: cursor}, block=block_ms, count=100
                )
            except Exception as exc:
                log.warning("publisher.flush_commands.xread_error", error=str(exc))
                break

            if not results:
                break

            for _stream, messages in results:
                for msg_id, msg_data in messages:
                    cursor = msg_id
                    payload = self._verify_and_parse(msg_data)
                    if payload is not None:
                        try:
                            await self._handle_command_async(payload)
                        except Exception as exc:
                            log.warning(
                                "publisher.flush_commands.dispatch_error",
                                msg_id=msg_id,
                                error=str(exc),
                            )
                    self._agent_state.last_stream_command_id = msg_id
                    try:
                        save_state(self._agent_state)
                    except Exception as save_exc:
                        log.warning(
                            "publisher.flush_commands.save_state_failed",
                            error=str(save_exc),
                        )

    # ── listener de event_ack ─────────────────────────────────────────────────

    def _verify_and_parse(self, msg_data: dict[str, Any]) -> dict[str, Any] | None:
        """
        Único punto de entrada para mensajes del stream commands (RN-79).

        Parsea el JSON del campo 'data' y verifica la firma HMAC-SHA256.
        Retorna el payload verificado o None si el JSON es inválido o la firma no coincide.
        Todo mensaje — presente o futuro — debe pasar por aquí antes de cualquier side effect.
        """
        raw = msg_data.get("data", "{}")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not verify_payload(self._shared_secret, payload):
            log.warning("publisher.command_signature_invalid")
            return None
        return payload

    async def _ack_listener(self, stop_event: asyncio.Event) -> None:
        """Lee 'commands', verifica HMAC y procesa comandos (RN-40, RN-73, RN-79, D5, RN-106)."""
        if self._agent_state is not None:
            last_id = self._agent_state.last_stream_command_id
        else:
            log.warning(
                "publisher.ack_listener.no_state",
                reason="agent_state not injected; starting from '$' (legacy mode)",
            )
            last_id = "$"

        while not stop_event.is_set():
            try:
                results = await self._client.xread(
                    {STREAM_COMMANDS: last_id}, block=1000, count=50
                )
                if results:
                    for _stream, messages in results:
                        for msg_id, msg_data in messages:
                            payload = self._verify_and_parse(msg_data)
                            last_id = msg_id
                            if payload is None:
                                # Advance cursor for verification-failed messages (not retried)
                                if self._agent_state is not None:
                                    self._agent_state.last_stream_command_id = msg_id
                                    try:
                                        save_state(self._agent_state)
                                    except Exception as save_exc:
                                        log.warning(
                                            "publisher.ack_listener.save_state_failed",
                                            error=str(save_exc),
                                        )
                                continue
                            await self._handle_command_async(payload)
                            # Persist cursor AFTER successful dispatch (at-least-once)
                            if self._agent_state is not None:
                                self._agent_state.last_stream_command_id = msg_id
                                try:
                                    save_state(self._agent_state)
                                except Exception as save_exc:
                                    log.warning(
                                        "publisher.ack_listener.save_state_failed",
                                        error=str(save_exc),
                                    )
            except Exception as exc:
                log.warning("publisher.ack_listener_error", error=str(exc))
                await asyncio.sleep(1)

    async def _handle_command_async(self, payload: dict[str, Any]) -> None:
        """
        Despacha un payload ya verificado y parseado por _verify_and_parse.

        El target_agent_id filtering ocurre aquí (después de verificar la firma — D5, RN-106).
        """
        # Filtrar por target_agent_id — D5, RN-106
        target = payload.get("target_agent_id")
        if target and target != self._config.agent_id:
            return
        cmd_type = payload.get("type") or payload.get("command_type") or ""
        if cmd_type == "event_ack":
            event_id = payload.get("event_id")
            if not event_id:
                return
            # D-4: ignorar respuestas para event_id que no están en la cola
            # local — contención ante un nack/ack inducido por un tercero.
            event_payload = self._trace_events.get(event_id, {"event_id": event_id})
            if not self._queue.contains(event_id):
                self._trace_record("ack_valid_ignored", event_payload, source="command", reason="queue_absent", outcome="ignored")
                log.info("publisher.ack_unknown_event_id", event_id=event_id)
                return
            self._trace_record("ack_valid", event_payload, source="command", outcome="acknowledged")
            self._queue.remove(event_id)
            self._pending.pop(event_id, None)
            self._trace_events.pop(event_id, None)
            if self._on_ack_cb is not None:
                self._on_ack_cb(event_id)
            log.info("publisher.event_acked", event_id=event_id)
        elif cmd_type == "event_nack":
            event_id = payload.get("event_id")
            if not event_id:
                return
            reason = payload.get("reason", "")
            retry_after = payload.get("retry_after")
            # D-4: misma contención que event_ack.
            event_payload = self._trace_events.get(event_id, {"event_id": event_id})
            if not self._queue.contains(event_id):
                self._trace_record("nack_valid_ignored", event_payload, source="command", reason="queue_absent", outcome="ignored")
                log.info(
                    "publisher.nack_unknown_event_id", event_id=event_id, reason=reason
                )
                return
            if retry_after is not None:
                # Retenible (D37 amendment: rate_limited y
                # schema_version_unsupported comparten este tratamiento —
                # la presencia de retry_after es lo que decide, no el motivo
                # literal). NO cuenta el intento, NO se borra de la cola.
                effective = self._apply_backpressure(retry_after)
                self._trace_record("nack_valid_retainable", event_payload, source="command", reason=self._trace_reason(reason), outcome="retained")
                log.info(
                    "publisher.event_nack_retainable",
                    event_id=event_id,
                    reason=reason,
                    retry_after=effective,
                )
            else:
                # Terminal (invalid_schema de payload ilegible, clock_skew).
                self._queue.discard(event_id, reason)
                self._pending.pop(event_id, None)
                self._trace_record("nack_valid_terminal", event_payload, source="command", reason=self._trace_reason(reason), outcome="dropped")
                self._trace_events.pop(event_id, None)
                self._discarded_events += 1
                log.warning(
                    "publisher.event_nack_terminal", event_id=event_id, reason=reason
                )
        elif cmd_type == "rule_sync":
            rules_payload = payload.get("rules")
            ruleset_version = payload.get("ruleset_version")
            if (
                isinstance(rules_payload, list)
                and isinstance(ruleset_version, int)
                and self._on_rule_sync_cb is not None
            ):
                self._on_rule_sync_cb(rules_payload, ruleset_version)
                log.info("publisher.rule_sync_received", ruleset_version=ruleset_version)
        elif cmd_type in (
            "baseline_update", "restore_file", "quarantine_file",
            "update_config", "rescan_baseline",
        ):
            # C13/C14: despachar al módulo commands si las instancias están registradas
            if (
                self._baseline_engine is not None
                and self._agent_state is not None
            ):
                from agent import commands as _commands
                await _commands.dispatch(
                    payload,
                    baseline_engine=self._baseline_engine,
                    state=self._agent_state,
                    valkey_client=self._client,
                    config=self._config,
                    journal=self._journal,
                    quarantine_dir=self._quarantine_dir,
                    quarantine_store=self._quarantine_store,
                    detector=self._detector,
                    preflight_registry=self._preflight_registry,
                )
            else:
                log.warning(
                    "publisher.command_handler_not_registered",
                    cmd_type=cmd_type,
                )

    # ── retry loop ─────────────────────────────────────────────────────────────

    async def _retry_loop(self, stop_event: asyncio.Event) -> None:
        """Re-publica eventos sin ack tras 60 s (RN-40, RN-73).

        Acotado por el techo de intentos por evento (D-7): al alcanzarlo, el
        evento se descarta con 'max_attempts_exceeded' y deja de publicarse.
        Respeta backpressure (D-6): mientras el publisher está pausado, no
        emite ningún XADD.
        """
        while not stop_event.is_set():
            await asyncio.sleep(5)
            if self._is_paused():
                continue
            now = asyncio.get_running_loop().time()
            for event_id, (published_at, payload) in list(self._pending.items()):
                if now - published_at < _ACK_TIMEOUT_S:
                    continue
                attempts = self._queue.get_attempts(event_id)
                if attempts >= self._config.publisher.max_publish_attempts:
                    self._queue.discard(event_id, "max_attempts_exceeded")
                    self._pending.pop(event_id, None)
                    self._trace_record("queue_discarded", self._trace_events.pop(event_id, payload), source="retry", attempt=attempts, reason="max_attempts_exceeded", outcome="dropped")
                    self._discarded_events += 1
                    log.warning(
                        "publisher.event_discarded",
                        event_id=event_id,
                        reason="max_attempts_exceeded",
                        attempts=attempts,
                    )
                    continue
                try:
                    await self._xadd_with_trace(payload, source="retry")
                    self._queue.bump_attempts(event_id)
                    self._pending[event_id] = (now, payload)
                    log.info("publisher.event_retried", event_id=event_id)
                except Exception as exc:
                    log.warning("publisher.retry_error", event_id=event_id, error=str(exc))
