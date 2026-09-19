#!/usr/bin/env python3
"""Compare HEAD queue bookkeeping with the current indexed implementation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.queue import EventQueue as IndexedEventQueue


COUNT = 3000
HERE = Path(__file__).resolve().parent


def load_head_queue(tempdir: Path) -> type[Any]:
    source = subprocess.check_output(["git", "show", "HEAD:agent/queue.py"], text=True)
    module_path = tempdir / "queue_at_head.py"
    module_path.write_text(source)
    spec = importlib.util.spec_from_file_location("queue_at_head", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.EventQueue


def profile(queue_type: type[Any], root: Path, payloads: list[dict[str, Any]]) -> dict[str, float | int]:
    queue = queue_type(root)
    started = time.perf_counter_ns()
    for payload in payloads:
        queue.enqueue(payload)
    enqueued = time.perf_counter_ns()
    for payload in payloads:
        queue.bump_attempts(payload["event_id"])
    bumped = time.perf_counter_ns()
    for payload in payloads:
        queue.remove(payload["event_id"])
    removed = time.perf_counter_ns()
    return {
        "enqueue_seconds": (enqueued - started) / 1e9,
        "bump_attempts_seconds": (bumped - enqueued) / 1e9,
        "remove_seconds": (removed - bumped) / 1e9,
        "remaining_events": queue.queue_size,
    }


base = datetime.now(timezone.utc)
payloads = [
    {
        "event_id": str(uuid.uuid4()),
        "detected_at": (base + timedelta(microseconds=index)).isoformat(),
        "path": f"/controlled/{index}",
        "hash_detected": "a" * 64,
        "schema_version": 1,
    }
    for index in range(COUNT)
]

with tempfile.TemporaryDirectory(prefix="fim-queue-comparison-") as directory:
    root = Path(directory)
    HeadEventQueue = load_head_queue(root)
    result = {
        "evaluation": "drenaje-20260910-queue-index-comparison",
        "events_per_variant": COUNT,
        "head_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "head_implementation": profile(HeadEventQueue, root / "head", payloads),
        "indexed_worktree_implementation": profile(IndexedEventQueue, root / "indexed", payloads),
        "clock": "time.perf_counter_ns",
        "controls": "same process, filesystem, payload list and operation order",
    }

(HERE / "comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(json.dumps(result, indent=2, sort_keys=True))
