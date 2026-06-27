"""
Publisher de eventos FIM al stream Valkey 'events' con cola offline durable.

Flujo por evento:
  1. Encolar (queue.enqueue) — siempre primero (D-2).
  2. XADD al stream 'events'.
  3. Esperar event_ack en 'commands'; si no llega en 60 s, reintentar.
  4. Al recibir event_ack, borrar archivo de cola (queue.remove).

Drenaje al arrancar: re-publica toda la cola local en orden FIFO antes de
procesar eventos nuevos (RN-39).

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

from agent.queue import EventQueue
from agent.state import save_state
from agent.streams import SCHEMA_VERSION, load_shared_secret, sign_payload, verify_payload

if TYPE_CHECKING:
    import valkey.asyncio as avalkey

    from agent.baseline import BaselineEngine
    from agent.config import AgentConfig
    from agent.detector import FanotifyDetector
    from agent.journal import JournalManager
    from agent.state import AgentState

log = structlog.get_logger()

STREAM_EVENTS = "events"
STREAM_COMMANDS = "commands"
_ACK_TIMEOUT_S = 60.0


class Publisher:
    """Gestiona la publicación de eventos firmados y la confirmación bidireccional."""

    def __init__(
        self,
        config: "AgentConfig",
        queue: EventQueue,
        client: "avalkey.Valkey",
    ) -> None:
        self._config = config
        self._queue = queue
        self._client = client
        self._shared_secret = load_shared_secret(config.storage.secrets_dir)
        # event_id → (loop_time_published, payload)
        self._pending: dict[str, tuple[float, dict[str, Any]]] = {}
        self._shutdown = False
        self._on_ack_cb: Callable[[str], None] | None = None
        self._on_update_config_cb: Callable[[list[str]], None] | None = None
        self._on_rule_sync_cb: Callable[[list, int], None] | None = None
        # C13/C14: referencias opcionales para dispatch de comandos del agente
        self._baseline_engine: "BaselineEngine | None" = None
        self._agent_state: "AgentState | None" = None
        self._journal: "JournalManager | None" = None
        self._quarantine_dir: str | None = None
        self._detector: "FanotifyDetector | None" = None

    # ── public ───────────────────────────────────────────────────────────────

    async def run(self, stop_event: asyncio.Event) -> None:
        """Lanza flush de comandos, drenaje de eventos y listeners; termina cuando stop_event se activa."""
        await self._flush_commands()
        await self._drain_queue()
        await asyncio.gather(
            self._ack_listener(stop_event),
            self._retry_loop(stop_event),
        )

    async def publish(self, event_data: dict[str, Any]) -> None:
        """Encola y publica un evento. event_data son los campos del cambio detectado."""
        payload = self._build_payload(event_data)
        self._queue.enqueue(payload)
        # Register in _pending BEFORE xadd so _retry_loop can pick it up if xadd fails.
        self._pending[payload["event_id"]] = (
            asyncio.get_running_loop().time(),
            payload,
        )
        try:
            await self._xadd(payload)
        except Exception:
            pass  # event stays in _pending; _retry_loop will retry
        log.info("publisher.event_published", event_id=payload["event_id"])

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
        detector: "FanotifyDetector | None" = None,
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
        self._detector = detector

    def set_shutdown(self, value: bool) -> None:
        """Marca el estado de drenaje graceful para que el heartbeat lo vea."""
        self._shutdown = value

    @property
    def shutdown(self) -> bool:
        return self._shutdown

    # ── helpers de construcción ───────────────────────────────────────────────

    def _build_payload(self, event_data: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "agent_id": self._config.agent_id,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            **event_data,
        }
        payload["signature"] = sign_payload(self._shared_secret, payload)
        return payload

    async def _xadd(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        await self._client.xadd(STREAM_EVENTS, {"data": data})

    # ── drenaje de cola ───────────────────────────────────────────────────────

    async def _drain_queue(self) -> None:
        """Publica en FIFO todos los eventos pendientes en cola (RN-39)."""
        for event in self._queue.iter_fifo():
            event_id = event.get("event_id")
            if not event_id:
                continue
            if event_id not in self._pending:
                try:
                    await self._xadd(event)
                    self._pending[event_id] = (asyncio.get_running_loop().time(), event)
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
            if event_id:
                self._queue.remove(event_id)
                self._pending.pop(event_id, None)
                if self._on_ack_cb is not None:
                    self._on_ack_cb(event_id)
                log.info("publisher.event_acked", event_id=event_id)
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
                    detector=self._detector,
                )
            else:
                log.warning(
                    "publisher.command_handler_not_registered",
                    cmd_type=cmd_type,
                )

    # ── retry loop ─────────────────────────────────────────────────────────────

    async def _retry_loop(self, stop_event: asyncio.Event) -> None:
        """Re-publica eventos sin ack tras 60 s (RN-40, RN-73)."""
        while not stop_event.is_set():
            await asyncio.sleep(5)
            now = asyncio.get_running_loop().time()
            for event_id, (published_at, payload) in list(self._pending.items()):
                if now - published_at >= _ACK_TIMEOUT_S:
                    try:
                        await self._xadd(payload)
                        self._pending[event_id] = (now, payload)
                        log.info("publisher.event_retried", event_id=event_id)
                    except Exception as exc:
                        log.warning("publisher.retry_error", event_id=event_id, error=str(exc))
