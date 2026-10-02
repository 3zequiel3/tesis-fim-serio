"""Durable registry of executed destructive commands (D83/RN-177, D-9).

The publisher persists its stream cursor only AFTER dispatching a command, so a
command can be redelivered after a restart. For destructive commands the handler
records the outcome here BEFORE publishing its ``command_ack``; a redelivery of an
already-recorded ``command_id`` re-publishes the same outcome and executes nothing.

The registry lives next to the journal (same durability domain). It is advisory:
a lost or corrupt file only loses deduplication, because re-execution stays
protected by the authenticated artifact and by the no-overwrite relocation.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


class ExecutedCommandRegistry:
    """``command_id -> {type, ok, error, executed_at}``, persisted atomically."""

    def __init__(self, path: str | Path, retention_days: int = 30) -> None:
        self._path = Path(path)
        self._retention = timedelta(days=retention_days)
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] | None = None

    def get(self, command_id: str) -> dict[str, Any] | None:
        """Return the recorded outcome of ``command_id`` or ``None``. Never raises."""
        with self._lock:
            entry = self._load().get(command_id)
            return dict(entry) if entry is not None else None

    def record(
        self,
        command_id: str,
        command_type: str,
        ok: bool,
        error: str | None,
        *,
        now: datetime | None = None,
    ) -> None:
        """Persist one outcome (tmp + fsync + replace + directory fsync, mode 0600).

        Entries older than the retention window are pruned on write: a command
        older than the oldest possible artifact can no longer have any effect.
        Write failures are logged and swallowed; they never reach the dispatcher.
        """
        effective_now = now or datetime.now(timezone.utc)
        with self._lock:
            entries = self._load()
            entries[command_id] = {
                "type": command_type,
                "ok": ok,
                "error": error,
                "executed_at": effective_now.isoformat(),
            }
            cutoff = effective_now - self._retention
            for key in [k for k, v in entries.items() if self._expired(v, cutoff)]:
                del entries[key]
            try:
                self._persist(entries)
            except OSError as exc:
                log.error("executed_commands.record_failed", errno=exc.errno)

    @staticmethod
    def _expired(entry: dict[str, Any], cutoff: datetime) -> bool:
        try:
            executed_at = datetime.fromisoformat(str(entry.get("executed_at")))
        except ValueError:
            return True
        if executed_at.tzinfo is None:
            executed_at = executed_at.replace(tzinfo=timezone.utc)
        return executed_at < cutoff

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        entries: dict[str, dict[str, Any]] = {}
        try:
            raw = json.loads(self._path.read_text())
            if not isinstance(raw, dict) or not all(
                isinstance(v, dict) for v in raw.values()
            ):
                raise ValueError("executed_commands_invalid_shape")
            entries = raw
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            log.error("executed_commands.load_failed", error_type=type(exc).__name__)
        self._entries = entries
        return entries

    def _persist(self, entries: dict[str, dict[str, Any]]) -> None:
        tmp = self._path.with_name(self._path.name + ".tmp")
        data = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=True) as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        dir_fd = os.open(self._path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
