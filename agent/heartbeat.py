"""
Heartbeat periódico del agente FIM al stream Valkey 'agent_heartbeat' (RN-92, RN-93).

Publica cada 10 s: {agent_id, timestamp, queue_size, ruleset_version,
                    queue_pressure, shutdown, schema_version}.

Durante el drenaje graceful (SIGTERM) publica shutdown=true (RN-93).
ruleset_version se lee desde state.json (via AgentState).
La señal de shutdown se lee desde publisher.shutdown (fuente de verdad, D-C26-4).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from agent.streams import SCHEMA_VERSION

if TYPE_CHECKING:
    import valkey.asyncio as avalkey

    from agent.config import AgentConfig
    from agent.publisher import Publisher
    from agent.queue import EventQueue
    from agent.state import AgentState

log = structlog.get_logger()

STREAM_HEARTBEAT = "agent_heartbeat"
_INTERVAL_S = 10.0


class HeartbeatPublisher:
    """Publica heartbeats periódicos al stream agent_heartbeat."""

    def __init__(
        self,
        config: "AgentConfig",
        queue: "EventQueue",
        state: "AgentState",
        client: "avalkey.Valkey",
        publisher: "Publisher | None" = None,
    ) -> None:
        self._config = config
        self._queue = queue
        self._state = state
        self._client = client
        self._publisher = publisher

    async def run(self, stop_event: asyncio.Event, shutdown_flag: "asyncio.Event | None" = None) -> None:
        """Loop de heartbeat. Lee publisher.shutdown como fuente de verdad (D-C26-4)."""
        while not stop_event.is_set():
            is_shutdown = self._is_shutdown(shutdown_flag)
            await self._publish(is_shutdown)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=_INTERVAL_S)
            except asyncio.TimeoutError:
                pass

    def _is_shutdown(self, shutdown_flag: "asyncio.Event | None") -> bool:
        """Determina el estado de shutdown: publisher.shutdown es la fuente de verdad."""
        if self._publisher is not None:
            return self._publisher.shutdown
        return shutdown_flag is not None and shutdown_flag.is_set()

    async def _publish(self, shutdown: bool = False) -> None:
        payload: dict[str, Any] = {
            "agent_id": self._config.agent_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "queue_size": self._queue.queue_size,
            "queue_pressure": self._queue.queue_pressure,
            "ruleset_version": self._state.ruleset_version,
            "shutdown": shutdown,
            "schema_version": SCHEMA_VERSION,
        }
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        try:
            await self._client.xadd(STREAM_HEARTBEAT, {"data": data})
            log.debug("heartbeat.published", agent_id=self._config.agent_id, shutdown=shutdown)
        except Exception as exc:
            log.warning("heartbeat.publish_error", error=str(exc))
