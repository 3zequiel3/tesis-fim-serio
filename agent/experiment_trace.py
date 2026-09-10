"""Opt-in append-only trace for controlled detection experiments.

The trace is deliberately observational: it neither changes detection decisions nor
contains file contents, event payloads, credentials, diffs, or process arguments.
It is enabled only with both ``FIM_EXPERIMENT_TRACE_FILE`` and
``FIM_EXPERIMENT_RUN_ID``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any


class ExperimentTrace:
    """Append JSONL records with a closed, content-free schema.

    A missing configuration is a no-op. Failures to write are intentionally
    best-effort: experimental observability must never alter the FIM pipeline.
    """

    _ALLOWED_FIELDS = frozenset({
        "event_id", "path", "operation", "kernel_event", "baseline_status",
        "baseline_hash", "hash_before", "hash_after", "decision", "reason",
        "outcome", "queue_size", "suppressed_count", "source", "attempt",
        "baseline_revision",
    })

    def __init__(self, path: Path | None = None, run_id: str | None = None) -> None:
        self._path = path
        self._run_id = run_id

    @classmethod
    def from_environment(cls) -> "ExperimentTrace":
        raw_path = os.environ.get("FIM_EXPERIMENT_TRACE_FILE")
        run_id = os.environ.get("FIM_EXPERIMENT_RUN_ID")
        if not raw_path or not run_id:
            return cls()
        return cls(Path(raw_path), run_id)

    @property
    def enabled(self) -> bool:
        return self._path is not None and bool(self._run_id)

    def record(self, stage: str, **fields: Any) -> None:
        """Append one schema-checked record, without raising into production code."""
        if not self.enabled:
            return
        unknown = set(fields).difference(self._ALLOWED_FIELDS)
        if unknown:
            raise ValueError(f"unsupported experiment trace fields: {sorted(unknown)}")
        record = {
            "schema_version": 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Comparable with the harness only in its shared host/kernel; Docker
            # does not create a time namespace in this compose configuration.
            "monotonic_ns": time.monotonic_ns(),
            "run_id": self._run_id,
            "stage": stage,
            **fields,
        }
        # JSON's default separators keep each line well below PIPE_BUF for the
        # closed schema above, so O_APPEND gives a single append operation.
        line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        try:
            assert self._path is not None
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        except OSError:
            # The trace is not evidence if it cannot be written, but it must not
            # cause a detection, queue, or publication failure.
            return
