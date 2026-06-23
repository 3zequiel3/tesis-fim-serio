"""Tests de deduplicación con parent_event_id y on_ack (C09, task 11.3)."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.detector import FanotifyDetector, FanotifyEvent


def _make_detector(tmp_path: Path) -> tuple[FanotifyDetector, asyncio.Event]:
    baseline = MagicMock()
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0
    stop_event = asyncio.Event()
    detector = FanotifyDetector(
        agent_id="agent-01",
        watch_paths=[str(tmp_path)],
        baseline=baseline,
        publisher=publisher,
        stop_event=stop_event,
    )
    return detector, stop_event


@pytest.mark.asyncio
async def test_first_event_has_no_parent_event_id(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    content = b"version1"
    f.write_bytes(content)

    detector, _ = _make_detector(tmp_path)
    # Baseline retorna None (archivo nuevo)
    detector._baseline.read_entry.return_value = None

    fan_event = FanotifyEvent(
        path=str(f), pid=100, uid=0, exe="/bin/test",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    await detector._process_event(fan_event)

    call_kwargs = detector._publisher.publish.call_args[0][0]
    assert call_kwargs["parent_event_id"] is None
    assert call_kwargs["path"] == str(f)


@pytest.mark.asyncio
async def test_second_event_has_parent_event_id(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_bytes(b"v1")

    detector, _ = _make_detector(tmp_path)
    detector._baseline.read_entry.return_value = None

    fan_event = FanotifyEvent(
        path=str(f), pid=100, uid=0, exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
    )

    # Primer evento
    await detector._process_event(fan_event)
    first_event_id = detector._publisher.publish.call_args[0][0]["event_id"]
    first_path_event_id = detector._pending.get(str(f))
    assert first_path_event_id == first_event_id

    # Cambiar contenido del archivo para que el segundo evento no se descarte
    f.write_bytes(b"v2")
    # Ahora el baseline retorna el hash de v1
    entry_mock = MagicMock()
    entry_mock.hash = hashlib.sha256(b"v1").hexdigest()
    entry_mock.content_b64 = None
    entry_mock.oversize = False
    detector._baseline.read_entry.return_value = entry_mock

    # Segundo evento
    await detector._process_event(fan_event)
    second_call = detector._publisher.publish.call_args[0][0]
    assert second_call["parent_event_id"] == first_event_id


def test_on_ack_removes_pending_entry(tmp_path: Path) -> None:
    detector, _ = _make_detector(tmp_path)
    # Populamos ambos mapas (invariante: _pending y _event_to_path siempre en lockstep)
    detector._pending["/etc/hosts"] = "event-abc"
    detector._event_to_path["event-abc"] = "/etc/hosts"
    detector._pending["/etc/passwd"] = "event-xyz"
    detector._event_to_path["event-xyz"] = "/etc/passwd"

    detector.on_ack("event-abc")

    assert "/etc/hosts" not in detector._pending
    assert "event-abc" not in detector._event_to_path
    assert "/etc/passwd" in detector._pending


def test_on_ack_ignores_unknown_event_id(tmp_path: Path) -> None:
    detector, _ = _make_detector(tmp_path)
    detector._pending["/etc/hosts"] = "event-abc"
    detector._event_to_path["event-abc"] = "/etc/hosts"

    detector.on_ack("event-unknown")  # no debe lanzar

    assert "/etc/hosts" in detector._pending
