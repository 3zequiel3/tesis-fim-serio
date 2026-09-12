"""Tests for binary-mode diff metadata (US-09): hash comparison + bounded partial
hex dump when the modified file is not UTF-8 text. Mirrors the harness pattern of
test_detector_multi_event.py / test_symlink_hardening.py (_process_event via a
mocked baseline + publisher, no real fanotify)."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.detector import FanotifyDetector, FanotifyEvent, _HEX_DUMP_BYTES, _hex_dump


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


# ── _hex_dump ─────────────────────────────────────────────────────────────────


def test_hex_dump_formats_bytes_in_16_byte_rows() -> None:
    data = bytes(range(20))
    dump = _hex_dump(data)
    lines = dump.splitlines()
    assert lines[0] == "00000000  00 01 02 03 04 05 06 07 08 09 0a 0b 0c 0d 0e 0f"
    assert lines[1] == "00000010  10 11 12 13"


def test_hex_dump_bounded_to_first_n_bytes() -> None:
    data = b"\xff" * (_HEX_DUMP_BYTES * 4)
    dump = _hex_dump(data)
    # Bounded: only the first _HEX_DUMP_BYTES bytes are ever rendered, regardless
    # of how much data is passed in (RN-09/US-09 defensive bound, same posture
    # as _MAX_DIFF_BYTES for text diffs).
    expected_rows = _HEX_DUMP_BYTES // 16
    assert len(dump.splitlines()) == expected_rows


def test_hex_dump_empty_bytes_returns_empty_string() -> None:
    assert _hex_dump(b"") == ""


# ── _process_event integration: binary file_modified ─────────────────────────


@pytest.mark.asyncio
async def test_binary_modification_sets_is_binary_and_hex_dumps(tmp_path: Path) -> None:
    """A non-UTF-8 modified file gets is_binary=True and bounded hex dumps on
    both sides, with diff_text staying None (no textual diff for binary content).
    """
    detector, baseline, publisher = _make_detector(tmp_path)

    target = tmp_path / "binary.dat"
    new_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
    target.write_bytes(new_content)

    old_content = b"\x89PNG\r\n\x1a\nOLDDATA"
    entry_mock = MagicMock()
    entry_mock.hash = "old-hash"
    entry_mock.content_b64 = base64.b64encode(old_content).decode()
    entry_mock.oversize = False
    entry_mock.status = "active"
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=str(target), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["diff_text"] is None
    assert published["is_binary"] is True
    assert published["hex_dump_after"] == _hex_dump(new_content)
    assert published["hex_dump_before"] == _hex_dump(old_content)


@pytest.mark.asyncio
async def test_binary_modification_without_previous_content_has_no_hex_dump_before(
    tmp_path: Path,
) -> None:
    """No usable baseline content (oversize) -> hex_dump_before stays None, but
    the current file's binary sample is still reported (hash + hex dump after)."""
    detector, baseline, publisher = _make_detector(tmp_path)

    target = tmp_path / "binary.dat"
    new_content = b"\x00\x01\x02binary-content"
    target.write_bytes(new_content)

    entry_mock = MagicMock()
    entry_mock.hash = "old-hash"
    entry_mock.content_b64 = None
    entry_mock.oversize = True
    entry_mock.status = "active"
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=str(target), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["is_binary"] is True
    assert published["hex_dump_before"] is None
    assert published["hex_dump_after"] == _hex_dump(new_content)


@pytest.mark.asyncio
async def test_text_modification_does_not_set_is_binary(tmp_path: Path) -> None:
    """A regular UTF-8 text modification keeps is_binary False and no hex dumps —
    the existing diff_text path already covers it."""
    detector, baseline, publisher = _make_detector(tmp_path)

    target = tmp_path / "config.txt"
    target.write_text("line1\nline2\n", encoding="utf-8")

    entry_mock = MagicMock()
    entry_mock.hash = "old-hash"
    entry_mock.content_b64 = base64.b64encode(b"line1\noldline2\n").decode()
    entry_mock.oversize = False
    entry_mock.status = "active"
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=str(target), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["diff_text"] is not None
    assert published["is_binary"] is False
    assert published["hex_dump_before"] is None
    assert published["hex_dump_after"] is None


@pytest.mark.asyncio
async def test_oversized_file_is_not_flagged_binary(tmp_path: Path) -> None:
    """A file over _MAX_DIFF_BYTES stays out of both modes (existing gap,
    unchanged): no textual diff AND no binary hex dump — ambiguous size, not a
    detected binary format."""
    from agent.detector import _MAX_DIFF_BYTES

    detector, baseline, publisher = _make_detector(tmp_path)

    target = tmp_path / "big.bin"
    target.write_bytes(b"\x00" * (_MAX_DIFF_BYTES + 1024))

    entry_mock = MagicMock()
    entry_mock.hash = "old-hash"
    entry_mock.content_b64 = None
    entry_mock.oversize = True
    entry_mock.status = "active"
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=str(target), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )
    await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["is_binary"] is False
    assert published["hex_dump_before"] is None
    assert published["hex_dump_after"] is None
