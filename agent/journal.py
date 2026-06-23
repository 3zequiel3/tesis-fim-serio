"""Journal transaccional pre/post-acción para el motor de decisión (C10, RN-83)."""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
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
    hmac: str | None = None


class JournalManager:
    """Gestiona el journal de acciones: pending → completed / failed (RN-83).

    Cada entrada se persiste con escritura atómica (tmp → fsync → os.replace)
    y se protege con HMAC-SHA256 para detectar manipulación o truncamiento.
    """

    def __init__(self, journal_dir: str | Path, shared_secret: bytes) -> None:
        self._dir = Path(journal_dir)
        self._secret = shared_secret

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
        """Retorna todas las entradas con state='pending' del journal_dir.

        Entradas truncadas o con HMAC inválido se descartan con warning.
        """
        entries: list[JournalEntry] = []
        try:
            for f in self._dir.iterdir():
                if f.suffix != ".json":
                    continue
                try:
                    data = json.loads(f.read_text())
                    entry = self._verify_and_build(data)
                    if entry is None:
                        log.warning("journal.load_hmac_invalid", file=str(f))
                        continue
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

    def _canonical_bytes(self, entry: JournalEntry) -> bytes:
        """JSON determinístico del entry excluyendo el campo hmac."""
        d = dataclasses.asdict(entry)
        d.pop("hmac", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()

    def _compute_hmac(self, entry: JournalEntry) -> str:
        return hmac.new(self._secret, self._canonical_bytes(entry), hashlib.sha256).hexdigest()

    def _write(self, entry: JournalEntry) -> None:
        entry.hmac = self._compute_hmac(entry)
        payload = json.dumps(dataclasses.asdict(entry)).encode()

        target = self._path(entry.event_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(target) + ".tmp")
        fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        os.replace(str(tmp), str(target))

    def _verify_and_build(self, data: dict) -> JournalEntry | None:
        """Construye un JournalEntry verificando el HMAC.

        Retorna None si el HMAC está ausente o no coincide.
        """
        stored_hmac = data.get("hmac")
        if not stored_hmac:
            return None
        # Construir el entry sin hmac para calcular el canonical
        data_no_hmac = {k: v for k, v in data.items() if k != "hmac"}
        candidate = JournalEntry(**data_no_hmac)
        expected = self._compute_hmac(candidate)
        if not hmac.compare_digest(expected, stored_hmac):
            return None
        candidate.hmac = stored_hmac
        return candidate

    def _read(self, event_id: str) -> JournalEntry | None:
        p = self._path(event_id)
        try:
            data = json.loads(p.read_text())
            entry = self._verify_and_build(data)
            if entry is None:
                log.warning("journal.read_hmac_invalid", event_id=event_id)
            return entry
        except Exception:
            return None
