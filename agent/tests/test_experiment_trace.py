from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.experiment_trace import ExperimentTrace


def test_trace_is_opt_in_and_append_only(tmp_path: Path) -> None:
    trace_path = tmp_path / "evidence" / "trace.jsonl"
    trace = ExperimentTrace(trace_path, "run-123")

    trace.record("kernel_received", path="/watch/file", kernel_event="close_write")
    trace.record("ack_received", event_id="event-1", outcome="acknowledged")

    rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert [row["stage"] for row in rows] == ["kernel_received", "ack_received"]
    assert all(row["run_id"] == "run-123" for row in rows)
    assert rows[0]["path"] == "/watch/file"
    assert isinstance(rows[0]["monotonic_ns"], int)
    assert "content" not in rows[0]


def test_trace_rejects_unbounded_or_secret_bearing_fields(tmp_path: Path) -> None:
    trace = ExperimentTrace(tmp_path / "trace.jsonl", "run-123")
    with pytest.raises(ValueError, match="unsupported"):
        trace.record("bad", content="must never be traced")
    assert not (tmp_path / "trace.jsonl").exists()


def test_trace_from_environment_requires_path_and_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIM_EXPERIMENT_TRACE_FILE", raising=False)
    monkeypatch.delenv("FIM_EXPERIMENT_RUN_ID", raising=False)
    assert not ExperimentTrace.from_environment().enabled
