"""
Cola offline durable para eventos FIM del agente (RN-38, RN-39, RN-40, RN-41, RN-84).

Formato de nombre: {detected_at_epoch_ms}_{event_id}.json
Escritura atómica: .tmp → os.replace()
Límite: 100 MB con política drop-oldest, medido sobre el tamaño en disco de
los blobs cifrados.

Cada archivo de cola guarda un SOBRE (D-7/D37, RN-131), no el payload
desnudo: `{"payload": {...}, "attempts": int, "first_attempt_at": str|None}`.
El payload NO lleva `signature` ni `sent_at` — ambos se calculan en el
publisher justo antes de cada XADD (D-1 del design de stream-ack-durability).
`attempts` es el contador durable de intentos de publicación; sobrevive a un
reinicio del agente porque `_drain_queue` republica toda la cola desde disco.

Desde Change 53 (D63/RN-157), todo archivo que se escribe en la cola y en el
directorio de descarte se cifra en reposo con AES-256-GCM. La clave se
deriva con `derive_queue_key(master_secret, agent_id)`, separada por dominio
de la clave de baseline (`baseline-v1`) y de cuarentena (`quarantine-v1`), y
vive solo en memoria. Cada blob tiene el layout
`[magic b"FIMQE\\x01"][nonce 12 bytes][ciphertext + tag GCM 16 bytes]`, con
datos asociados `magic + nombre_de_archivo`, que ligan el contenido a su
`event_id` y a su posición FIFO — un archivo renombrado o intercambiado con
otro no se autentica. `EventQueue` MUST NOT construirse sin `master_secret`
ni `agent_id`; no existe un modo de cola en claro.

La lectura DETECTA el formato por el prefijo del archivo, nunca por un
intento de descifrado fallido: un blob cifrado se descifra; un objeto JSON
en claro (sobre o payload desnudo, escrito por una versión anterior del
agente) se interpreta como hoy y se reescribe cifrado en el arranque
siguiente o en la próxima lectura, sin script de migración separado.

El destino terminal de un evento que agota su techo de reintentos o recibe
un `event_nack` terminal es el directorio de descarte (D-8/D37), un
hermano de la cola que NO cuenta para el presupuesto de 100 MB ni para
`queue_pressure`, acotado por cantidad de archivos con su propio
drop-oldest. Sus registros también se cifran (D63/RN-157); su inspección
forense pasa por `python -m agent.queue_inspect` (D-9), un CLI root-only
de solo lectura.

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
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

log = structlog.get_logger()

_MAX_BYTES: int = 100 * 1024 * 1024  # 100 MB
_DEFAULT_MAX_DISCARD_FILES: int = 1000

# W3/RN-84, D72/RN-166: umbral único para el flag `queue_pressure_high` del
# heartbeat (agent/heartbeat.py). Comparación estricta (`>`): al *superar*
# el 80% del límite de 100 MB de la cola offline, no al alcanzarlo.
QUEUE_PRESSURE_HIGH_THRESHOLD: float = 0.8

# ── Cifrado (D63/RN-157) ───────────────────────────────────────────────────

_MAGIC_VERSION: bytes = b"FIMQE\x01"
_NONCE_LEN: int = 12
_TAG_LEN: int = 16
_MIN_BLOB_LEN: int = len(_MAGIC_VERSION) + _NONCE_LEN + _TAG_LEN


class QueueFileUnreadable(Exception):
    """A queue/discard file failed authentication or is not a valid envelope.

    Handled by the same path the queue already applies to an ilegible file
    (D-6): the file is skipped, never published, never reinterpreted as
    plaintext, and no content is logged. ``reason`` is one of
    ``"authentication_failed"`` (GCM tag/nonce/name mismatch) or
    ``"malformed"`` (truncated or not a valid encrypted blob nor legacy
    JSON object).
    """

    def __init__(self, reason: str) -> None:
        if reason not in ("authentication_failed", "malformed"):
            raise ValueError(f"invalid QueueFileUnreadable reason: {reason!r}")
        self.reason = reason
        super().__init__(reason)


def derive_queue_key(master_secret: bytes, agent_id: str) -> bytes:
    """Deriva la clave de cola, separada por dominio de baseline/cuarentena (D-1).

    `HKDF-SHA256(ikm=master_secret, salt=agent_id, info=b"queue-v1", length=32)`.
    """
    if len(master_secret) != 32:
        raise ValueError("master_secret must be exactly 32 bytes")
    return HKDF(
        algorithm=SHA256(),
        length=32,
        salt=agent_id.encode(),
        info=b"queue-v1",
    ).derive(master_secret)


def _encrypt_blob(key: bytes, name: str, plaintext: bytes) -> bytes:
    """Cifra plaintext con un nonce nuevo, ligado a `name` por AAD (D-3)."""
    nonce = os.urandom(_NONCE_LEN)
    aad = _MAGIC_VERSION + name.encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return _MAGIC_VERSION + nonce + ciphertext


def _decrypt_blob(key: bytes, name: str, blob: bytes) -> bytes:
    """Descifra un blob de cola/descarte o levanta QueueFileUnreadable (D-3, D-6)."""
    if len(blob) < _MIN_BLOB_LEN or blob[: len(_MAGIC_VERSION)] != _MAGIC_VERSION:
        raise QueueFileUnreadable("malformed")
    nonce = blob[len(_MAGIC_VERSION) : len(_MAGIC_VERSION) + _NONCE_LEN]
    ciphertext = blob[len(_MAGIC_VERSION) + _NONCE_LEN :]
    aad = _MAGIC_VERSION + name.encode("utf-8")
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise QueueFileUnreadable("authentication_failed") from exc
    except ValueError as exc:
        raise QueueFileUnreadable("malformed") from exc


def _load_envelope(path: Path, key: bytes) -> tuple[dict[str, Any], bool]:
    """Carga un sobre de cola/descarte, clasificando por el prefijo del archivo (D-5).

    Retorna `(envelope, is_legacy_plaintext)`. La clasificación depende
    únicamente de si el archivo empieza con el magic cifrado, nunca de un
    intento de descifrado fallido: un archivo con el magic que no se
    autentica es QueueFileUnreadable y NUNCA se reinterpreta como JSON en
    claro (D-6). Un objeto sin clave 'payload' (formato anterior a Change 42)
    se envuelve con attempts=0, first_attempt_at=None, igual en ambas ramas.
    """
    raw = path.read_bytes()
    if raw[: len(_MAGIC_VERSION)] == _MAGIC_VERSION:
        plaintext = _decrypt_blob(key, path.name, raw)
        try:
            envelope = json.loads(plaintext)
        except json.JSONDecodeError as exc:
            raise QueueFileUnreadable("malformed") from exc
        if not isinstance(envelope, dict):
            raise QueueFileUnreadable("malformed")
        if "payload" not in envelope:
            envelope = {"payload": envelope, "attempts": 0, "first_attempt_at": None}
        return envelope, False

    try:
        legacy = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QueueFileUnreadable("malformed") from exc
    if not isinstance(legacy, dict):
        raise QueueFileUnreadable("malformed")
    if "payload" not in legacy:
        legacy = {"payload": legacy, "attempts": 0, "first_attempt_at": None}
    return legacy, True


def _atomic_write_envelope(key: bytes, final: Path, data_obj: dict[str, Any]) -> None:
    """Cifra data_obj y lo escribe en final de forma atómica (tmp + os.replace)."""
    plaintext = json.dumps(data_obj, sort_keys=True, separators=(",", ":")).encode()
    blob = _encrypt_blob(key, final.name, plaintext)
    tmp = final.parent / (final.name + ".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    os.replace(str(tmp), str(final))


def read_queue_file(path: str | Path, key: bytes) -> dict[str, Any]:
    """Descifra (o interpreta) un archivo de cola/descarte para inspección (D-9).

    Función pública que reutiliza `_load_envelope`/`_decrypt_blob` en vez de
    que el CLI de inspección forense duplique la lógica de cifrado o
    dependa de símbolos privados. Levanta QueueFileUnreadable si el archivo
    no se autentica o no es un sobre válido.
    """
    envelope, _is_legacy = _load_envelope(Path(path), key)
    return envelope


def classify_queue_file(path: str | Path, key: bytes) -> str:
    """Clasifica un archivo de cola/descarte sin devolver ni imprimir contenido (D-9).

    Retorna `"ok"`, `"authentication_failed"`, `"malformed"` o
    `"legacy_plaintext"`. Usado por el modo lista del CLI de inspección
    forense, que nunca debe descifrar con fines de impresión.
    """
    try:
        _envelope, is_legacy = _load_envelope(Path(path), key)
    except QueueFileUnreadable as exc:
        return exc.reason
    return "legacy_plaintext" if is_legacy else "ok"


def _ensure_dir_0700(path: Path) -> None:
    """Creates path if needed and enforces 0700 permissions (privacy hardening).

    Mirrors the mkdir-mode + chmod-fallback + verify pattern already used by
    baseline.py/_ensure_dir and quarantine.py/_ensure_directory: the queue
    stores full event envelopes encrypted at rest (D63/RN-157), but 0700
    still limits access to the encrypted bytes and metadata on a live host,
    so a pre-existing directory with laxer permissions (e.g. 0755) must be
    hardened, not just left alone because it already exists.
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


class EventQueue:
    """Cola de eventos en disco, cifrada en reposo, con límite de 100 MB."""

    def __init__(
        self,
        queue_dir: str | Path,
        *,
        master_secret: bytes,
        agent_id: str,
        discard_dir: str | Path | None = None,
        max_discard_files: int = _DEFAULT_MAX_DISCARD_FILES,
    ) -> None:
        # La clave se deriva (y master_secret/agent_id se validan) ANTES de
        # tocar el filesystem: una construcción sin clave válida no debe
        # crear ni escribir ningún archivo (D-2, task 6.15).
        self._key = derive_queue_key(master_secret, agent_id)
        self._dir = Path(queue_dir)
        _ensure_dir_0700(self._dir)
        self._discard_dir = Path(discard_dir) if discard_dir else self._dir.parent / "discarded"
        self._max_discard_files = max_discard_files
        # Acumulativo durante la vida de esta instancia, igual que los otros
        # contadores operativos que el agente expone por heartbeat.
        self._evicted_events = 0
        self._sweep_orphaned_tmp()
        self._migrate_legacy_files()
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

    def _migrate_legacy_files(self) -> None:
        """Pasada única de migración en el lugar sobre cola y descarte (D-5, D63).

        Corre después de `_sweep_orphaned_tmp()` y antes de construir los
        índices, para que `_size_bytes` refleje el tamaño ya cifrado. Emite
        un único log agregado con conteos por directorio, sin nombres de
        archivo ni contenido.
        """
        queue_counts = self._migrate_legacy_pass(self._dir)
        discard_counts = self._migrate_legacy_pass(self._discard_dir)
        log.info(
            "queue.migration",
            queue_migrated=queue_counts["migrated"],
            queue_unreadable=queue_counts["unreadable"],
            queue_failed=queue_counts["failed"],
            discard_migrated=discard_counts["migrated"],
            discard_unreadable=discard_counts["unreadable"],
            discard_failed=discard_counts["failed"],
        )

    def _migrate_legacy_pass(self, directory: Path) -> dict[str, int]:
        counts = {"migrated": 0, "unreadable": 0, "failed": 0}
        for f in sorted(directory.glob("*.json")):
            try:
                envelope, is_legacy = _load_envelope(f, self._key)
            except QueueFileUnreadable:
                counts["unreadable"] += 1
                continue
            except OSError:
                counts["unreadable"] += 1
                continue
            if not is_legacy:
                continue
            try:
                _atomic_write_envelope(self._key, f, envelope)
                counts["migrated"] += 1
            except OSError:
                counts["failed"] += 1
        return counts

    def _retry_migrate(self, path: Path, envelope: dict[str, Any]) -> None:
        """Reintenta cifrar un archivo legacy encontrado fuera de la pasada de
        arranque (task 2.4). Mantiene `_size_bytes` en sincronía; sólo se usa
        para archivos de `queue_dir`, que sí participan del índice de tamaño."""
        try:
            previous_size = path.stat().st_size
        except OSError:
            previous_size = 0
        try:
            _atomic_write_envelope(self._key, path, envelope)
        except OSError:
            return
        try:
            self._size_bytes += path.stat().st_size - previous_size
        except OSError:
            pass

    def _log_unreadable(self, path: Path, reason: str) -> None:
        parts = path.stem.split("_", 1)
        event_id = parts[1] if len(parts) == 2 else None
        log.warning("queue.unreadable_file", event_id=event_id, reason=reason)

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
        Aplica drop-oldest si agregar el evento supera 100 MB (RN-84), medido
        sobre el tamaño del blob cifrado en disco (D-7).
        Retorna el path final del archivo.
        """
        event_id: str = payload["event_id"]
        detected_at_ms: int = _iso_to_epoch_ms(payload["detected_at"])
        envelope: dict[str, Any] = {
            "payload": payload,
            "attempts": 0,
            "first_attempt_at": None,
        }
        final = self._dir / f"{detected_at_ms:016d}_{event_id}.json"
        plaintext = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        new_size = len(plaintext) + _MIN_BLOB_LEN

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

        _atomic_write_envelope(self._key, final, envelope)
        self._files_by_event_id[event_id] = final
        self._size_bytes += final.stat().st_size
        return final

    def iter_entries(self) -> list[dict[str, Any]]:
        """Retorna los sobres completos en orden FIFO (por prefijo de timestamp).

        Tolera archivos del formato anterior (payload desnudo o en claro),
        envolviéndolos y reintentando su migración al vuelo (D-5, D-7). Un
        archivo que no se autentica o está mal formado se saltea y se
        registra sin contenido (D-6).
        """
        entries: list[dict[str, Any]] = []
        for f in self._json_files():
            try:
                envelope, is_legacy = _load_envelope(f, self._key)
            except QueueFileUnreadable as exc:
                self._log_unreadable(f, exc.reason)
                continue
            except OSError:
                continue
            if is_legacy:
                self._retry_migrate(f, envelope)
            entries.append(envelope)
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
        """Contador de intentos persistido para event_id, o 0 si no está en cola
        o si el archivo no se autentica (D-6)."""
        f = self._find_file(event_id)
        if f is None:
            return 0
        try:
            envelope, is_legacy = _load_envelope(f, self._key)
        except QueueFileUnreadable as exc:
            self._log_unreadable(f, exc.reason)
            return 0
        except OSError:
            return 0
        if is_legacy:
            self._retry_migrate(f, envelope)
        return int(envelope.get("attempts", 0) or 0)

    def bump_attempts(self, event_id: str) -> int:
        """Incrementa el contador de intentos de event_id y lo persiste (D-7).

        Sella first_attempt_at si todavía era None. Reescribe el sobre
        cifrado de forma atómica, lo que también migra un archivo legacy que
        todavía estuviera en claro. Si el evento no está en cola o su
        archivo no se autentica, retorna 0 sin reescribir (D-6).
        """
        f = self._find_file(event_id)
        if f is None:
            return 0
        try:
            envelope, _is_legacy = _load_envelope(f, self._key)
        except QueueFileUnreadable as exc:
            self._log_unreadable(f, exc.reason)
            return 0
        except OSError:
            return 0
        envelope["attempts"] = int(envelope.get("attempts", 0) or 0) + 1
        if not envelope.get("first_attempt_at"):
            envelope["first_attempt_at"] = datetime.now(timezone.utc).isoformat()
        try:
            previous_size = f.stat().st_size
        except OSError:
            previous_size = 0
        _atomic_write_envelope(self._key, f, envelope)
        try:
            self._size_bytes += f.stat().st_size - previous_size
        except OSError:
            pass
        return envelope["attempts"]

    def discard(self, event_id: str, reason: str) -> bool:
        """Mueve el sobre de event_id al directorio de descarte con motivo (D-8).

        Descifra el archivo de cola y escribe el registro de descarte como un
        blob nuevo, con nonce nuevo, bajo el mismo nombre base (D-3). Crea el
        directorio de descarte bajo demanda (mismos permisos que la cola) y
        aplica drop-oldest por cantidad de archivos. No cuenta para el
        presupuesto de 100 MB ni para queue_pressure. Retorna False si el
        evento no está en cola. Un archivo de origen que no se autentica se
        descarta igual, con payload vacío (D-6, comportamiento preexistente).
        """
        f = self._find_file(event_id)
        if f is None:
            return False
        try:
            envelope, _is_legacy = _load_envelope(f, self._key)
        except QueueFileUnreadable as exc:
            self._log_unreadable(f, exc.reason)
            envelope = {"payload": {}, "attempts": 0, "first_attempt_at": None}
        except OSError:
            envelope = {"payload": {}, "attempts": 0, "first_attempt_at": None}
        envelope["discard_reason"] = reason
        envelope["discarded_at"] = datetime.now(timezone.utc).isoformat()

        _ensure_dir_0700(self._discard_dir)
        dest = self._discard_dir / f.name
        _atomic_write_envelope(self._key, dest, envelope)
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
