"""Tests de reload_paths (C09, task 11.6)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from agent.detector import FanotifyDetector


def _make_detector_with_mock_fan(tmp_path: Path) -> FanotifyDetector:
    baseline = MagicMock()
    baseline.init_scan = MagicMock()
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0
    stop_event = MagicMock()
    detector = FanotifyDetector(
        agent_id="agent-01",
        watch_paths=["/etc"],
        baseline=baseline,
        publisher=publisher,
        stop_event=stop_event,
    )
    # Mock backend fanotify methods
    detector._flush_marks = MagicMock()
    detector._mark_paths = MagicMock()
    detector._mark_exclusion = MagicMock()
    return detector


def test_reload_paths_flushes_before_remark(tmp_path: Path) -> None:
    detector = _make_detector_with_mock_fan(tmp_path)
    detector.reload_paths(["/etc", "/opt/app"])

    detector._flush_marks.assert_called_once()
    detector._mark_paths.assert_called_once_with(["/etc", "/opt/app"])
    detector._mark_exclusion.assert_called_once()


def test_reload_paths_scans_new_paths_only(tmp_path: Path) -> None:
    detector = _make_detector_with_mock_fan(tmp_path)
    detector.reload_paths(["/etc", "/opt/app"])

    # /etc ya estaba en watch_paths; /opt/app es nuevo → solo scan de /opt/app
    detector._baseline.init_scan.assert_called_once_with(["/opt/app"])


def test_reload_paths_no_scan_when_no_new_paths(tmp_path: Path) -> None:
    detector = _make_detector_with_mock_fan(tmp_path)
    detector.reload_paths(["/etc"])

    detector._baseline.init_scan.assert_not_called()


def test_reload_paths_updates_watch_paths(tmp_path: Path) -> None:
    detector = _make_detector_with_mock_fan(tmp_path)
    detector.reload_paths(["/var/log"])

    assert detector._watch_paths == ["/var/log"]


def test_reload_paths_handles_flush_error_gracefully(tmp_path: Path) -> None:
    detector = _make_detector_with_mock_fan(tmp_path)
    detector._flush_marks.side_effect = OSError("flush failed")

    # No debe lanzar excepción
    detector.reload_paths(["/etc"])

    # Aún debe re-marcar y actualizar paths
    detector._mark_paths.assert_called_once()
