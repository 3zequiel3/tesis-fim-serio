"""
Cola offline durable para eventos FIM del agente (RN-38, RN-39, RN-40, RN-41, RN-84).

Formato de nombre: {detected_at_epoch_ms}_{event_id}.json
Escritura atómica: .tmp → os.replace()
Límite: 100 MB con política drop-oldest.
Borrado de archivo solo tras event_ack (llamar remove(event_id)).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MAX_BYTES: int = 100 * 1024 * 1024  # 100 MB


def _iso_to_epoch_ms(iso_str: str) -> int:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


class EventQueue:
    """Cola de eventos en disco con escritura atómica y límite de 100 MB."""

    def __init__(self, queue_dir: str | Path) -> None:
        self._dir = Path(queue_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._sweep_orphaned_tmp()

    # ── internals ────────────────────────────────────────────────────────────

    def _sweep_orphaned_tmp(self) -> None:
        """Barre archivos .tmp huérfanos de crasheos anteriores — RN-41."""
        for f in self._dir.glob("*.tmp"):
            try:
                f.unlink()
            except OSError:
                pass

    def _json_files(self) -> list[Path]:
        # Extrae el timestamp numérico del prefijo para ordenar correctamente
        # con nombres legacy (sin pad) y padded mezclados.
        return sorted(
            self._dir.glob("*.json"),
            key=lambda f: int(f.stem.split("_", 1)[0]),
        )

    def _total_bytes(self) -> int:
        total = 0
        for f in self._json_files():
            try:
                total += f.stat().st_size
            except OSError:
                pass
        return total

    # ── public API ───────────────────────────────────────────────────────────

    def enqueue(self, payload: dict[str, Any]) -> Path:
        """Encola un evento de forma atómica.

        El payload MUST tener 'event_id' y 'detected_at' (ISO 8601).
        Aplica drop-oldest si agregar el evento supera 100 MB (RN-84).
        Retorna el path final del archivo.
        """
        event_id: str = payload["event_id"]
        detected_at_ms: int = _iso_to_epoch_ms(payload["detected_at"])
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        new_size = len(data)

        # Drop-oldest hasta que haya espacio — RN-84
        while self._total_bytes() + new_size > _MAX_BYTES:
            files = self._json_files()
            if not files:
                break
            try:
                files[0].unlink()
            except OSError:
                break

        tmp = self._dir / f"{detected_at_ms:016d}_{event_id}.json.tmp"
        final = self._dir / f"{detected_at_ms:016d}_{event_id}.json"
        fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        os.replace(str(tmp), str(final))
        return final

    def iter_fifo(self) -> list[dict[str, Any]]:
        """Retorna eventos en orden FIFO (por prefijo de timestamp) — RN-39."""
        events: list[dict[str, Any]] = []
        for f in self._json_files():
            try:
                events.append(json.loads(f.read_bytes()))
            except (json.JSONDecodeError, OSError):
                pass
        return events

    def remove(self, event_id: str) -> bool:
        """Borra el archivo de cola del evento confirmado (RN-40).

        El nombre de archivo tiene formato {ms}_{event_id}.json; separamos en
        el primer guion bajo porque el timestamp no contiene guiones bajos.
        """
        for f in self._json_files():
            parts = f.stem.split("_", 1)
            if len(parts) == 2 and parts[1] == event_id:
                try:
                    f.unlink()
                    return True
                except OSError:
                    return False
        return False

    @property
    def queue_size(self) -> int:
        """Cantidad de eventos en cola."""
        return len(self._json_files())

    @property
    def queue_pressure(self) -> float:
        """Ratio used_bytes / 100MB entre 0.0 y 1.0 — RN-84."""
        return min(self._total_bytes() / _MAX_BYTES, 1.0)
