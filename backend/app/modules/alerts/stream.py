"""
Broadcaster SSE in-process para FIM Platform (C16 — backend-sse-alerts).

AlertsBroadcaster mantiene una queue asyncio por suscriptor activo.
Cuando notify_if_applicable crea una Alert, llama a alerts_broadcaster.publish()
y cada conexión SSE recibe el dict inmediatamente.

Single-instance backend (RN-76): no se necesita pub-sub externo.
"""

from __future__ import annotations

import asyncio
from typing import Any


class AlertsBroadcaster:
    """Pub-sub in-process vía asyncio.Queue por suscriptor."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def publish(self, alert_dict: dict[str, Any]) -> None:
        for queue in self._subscribers:
            queue.put_nowait(alert_dict)


alerts_broadcaster = AlertsBroadcaster()
