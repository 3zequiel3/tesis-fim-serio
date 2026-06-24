"""Tests de multi-evento fanotify y operation_type (D12, C26 task 3.x)."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.detector import FanotifyDetector, FanotifyEvent


def _make_detector(tmp_path: Path) -> tuple[FanotifyDetector, MagicMock, MagicMock]:
    baseline = MagicMock()
    baseline.read_entry.return_value = None

    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0

    detector = FanotifyDetector(
        agent_id="agent-test",
        watch_paths=[str(tmp_path)],
        baseline=baseline,
        publisher=publisher,
        stop_event=asyncio.Event(),
    )
    return detector, baseline, publisher


# ── classify_event ────────────────────────────────────────────────────────────

def test_classify_event_no_fanotify_returns_file_modified() -> None:
    """Sin fanotify disponible, _classify_event siempre devuelve file_modified."""
    from agent.detector import _HAS_FAN
    if _HAS_FAN:
        pytest.skip("test only applies when pyfanotify is not available")

    detector = FanotifyDetector(
        agent_id="a",
        watch_paths=["/tmp"],
        baseline=MagicMock(),
        publisher=MagicMock(),
        stop_event=asyncio.Event(),
    )
    assert detector._classify_event(0) == "file_modified"
    assert detector._classify_event(0xFF) == "file_modified"


# ── FAN_DELETE → file_deleted ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fanotify_delete_emits_file_deleted(tmp_path: Path) -> None:
    """Evento FAN_DELETE: emite operation_type=file_deleted, hash nulo, llama mark_absent."""
    detector, baseline, publisher = _make_detector(tmp_path)

    # Simular que hay entry previa con hash
    entry_mock = MagicMock()
    entry_mock.hash = "deadbeef"
    baseline.read_entry.return_value = entry_mock

    # Forzar mask = FAN_DELETE (simular sin fanotify real)
    # _classify_event con mask que tiene bit FAN_DELETE
    # Parcheamos _classify_event para retornar file_deleted
    with patch.object(detector, "_classify_event", return_value="file_deleted"):
        fan_event = FanotifyEvent(
            path=str(tmp_path / "deleted_file.txt"),
            pid=100, uid=0, exe=None,
            timestamp="2026-01-01T00:00:00+00:00",
            mask=0,
        )
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["operation_type"] == "file_deleted"
    assert published["event_type"] == "file_deleted"
    assert published["current_hash"] is None
    baseline.mark_absent.assert_called_once_with(str(tmp_path / "deleted_file.txt"))


# ── FAN_MOVED_FROM → file_deleted ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fanotify_moved_from_emits_file_deleted(tmp_path: Path) -> None:
    detector, baseline, publisher = _make_detector(tmp_path)

    with patch.object(detector, "_classify_event", return_value="file_deleted"):
        fan_event = FanotifyEvent(
            path=str(tmp_path / "moved.txt"),
            pid=100, uid=0, exe=None,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["operation_type"] == "file_deleted"
    baseline.mark_absent.assert_called_once()


# ── FAN_CREATE → file_created ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fanotify_create_emits_file_created(tmp_path: Path) -> None:
    """Evento FAN_CREATE: emite operation_type=file_created, hashea, llama write_entry."""
    target = tmp_path / "new_file.txt"
    content = b"brand new file"
    target.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()

    detector, baseline, publisher = _make_detector(tmp_path)

    with (
        patch.object(detector, "_classify_event", return_value="file_created"),
        patch("agent.detector._hash_file_async", return_value=expected_hash),
    ):
        fan_event = FanotifyEvent(
            path=str(target),
            pid=100, uid=0, exe=None,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["operation_type"] == "file_created"
    assert published["event_type"] == "file_created"
    assert published["current_hash"] == expected_hash
    assert published["previous_hash"] is None
    baseline.write_entry.assert_called_once_with(str(target))


# ── FAN_MOVED_TO → file_created ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fanotify_moved_to_emits_file_created(tmp_path: Path) -> None:
    target = tmp_path / "moved_to.txt"
    content = b"moved content"
    target.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()

    detector, baseline, publisher = _make_detector(tmp_path)

    with (
        patch.object(detector, "_classify_event", return_value="file_created"),
        patch("agent.detector._hash_file_async", return_value=expected_hash),
    ):
        fan_event = FanotifyEvent(
            path=str(target), pid=100, uid=0, exe=None,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["operation_type"] == "file_created"
    baseline.write_entry.assert_called_once()


# ── FAN_CLOSE_WRITE → file_modified ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_fanotify_close_write_emits_file_modified(tmp_path: Path) -> None:
    target = tmp_path / "modified.txt"
    content = b"modified content"
    target.write_bytes(content)
    new_hash = hashlib.sha256(content).hexdigest()

    detector, baseline, publisher = _make_detector(tmp_path)

    with (
        patch.object(detector, "_classify_event", return_value="close_write"),
        patch("agent.detector._hash_file_async", return_value=new_hash),
    ):
        fan_event = FanotifyEvent(
            path=str(target), pid=100, uid=0, exe=None,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["operation_type"] == "file_modified"
    assert published["event_type"] == "file_modified"


# ── file_created cuando el archivo ya desapareció ────────────────────────────

@pytest.mark.asyncio
async def test_fanotify_create_file_vanished_no_publish(tmp_path: Path) -> None:
    """FAN_CREATE pero el archivo desapareció antes de hashear: no publicar."""
    detector, baseline, publisher = _make_detector(tmp_path)

    with (
        patch.object(detector, "_classify_event", return_value="file_created"),
        patch("agent.detector._hash_file_async", return_value=None),
    ):
        fan_event = FanotifyEvent(
            path=str(tmp_path / "ghost.txt"), pid=100, uid=0, exe=None,
            timestamp="2026-01-01T00:00:00+00:00",
        )
        await detector._process_event(fan_event)

    publisher.publish.assert_not_called()


# ── ev.path is None → drop + warning ─────────────────────────────────────────

def test_fanotify_null_path_dropped() -> None:
    """_read_loop descarta eventos con ev.path is None y emite warning."""
    import structlog
    from agent.detector import FanotifyDetector

    stop = asyncio.Event()
    stop.set()  # loop se detiene inmediatamente

    detector = FanotifyDetector(
        agent_id="agent-null-test",
        watch_paths=["/tmp"],
        baseline=MagicMock(),
        publisher=MagicMock(),
        stop_event=stop,
    )

    null_ev = MagicMock()
    null_ev.path = None
    null_ev.pid = 999

    loop = asyncio.new_event_loop()
    detector._loop = loop
    raw_queue_items: list = []
    detector._raw_queue = MagicMock()
    detector._raw_queue.put_nowait = raw_queue_items.append

    with patch.object(detector, "_read_fan_events", return_value=[null_ev]):
        # Forzar una iteración: stop_event ya está set, pero necesitamos que no sea visto antes
        detector._stop_event = asyncio.Event()
        import threading

        def _run_then_stop() -> None:
            import time
            time.sleep(0.05)
            detector._stop_event.set()

        t = threading.Thread(target=_run_then_stop)
        t.start()
        detector._read_loop()
        t.join()

    # El evento null no fue encolado
    assert raw_queue_items == []
    loop.close()


# ── operation_type en payload ─────────────────────────────────────────────────

def test_detected_change_to_event_data_includes_operation_type() -> None:
    from agent.detector import DetectedChange
    change = DetectedChange(
        event_id="test-001",
        path="/etc/test",
        event_type="file_modified",
        operation_type="file_modified",
        previous_hash="abc",
        current_hash="def",
        diff_text=None,
        process_pid=1,
        process_uid=0,
        process_exe=None,
        detected_at="2026-01-01T00:00:00+00:00",
        parent_event_id=None,
    )
    data = change.to_event_data()
    assert "operation_type" in data
    assert data["operation_type"] == "file_modified"
    assert data["event_type"] == "file_modified"
