"""
Tests del motor de baseline AES-256-GCM (Change 07).
Cubren criterios Done + RN-15/19/20/47/48/49/50/66/82.
Los tests de permisos se saltan en plataformas no-Linux (el agente es Linux-only).
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import os
import platform
import stat
from pathlib import Path

import pytest

_LINUX = platform.system() == "Linux"

from agent.baseline import (
    BaselineEngine,
    BaselineIntegrityError,
    ScanReport,
    _decrypt,
    _encrypt,
    _NONCE_LEN,
    derive_baseline_key,
    load_master_secret,
)
from agent.config import AgentConfig, StorageConfig


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def master_secret() -> bytes:
    return os.urandom(32)


@pytest.fixture()
def secrets_dir(tmp_path: Path, master_secret: bytes) -> Path:
    sd = tmp_path / "secrets"
    sd.mkdir(mode=0o700)
    ms_path = sd / "master_secret"
    fd = os.open(str(ms_path), os.O_CREAT | os.O_WRONLY, 0o400)
    with os.fdopen(fd, "wb") as f:
        f.write(master_secret)
    return sd


@pytest.fixture()
def storage(tmp_path: Path, secrets_dir: Path) -> StorageConfig:
    return StorageConfig(
        baseline_dir=str(tmp_path / "baseline"),
        queue_dir=str(tmp_path / "queue"),
        journal_dir=str(tmp_path / "journal"),
        secrets_dir=str(secrets_dir),
        certs_dir=str(tmp_path / "certs"),
    )


@pytest.fixture()
def config(storage: StorageConfig) -> AgentConfig:
    return AgentConfig(
        agent_id="test-agent-01",
        backend_url="http://localhost:8000",
        valkey_url="redis://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/tmp"],  # placeholder; tests override as needed
        storage=storage,
    )


@pytest.fixture()
def engine(config: AgentConfig, master_secret: bytes) -> BaselineEngine:
    return BaselineEngine(config, master_secret)


@pytest.fixture()
def sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "sample.txt"
    p.write_bytes(b"hello baseline world")
    return p


# ── 7.1 Derivación determinística ─────────────────────────────────────────────

def test_key_derivation_deterministic(master_secret: bytes) -> None:
    k1 = derive_baseline_key(master_secret, "agent-A")
    k2 = derive_baseline_key(master_secret, "agent-A")
    assert k1 == k2


def test_key_derivation_different_agents(master_secret: bytes) -> None:
    k1 = derive_baseline_key(master_secret, "agent-A")
    k2 = derive_baseline_key(master_secret, "agent-B")
    assert k1 != k2


# ── 7.2 Round-trip cifrado/descifrado ─────────────────────────────────────────

def test_encrypt_decrypt_roundtrip(master_secret: bytes) -> None:
    key = derive_baseline_key(master_secret, "agent-X")
    plaintext = b'{"path": "/etc/test", "status": "present"}'
    blob = _encrypt(key, plaintext)
    recovered = _decrypt(key, blob)
    assert recovered == plaintext


# ── 7.3 Alteración del blob → BaselineIntegrityError ─────────────────────────

def test_tampered_blob_raises(engine: BaselineEngine, sample_file: Path) -> None:
    engine.write_entry(str(sample_file))
    from agent.baseline import _entry_path
    ep = _entry_path(engine._baseline_dir, str(sample_file))
    data = bytearray(ep.read_bytes())
    data[-1] ^= 0xFF  # flip last byte of GCM tag
    ep.write_bytes(bytes(data))
    with pytest.raises(BaselineIntegrityError) as exc_info:
        engine.read_entry(str(sample_file))
    assert exc_info.value.path == str(sample_file)


# ── 7.4 Nonce único por escritura ─────────────────────────────────────────────

def test_unique_nonce_per_write(engine: BaselineEngine, sample_file: Path) -> None:
    engine.write_entry(str(sample_file))
    from agent.baseline import _entry_path
    ep = _entry_path(engine._baseline_dir, str(sample_file))
    nonce1 = ep.read_bytes()[1:1 + _NONCE_LEN]

    sample_file.write_bytes(b"updated content")
    engine.write_entry(str(sample_file))
    nonce2 = ep.read_bytes()[1:1 + _NONCE_LEN]

    assert nonce1 != nonce2


# ── 7.5 GCM detecta swapping de entradas ──────────────────────────────────────

def test_gcm_detects_path_swap(engine: BaselineEngine, tmp_path: Path) -> None:
    file_a = tmp_path / "file_a.txt"
    file_b = tmp_path / "file_b.txt"
    file_a.write_bytes(b"content of A")
    file_b.write_bytes(b"content of B")

    engine.write_entry(str(file_a))
    engine.write_entry(str(file_b))

    from agent.baseline import _entry_path
    ep_a = _entry_path(engine._baseline_dir, str(file_a))
    ep_b = _entry_path(engine._baseline_dir, str(file_b))

    # Swap blobs on disk
    blob_a = ep_a.read_bytes()
    ep_a.write_bytes(ep_b.read_bytes())
    ep_b.write_bytes(blob_a)

    # Reading file_a now gets file_b's blob → path mismatch → integrity error
    with pytest.raises(BaselineIntegrityError):
        engine.read_entry(str(file_a))


# ── 7.6 Init scan: permisos e idempotencia ─────────────────────────────────────

def test_init_scan_creates_entries(engine: BaselineEngine, tmp_path: Path) -> None:
    watch = tmp_path / "watched"
    watch.mkdir()
    (watch / "a.txt").write_bytes(b"file a")
    (watch / "b.txt").write_bytes(b"file b")

    report = engine.init_scan([str(watch)])

    assert report.scanned == 2
    assert report.skipped == 0
    assert report.errors == 0

    from agent.baseline import _entry_path
    for fname in ["a.txt", "b.txt"]:
        ep = _entry_path(engine._baseline_dir, str(watch / fname))
        assert ep.exists()


@pytest.mark.skipif(not _LINUX, reason="Unix permissions only enforced on Linux")
def test_baseline_file_permissions(engine: BaselineEngine, tmp_path: Path) -> None:
    watch = tmp_path / "watched_perms"
    watch.mkdir()
    (watch / "a.txt").write_bytes(b"file a")

    engine.init_scan([str(watch)])

    from agent.baseline import _entry_path
    ep = _entry_path(engine._baseline_dir, str(watch / "a.txt"))
    file_mode = stat.S_IMODE(ep.stat().st_mode)
    assert file_mode == 0o600, f"Expected 0600 got {oct(file_mode)}"

    dir_mode = stat.S_IMODE(engine._baseline_dir.stat().st_mode)
    assert dir_mode == 0o700


def test_init_scan_is_idempotent(engine: BaselineEngine, tmp_path: Path) -> None:
    watch = tmp_path / "watched2"
    watch.mkdir()
    (watch / "c.txt").write_bytes(b"idempotent")

    r1 = engine.init_scan([str(watch)])
    assert r1.scanned == 1

    r2 = engine.init_scan([str(watch)])
    assert r2.scanned == 0
    assert r2.skipped == 1


# ── 7.7 mark_absent ───────────────────────────────────────────────────────────

def test_mark_absent(engine: BaselineEngine, sample_file: Path) -> None:
    engine.write_entry(str(sample_file))
    entry = engine.mark_absent(str(sample_file))
    assert entry.status == "absent"
    assert entry.hash is None
    assert entry.content_b64 is None

    read_back = engine.read_entry(str(sample_file))
    assert read_back is not None
    assert read_back.status == "absent"
    assert read_back.hash is None


# ── 7.8 Snapshots: dedup, FIFO, gzip ──────────────────────────────────────────

def test_snapshot_dedup(engine: BaselineEngine, sample_file: Path) -> None:
    engine.write_entry(str(sample_file))
    added = engine.add_snapshot(str(sample_file))
    assert added is True
    entry = engine.read_entry(str(sample_file))
    assert entry is not None
    count = len(entry.snapshots)

    # Same hash → dedup, no new snapshot
    added2 = engine.add_snapshot(str(sample_file))
    assert added2 is False
    entry2 = engine.read_entry(str(sample_file))
    assert entry2 is not None
    assert len(entry2.snapshots) == count


def test_snapshot_fifo_max_3(engine: BaselineEngine, sample_file: Path) -> None:
    for i in range(4):
        sample_file.write_bytes(f"version {i}".encode())
        engine.write_entry(str(sample_file))
        engine.add_snapshot(str(sample_file))

    entry = engine.read_entry(str(sample_file))
    assert entry is not None
    assert len(entry.snapshots) <= 3


def test_snapshot_active_uncompressed_others_gzipped(
    engine: BaselineEngine, sample_file: Path
) -> None:
    # Write v1 and snapshot it (making it non-active)
    sample_file.write_bytes(b"version 1 content that is long enough to compress well")
    engine.write_entry(str(sample_file))
    engine.add_snapshot(str(sample_file))

    # Write v2 — now v1 snapshot should be gzipped, the new active is not
    sample_file.write_bytes(b"version 2 content is also moderately long for testing")
    engine.write_entry(str(sample_file))
    engine.add_snapshot(str(sample_file))

    entry = engine.read_entry(str(sample_file))
    assert entry is not None
    assert len(entry.snapshots) >= 1
    # All but the last should be gzipped
    for snap in entry.snapshots[:-1]:
        assert snap.gzip is True
    # Last snapshot (most recent) is not gzipped
    assert entry.snapshots[-1].gzip is False


# ── 7.9 master_secret inválido ────────────────────────────────────────────────

def test_load_master_secret_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_master_secret(tmp_path)


def test_load_master_secret_wrong_size(tmp_path: Path) -> None:
    ms = tmp_path / "master_secret"
    ms.write_bytes(b"\x00" * 16)  # solo 16 bytes, no 32
    with pytest.raises(ValueError, match="32 bytes"):
        load_master_secret(tmp_path)


def test_load_master_secret_ok(secrets_dir: Path, master_secret: bytes) -> None:
    loaded = load_master_secret(secrets_dir)
    assert loaded == master_secret
    assert len(loaded) == 32


# ── C23-H4: update_from_command preserva snapshots y content_b64 ──────────────

def test_update_from_command_preserves_snapshots(
    engine: BaselineEngine, sample_file: Path
) -> None:
    """update_from_command preserva los snapshots de la entrada existente."""
    # Crear entry inicial con snapshot
    engine.write_entry(str(sample_file))
    engine.add_snapshot(str(sample_file))

    existing = engine.read_entry(str(sample_file))
    assert existing is not None
    assert len(existing.snapshots) == 1

    # Aplicar un baseline_update por aprobación de cambio
    new_hash = "aabbccdd" * 8  # 64 chars hex
    updated = engine.update_from_command(str(sample_file), new_hash, "present")

    assert updated.hash == new_hash
    assert len(updated.snapshots) == 1, "Los snapshots deben preservarse"
    assert updated.snapshots[0].hash == existing.snapshots[0].hash


def test_update_from_command_preserves_content_b64(
    engine: BaselineEngine, sample_file: Path
) -> None:
    """update_from_command preserva content_b64 para que restore_file funcione."""
    engine.write_entry(str(sample_file))
    existing = engine.read_entry(str(sample_file))
    assert existing is not None
    original_content = existing.content_b64
    assert original_content is not None  # el sample_file es pequeño, debe tener content

    new_hash = "deadbeef" * 8
    updated = engine.update_from_command(str(sample_file), new_hash, "present")

    assert updated.content_b64 == original_content


def test_update_from_command_no_existing_creates_empty(
    engine: BaselineEngine, tmp_path: Path
) -> None:
    """Sin entry previo, update_from_command crea entry con content vacío."""
    path = str(tmp_path / "new_file.txt")
    result = engine.update_from_command(path, "abcd1234" * 8, "present")

    assert result.snapshots == []
    assert result.content_b64 is None
    assert result.hash == "abcd1234" * 8


def test_update_from_command_idempotent(
    engine: BaselineEngine, sample_file: Path
) -> None:
    """Re-delivery del mismo comando es idempotente y no corrompe el content."""
    engine.write_entry(str(sample_file))
    original = engine.read_entry(str(sample_file))
    assert original is not None

    new_hash = "11223344" * 8
    engine.update_from_command(str(sample_file), new_hash, "present")
    engine.update_from_command(str(sample_file), new_hash, "present")  # re-delivery

    final = engine.read_entry(str(sample_file))
    assert final is not None
    assert final.hash == new_hash
    # El content_b64 original debe seguir presente
    assert final.content_b64 == original.content_b64


# ── C37/C39: symlinks en el scan (RN-04/RN-125, D31; refinado por RN-127, D33) ──

def test_init_scan_baselines_escape_symlink_as_object(
    engine: BaselineEngine, tmp_path: Path
) -> None:
    """
    D33/RN-127 (refina D31/RN-125, hallazgo MEDIUM-2 de la revisión de C37):
    un symlink dentro del watch_path que apunta afuera (p. ej. /root/.ssh) ya NO
    se omite del baseline — se registra como objeto propio (metadata del link,
    is_symlink() ANTES de is_file()), sin leer/cifrar el contenido del destino.
    El archivo regular in-scope se baseline normalmente. Matriz de edge cases
    completa en test_symlink_hardening.py.
    """
    watch = tmp_path / "watched_scope"
    watch.mkdir()
    outside_dir = tmp_path / "root_ssh"
    outside_dir.mkdir()
    secret_file = outside_dir / "id_rsa"
    secret_file.write_bytes(b"super secret key material")

    escape_link = watch / "escape_link"
    escape_link.symlink_to(secret_file)
    (watch / "regular.txt").write_bytes(b"in scope content")

    report = engine.init_scan([str(watch)])

    assert report.scanned == 2  # regular.txt + escape_link (symlink-as-object)
    assert report.skipped == 0
    assert report.errors == 0

    from agent.baseline import _entry_path
    assert _entry_path(engine._baseline_dir, str(watch / "regular.txt")).exists()
    link_entry = engine.read_entry(str(escape_link))
    assert link_entry is not None
    assert link_entry.content_b64 is None
    assert link_entry.symlink_target == str(secret_file)


def test_init_scan_in_scope_file_baselined_normally(
    engine: BaselineEngine, tmp_path: Path
) -> None:
    watch = tmp_path / "watched_scope_ok"
    watch.mkdir()
    (watch / "a.txt").write_bytes(b"file a")

    report = engine.init_scan([str(watch)])

    assert report.scanned == 1
    assert report.skipped == 0

    entry = engine.read_entry(str(watch / "a.txt"))
    assert entry is not None
    assert entry.status == "present"


def test_run_scan_baselines_escape_symlink_as_object(
    engine: BaselineEngine, tmp_path: Path
) -> None:
    """run_scan aplica el mismo criterio de clasificación que init_scan (D33/RN-127)."""
    watch = tmp_path / "watched_scope_rescan"
    watch.mkdir()
    outside_dir = tmp_path / "root_ssh_rescan"
    outside_dir.mkdir()
    secret_file = outside_dir / "id_rsa"
    secret_file.write_bytes(b"super secret key material")

    escape_link = watch / "escape_link"
    escape_link.symlink_to(secret_file)
    (watch / "regular.txt").write_bytes(b"in scope content")

    report = engine.run_scan([str(watch)])

    assert report.scanned == 2
    assert report.skipped == 0

    from agent.baseline import _entry_path
    assert _entry_path(engine._baseline_dir, str(watch / "regular.txt")).exists()
    link_entry = engine.read_entry(str(escape_link))
    assert link_entry is not None
    assert link_entry.content_b64 is None
    assert link_entry.symlink_target == str(secret_file)
