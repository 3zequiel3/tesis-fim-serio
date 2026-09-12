"""Tests de US-30 — `_drain_then_stop` (agent/__main__.py, RN-93/W17).

Cubre el timeout de 30 s del drenaje graceful: la cola local debe drenar
publicando al stream antes de que el agente detenga sus loops (`stop_event`),
pero un drenaje que nunca termina (Valkey caído, cola nunca baja a 0) no debe
colgar el proceso indefinidamente — a los 30 s (parametrizable vía el arg
`timeout`, usado acá con valores chicos para no alargar la suite) el agente
igual activa `stop_event` y termina.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from agent.__main__ import _drain_then_stop


def _make_queue(queue_size: int) -> MagicMock:
    queue = MagicMock()
    queue.queue_size = queue_size
    return queue


@pytest.mark.asyncio
async def test_drain_then_stop_sets_stop_event_when_queue_already_empty() -> None:
    """Cola ya vacía al arrancar el drain → stop_event se activa de inmediato,
    sin esperar el timeout completo."""
    queue = _make_queue(0)
    stop_event = asyncio.Event()

    await asyncio.wait_for(_drain_then_stop(queue, stop_event, timeout=5.0), timeout=1.0)

    assert stop_event.is_set()


class _DrainingQueue:
    """Simula una cola cuyo queue_size baja a 0 tras un par de polls (el
    publisher real la va vaciando concurrentemente)."""

    def __init__(self, sizes: list[int]) -> None:
        self._sizes = list(sizes)

    @property
    def queue_size(self) -> int:
        if len(self._sizes) > 1:
            return self._sizes.pop(0)
        return self._sizes[0]


@pytest.mark.asyncio
async def test_drain_then_stop_waits_until_queue_drains() -> None:
    """La cola drena a mitad de camino → stop_event se activa apenas llega a
    0, sin esperar el timeout completo (poll interno de 0.5 s)."""
    queue = _DrainingQueue([3, 3, 0])
    stop_event = asyncio.Event()

    await asyncio.wait_for(_drain_then_stop(queue, stop_event, timeout=5.0), timeout=3.0)

    assert stop_event.is_set()


@pytest.mark.asyncio
async def test_drain_then_stop_times_out_if_queue_never_empties() -> None:
    """Cola que nunca drena (Valkey caído) → stop_event se activa igual al
    cumplirse el timeout, no se cuelga indefinidamente (RN-93: ventana de
    drenaje acotada)."""
    queue = _make_queue(999)  # nunca baja a 0
    stop_event = asyncio.Event()

    start = asyncio.get_event_loop().time()
    await asyncio.wait_for(_drain_then_stop(queue, stop_event, timeout=0.2), timeout=2.0)
    elapsed = asyncio.get_event_loop().time() - start

    assert stop_event.is_set()
    # Terminó por el timeout, no antes (con margen para el jitter del sleep interno).
    assert elapsed >= 0.15


@pytest.mark.asyncio
async def test_drain_then_stop_default_timeout_is_30_seconds() -> None:
    """El contrato de RN-93/W17 es 30 s — verificado contra el default real
    de la firma, no un valor hardcodeado en el test."""
    import inspect

    sig = inspect.signature(_drain_then_stop)
    assert sig.parameters["timeout"].default == 30.0
