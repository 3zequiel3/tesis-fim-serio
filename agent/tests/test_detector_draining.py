"""Tests de US-30 — el detector deja de aceptar nuevos eventos de fanotify
durante el drenaje graceful (RN-93/W17).

Antes de este fix, `_try_enqueue` encolaba cualquier evento recibido del
hilo lector sin importar el estado de shutdown: el agente seguía aceptando
(y por lo tanto encolando/publicando) cambios de archivo detectados durante
el drenaje. `set_draining(True)` (llamado desde `__main__._shutdown` junto a
`publisher.set_shutdown(True)`) hace que `_try_enqueue` descarte silenciosamente
los eventos nuevos, sin tocar el backend fanotify real — no requiere
CAP_SYS_ADMIN ni el módulo ctypes, mismo patrón de mock que
test_stability_fixes.py.
"""
from __future__ import annotations

import asyncio

import pytest

from agent.detector import FanotifyDetector, FanotifyEvent


def _make_fan_event(path: str = "/etc/hosts") -> FanotifyEvent:
    return FanotifyEvent(
        path=path,
        pid=1,
        uid=0,
        exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_try_enqueue_processes_normally_when_not_draining() -> None:
    """Comportamiento previo intacto: sin draining, el evento se encola."""
    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._raw_queue = asyncio.Queue(maxsize=10)
    detector._event_drops = 0
    detector._loop = asyncio.get_running_loop()

    detector._try_enqueue(_make_fan_event())

    assert detector._raw_queue.qsize() == 1
    assert detector._event_drops == 0


@pytest.mark.asyncio
async def test_set_draining_stops_accepting_new_events() -> None:
    """Tras set_draining(True), _try_enqueue descarta el evento sin encolarlo."""
    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._raw_queue = asyncio.Queue(maxsize=10)
    detector._event_drops = 0
    detector._loop = asyncio.get_running_loop()

    detector.set_draining(True)
    detector._try_enqueue(_make_fan_event())

    assert detector._raw_queue.qsize() == 0
    # No se cuenta como drop por cola llena — es un descarte deliberado
    # por shutdown, métrica distinta (evita confundir el diagnóstico de
    # detection_gap/event_drops con un rechazo intencional).
    assert detector._event_drops == 0


@pytest.mark.asyncio
async def test_set_draining_false_resumes_accepting_events() -> None:
    """set_draining(False) revierte el descarte (no debería ocurrir en la
    práctica — el agente termina tras drenar — pero el método debe ser
    reversible y no dejar estado espurio)."""
    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._raw_queue = asyncio.Queue(maxsize=10)
    detector._event_drops = 0
    detector._loop = asyncio.get_running_loop()

    detector.set_draining(True)
    detector.set_draining(False)
    detector._try_enqueue(_make_fan_event())

    assert detector._raw_queue.qsize() == 1


@pytest.mark.asyncio
async def test_try_enqueue_defaults_to_not_draining_without_init() -> None:
    """Un detector construido sin pasar por __init__ (patrón __new__ de los
    tests existentes) y sin `_draining` seteado explícitamente se comporta
    como si no estuviera drenando — no debe romper los tests preexistentes
    que instancian FanotifyDetector.__new__ sin conocer este atributo nuevo."""
    detector = FanotifyDetector.__new__(FanotifyDetector)
    detector._raw_queue = asyncio.Queue(maxsize=10)
    detector._event_drops = 0
    detector._loop = asyncio.get_running_loop()
    # _draining deliberadamente NO seteado.

    detector._try_enqueue(_make_fan_event())

    assert detector._raw_queue.qsize() == 1
