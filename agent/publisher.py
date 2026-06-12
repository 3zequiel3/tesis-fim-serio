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
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from agent.queue import EventQueue
from agent.streams import SCHEMA_VERSION, load_shared_secret, sign_payload

if TYPE_CHECKING:
    import valkey.asyncio as avalkey

    from agent.config import AgentConfig

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

    # ── public ───────────────────────────────────────────────────────────────

    async def run(self, stop_event: asyncio.Event) -> None:
        """Lanza drenaje, listener y retry; termina cuando stop_event se activa."""
        await self._drain_queue()
        await asyncio.gather(
            self._ack_listener(stop_event),
            self._retry_loop(stop_event),
        )

    async def publish(self, event_data: dict[str, Any]) -> None:
        """Encola y publica un evento. event_data son los campos del cambio detectado."""
        payload = self._build_payload(event_data)
        self._queue.enqueue(payload)
        await self._xadd(payload)
        self._pending[payload["event_id"]] = (
            asyncio.get_event_loop().time(),
            payload,
        )
        log.info("publisher.event_published", event_id=payload["event_id"])

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
                    self._pending[event_id] = (asyncio.get_event_loop().time(), event)
                    log.info("publisher.queue_drained", event_id=event_id)
                except Exception as exc:
                    log.warning("publisher.drain_error", event_id=event_id, error=str(exc))

    # ── listener de event_ack ─────────────────────────────────────────────────

    async def _ack_listener(self, stop_event: asyncio.Event) -> None:
        """Lee 'commands' y procesa event_ack (RN-40, RN-73, D5, RN-106)."""
        last_id = "$"
        while not stop_event.is_set():
            try:
                results = await self._client.xread(
                    {STREAM_COMMANDS: last_id}, block=1000, count=50
                )
                if results:
                    for _stream, messages in results:
                        for msg_id, msg_data in messages:
                            self._handle_command(msg_data)
                            last_id = msg_id
            except Exception as exc:
                log.warning("publisher.ack_listener_error", error=str(exc))
                await asyncio.sleep(1)

    def _handle_command(self, msg_data: dict[str, Any]) -> None:
        """Procesa un mensaje del stream commands."""
        raw = msg_data.get("data", "{}")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return
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
                log.info("publisher.event_acked", event_id=event_id)

    # ── retry loop ─────────────────────────────────────────────────────────────

    async def _retry_loop(self, stop_event: asyncio.Event) -> None:
        """Re-publica eventos sin ack tras 60 s (RN-40, RN-73)."""
        while not stop_event.is_set():
            await asyncio.sleep(5)
            now = asyncio.get_event_loop().time()
            for event_id, (published_at, payload) in list(self._pending.items()):
                if now - published_at >= _ACK_TIMEOUT_S:
                    try:
                        await self._xadd(payload)
                        self._pending[event_id] = (now, payload)
                        log.info("publisher.event_retried", event_id=event_id)
                    except Exception as exc:
                        log.warning("publisher.retry_error", event_id=event_id, error=str(exc))
