#!/usr/bin/env python3
"""Measure durable queue bookkeeping after the in-memory index change."""

from __future__ import annotations

import json
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.queue import EventQueue


COUNT = 3000
HERE = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="fim-queue-index-") as directory:
    queue = EventQueue(Path(directory) / "queue")
    base = datetime.now(timezone.utc)
    event_ids: list[str] = []

    started = time.perf_counter_ns()
    for index in range(COUNT):
        event_id = str(uuid.uuid4())
        event_ids.append(event_id)
        queue.enqueue(
            {
                "event_id": event_id,
                "detected_at": (base + timedelta(microseconds=index)).isoformat(),
                "path": f"/controlled/{index}",
                "hash_detected": "a" * 64,
                "schema_version": 1,
            }
        )
    enqueued = time.perf_counter_ns()

    for event_id in event_ids:
        queue.bump_attempts(event_id)
    bumped = time.perf_counter_ns()

    for event_id in event_ids:
        queue.remove(event_id)
    removed = time.perf_counter_ns()

    result = {
        "evaluation": "drenaje-20260910-queue-index-profile",
        "new_evaluation": True,
        "events": COUNT,
        "enqueue_seconds": (enqueued - started) / 1e9,
        "bump_attempts_seconds": (bumped - enqueued) / 1e9,
        "remove_seconds": (removed - bumped) / 1e9,
        "remaining_events": queue.queue_size,
        "remaining_bytes": queue._total_bytes(),
        "clock": "time.perf_counter_ns",
        "scope": "local durable queue only; excludes Valkey and PostgreSQL",
    }
    (HERE / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
