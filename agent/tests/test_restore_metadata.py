"""Tests de filesystem real, sin root, para la restauración de metadata
(D36/RN-130, D-6/D-12 del design).

La suite del agente mockea el filesystem con generosidad y por eso no
detectó nada de este comportamiento — estos tests tocan archivos de verdad,
siguiendo la cadena de fixtures de agent/tests/test_baseline.py:36-81.
fchown a la propia uid/gid del proceso es un no-op permitido por el kernel
sin CAP_CHOWN (inode_change_ok en fs/attr.c no exige la capability cuando la
uid nueva coincide con la uid ya dueña del archivo), así que estos tests
corren sin privilegios.
"""
from __future__ import annotations

import base64
import hashlib
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.baseline import BaselineEntry
from agent.decision import DecisionEngine
from agent.journal import JournalManager
from agent.rules import RulesCache


def _entry(target: Path, content: bytes, *, mode: str = "0o644") -> BaselineEntry:
    return BaselineEntry(
        path=str(target),
        status="present",
        hash=hashlib.sha256(content).hexdigest(),
        size=len(content),
        mode=mode,
        uid=os.getuid(),
        gid=os.getgid(),
        mtime="2026-01-01T00:00:00+00:00",
        captured_at="2026-01-01T00:00:00+00:00",
        snapshots=[],
        content_b64=base64.b64encode(content).decode(),
    )


def _engine(tmp_path: Path, entry: BaselineEntry) -> tuple[DecisionEngine, JournalManager]:
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir(exist_ok=True)

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = "auto_restore"
    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")

    baseline = MagicMock()
    baseline.read_entry.return_value = entry

    engine = DecisionEngine(
        rules=rules_cache, journal=journal, baseline=baseline, quarantine_dir=quarantine_dir,
    )
    return engine, journal


def _change(event_id: str, target: Path) -> MagicMock:
    change = MagicMock()
    change.event_id = event_id
    change.path = str(target)
    change.event_type = "file_modified"
    change.to_event_data.return_value = {
        "event_id": event_id,
        "path": str(target),
        "event_type": "file_modified",
        "hash_expected": None,
        "hash_detected": None,
        "diff_text": None,
        "process_pid": 0,
        "process_uid": 0,
        "process_exe": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "parent_event_id": None,
    }
    return change


# ── 11.1: la restauración preserva el modo ────────────────────────────────────


def test_restore_preserves_mode_real_filesystem(tmp_path: Path) -> None:
    content = b"restored content"
    target = tmp_path / "target.conf"
    target.write_bytes(b"tampered")
    target.chmod(0o644)  # el archivo tampereado no necesariamente comparte el modo del baseline

    entry = _entry(target, content, mode="0o600")
    engine, journal = _engine(tmp_path, entry)

    payload, commit_fn = engine.evaluate_and_act(_change("evt-mode-001", target))

    assert payload.get("action_failed") is not True
    assert target.read_bytes() == content
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


# ── 11.2: no_baseline_metadata deja el archivo original intacto ──────────────


@pytest.mark.parametrize("missing_field", ["mode", "uid", "gid"])
def test_missing_metadata_field_aborts_and_leaves_original_intact(
    tmp_path: Path, missing_field: str
) -> None:
    content = b"restored content"
    target = tmp_path / "target.conf"
    original = b"original on-disk content, untouched"
    target.write_bytes(original)

    entry = _entry(target, content)
    kwargs = {}
    if missing_field == "mode":
        entry = BaselineEntry(**{**entry.__dict__, "mode": None})
    elif missing_field == "uid":
        entry = BaselineEntry(**{**entry.__dict__, "uid": None})
    else:
        entry = BaselineEntry(**{**entry.__dict__, "gid": None})

    engine, journal = _engine(tmp_path, entry)

    payload, commit_fn = engine.evaluate_and_act(_change("evt-meta-001", target))

    assert payload["action_failed"] is True
    assert payload["action_error"] == "no_baseline_metadata"
    assert target.read_bytes() == original
    assert not (tmp_path / "target.conf.fim_restore_tmp").exists()


def test_unparseable_mode_aborts_and_leaves_no_orphan_tmp(tmp_path: Path) -> None:
    content = b"restored content"
    target = tmp_path / "target.conf"
    original = b"original on-disk content"
    target.write_bytes(original)

    entry = _entry(target, content)
    entry = BaselineEntry(**{**entry.__dict__, "mode": "garbage"})
    engine, journal = _engine(tmp_path, entry)

    payload, commit_fn = engine.evaluate_and_act(_change("evt-meta-002", target))

    assert payload["action_error"] == "no_baseline_metadata"
    assert target.read_bytes() == original
    assert not (tmp_path / "target.conf.fim_restore_tmp").exists()


# ── 11.3: permission_denied real ──────────────────────────────────────────────


def test_permission_denied_real_chmod_on_parent_dir(tmp_path: Path) -> None:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    target = watch_dir / "target.conf"
    content = b"restored content"
    target.write_bytes(b"tampered")

    entry = _entry(target, content)
    engine, journal = _engine(tmp_path, entry)

    os.chmod(str(watch_dir), 0o500)  # r-x------: sin escritura ni para el dueño
    try:
        payload, commit_fn = engine.evaluate_and_act(_change("evt-perm-001", target))
    finally:
        os.chmod(str(watch_dir), 0o700)  # restaurar para que tmp_path pueda limpiar

    assert payload["action_failed"] is True
    assert payload["action_error"] == "permission_denied"
    assert target.read_bytes() == b"tampered"  # original intacto


# ── 11.4: O_EXCL — un tmp huérfano hace fallar el intento, no lo reusa ───────


def test_orphaned_tmp_file_makes_restore_fail_not_reused(tmp_path: Path) -> None:
    content = b"restored content"
    target = tmp_path / "target.conf"
    target.write_bytes(b"tampered")

    orphan_tmp = tmp_path / "target.conf.fim_restore_tmp"
    orphan_tmp.write_bytes(b"leftover from a previous crashed attempt")

    entry = _entry(target, content)
    engine, journal = _engine(tmp_path, entry)

    payload, commit_fn = engine.evaluate_and_act(_change("evt-excl-001", target))

    assert payload["action_failed"] is True
    # EEXIST no es EROFS/EACCES/EPERM => fallback del sitio (write_failed).
    assert payload["action_error"] == "write_failed"
    # El original queda intacto: la restauración no truncó ni reusó el huérfano.
    assert target.read_bytes() == b"tampered"
    assert orphan_tmp.read_bytes() == b"leftover from a previous crashed attempt"


# ── 11.5: orden fchown ANTES que fchmod ───────────────────────────────────────


def test_fchown_called_before_fchmod(tmp_path: Path) -> None:
    """Mock legítimo (D-12): no pretende demostrar que chown funciona — eso lo
    prueba 11.1/11.3 con filesystem real — demuestra que el ORDEN se respeta,
    que es la propiedad destructiva (chown limpia setuid/setgid si corre
    después de chmod)."""
    content = b"restored content"
    target = tmp_path / "target.conf"
    target.write_bytes(b"tampered")

    entry = _entry(target, content)
    engine, journal = _engine(tmp_path, entry)

    call_order: list[str] = []
    real_fchown = os.fchown
    real_fchmod = os.fchmod

    def recording_fchown(fd: int, uid: int, gid: int) -> None:
        call_order.append("fchown")
        real_fchown(fd, uid, gid)

    def recording_fchmod(fd: int, mode: int) -> None:
        call_order.append("fchmod")
        real_fchmod(fd, mode)

    with patch("os.fchown", side_effect=recording_fchown), \
         patch("os.fchmod", side_effect=recording_fchmod):
        payload, commit_fn = engine.evaluate_and_act(_change("evt-order-001", target))

    assert payload.get("action_failed") is not True
    assert call_order == ["fchown", "fchmod"], (
        "fchown DEBE preceder a fchmod — invertir el orden pierde setuid/setgid"
    )
