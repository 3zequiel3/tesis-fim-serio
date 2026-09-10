from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent.config import AgentConfig, StorageConfig
from agent.experiment_trace import ExperimentTrace
from agent.publisher import Publisher
from agent.queue import EventQueue


@pytest.fixture()
def publisher(tmp_path: Path) -> tuple[Publisher, Path, AsyncMock]:
    secrets = tmp_path / "secrets"; secrets.mkdir()
    (secrets / "shared_secret").write_bytes(os.urandom(32))
    cfg = AgentConfig(
        agent_id="trace-agent", backend_url="http://backend", valkey_url="redis://valkey",
        ca_cert_path="/certs/ca.pem", watch_paths=["/watch"],
        storage=StorageConfig(baseline_dir=str(tmp_path / "baseline"), queue_dir=str(tmp_path / "queue"),
                              journal_dir=str(tmp_path / "journal"), secrets_dir=str(secrets), certs_dir=str(tmp_path / "certs")),
    )
    client = AsyncMock(); client.xadd = AsyncMock(return_value="1-0")
    trace_path = tmp_path / "trace.jsonl"
    return Publisher(cfg, EventQueue(cfg.storage.queue_dir), client, ExperimentTrace(trace_path, "run-trace")), trace_path, client


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_xadd_failure_is_not_reported_as_success(publisher: tuple[Publisher, Path, AsyncMock]) -> None:
    pub, trace_path, client = publisher
    client.xadd.side_effect = ConnectionError("offline")
    asyncio.run(pub.publish({"event_id": "event-1", "path": "/watch/a", "hash_detected": "after"}))
    stages = [row["stage"] for row in rows(trace_path)]
    assert "queue_enqueue_persisted" in stages
    assert "xadd_failed" in stages
    assert "xadd_succeeded" not in stages


def test_valid_ack_is_recorded_by_publisher_before_detector_callback(publisher: tuple[Publisher, Path, AsyncMock]) -> None:
    pub, trace_path, _client = publisher
    asyncio.run(pub.publish({"event_id": "event-2", "path": "/watch/a", "hash_detected": "after"}))
    asyncio.run(pub._handle_command_async({"type": "event_ack", "event_id": "event-2"}))
    assert any(row["stage"] == "ack_valid" and row["event_id"] == "event-2" for row in rows(trace_path))


def test_queue_eviction_is_recorded_at_publisher_boundary(publisher: tuple[Publisher, Path, AsyncMock]) -> None:
    pub, trace_path, _client = publisher
    pub._trace_events["old"] = {"event_id": "old", "path": "/watch/a"}
    pub._forget_evicted_event("old")
    assert rows(trace_path)[-1]["stage"] == "queue_evicted"
