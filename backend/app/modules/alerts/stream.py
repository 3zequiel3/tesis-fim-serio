"""
Broadcaster SSE in-process para FIM Platform (C16 — backend-sse-alerts).

AlertsBroadcaster mantiene una queue asyncio por suscriptor activo.
Cuando notify_if_applicable crea una Alert, llama a alerts_broadcaster.publish()
y cada conexión SSE recibe el dict inmediatamente.

Single-instance backend (RN-76): no se necesita pub-sub externo.

FIX-01 (D24): la cola por suscriptor tiene maxsize=100. Cuando está llena,
el evento nuevo se descarta (política drop-newest) y se registra WARNING.
Esto evita consumo de RAM descontrolado bajo ráfagas de alertas.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

log = structlog.get_logger()

_QUEUE_MAX_SIZE = 100


class AlertsBroadcaster:
    """Pub-sub in-process vía asyncio.Queue por suscriptor."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        # FIX-01: cola acotada para evitar OOM bajo ráfaga (D24)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def publish(self, alert_dict: dict[str, Any]) -> None:
        for queue in self._subscribers:
            try:
                queue.put_nowait(alert_dict)
            except asyncio.QueueFull:
                # FIX-01: política drop-newest — descartar el evento entrante (D24)
                log.warning(
                    "alerts_broadcaster.queue_full.drop_newest",
                    alert_id=alert_dict.get("id"),
                    queue_size=queue.qsize(),
                )


alerts_broadcaster = AlertsBroadcaster()
