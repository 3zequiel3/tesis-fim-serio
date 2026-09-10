"""Encrypted, crash-safe local quarantine storage.

The master secret is intentionally only a root key.  Quarantine uses a
domain-separated HKDF key, never the baseline key.  This protects an isolated
copy of the quarantine directory when the secrets directory is not acquired;
it does not protect a live host, process memory, ``root``, or an acquisition
that also contains ``master_secret``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_MAGIC_VERSION = b"FIMQ\x01"
_NONCE_BYTES = 12
_TAG_BYTES = 16
_AAD = _MAGIC_VERSION
_CHUNK_BYTES = 64 * 1024
_MAX_METADATA_BYTES = 64 * 1024
_AUTOMATIC_LEGACY_NAME = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}_.+"
)
_COMMAND_LEGACY_NAME = re.compile(r"^.+\.(\d{8}T\d{6})$")


class QuarantineError(Exception):
    """A quarantine operation failed without safely removing the source."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class QuarantineIntegrityError(QuarantineError):
    """An existing encrypted artifact is corrupt or has incompatible metadata."""


@dataclass(frozen=True)
class QuarantineArtifact:
    path: Path
    metadata: dict[str, Any]
    content: bytes


@dataclass(frozen=True)
class QuarantineMigrationReport:
    """Aggregate-only migration result; legacy names never enter logs."""

    migrated: int = 0
    skipped: int = 0
    failed: int = 0
    pending: int = 0


@dataclass(frozen=True)
class QuarantineCleanupReport:
    deleted: int = 0
    retained: int = 0
    corrupt: int = 0
    failed: int = 0

    @property
    def degraded(self) -> bool:
        return self.corrupt > 0 or self.failed > 0


@dataclass(frozen=True)
class QuarantineMaintenanceReport:
    migration: QuarantineMigrationReport
    cleanup: QuarantineCleanupReport

    @property
    def degraded(self) -> bool:
        return (
            self.migration.failed > 0
            or self.migration.pending > 0
            or self.cleanup.degraded
        )


def derive_quarantine_key(master_secret: bytes, agent_id: str) -> bytes:
    """Derive an AES-256 key separated from ``baseline-v1``."""
    if len(master_secret) != 32:
        raise ValueError("master_secret must be exactly 32 bytes")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=agent_id.encode(),
        info=b"quarantine-v1",
    ).derive(master_secret)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _stat_identity(st: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        st.st_dev,
        st.st_ino,
        stat.S_IFMT(st.st_mode),
        st.st_size,
        st.st_mtime_ns,
        st.st_ctime_ns,
    )


class QuarantineStore:
    """Store untrusted files as opaque authenticated encrypted artifacts."""

    def __init__(
        self,
        directory: str | Path,
        master_secret: bytes,
        agent_id: str,
        retention_days: int = 30,
    ) -> None:
        if (
            not isinstance(retention_days, int)
            or isinstance(retention_days, bool)
            or not 1 <= retention_days <= 365
        ):
            raise ValueError("retention_days must be between 1 and 365")
        self.directory = Path(directory)
        self._key = derive_quarantine_key(master_secret, agent_id)
        self.retention_days = retention_days
        self._lock = threading.Lock()
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_stat = os.lstat(self.directory)
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise QuarantineError("quarantine_directory_invalid")
        try:
            os.chmod(self.directory, 0o700, follow_symlinks=False)
        except OSError as exc:
            raise QuarantineError("quarantine_permissions_failed") from exc
        if stat.S_IMODE(os.lstat(self.directory).st_mode) != 0o700:
            raise QuarantineError("quarantine_permissions_failed")

    def artifact_path(self, action_id: str, source_path: str) -> Path:
        if not action_id:
            raise QuarantineError("quarantine_identity_missing")
        source = os.path.abspath(source_path)
        opaque = hashlib.sha256(
            action_id.encode() + b"\x00" + source.encode()
        ).hexdigest()
        return self.directory / f"{opaque}.fimq"

    def quarantine(self, action_id: str, source_path: str) -> QuarantineArtifact:
        """Encrypt and verify a source before removing its directory entry.

        The deterministic artifact identity makes journal rehydration and
        command redelivery idempotent.  If the source path was recreated after
        capture, the authenticated artifact is retained but the new path is
        never deleted and the action fails honestly.
        """
        source = os.path.abspath(source_path)
        artifact_path = self.artifact_path(action_id, source)
        with self._lock:
            if artifact_path.exists():
                artifact = self._read_artifact(artifact_path, include_content=False)
                self._validate_identity(artifact.metadata, action_id, source)
                self._remove_matching_source(source, artifact.metadata)
                return artifact

            source_handle, content, metadata = self._capture_source(action_id, source)
            try:
                self._write_encrypted(artifact_path, metadata, source_handle, content)
            finally:
                if source_handle is not None:
                    source_handle.close()

            artifact = self._read_artifact(artifact_path, include_content=False)
            self._validate_identity(artifact.metadata, action_id, source)
            self._remove_matching_source(source, artifact.metadata)
            return artifact

    def maintain(self, *, now: datetime | None = None) -> QuarantineMaintenanceReport:
        """Migrate known plaintext formats, then enforce encrypted retention."""
        effective_now = self._normalise_now(now)
        migration = self.migrate_legacy(now=effective_now)
        cleanup = self.cleanup_expired(now=effective_now)
        return QuarantineMaintenanceReport(migration=migration, cleanup=cleanup)

    def migrate_legacy(
        self, *, now: datetime | None = None
    ) -> QuarantineMigrationReport:
        """Atomically migrate both historical plaintext naming schemes.

        Unknown entries are preserved and counted as pending.  A live symlink
        is captured as target text; a multiply-linked regular file is rejected
        fail-closed.  Reports contain counts only so legacy names and paths do
        not leak into operational logs.
        """
        effective_now = self._normalise_now(now)
        counts = {"migrated": 0, "skipped": 0, "failed": 0, "pending": 0}
        with self._lock:
            for path in sorted(self.directory.iterdir(), key=lambda item: item.name):
                if path.name.endswith(".fimq") or path.name.startswith("."):
                    continue
                legacy_format, captured_at = self._classify_legacy(path, effective_now)
                if legacy_format is None:
                    counts["pending"] += 1
                    continue
                try:
                    changed = self._migrate_legacy_artifact(
                        path, legacy_format, captured_at
                    )
                except QuarantineError:
                    counts["failed"] += 1
                else:
                    counts["migrated" if changed else "skipped"] += 1
        return QuarantineMigrationReport(**counts)

    def cleanup_expired(
        self, *, now: datetime | None = None
    ) -> QuarantineCleanupReport:
        """Delete authenticated artifacts at their retention boundary.

        Corrupt or unauthenticatable artifacts are never deleted automatically:
        they are preserved and make the report degraded for administrator
        investigation.
        """
        effective_now = self._normalise_now(now)
        cutoff = effective_now - timedelta(days=self.retention_days)
        counts = {"deleted": 0, "retained": 0, "corrupt": 0, "failed": 0}
        with self._lock:
            for path in sorted(self.directory.glob("*.fimq"), key=lambda item: item.name):
                try:
                    artifact = self._read_artifact(path, include_content=False)
                    captured_at = self._metadata_time(artifact.metadata)
                except QuarantineError:
                    counts["corrupt"] += 1
                    continue
                if captured_at > cutoff:
                    counts["retained"] += 1
                    continue
                try:
                    path.unlink()
                    _fsync_directory(self.directory)
                except OSError:
                    counts["failed"] += 1
                else:
                    counts["deleted"] += 1
        return QuarantineCleanupReport(**counts)

    @staticmethod
    def _normalise_now(now: datetime | None) -> datetime:
        value = now or datetime.now(timezone.utc)
        if value.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _metadata_time(metadata: dict[str, Any]) -> datetime:
        value = metadata.get("quarantined_at")
        if not isinstance(value, str):
            raise QuarantineIntegrityError("quarantine_metadata_invalid")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise QuarantineIntegrityError("quarantine_metadata_invalid") from exc
        if parsed.tzinfo is None:
            raise QuarantineIntegrityError("quarantine_metadata_invalid")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _classify_legacy(
        path: Path, fallback_time: datetime
    ) -> tuple[str | None, datetime]:
        if _AUTOMATIC_LEGACY_NAME.fullmatch(path.name):
            try:
                return "automatic", datetime.fromtimestamp(
                    os.lstat(path).st_ctime, timezone.utc
                )
            except OSError:
                return "automatic", fallback_time
        match = _COMMAND_LEGACY_NAME.fullmatch(path.name)
        if match:
            try:
                return "command", datetime.strptime(
                    match.group(1), "%Y%m%dT%H%M%S"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                return None, fallback_time
        return None, fallback_time

    def _legacy_artifact_path(self, legacy_name: str) -> Path:
        opaque = hashlib.sha256(b"legacy-v1\x00" + legacy_name.encode()).hexdigest()
        return self.directory / f"{opaque}.fimq"

    def _migrate_legacy_artifact(
        self, source_path: Path, legacy_format: str, captured_at: datetime
    ) -> bool:
        source = str(source_path.absolute())
        action_id = f"legacy:{legacy_format}:{source_path.name}"
        final_path = self._legacy_artifact_path(source_path.name)
        if final_path.exists():
            artifact = self._read_artifact(final_path, include_content=False)
            self._validate_legacy_identity(
                artifact.metadata, legacy_format, source_path.name
            )
            self._remove_matching_source(source, artifact.metadata)
            return False

        source_handle, content, metadata = self._capture_source(action_id, source)
        metadata["quarantined_at"] = captured_at.isoformat()
        # Historical filenames retained only basename, never the original
        # directory.  Do not misrepresent the quarantine directory as a
        # restorable origin path; recovery requires an operator-selected path.
        metadata["original_path"] = None
        metadata["original_path_known"] = False
        metadata["legacy_format"] = legacy_format
        metadata["legacy_name"] = source_path.name
        try:
            self._write_encrypted(
                final_path,
                metadata,
                source_handle,
                content,
                no_overwrite=True,
            )
        finally:
            if source_handle is not None:
                source_handle.close()
        artifact = self._read_artifact(final_path, include_content=False)
        self._validate_legacy_identity(
            artifact.metadata, legacy_format, source_path.name
        )
        self._remove_matching_source(source, artifact.metadata)
        return True

    @staticmethod
    def _validate_legacy_identity(
        metadata: dict[str, Any], legacy_format: str, legacy_name: str
    ) -> None:
        if (
            metadata.get("legacy_format") != legacy_format
            or metadata.get("legacy_name") != legacy_name
        ):
            raise QuarantineIntegrityError("quarantine_identity_mismatch")

    def _capture_source(
        self, action_id: str, source: str
    ) -> tuple[BinaryIO | None, bytes | None, dict[str, Any]]:
        try:
            st = os.lstat(source)
        except FileNotFoundError as exc:
            raise QuarantineError("file_not_found") from exc
        except OSError as exc:
            raise QuarantineError("quarantine_source_open_failed") from exc

        kind: str
        handle: BinaryIO | None = None
        content: bytes | None = None
        if stat.S_ISLNK(st.st_mode):
            kind = "symlink"
            try:
                content = os.readlink(source).encode()
            except OSError as exc:
                raise QuarantineError("quarantine_source_changed") from exc
            digest = hashlib.sha256(content).hexdigest()
        elif stat.S_ISREG(st.st_mode):
            if st.st_nlink > 1:
                raise QuarantineError("hardlink_not_isolatable")
            kind = "regular"
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            try:
                fd = os.open(source, flags)
                handle = os.fdopen(fd, "rb", closefd=True)
                opened = os.fstat(handle.fileno())
            except OSError as exc:
                raise QuarantineError("quarantine_source_open_failed") from exc
            if not stat.S_ISREG(opened.st_mode) or _stat_identity(opened) != _stat_identity(st):
                handle.close()
                raise QuarantineError("quarantine_source_changed")
            hasher = hashlib.sha256()
            while chunk := handle.read(_CHUNK_BYTES):
                hasher.update(chunk)
            after_hash = os.fstat(handle.fileno())
            if _stat_identity(after_hash) != _stat_identity(st):
                handle.close()
                raise QuarantineError("quarantine_source_changed")
            digest = hasher.hexdigest()
            handle.seek(0)
        else:
            raise QuarantineError("unsupported_file_type")

        metadata: dict[str, Any] = {
            "action_id": action_id,
            "original_path": source,
            "quarantined_at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "mode": stat.S_IMODE(st.st_mode),
            "uid": st.st_uid,
            "gid": st.st_gid,
            "size": len(content) if content is not None else st.st_size,
            "sha256": digest,
            "source_dev": st.st_dev,
            "source_ino": st.st_ino,
            "source_nlink": st.st_nlink,
            "source_mtime_ns": st.st_mtime_ns,
            "source_ctime_ns": st.st_ctime_ns,
        }
        return handle, content, metadata

    def _write_encrypted(
        self,
        final_path: Path,
        metadata: dict[str, Any],
        source_handle: BinaryIO | None,
        content: bytes | None,
        *,
        no_overwrite: bool = False,
    ) -> None:
        metadata_bytes = json.dumps(
            metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        if len(metadata_bytes) > _MAX_METADATA_BYTES:
            raise QuarantineError("quarantine_metadata_too_large")

        nonce = os.urandom(_NONCE_BYTES)
        encryptor = Cipher(algorithms.AES(self._key), modes.GCM(nonce)).encryptor()
        encryptor.authenticate_additional_data(_AAD)
        tmp_path = final_path.with_name(f".{final_path.name}.{uuid.uuid4().hex}.tmp")
        fd = -1
        second_hash = hashlib.sha256()
        try:
            fd = os.open(tmp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as output:
                fd = -1
                output.write(_MAGIC_VERSION)
                output.write(nonce)
                output.write(encryptor.update(struct.pack(">I", len(metadata_bytes))))
                output.write(encryptor.update(metadata_bytes))
                if content is not None:
                    second_hash.update(content)
                    output.write(encryptor.update(content))
                elif source_handle is not None:
                    while chunk := source_handle.read(_CHUNK_BYTES):
                        second_hash.update(chunk)
                        output.write(encryptor.update(chunk))
                output.write(encryptor.finalize())
                output.write(encryptor.tag)
                output.flush()
                os.fsync(output.fileno())
                os.fchmod(output.fileno(), 0o400)
                os.fsync(output.fileno())

            if second_hash.hexdigest() != metadata["sha256"]:
                raise QuarantineError("quarantine_source_changed")
            if no_overwrite:
                try:
                    os.link(tmp_path, final_path, follow_symlinks=False)
                except FileExistsError as exc:
                    raise QuarantineError("quarantine_artifact_exists") from exc
                tmp_path.unlink()
            else:
                os.replace(tmp_path, final_path)
            _fsync_directory(self.directory)
        except QuarantineError:
            raise
        except OSError as exc:
            raise QuarantineError("quarantine_write_failed") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def read_artifact(self, artifact_path: str | Path) -> QuarantineArtifact:
        """Authenticate and decrypt one artifact for verification/recovery."""
        return self._read_artifact(artifact_path, include_content=True)

    def _read_artifact(
        self, artifact_path: str | Path, *, include_content: bool
    ) -> QuarantineArtifact:
        """Verify in bounded memory; materialize content only for explicit reads."""
        path = Path(artifact_path)
        pending = bytearray()
        metadata_len: int | None = None
        metadata_raw: bytes | None = None
        content_parts: list[bytes] = []
        content_hash = hashlib.sha256()
        content_size = 0

        def consume(clear: bytes) -> None:
            nonlocal metadata_len, metadata_raw, content_size
            pending.extend(clear)
            if metadata_len is None and len(pending) >= 4:
                metadata_len = struct.unpack(">I", pending[:4])[0]
                if metadata_len > _MAX_METADATA_BYTES:
                    raise QuarantineIntegrityError("quarantine_metadata_invalid")
            if metadata_raw is None and metadata_len is not None and len(pending) >= 4 + metadata_len:
                metadata_raw = bytes(pending[4 : 4 + metadata_len])
                del pending[: 4 + metadata_len]
            if metadata_raw is not None and pending:
                chunk = bytes(pending)
                pending.clear()
                content_hash.update(chunk)
                content_size += len(chunk)
                if include_content:
                    content_parts.append(chunk)

        try:
            artifact_stat = os.lstat(path)
            if not stat.S_ISREG(artifact_stat.st_mode):
                raise QuarantineIntegrityError("quarantine_artifact_type")
            size = artifact_stat.st_size
            if size < len(_MAGIC_VERSION) + _NONCE_BYTES + _TAG_BYTES + 4:
                raise QuarantineIntegrityError("quarantine_artifact_truncated")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb", closefd=True) as source:
                if _stat_identity(os.fstat(source.fileno())) != _stat_identity(artifact_stat):
                    raise QuarantineIntegrityError("quarantine_artifact_changed")
                if source.read(len(_MAGIC_VERSION)) != _MAGIC_VERSION:
                    raise QuarantineIntegrityError("quarantine_artifact_version")
                nonce = source.read(_NONCE_BYTES)
                source.seek(-_TAG_BYTES, os.SEEK_END)
                tag = source.read(_TAG_BYTES)
                encrypted_len = size - len(_MAGIC_VERSION) - _NONCE_BYTES - _TAG_BYTES
                source.seek(len(_MAGIC_VERSION) + _NONCE_BYTES)
                decryptor = Cipher(
                    algorithms.AES(self._key), modes.GCM(nonce, tag)
                ).decryptor()
                decryptor.authenticate_additional_data(_AAD)
                remaining = encrypted_len
                while remaining:
                    chunk = source.read(min(_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise QuarantineIntegrityError("quarantine_artifact_truncated")
                    remaining -= len(chunk)
                    consume(decryptor.update(chunk))
                consume(decryptor.finalize())
        except QuarantineIntegrityError:
            raise
        except (InvalidTag, ValueError, OSError) as exc:
            raise QuarantineIntegrityError("quarantine_integrity_failure") from exc

        if metadata_raw is None:
            raise QuarantineIntegrityError("quarantine_metadata_invalid")
        try:
            metadata = json.loads(metadata_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise QuarantineIntegrityError("quarantine_metadata_invalid") from exc
        if not isinstance(metadata, dict):
            raise QuarantineIntegrityError("quarantine_metadata_invalid")
        if (
            metadata.get("size") != content_size
            or metadata.get("sha256") != content_hash.hexdigest()
        ):
            raise QuarantineIntegrityError("quarantine_content_mismatch")
        content = b"".join(content_parts) if include_content else b""
        return QuarantineArtifact(path=path, metadata=metadata, content=content)

    @staticmethod
    def _validate_identity(metadata: dict[str, Any], action_id: str, source: str) -> None:
        if metadata.get("action_id") != action_id or metadata.get("original_path") != source:
            raise QuarantineIntegrityError("quarantine_identity_mismatch")

    def _remove_matching_source(self, source: str, metadata: dict[str, Any]) -> None:
        try:
            current = os.lstat(source)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise QuarantineError("quarantine_source_check_failed") from exc

        # `mode` stores S_IMODE, so compare the kind independently.
        same_kind = (
            metadata.get("kind") == "regular" and stat.S_ISREG(current.st_mode)
        ) or (
            metadata.get("kind") == "symlink" and stat.S_ISLNK(current.st_mode)
        )
        comparable = (
            current.st_dev,
            current.st_ino,
            0,
            current.st_size,
            current.st_mtime_ns,
            current.st_ctime_ns,
        )
        expected = (
            metadata.get("source_dev"),
            metadata.get("source_ino"),
            0,
            metadata.get("size"),
            metadata.get("source_mtime_ns"),
            metadata.get("source_ctime_ns"),
        )
        if (
            not same_kind
            or comparable != expected
            or current.st_nlink != metadata.get("source_nlink")
            or (metadata.get("kind") == "regular" and current.st_nlink != 1)
        ):
            raise QuarantineError("quarantine_source_changed")
        try:
            os.unlink(source)
            _fsync_directory(Path(source).parent)
        except OSError as exc:
            raise QuarantineError("quarantine_source_remove_failed") from exc
