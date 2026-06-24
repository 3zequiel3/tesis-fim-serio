"""
Motor de baseline cifrado AES-256-GCM para el agente FIM (Change 07, RN-15/19/47-50/66/82).

API in-process — sin servidor HTTP (D8/RN-108).
Flujo típico de cambio detectado:
    engine.add_snapshot(path)   # archiva versión actual en snapshots
    engine.write_entry(path)    # actualiza entry con nuevo contenido
"""

from __future__ import annotations

import base64
import dataclasses
import gzip
import hashlib
import json
import os
import platform
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

_LINUX = platform.system() == "Linux"

import structlog
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

if TYPE_CHECKING:
    from agent.config import AgentConfig

log = structlog.get_logger()

_VERSION = b"\x01"
_NONCE_LEN = 12
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB — archivos más grandes: solo hash+metadata
_MAX_SNAPSHOTS = 3


class BaselineIntegrityError(Exception):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"baseline integrity failure: {path}")


@dataclass
class Snapshot:
    hash: str
    captured_at: str
    gzip: bool
    content_b64: str | None


@dataclass
class BaselineEntry:
    path: str
    status: str  # "present" | "absent"
    hash: str | None
    size: int | None
    mode: str | None
    uid: int | None
    gid: int | None
    mtime: str | None
    captured_at: str
    snapshots: list[Snapshot]
    content_b64: str | None
    oversize: bool = False

    def to_json_bytes(self) -> bytes:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False).encode()

    @classmethod
    def from_dict(cls, d: dict) -> "BaselineEntry":
        snaps = [Snapshot(**s) for s in d.get("snapshots", [])]
        fields = {k: v for k, v in d.items() if k != "snapshots"}
        return cls(**fields, snapshots=snaps)


@dataclass
class ScanReport:
    scanned: int
    skipped: int
    oversize: int
    errors: int


# ── 1. Cripto ────────────────────────────────────────────────────────────────

def load_master_secret(secrets_dir: str | Path) -> bytes:
    p = Path(secrets_dir) / "master_secret"
    if not p.exists():
        raise FileNotFoundError(f"master_secret not found: {p}")
    data = p.read_bytes()
    if len(data) != 32:
        raise ValueError(f"master_secret must be exactly 32 bytes, got {len(data)}")
    return data


def derive_baseline_key(master_secret: bytes, agent_id: str) -> bytes:
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=agent_id.encode(),
        info=b"baseline-v1",
    )
    return hkdf.derive(master_secret)


def _encrypt(key: bytes, plaintext_json: bytes) -> bytes:
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext_json, None)
    return _VERSION + nonce + ciphertext


def _decrypt(key: bytes, blob: bytes) -> bytes:
    if len(blob) < 1 + _NONCE_LEN + 16:
        raise ValueError("blob too short")
    if blob[0:1] != _VERSION:
        raise ValueError(f"unknown baseline version: {blob[0]:#04x}")
    nonce = blob[1:1 + _NONCE_LEN]
    ciphertext = blob[1 + _NONCE_LEN:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)  # raises InvalidTag on tamper


# ── 2. Persistencia atómica ───────────────────────────────────────────────────

def _entry_path(baseline_dir: Path, path: str) -> Path:
    name = hashlib.sha256(path.encode()).hexdigest() + ".bin"
    return baseline_dir / name


def _atomic_write(final_path: Path, data: bytes) -> None:
    tmp = Path(str(final_path) + ".tmp")
    fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        try:
            os.unlink(str(tmp))
        except OSError:
            pass
        raise
    os.replace(str(tmp), str(final_path))


# ── helpers ───────────────────────────────────────────────────────────────────

def _sha256_file(path: str) -> tuple[str, bytes]:
    h = hashlib.sha256()
    chunks: list[bytes] = []
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
            chunks.append(chunk)
    return h.hexdigest(), b"".join(chunks)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Helper de selección de contenido restaurable ─────────────────────────────

def select_restorable_content(entry: "BaselineEntry") -> tuple[bytes, str] | None:
    """
    Retorna (content_bytes, expected_hash) del mejor origen restaurable.

    Primero intenta el contenido activo (entry.content_b64). Si es None,
    itera entry.snapshots en orden inverso (más reciente primero) buscando
    el primero con content_b64 no nulo — descomprimiendo si gzip=True.

    Retorna None si no hay ningún origen restaurable.
    """
    if entry.content_b64 is not None:
        return base64.b64decode(entry.content_b64), entry.hash or ""

    for snap in reversed(entry.snapshots):
        if snap.content_b64 is None:
            continue
        raw = base64.b64decode(snap.content_b64)
        if snap.gzip:
            raw = gzip.decompress(raw)
        return raw, snap.hash

    return None


# ── Motor ─────────────────────────────────────────────────────────────────────

class BaselineEngine:
    """
    Motor de baseline AES-256-GCM.  Sin servidor HTTP (D8).

    Uso típico:
        engine = BaselineEngine(config, master_secret_bytes)
        report = engine.init_scan(config.watch_paths)
    """

    def __init__(self, config: "AgentConfig", master_secret_bytes: bytes) -> None:
        self._config = config
        self._baseline_dir = Path(config.storage.baseline_dir)
        self._key = derive_baseline_key(master_secret_bytes, config.agent_id)
        self._ensure_dir()

    # ── 2.3 permisos del directorio ────────────────────────────────────────

    def _ensure_dir(self) -> None:
        self._baseline_dir.mkdir(parents=True, exist_ok=True)
        if not _LINUX:
            return  # permisos Unix solo se verifican en producción (Linux)
        try:
            os.chmod(self._baseline_dir, 0o700)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot set 0700 on baseline dir {self._baseline_dir}: {exc}"
            ) from exc
        actual = stat.S_IMODE(self._baseline_dir.stat().st_mode)
        if actual != 0o700:
            raise RuntimeError(
                f"baseline dir {self._baseline_dir} has wrong permissions: {oct(actual)}"
            )

    # ── cifrado/descifrado internos ───────────────────────────────────────

    def _encrypt_entry(self, entry: BaselineEntry) -> bytes:
        return _encrypt(self._key, entry.to_json_bytes())

    def _decrypt_entry(self, blob: bytes, expected_path: str) -> BaselineEntry:
        try:
            plaintext = _decrypt(self._key, blob)
        except InvalidTag:
            log.error("baseline.integrity_failure", path=expected_path, reason="gcm_tag_invalid")
            raise BaselineIntegrityError(expected_path)
        try:
            d = json.loads(plaintext)
            entry = BaselineEntry.from_dict(d)
        except Exception as exc:
            log.error("baseline.parse_failure", path=expected_path, error=str(exc))
            raise BaselineIntegrityError(expected_path) from exc
        # Detecta swapping: el path dentro del plaintext debe coincidir
        if entry.path != expected_path:
            log.error(
                "baseline.path_mismatch",
                expected=expected_path,
                found=entry.path,
            )
            raise BaselineIntegrityError(expected_path)
        return entry

    # ── 3. CRUD de entradas ────────────────────────────────────────────────

    def write_entry(self, path: str) -> BaselineEntry:
        """Escribe/actualiza la entry del path con el contenido actual del archivo.
        Preserva snapshots existentes."""
        file_size = os.path.getsize(path)
        oversize = file_size > _MAX_FILE_BYTES

        existing = self.read_entry(path)
        existing_snapshots = existing.snapshots if existing else []

        hash_hex: str | None = None
        content_b64: str | None = None

        if not oversize:
            hash_hex, content = _sha256_file(path)
            content_b64 = base64.b64encode(content).decode()
        else:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            hash_hex = h.hexdigest()

        st = os.stat(path)
        entry = BaselineEntry(
            path=path,
            status="present",
            hash=hash_hex,
            size=file_size,
            mode=oct(stat.S_IMODE(st.st_mode)),
            uid=st.st_uid,
            gid=st.st_gid,
            mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            captured_at=_now_iso(),
            snapshots=existing_snapshots,
            content_b64=content_b64,
            oversize=oversize,
        )
        blob = self._encrypt_entry(entry)
        _atomic_write(_entry_path(self._baseline_dir, path), blob)
        return entry

    def read_entry(self, path: str) -> BaselineEntry | None:
        ep = _entry_path(self._baseline_dir, path)
        if not ep.exists():
            return None
        try:
            return self._decrypt_entry(ep.read_bytes(), path)
        except BaselineIntegrityError:
            raise

    def mark_absent(self, path: str) -> BaselineEntry:
        entry = BaselineEntry(
            path=path,
            status="absent",
            hash=None,
            size=None,
            mode=None,
            uid=None,
            gid=None,
            mtime=None,
            captured_at=_now_iso(),
            snapshots=[],
            content_b64=None,
        )
        blob = self._encrypt_entry(entry)
        _atomic_write(_entry_path(self._baseline_dir, path), blob)
        return entry

    def list_entries(self) -> list[str]:
        paths: list[str] = []
        for f in self._baseline_dir.glob("*.bin"):
            try:
                blob = f.read_bytes()
                plaintext = _decrypt(self._key, blob)
                d = json.loads(plaintext)
                paths.append(d["path"])
            except (InvalidTag, KeyError, json.JSONDecodeError, ValueError, OSError) as exc:
                log.warning("baseline.list_entry_unreadable", file=str(f), error=str(exc))
        return paths

    # ── 4. Snapshots ──────────────────────────────────────────────────────

    def add_snapshot(self, path: str) -> bool:
        """Archiva el contenido activo actual como snapshot (llamar ANTES de write_entry).
        Retorna True si se agregó, False si se omitió por dedup o entry ausente."""
        entry = self.read_entry(path)
        if entry is None or entry.status == "absent" or entry.hash is None:
            return False

        # Dedup: si el último snapshot ya tiene el mismo hash, no agregar
        if entry.snapshots and entry.snapshots[-1].hash == entry.hash:
            return False

        # Nuevo snapshot del contenido activo actual (sin comprimir)
        new_snap = Snapshot(
            hash=entry.hash,
            captured_at=entry.captured_at,
            gzip=False,
            content_b64=entry.content_b64,
        )

        # Comprimir todos los snapshots existentes (pasan a no-activos)
        compressed: list[Snapshot] = []
        for snap in entry.snapshots:
            if not snap.gzip and snap.content_b64 is not None:
                raw = base64.b64decode(snap.content_b64)
                c = gzip.compress(raw, compresslevel=6)
                compressed.append(Snapshot(
                    hash=snap.hash,
                    captured_at=snap.captured_at,
                    gzip=True,
                    content_b64=base64.b64encode(c).decode(),
                ))
            else:
                compressed.append(snap)

        all_snaps = compressed + [new_snap]

        # FIFO: máx 3
        if len(all_snaps) > _MAX_SNAPSHOTS:
            all_snaps = all_snaps[-_MAX_SNAPSHOTS:]

        entry.snapshots = all_snaps
        _atomic_write(_entry_path(self._baseline_dir, path), self._encrypt_entry(entry))
        return True

    # ── 5. Scan y verificación ────────────────────────────────────────────

    def init_scan(self, watch_paths: list[str]) -> ScanReport:
        """Escaneo inicial idempotente: solo procesa archivos sin entry existente."""
        scanned = skipped = oversize_count = errors = 0
        for watch_path in watch_paths:
            p = Path(watch_path)
            if not p.exists():
                log.warning("baseline.watch_path_missing", path=watch_path)
                continue
            candidates = [p] if p.is_file() else list(p.rglob("*"))
            for file_path in candidates:
                if not file_path.is_file():
                    continue
                path_str = str(file_path)
                if _entry_path(self._baseline_dir, path_str).exists():
                    skipped += 1
                    continue
                try:
                    entry = self.write_entry(path_str)
                    scanned += 1
                    if entry.oversize:
                        oversize_count += 1
                except OSError as exc:
                    log.error("baseline.scan_error", path=path_str, error=str(exc))
                    errors += 1
        return ScanReport(
            scanned=scanned,
            skipped=skipped,
            oversize=oversize_count,
            errors=errors,
        )

    def run_scan(self, paths: list[str]) -> ScanReport:
        """
        Escaneo bajo demanda para una lista de paths dada (C14, D-C14-07).

        Idéntico al scan inicial pero sin skip de entries existentes:
        sobreescribe (upsert) cualquier entry ya presente — útil para
        rescan_baseline y para paths recién añadidos en update_config.

        Si un path no existe → log warning y continua (no lanza excepción).
        """
        scanned = skipped = oversize_count = errors = 0
        for watch_path in paths:
            p = Path(watch_path)
            if not p.exists():
                log.warning("baseline.run_scan.path_missing", path=watch_path)
                continue
            candidates = [p] if p.is_file() else list(p.rglob("*"))
            for file_path in candidates:
                if not file_path.is_file():
                    continue
                path_str = str(file_path)
                try:
                    entry = self.write_entry(path_str)
                    scanned += 1
                    if entry.oversize:
                        oversize_count += 1
                except OSError as exc:
                    log.error("baseline.run_scan.error", path=path_str, error=str(exc))
                    errors += 1
        return ScanReport(
            scanned=scanned,
            skipped=skipped,
            oversize=oversize_count,
            errors=errors,
        )

    def verify_entry(self, path: str) -> bool:
        """Verifica integridad GCM. True = íntegra. Raise BaselineIntegrityError si falló el tag."""
        ep = _entry_path(self._baseline_dir, path)
        if not ep.exists():
            return False
        try:
            self._decrypt_entry(ep.read_bytes(), path)
            return True
        except BaselineIntegrityError:
            raise

    def update_from_command(
        self,
        path: str,
        hash_value: str | None,
        baseline_status: str,
    ) -> BaselineEntry:
        """
        Actualiza (o crea) la entrada de baseline a partir de un comando baseline_update
        recibido desde el backend (C13, RN handler 8.3).

        Si ya existe una entrada, preserva snapshots y content_b64 para que
        restore_file siga funcionando tras una aprobación de cambio (C23-H4).
        Actualiza solo hash, status y captured_at.

        Misma clave HKDF que el resto del motor. Nuevo nonce AES-GCM por escritura.

        Args:
            path: ruta del archivo monitorizado.
            hash_value: SHA-256 hexadecimal del archivo, o None si status=absent.
            baseline_status: "present" | "absent".
        """
        existing = self.read_entry(path)

        if existing is not None:
            entry = BaselineEntry(
                path=path,
                status=baseline_status,
                hash=hash_value,
                size=existing.size,
                mode=existing.mode,
                uid=existing.uid,
                gid=existing.gid,
                mtime=existing.mtime,
                captured_at=_now_iso(),
                snapshots=existing.snapshots,
                content_b64=existing.content_b64,
                oversize=existing.oversize,
            )
        else:
            entry = BaselineEntry(
                path=path,
                status=baseline_status,
                hash=hash_value,
                size=None,
                mode=None,
                uid=None,
                gid=None,
                mtime=None,
                captured_at=_now_iso(),
                snapshots=[],
                content_b64=None,
            )

        blob = self._encrypt_entry(entry)
        _atomic_write(_entry_path(self._baseline_dir, path), blob)
        log.info(
            "baseline.update_from_command",
            path=path,
            status=baseline_status,
            hash=hash_value,
        )
        return entry
