"""Integral log-inspection test (US-09, W6): processing a real file
modification (text and binary) must never emit diff/hex-dump content through
the agent's structured logs — only hash_before/hash_after/size_delta reach
the (opt-in) experiment trace, and no structlog call anywhere in the
_process_event path carries diff_text/hex_dump_* content.

Uses structlog.testing.capture_logs(), which captures the RAW event dict
passed to each log call — i.e. it exercises the actual call sites in
detector.py directly, independent of (and in addition to) the sanitize_logs
processor already covered by test_logging.py.
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from agent.detector import FanotifyDetector, FanotifyEvent, _hex_dump
from agent.experiment_trace import ExperimentTrace


def _make_detector(
    tmp_path: Path, experiment_trace: ExperimentTrace
) -> tuple[FanotifyDetector, MagicMock, MagicMock]:
    baseline = MagicMock()
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
        experiment_trace=experiment_trace,
    )
    return detector, baseline, publisher


def _read_classified_records(trace_path: Path) -> list[dict]:
    lines = trace_path.read_text().splitlines()
    records = [json.loads(line) for line in lines]
    return [r for r in records if r["stage"] == "change_classified"]


@pytest.mark.asyncio
async def test_binary_modification_never_logs_diff_or_hexdump_content(
    tmp_path: Path,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace = ExperimentTrace(trace_path, "run-binary")
    detector, baseline, _publisher = _make_detector(tmp_path, trace)

    target = tmp_path / "binary.dat"
    new_content = b"\x89PNG\r\n\x1a\nNEWSECRETBYTES"
    target.write_bytes(new_content)

    old_content = b"\x89PNG\r\n\x1a\nOLDSECRETBYTES"
    entry_mock = MagicMock()
    entry_mock.hash = "old-hash"
    entry_mock.content_b64 = base64.b64encode(old_content).decode()
    entry_mock.oversize = False
    entry_mock.status = "active"
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=str(target), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )

    with structlog.testing.capture_logs() as captured:
        await detector._process_event(fan_event)

    expected_hex_after = _hex_dump(new_content)
    expected_hex_before = _hex_dump(old_content)
    for record in captured:
        assert "diff_text" not in record
        assert "hex_dump_before" not in record
        assert "hex_dump_after" not in record
        serialized = json.dumps(record, default=str)
        assert expected_hex_after not in serialized
        assert expected_hex_before not in serialized
        assert "NEWSECRETBYTES" not in serialized
        assert "OLDSECRETBYTES" not in serialized

    classified = _read_classified_records(trace_path)
    assert len(classified) == 1
    record = classified[0]
    assert record["hash_before"] == "old-hash"
    assert record["hash_after"]
    assert record["size_delta"] == len(new_content) - len(old_content)
    assert "diff_text" not in record
    assert "hex_dump_before" not in record
    assert "hex_dump_after" not in record


@pytest.mark.asyncio
async def test_text_modification_never_logs_diff_content(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace = ExperimentTrace(trace_path, "run-text")
    detector, baseline, _publisher = _make_detector(tmp_path, trace)

    target = tmp_path / "config.txt"
    target.write_text("line1\nSECRET-NEW-LINE\n", encoding="utf-8")

    entry_mock = MagicMock()
    entry_mock.hash = "old-hash"
    entry_mock.content_b64 = base64.b64encode(b"line1\nSECRET-OLD-LINE\n").decode()
    entry_mock.oversize = False
    entry_mock.status = "active"
    baseline.read_entry.return_value = entry_mock

    fan_event = FanotifyEvent(
        path=str(target), pid=1, uid=0, exe=None, timestamp="2026-01-01T00:00:00+00:00",
    )

    with structlog.testing.capture_logs() as captured:
        await detector._process_event(fan_event)

    for record in captured:
        assert "diff_text" not in record
        serialized = json.dumps(record, default=str)
        assert "SECRET-NEW-LINE" not in serialized
        assert "SECRET-OLD-LINE" not in serialized

    classified = _read_classified_records(trace_path)
    assert len(classified) == 1
    record = classified[0]
    assert record["hash_before"] == "old-hash"
    assert record["hash_after"]
    # Text path: size_delta is still bounded/available since both sizes are
    # known (the diff itself is the thing withheld from logs, not the size).
    assert record["size_delta"] == len("line1\nSECRET-NEW-LINE\n") - len(
        "line1\nSECRET-OLD-LINE\n"
    )
    assert "diff_text" not in record
