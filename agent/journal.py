"""Journal transaccional pre/post-acción para el motor de decisión (C10, RN-83)."""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger()


@dataclasses.dataclass
class JournalEntry:
    event_id: str
    path: str
    action: str
    state: str  # "pending" | "completed" | "failed"
    created_at: str
    updated_at: str
    error: str | None = None


class JournalManager:
    """Gestiona el journal de acciones: pending → completed / failed (RN-83)."""

    def __init__(self, journal_dir: str | Path) -> None:
        self._dir = Path(journal_dir)

    # ── escritura ─────────────────────────────────────────────────────────────

    def write_pending(self, event_id: str, path: str, action: str) -> JournalEntry:
        """Escribe entrada pending antes de ejecutar la acción."""
        now = datetime.now(timezone.utc).isoformat()
        entry = JournalEntry(
            event_id=event_id,
            path=path,
            action=action,
            state="pending",
            created_at=now,
            updated_at=now,
        )
        self._write(entry)
        return entry

    def mark_completed(self, event_id: str) -> None:
        entry = self._read(event_id)
        if entry is None:
            return
        entry.state = "completed"
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        self._write(entry)

    def mark_failed(self, event_id: str, error: str) -> None:
        entry = self._read(event_id)
        if entry is None:
            return
        entry.state = "failed"
        entry.error = error
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        self._write(entry)

    # ── lectura ───────────────────────────────────────────────────────────────

    def load_pending(self) -> list[JournalEntry]:
        """Retorna todas las entradas con state='pending' del journal_dir."""
        entries: list[JournalEntry] = []
        try:
            for f in self._dir.iterdir():
                if f.suffix != ".json":
                    continue
                try:
                    data = json.loads(f.read_text())
                    entry = JournalEntry(**data)
                    if entry.state == "pending":
                        entries.append(entry)
                except Exception as exc:
                    log.warning("journal.load_entry_failed", file=str(f), error=str(exc))
        except OSError as exc:
            log.warning("journal.scandir_failed", dir=str(self._dir), error=str(exc))
        return entries

    # ── eliminación ───────────────────────────────────────────────────────────

    def delete(self, event_id: str) -> None:
        p = self._dir / f"{event_id}.json"
        try:
            p.unlink()
        except FileNotFoundError:
            pass

    # ── helpers privados ──────────────────────────────────────────────────────

    def _path(self, event_id: str) -> Path:
        return self._dir / f"{event_id}.json"

    def _write(self, entry: JournalEntry) -> None:
        self._path(entry.event_id).write_text(json.dumps(dataclasses.asdict(entry)))

    def _read(self, event_id: str) -> JournalEntry | None:
        p = self._path(event_id)
        try:
            data = json.loads(p.read_text())
            return JournalEntry(**data)
        except Exception:
            return None
