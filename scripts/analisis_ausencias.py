#!/usr/bin/env python3
"""Correlate append-only controlled-operation, agent, and backend evidence.

The trace proves only the stages it records. With no database lookup (or a failed
lookup), backend persistence remains ``unknown``; it is never rewritten as false.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import psycopg
except ImportError:
    psycopg = None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def operation_start(operation: dict[str, Any]) -> tuple[datetime, int | None]:
    """Read the pre-mutation boundary, with legacy JSONL fallback."""
    epoch = operation.get("started_epoch", operation.get("ts_epoch"))
    wall = datetime.fromtimestamp(float(epoch), tz=timezone.utc) if epoch is not None else parse_iso(operation["ts_utc"])
    monotonic = operation.get("started_monotonic_ns")
    return wall, int(monotonic) if monotonic is not None else None


def operation_windows(operations: list[dict[str, Any]], tolerance_s: float) -> dict[int, tuple[datetime, int | None, bool]]:
    """Return non-overlapping per-path windows based on pre-mutation starts.

    The shared host/kernel monotonic clock is preferred when present in both
    artifacts. It orders generator and agent records without wall-clock skew.
    It is valid here because the compose setup does not configure a time namespace.
    Legacy records fall back to UTC wall timestamps.
    """
    by_path: dict[str, list[tuple[int, datetime, int | None]]] = {}
    for index, operation in enumerate(operations):
        wall, monotonic = operation_start(operation)
        by_path.setdefault(operation["ruta_agente"], []).append((index, wall, monotonic))
    windows: dict[int, tuple[datetime, int | None, bool]] = {}
    for entries in by_path.values():
        entries.sort(key=lambda item: (item[2] if item[2] is not None else item[1].timestamp(), item[0]))
        for position, (index, start_wall, start_monotonic) in enumerate(entries):
            if position + 1 < len(entries):
                _, next_wall, next_monotonic = entries[position + 1]
                windows[index] = (next_wall, next_monotonic, False)
            else:
                windows[index] = (
                    start_wall + timedelta(seconds=tolerance_s),
                    (start_monotonic + int(tolerance_s * 1_000_000_000)) if start_monotonic is not None else None,
                    True,
                )
    return windows


def stages_for_operation(
    operation: dict[str, Any], trace: Iterable[dict[str, Any]], tolerance_s: float,
    *, end: datetime | None = None, end_monotonic_ns: int | None = None, end_inclusive: bool = True,
) -> list[dict[str, Any]]:
    start_wall, start_monotonic = operation_start(operation)
    wall_boundary = end or start_wall + timedelta(seconds=tolerance_s)
    monotonic_boundary = end_monotonic_ns
    if monotonic_boundary is None and start_monotonic is not None:
        monotonic_boundary = start_monotonic + int(tolerance_s * 1_000_000_000)

    def within(row: dict[str, Any]) -> bool:
        row_monotonic = row.get("monotonic_ns")
        if start_monotonic is not None and monotonic_boundary is not None and row_monotonic is not None:
            timestamp = int(row_monotonic)
            return start_monotonic <= timestamp <= monotonic_boundary if end_inclusive else start_monotonic <= timestamp < monotonic_boundary
        timestamp = parse_iso(row["timestamp"])
        return start_wall <= timestamp <= wall_boundary if end_inclusive else start_wall <= timestamp < wall_boundary

    return [
        row for row in trace
        if row.get("run_id") == operation["run_id"]
        and row.get("path") == operation["ruta_agente"]
        and within(row)
    ]

def classify(operation: dict[str, Any], stages: list[dict[str, Any]], backend: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    names = {str(row.get("stage")) for row in stages}
    ids = {str(row["event_id"]) for row in stages if row.get("event_id")}
    relevant_ids = {str(row["event_id"]) for row in stages if row.get("stage") == "xadd_succeeded" and row.get("event_id")}
    backend_rows = [backend[event_id] for event_id in sorted(relevant_ids) if backend is not None and event_id in backend]
    if backend is None:
        persisted: str | bool = "unknown"
    elif not relevant_ids:
        persisted = "not_applicable"
    else:
        persisted = bool(backend_rows)
    return {
        "operation_id": operation["operation_id"], "case": operation["case"], "operation": operation["operation"],
        "expected_detection": operation["deteccion_agente_esperada"],
        "kernel_seen": "kernel_received" in names,
        "suppressed": "decision_suppressed" in names,
        "decision_seen": "decision_evaluated" in names,
        "queue_persisted": "queue_enqueue_persisted" in names,
        "xadd_succeeded": "xadd_succeeded" in names,
        "xadd_failed": "xadd_failed" in names,
        "acknowledged": "ack_valid" in names,
        "backend_persisted": persisted,
        "backend_status": "|".join(str(row.get("status", "")) for row in backend_rows),
        "backend_received_at": "|".join(str(row.get("received_at", "")) for row in backend_rows),
        "event_ids": "|".join(sorted(ids)),
        "stages": "|".join(sorted(names)),
        "interpretation": interpretation(names, relevant_ids, backend),
    }


def interpretation(stages: set[str], xadd_ids: set[str], backend: dict[str, dict[str, Any]] | None) -> str:
    # One filesystem operation can produce more than one kernel notification.
    # A later duplicate may be suppressed after the first notification emitted
    # an event; that does not make the generator operation itself absent.
    if "decision_suppressed" in stages and "xadd_succeeded" not in stages:
        return "suppressed_by_active_baseline"
    if "kernel_received" not in stages:
        return "no_kernel_trace_in_window"
    if "decision_evaluated" not in stages:
        return "kernel_to_decision_gap"
    if "queue_enqueue_persisted" not in stages:
        return "decision_to_queue_gap"
    if "xadd_succeeded" not in stages:
        return "queue_to_xadd_gap"
    if backend is None:
        return "backend_lookup_unknown"
    if xadd_ids and not any(event_id in backend for event_id in xadd_ids):
        return "xadd_to_backend_gap"
    if "ack_valid" not in stages:
        return "backend_or_ack_pending"
    return "fully_correlated"


def backend_rows(database_url: str | None, event_ids: set[str]) -> dict[str, dict[str, Any]] | None:
    if not database_url:
        return None
    if psycopg is None:
        raise RuntimeError("psycopg is required for --database-url")
    if not event_ids:
        return {}
    query = "SELECT event_id::text, status, received_at FROM events WHERE event_id::text = ANY(%s)"
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(query, (list(event_ids),))
        return {str(event_id): {"status": status, "received_at": received_at} for event_id, status, received_at in cur.fetchall()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--operaciones", required=True, type=Path)
    parser.add_argument("--traza", required=True, type=Path)
    parser.add_argument("--salida", type=Path, default=Path("bateria9_correlacion.csv"))
    parser.add_argument("--tolerancia-s", type=float, default=30.0)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"), help="Optional read-only backend lookup")
    args = parser.parse_args(argv)
    operations, trace = read_jsonl(args.operaciones), read_jsonl(args.traza)
    if not operations:
        print("No operations to correlate", file=sys.stderr)
        return 2
    xadd_ids = {str(row["event_id"]) for row in trace if row.get("stage") == "xadd_succeeded" and row.get("event_id")}
    try:
        backend = backend_rows(args.database_url, xadd_ids)
    except Exception as exc:
        print(f"Backend lookup unavailable; backend_persisted=unknown: {type(exc).__name__}: {exc}", file=sys.stderr)
        backend = None
    windows = operation_windows(operations, args.tolerancia_s)
    rows = [
        classify(op, stages_for_operation(op, trace, args.tolerancia_s, end=windows[index][0], end_monotonic_ns=windows[index][1], end_inclusive=windows[index][2]), backend)
        for index, op in enumerate(operations)
    ]
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    with args.salida.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    counts: dict[str, int] = {}
    for row in rows: counts[row["interpretation"]] = counts.get(row["interpretation"], 0) + 1
    print(f"CSV: {args.salida}")
    print(" | ".join(f"{name}={count}" for name, count in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
