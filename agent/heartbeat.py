"""
Heartbeat periódico del agente FIM al stream Valkey 'agent_heartbeat' (RN-92, RN-93).

Publica cada 10 s: {agent_id, timestamp, queue_size, ruleset_version,
                    queue_pressure, shutdown, schema_version, watch_path_status,
                    discarded_events}.

D37/RN-131: `discarded_events` es el contador acumulativo de eventos que el
publisher descartó localmente desde el arranque del proceso (techo de
reintentos o nack terminal), mismo patrón que el contador de drops del
detector (event_drops).

Durante el drenaje graceful (SIGTERM) publica shutdown=true (RN-93).
ruleset_version se lee desde state.json (via AgentState).
La señal de shutdown se lee desde publisher.shutdown (fuente de verdad, D-C26-4).

D36/RN-130 (D-5): `watch_path_status` es el mapa COMPLETO path -> clasificación
del preflight (agent/preflight.py), no solo los degradados — omitir los
escribibles haría ambiguo un path ausente (¿escribible, o agente viejo que no
reporta?). Agregar la clave es seguro para la firma: canonical_json firma el
dict completo ordenado, sin allowlist por clave.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from agent.streams import SCHEMA_VERSION, sign_payload

if TYPE_CHECKING:
    import valkey.asyncio as avalkey

    from agent.config import AgentConfig
    from agent.detector import FanotifyDetector
    from agent.preflight import PreflightRegistry
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
        detector: "FanotifyDetector | None" = None,
        shared_secret: bytes | None = None,
        preflight_registry: "PreflightRegistry | None" = None,
    ) -> None:
        self._config = config
        self._queue = queue
        self._state = state
        self._client = client
        self._publisher = publisher
        self._detector = detector
        # Mismo shared_secret que el Publisher: el heartbeat también debe ir firmado
        # con HMAC o el heartbeat_consumer del backend lo descarta (invalid_signature).
        # En producción lo inyecta __main__; se pasa por parámetro (no I/O en __init__).
        self._shared_secret = shared_secret
        # D36/RN-130: registry compartido con __main__/handle_update_config.
        # None si el agente arranca sin preflight wireado (tests legacy).
        self._preflight_registry = preflight_registry

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
            "event_drops": self._detector.event_drops if self._detector is not None else 0,
            "out_of_scope_drops": self._detector.out_of_scope_drops if self._detector is not None else 0,
            # D33/RN-127: contador detective opcional, sin cambio de comportamiento.
            "hardlink_suspected": self._detector.hardlink_suspected if self._detector is not None else 0,
            # D37/RN-131: contador acumulativo de eventos descartados localmente.
            "discarded_events": self._publisher.discarded_events if self._publisher is not None else 0,
        }
        if self._preflight_registry is not None:
            payload["watch_path_status"] = self._preflight_registry.snapshot()
            config_persisted = self._preflight_registry.config_persisted
            if config_persisted is not None:
                payload["config_persisted"] = config_persisted
        if self._shared_secret is not None:
            payload["signature"] = sign_payload(self._shared_secret, payload)
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        try:
            await self._client.xadd(STREAM_HEARTBEAT, {"data": data})
            log.debug("heartbeat.published", agent_id=self._config.agent_id, shutdown=shutdown)
        except Exception as exc:
            log.warning("heartbeat.publish_error", error=str(exc))
