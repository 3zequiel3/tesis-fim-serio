#!/usr/bin/env python3
"""Derive transparent diagnostics from Run 2 metrics.jsonl."""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
rows = [json.loads(line) for line in (ROOT / "metrics.jsonl").read_text().splitlines()]
# Multiple queue filenames can share the same millisecond prefix; filesystem
# glob order inside that tie is not the generator sequence. Use the observed
# first XADD order for inter-publication gaps.
ordered = sorted(rows, key=lambda row: row["xadd_start_ns"])


def span_seconds(key: str) -> float | None:
    values = [row[key] for row in rows if key in row]
    return (max(values) - min(values)) / 1e9 if values else None


post_xadd_gap_ms = [
    (current["xadd_start_ns"] - previous["xadd_end_ns"]) / 1e6
    for previous, current in zip(ordered, ordered[1:])
]

result = {
    "unique_events": len(rows),
    "stream_publications": sum(row.get("event_xadd_count", 0) for row in rows),
    "excess_publications": sum(max(row.get("event_xadd_count", 0) - 1, 0) for row in rows),
    "publication_count_distribution": dict(sorted(Counter(row.get("event_xadd_count", 0) for row in rows).items())),
    "consumer_deliveries_observed_before_stop": sum(row.get("consumer_delivery_count", 0) for row in rows),
    "xacks_observed_before_stop": sum(row.get("xack_count", 0) for row in rows),
    "first_publication_span_seconds": span_seconds("xadd_end_ns"),
    "first_consumer_read_span_seconds": span_seconds("consumer_read_ns"),
    "first_commit_span_seconds": span_seconds("persist_commit_ns"),
    "agent_ack_apply_span_seconds": span_seconds("agent_ack_applied_ns"),
    "between_sequential_first_xadds": {
        "mean_ms": statistics.mean(post_xadd_gap_ms),
        "median_ms": statistics.median(post_xadd_gap_ms),
        "p95_ms_nearest_rank": sorted(post_xadd_gap_ms)[int(0.95 * (len(post_xadd_gap_ms) - 1))],
    },
    "interpretation_limits": [
        "Stage intervals overlap because publisher and consumer run concurrently; they must not be summed.",
        "A small negative ack-publication-to-agent-observation interval is possible because XREAD can wake before the producer coroutine records return from XADD.",
        "The harness stopped once all unique events were persisted and the local queue was empty; excess duplicate stream entries remained outside the completion contract.",
    ],
}
(ROOT / "analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
print(json.dumps(result, indent=2, sort_keys=True))
