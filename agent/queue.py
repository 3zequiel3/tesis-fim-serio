"""
Cola offline durable para eventos FIM del agente (RN-38, RN-39, RN-40, RN-41, RN-84).

Formato de nombre: {detected_at_epoch_ms}_{event_id}.json
Escritura atómica: .tmp → os.replace()
Límite: 100 MB con política drop-oldest.

Cada archivo de cola guarda un SOBRE (D-7/D37, RN-131), no el payload
desnudo: `{"payload": {...}, "attempts": int, "first_attempt_at": str|None}`.
El payload NO lleva `signature` ni `sent_at` — ambos se calculan en el
publisher justo antes de cada XADD (D-1 del design). `attempts` es el
contador durable de intentos de publicación; sobrevive a un reinicio del
agente porque `_drain_queue` republica toda la cola desde disco.

La lectura DETECTA el formato: un objeto sin clave `payload` es un archivo
escrito por una versión anterior del agente y se envuelve con `attempts=0`
y `first_attempt_at=None`. Sin script de migración.

El destino terminal de un evento que agota su techo de reintentos o recibe
un `event_nack` terminal es el directorio de descarte (D-8/D37), un
hermano de la cola que NO cuenta para el presupuesto de 100 MB ni para
`queue_pressure`, acotado por cantidad de archivos con su propio
drop-oldest.

Borrado de archivo de cola solo tras event_ack o event_nack terminal
(llamar remove(event_id) o discard(event_id, reason)).
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import structlog

log = structlog.get_logger()

_MAX_BYTES: int = 100 * 1024 * 1024  # 100 MB
_DEFAULT_MAX_DISCARD_FILES: int = 1000


def _ensure_dir_0700(path: Path) -> None:
    """Creates path if needed and enforces 0700 permissions (privacy hardening).

    Mirrors the mkdir-mode + chmod-fallback + verify pattern already used by
    baseline.py/_ensure_dir and quarantine.py/_ensure_directory: the queue
    stores full event envelopes in plaintext JSON, including diff_text when
    present, so a pre-existing directory with laxer permissions (e.g. 0755)
    must be hardened, not just left alone because it already exists.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError as exc:
        raise RuntimeError(f"Cannot set 0700 on queue dir {path}: {exc}") from exc
    actual = stat.S_IMODE(path.stat().st_mode)
    if actual != 0o700:
        raise RuntimeError(f"queue dir {path} has wrong permissions: {oct(actual)}")


def _iso_to_epoch_ms(iso_str: str) -> int:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _load_envelope(path: Path) -> dict[str, Any]:
    """Carga un archivo de cola detectando el formato (D-7).

    Un objeto sin clave 'payload' es un archivo del formato anterior
    (payload desnudo) y se envuelve con attempts=0, first_attempt_at=None.
    """
    raw = json.loads(path.read_bytes())
    if not isinstance(raw, dict) or "payload" not in raw:
        return {"payload": raw, "attempts": 0, "first_attempt_at": None}
    return raw


def _atomic_write_json(final: Path, data_obj: dict[str, Any]) -> None:
    """Escribe data_obj como JSON en final de forma atómica (tmp + os.replace)."""
    data = json.dumps(data_obj, sort_keys=True, separators=(",", ":")).encode()
    tmp = final.parent / (final.name + ".tmp")
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


class EventQueue:
    """Cola de eventos en disco con escritura atómica y límite de 100 MB."""

    def __init__(
        self,
        queue_dir: str | Path,
        discard_dir: str | Path | None = None,
        max_discard_files: int = _DEFAULT_MAX_DISCARD_FILES,
    ) -> None:
        self._dir = Path(queue_dir)
        _ensure_dir_0700(self._dir)
        self._discard_dir = Path(discard_dir) if discard_dir else self._dir.parent / "discarded"
        self._max_discard_files = max_discard_files
        # Acumulativo durante la vida de esta instancia, igual que los otros
        # contadores operativos que el agente expone por heartbeat.
        self._evicted_events = 0
        self._sweep_orphaned_tmp()
        # Hot-path index built once per process start.  The previous
        # implementation globbed, parsed and sorted the complete directory in
        # contains/get_attempts/bump_attempts/remove and queue_size.  Draining
        # N entries therefore performed O(N²) directory work.
        files = self._json_files()
        self._files_by_event_id: dict[str, Path] = {}
        self._size_bytes = 0
        for path in files:
            parts = path.stem.split("_", 1)
            if len(parts) == 2:
                self._files_by_event_id[parts[1]] = path
            try:
                self._size_bytes += path.stat().st_size
            except OSError:
                pass

    # ── internals ────────────────────────────────────────────────────────────

    def _sweep_orphaned_tmp(self) -> None:
        """Barre archivos .tmp huérfanos de crasheos anteriores — RN-41.

        Cubre tanto la cola como el directorio de descarte (D-8); este último
        puede no existir todavía, glob() sobre un directorio inexistente no
        lanza excepción.
        """
        for f in self._dir.glob("*.tmp"):
            try:
                f.unlink()
            except OSError:
                pass
        for f in self._discard_dir.glob("*.tmp"):
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

    def _discard_json_files(self) -> list[Path]:
        return sorted(
            self._discard_dir.glob("*.json"),
            key=lambda f: int(f.stem.split("_", 1)[0]),
        )

    def _total_bytes(self) -> int:
        return self._size_bytes

    def _find_file(self, event_id: str) -> Path | None:
        """Ubica el archivo de cola de un event_id por nombre (no por contenido).

        El nombre de archivo tiene formato {ms}_{event_id}.json; separamos en
        el primer guion bajo porque el timestamp no contiene guiones bajos.
        """
        path = self._files_by_event_id.get(event_id)
        if path is not None and path.exists():
            return path
        if path is not None:
            self._files_by_event_id.pop(event_id, None)
        return None

    def _apply_discard_drop_oldest(self) -> None:
        """Drop-oldest del directorio de descarte por CANTIDAD de archivos (D-8)."""
        files = self._discard_json_files()
        excess = len(files) - self._max_discard_files
        for f in files[: max(excess, 0)]:
            try:
                f.unlink()
            except OSError:
                pass

    # ── public API ───────────────────────────────────────────────────────────

    def enqueue(
        self,
        payload: dict[str, Any],
        *,
        on_evict: Callable[[str], None] | None = None,
    ) -> Path:
        """Encola un evento de forma atómica, envuelto en un sobre con attempts=0.

        El payload MUST tener 'event_id' y 'detected_at' (ISO 8601), y NO debe
        llevar 'signature' ni 'sent_at' — ambos se calculan al transmitir (D-1).
        Aplica drop-oldest si agregar el evento supera 100 MB (RN-84).
        Retorna el path final del archivo.
        """
        event_id: str = payload["event_id"]
        detected_at_ms: int = _iso_to_epoch_ms(payload["detected_at"])
        envelope: dict[str, Any] = {
            "payload": payload,
            "attempts": 0,
            "first_attempt_at": None,
        }
        data = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        new_size = len(data)

        # Drop-oldest hasta que haya espacio — RN-84
        while self._total_bytes() + new_size > _MAX_BYTES:
            files = self._json_files()
            if not files:
                break
            try:
                evicted = files[0]
                parts = evicted.stem.split("_", 1)
                evicted_event_id = parts[1] if len(parts) == 2 else None
                evicted_size = evicted.stat().st_size
                evicted.unlink()
                self._size_bytes = max(0, self._size_bytes - evicted_size)
                if evicted_event_id is not None:
                    self._files_by_event_id.pop(evicted_event_id, None)
                self._evicted_events += 1
                log.warning(
                    "queue.drop_oldest",
                    event_id=evicted_event_id,
                    total_evicted=self._evicted_events,
                    reason="queue_capacity",
                )
                if evicted_event_id is not None and on_evict is not None:
                    on_evict(evicted_event_id)
            except OSError:
                break

        final = self._dir / f"{detected_at_ms:016d}_{event_id}.json"
        _atomic_write_json(final, envelope)
        self._files_by_event_id[event_id] = final
        self._size_bytes += final.stat().st_size
        return final

    def iter_entries(self) -> list[dict[str, Any]]:
        """Retorna los sobres completos en orden FIFO (por prefijo de timestamp).

        Tolera archivos del formato anterior (payload desnudo), envolviéndolos
        con attempts=0 al vuelo (D-7).
        """
        entries: list[dict[str, Any]] = []
        for f in self._json_files():
            try:
                entries.append(_load_envelope(f))
            except (json.JSONDecodeError, OSError):
                pass
        return entries

    def iter_fifo(self) -> list[dict[str, Any]]:
        """Retorna solo los payloads en orden FIFO — RN-39.

        Mantiene la forma anterior para callers que solo quieren el payload.
        """
        return [entry["payload"] for entry in self.iter_entries()]

    def contains(self, event_id: str) -> bool:
        """True si hay un archivo de cola para event_id (D-4: base para el
        chequeo de containment del publisher ante event_ack/event_nack)."""
        return self._find_file(event_id) is not None

    def get_attempts(self, event_id: str) -> int:
        """Contador de intentos persistido para event_id, o 0 si no está en cola."""
        f = self._find_file(event_id)
        if f is None:
            return 0
        try:
            envelope = _load_envelope(f)
        except (json.JSONDecodeError, OSError):
            return 0
        return int(envelope.get("attempts", 0) or 0)

    def bump_attempts(self, event_id: str) -> int:
        """Incrementa el contador de intentos de event_id y lo persiste (D-7).

        Sella first_attempt_at si todavía era None. Reescribe el sobre de
        forma atómica. Si el evento no está en cola, retorna 0 sin crear nada.
        """
        f = self._find_file(event_id)
        if f is None:
            return 0
        try:
            envelope = _load_envelope(f)
        except (json.JSONDecodeError, OSError):
            return 0
        envelope["attempts"] = int(envelope.get("attempts", 0) or 0) + 1
        if not envelope.get("first_attempt_at"):
            envelope["first_attempt_at"] = datetime.now(timezone.utc).isoformat()
        try:
            previous_size = f.stat().st_size
        except OSError:
            previous_size = 0
        _atomic_write_json(f, envelope)
        try:
            self._size_bytes += f.stat().st_size - previous_size
        except OSError:
            pass
        return envelope["attempts"]

    def discard(self, event_id: str, reason: str) -> bool:
        """Mueve el sobre de event_id al directorio de descarte con motivo (D-8).

        Crea el directorio de descarte bajo demanda (mismos permisos que la
        cola) y aplica drop-oldest por cantidad de archivos. No cuenta para
        el presupuesto de 100 MB ni para queue_pressure. Retorna False si el
        evento no está en cola.
        """
        f = self._find_file(event_id)
        if f is None:
            return False
        try:
            envelope = _load_envelope(f)
        except (json.JSONDecodeError, OSError):
            envelope = {"payload": {}, "attempts": 0, "first_attempt_at": None}
        envelope["discard_reason"] = reason
        envelope["discarded_at"] = datetime.now(timezone.utc).isoformat()

        _ensure_dir_0700(self._discard_dir)
        dest = self._discard_dir / f.name
        _atomic_write_json(dest, envelope)
        try:
            queued_size = f.stat().st_size
            f.unlink()
            self._size_bytes = max(0, self._size_bytes - queued_size)
            self._files_by_event_id.pop(event_id, None)
        except OSError:
            pass
        self._apply_discard_drop_oldest()
        return True

    def remove(self, event_id: str) -> bool:
        """Borra el archivo de cola del evento confirmado (RN-40)."""
        f = self._find_file(event_id)
        if f is None:
            return False
        try:
            queued_size = f.stat().st_size
            f.unlink()
            self._size_bytes = max(0, self._size_bytes - queued_size)
            self._files_by_event_id.pop(event_id, None)
            return True
        except OSError:
            return False

    @property
    def queue_size(self) -> int:
        """Cantidad de eventos en cola."""
        return len(self._files_by_event_id)

    @property
    def evicted_events(self) -> int:
        """Eventos eliminados por la política drop-oldest desde este arranque."""
        return self._evicted_events

    @property
    def queue_pressure(self) -> float:
        """Ratio used_bytes / 100MB entre 0.0 y 1.0 — RN-84.

        Refleja únicamente la cola; el directorio de descarte no contribuye.
        """
        return min(self._total_bytes() / _MAX_BYTES, 1.0)
