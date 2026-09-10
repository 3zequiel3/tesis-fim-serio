"""Tests de detección de FAN_Q_OVERFLOW y emisión de detection_gap (D50/RN-144, tasks 5.5-5.11)."""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent._fanotify import FAN_Q_OVERFLOW
from agent.detector import FanotifyDetector, _DETECTION_GAP_WINDOW_S


def _make_detector(
    tmp_path: Path, decision_engine: MagicMock | None = None
) -> tuple[FanotifyDetector, MagicMock, MagicMock]:
    baseline = MagicMock()
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0

    detector = FanotifyDetector(
        agent_id="agent-detection-gap-test",
        watch_paths=[str(tmp_path)],
        baseline=baseline,
        publisher=publisher,
        stop_event=asyncio.Event(),
        decision_engine=decision_engine,
    )
    return detector, baseline, publisher


def _make_overflow_event() -> MagicMock:
    """Evento crudo con el bit FAN_Q_OVERFLOW, sin path (5.11: constante real)."""
    ev = MagicMock()
    ev.path = None
    ev.pid = 0
    ev.mask = FAN_Q_OVERFLOW
    return ev


async def _drain(n: int = 5) -> None:
    """Cede el control al loop varias veces para que callbacks/tasks agendados corran."""
    for _ in range(n):
        await asyncio.sleep(0)


def _run_read_loop_once(detector: FanotifyDetector, events_batch: list) -> None:
    """Corre `_read_loop` real una vez (mismo patrón que test_scope_filter.py)."""

    def _batches():
        yield events_batch
        while True:
            yield []

    gen = _batches()
    detector._read_fan_events = MagicMock(side_effect=lambda: next(gen))

    def _stop_soon() -> None:
        time.sleep(0.05)
        detector._stop_event.set()

    t = threading.Thread(target=_stop_soon)
    t.start()
    detector._read_loop()
    t.join()


# ── 5.5 — un desbordamiento produce un evento detection_gap publicado ────────


@pytest.mark.asyncio
async def test_overflow_emits_detection_gap(tmp_path: Path) -> None:
    detector, _baseline, publisher = _make_detector(tmp_path)
    detector._loop = asyncio.get_running_loop()

    detector._handle_overflow()
    await _drain()

    publisher.publish.assert_called_once()
    payload = publisher.publish.call_args[0][0]
    assert payload["event_type"] == "detection_gap"
    assert payload["operation_type"] == "detection_gap"
    assert payload["path"] is None
    assert payload["process_pid"] is None
    assert payload["process_uid"] is None
    assert payload["process_exe"] is None
    assert payload["cause"] == "fan_q_overflow"
    assert payload["action"] == "alert_only"


# ── 5.6 — el desbordamiento no cae en el descarte por path nulo ──────────────


def test_overflow_does_not_hit_null_path_discard(tmp_path: Path) -> None:
    detector, _baseline, _publisher = _make_detector(tmp_path)
    # call_soon_threadsafe sincrónico: alcanza para observar que SE agenda la
    # publicación (5.6 no exige que el publish real corra, solo que el evento
    # no caiga en el descarte por path nulo).
    detector._loop = MagicMock()
    detector._loop.call_soon_threadsafe.side_effect = lambda fn, arg: fn(arg)
    # `create_task` no ejecuta la corrutina en este test (no es su foco); se
    # cierra explícitamente para no dejar un warning de "never awaited".
    detector._loop.create_task = MagicMock(side_effect=lambda coro: coro.close())

    with patch("agent.detector.log") as mock_log:
        _run_read_loop_once(detector, [_make_overflow_event()])

    null_path_calls = [
        c for c in mock_log.warning.call_args_list if c.args and c.args[0] == "detector.event_null_path"
    ]
    detection_gap_calls = [
        c for c in mock_log.warning.call_args_list if c.args and c.args[0] == "detector.detection_gap"
    ]
    assert null_path_calls == []
    assert len(detection_gap_calls) == 1


# ── 5.7 — el detection_gap no atraviesa el motor de decisión ─────────────────


def test_overflow_bypasses_decision_engine(tmp_path: Path) -> None:
    decision_engine = MagicMock()
    detector, _baseline, _publisher = _make_detector(tmp_path, decision_engine=decision_engine)
    detector._loop = MagicMock()
    detector._loop.call_soon_threadsafe.side_effect = lambda fn, arg: fn(arg)
    # `create_task` no ejecuta la corrutina en este test (no es su foco); se
    # cierra explícitamente para no dejar un warning de "never awaited".
    detector._loop.create_task = MagicMock(side_effect=lambda coro: coro.close())

    detector._handle_overflow()

    # El único punto por el que el detector escribe journal es a través de
    # evaluate_and_act (agent/decision.py:write_pending); si no se invoca,
    # no hay entrada de journal posible para este evento (D-5 del design).
    decision_engine.evaluate_and_act.assert_not_called()


# ── 5.8 / 5.9 — deduplicación por ventana de 60 s ─────────────────────────────


def test_isolated_overflow_reports_zero_suppressions(tmp_path: Path) -> None:
    detector, _baseline, _publisher = _make_detector(tmp_path)
    with patch.object(detector, "_schedule_detection_gap_publish") as scheduled:
        detector._loop = MagicMock()
        detector._loop.call_soon_threadsafe.side_effect = lambda fn, arg: fn(arg)
        detector._handle_overflow()

    scheduled.assert_called_once()
    payload = scheduled.call_args[0][0]
    assert payload["suppressed_count"] == 0


def test_detection_gap_dedup_window(tmp_path: Path) -> None:
    detector, _baseline, _publisher = _make_detector(tmp_path)
    detector._loop = MagicMock()
    detector._loop.call_soon_threadsafe.side_effect = lambda fn, arg: fn(arg)

    fake_now = [1000.0]
    with (
        patch("agent.detector.time.monotonic", side_effect=lambda: fake_now[0]),
        patch.object(detector, "_schedule_detection_gap_publish") as scheduled,
    ):
        # Cinco desbordamientos dentro de la misma ventana de 60 s.
        for _ in range(5):
            detector._handle_overflow()

        assert scheduled.call_count == 1
        first_payload = scheduled.call_args[0][0]
        assert first_payload["suppressed_count"] == 0

        # Reloj monótono avanza > 60 s (nunca dormir de verdad, D-4 del design).
        fake_now[0] += _DETECTION_GAP_WINDOW_S + 1
        detector._handle_overflow()

        assert scheduled.call_count == 2
        second_payload = scheduled.call_args[0][0]
        assert second_payload["suppressed_count"] == 4


# ── 5.10 — el detection_gap no consume la cola interna ───────────────────────


def test_detection_gap_does_not_consume_internal_queue(tmp_path: Path) -> None:
    detector, _baseline, _publisher = _make_detector(tmp_path)
    detector._raw_queue = asyncio.Queue(maxsize=1)
    detector._raw_queue.put_nowait(MagicMock())  # cola interna llena

    detector._loop = MagicMock()
    detector._loop.call_soon_threadsafe.side_effect = lambda fn, arg: fn(arg)
    # `create_task` no ejecuta la corrutina en este test (no es su foco); se
    # cierra explícitamente para no dejar un warning de "never awaited".
    detector._loop.create_task = MagicMock(side_effect=lambda coro: coro.close())

    detector._handle_overflow()

    assert detector._raw_queue.qsize() == 1  # sigue llena, nada se agregó
    assert detector.event_drops == 0
    detector._loop.create_task.assert_called_once()  # el aviso sí se agendó
