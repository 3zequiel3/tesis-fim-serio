"""Tests de descarte de eventos cuando el hash no cambió (C09, task 11.4)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.detector import FanotifyDetector, FanotifyEvent


@pytest.mark.asyncio
async def test_event_discarded_when_hash_unchanged(tmp_path: Path) -> None:
    content = b"unchanged content"
    f = tmp_path / "file.txt"
    f.write_bytes(content)

    baseline = MagicMock()
    entry_mock = MagicMock()
    entry_mock.hash = hashlib.sha256(content).hexdigest()
    baseline.read_entry.return_value = entry_mock

    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0

    detector = FanotifyDetector(
        agent_id="agent-01",
        watch_paths=[str(tmp_path)],
        baseline=baseline,
        publisher=publisher,
        stop_event=MagicMock(),
    )

    fan_event = FanotifyEvent(
        path=str(f), pid=100, uid=0, exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    await detector._process_event(fan_event)

    publisher.publish.assert_not_called()
