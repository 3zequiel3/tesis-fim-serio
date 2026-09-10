"""Tests de DecisionEngine (acciones y rehidratación) (C10, tasks 10.1–11.3)."""
from __future__ import annotations

import base64
import errno
import hashlib
import json
import os
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.decision import (
    DecisionEngine,
    action_error_from_oserror,
    parse_baseline_mode,
)
from agent.journal import JournalManager
from agent.rules import RulesCache


def _metadata(entry_mock: MagicMock, *, mode: str = "0o644") -> None:
    """Setea mode/uid/gid del entry_mock al proceso actual (D36/RN-130 D-6):
    restaura sin privilegios porque fchown a la misma uid/gid ya dueña del
    tmp es un no-op permitido sin CAP_CHOWN."""
    entry_mock.mode = mode
    entry_mock.uid = os.getuid()
    entry_mock.gid = os.getgid()


def _make_engine(
    tmp_path: Path,
    action: str = "alert_only",
) -> tuple[DecisionEngine, JournalManager, MagicMock]:
    """Helper: crea DecisionEngine con acción fija, journal real, baseline mock."""
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()
    state_path = tmp_path / "state.json"

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = action

    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")

    baseline = MagicMock()

    engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline,
        quarantine_dir=quarantine_dir,
    )
    return engine, journal, baseline


def _make_change(tmp_path: Path, path: str | None = None) -> MagicMock:
    change = MagicMock()
    change.event_id = "test-event-001"
    change.path = path or str(tmp_path / "target.txt")
    change.event_type = "file_modified"
    change.to_event_data.return_value = {
        "event_id": change.event_id,
        "path": change.path,
        "event_type": "file_modified",
        "hash_expected": None,
        "hash_detected": None,
        "diff_text": None,
        "process_pid": 100,
        "process_uid": 0,
        "process_exe": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "parent_event_id": None,
    }
    return change


# ── auto_restore ──────────────────────────────────────────────────────────────

def test_decision_auto_restore_success(tmp_path: Path) -> None:
    content = b"good content"
    content_b64 = base64.b64encode(content).decode()
    content_hash = hashlib.sha256(content).hexdigest()

    target = tmp_path / "target.txt"
    target.write_bytes(b"bad content")  # versión modificada en disco

    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    entry_mock = MagicMock()
    entry_mock.content_b64 = content_b64
    entry_mock.hash = content_hash
    _metadata(entry_mock, mode="0o640")
    baseline.read_entry.return_value = entry_mock

    change = _make_change(tmp_path, path=str(target))
    payload, commit_fn = engine.evaluate_and_act(change)

    # D35/RN-129 (C40): event_type conserva el tipo de operación de filesystem,
    # el resultado de la acción viaja en action/action_failed.
    assert payload["event_type"] == "file_modified"
    assert payload["action"] == "auto_restore"
    assert payload.get("action_failed") is not True
    assert "action_error" not in payload
    assert target.read_bytes() == content  # archivo restaurado
    # D36/RN-130 (D-6): la restauración también aplica mode desde el baseline.
    assert stat.S_IMODE(target.stat().st_mode) == 0o640

    # Estado pending hasta que commit_fn sea invocado
    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["state"] == "pending"

    commit_fn()
    # BUG-10 fix: commit_fn calls delete(event_id) after mark_completed — file is gone
    assert not (tmp_path / "journal" / "test-event-001.json").exists(), (
        "journal file must be deleted after successful commit"
    )


def test_decision_auto_restore_no_content(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    entry_mock = MagicMock()
    entry_mock.content_b64 = None
    entry_mock.snapshots = []  # sin snapshots utilizables
    baseline.read_entry.return_value = entry_mock

    change = _make_change(tmp_path)
    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload["action_failed"] is True
    commit_fn()
    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["state"] == "failed"
    assert data["error"] == "no_restorable_content"


def test_decision_auto_restore_hash_mismatch(tmp_path: Path) -> None:
    content = b"good content"
    target = tmp_path / "target.txt"
    target.write_bytes(b"anything")

    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    entry_mock = MagicMock()
    entry_mock.content_b64 = base64.b64encode(content).decode()
    entry_mock.hash = "000000deadbeef"  # hash incorrecto
    _metadata(entry_mock)
    baseline.read_entry.return_value = entry_mock

    change = _make_change(tmp_path, path=str(target))
    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload["action_failed"] is True
    assert payload["action_error"] == "hash_mismatch_after_restore"
    commit_fn()
    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["error"] == "hash_mismatch_after_restore"


# ── metadata ausente (D36/RN-130 D-6): la restauración falla, no a medias ────


def test_decision_auto_restore_missing_uid_fails(tmp_path: Path) -> None:
    """mark_absent produce entries con uid/gid/mode en None (baseline.py:351-360)."""
    content = b"good content"
    target = tmp_path / "target.txt"
    original = b"unrelated content on disk"
    target.write_bytes(original)

    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    entry_mock = MagicMock()
    entry_mock.content_b64 = base64.b64encode(content).decode()
    entry_mock.hash = hashlib.sha256(content).hexdigest()
    entry_mock.mode = "0o644"
    entry_mock.uid = None
    entry_mock.gid = os.getgid()
    baseline.read_entry.return_value = entry_mock

    change = _make_change(tmp_path, path=str(target))
    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload["action_failed"] is True
    assert payload["action_error"] == "no_baseline_metadata"
    # El archivo original queda intacto — no hay restauración parcial.
    assert target.read_bytes() == original
    assert not (tmp_path / "target.txt.fim_restore_tmp").exists()
    commit_fn()
    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["error"] == "no_baseline_metadata"


def test_decision_auto_restore_unparseable_mode_fails(tmp_path: Path) -> None:
    content = b"good content"
    target = tmp_path / "target.txt"
    original = b"unrelated content on disk"
    target.write_bytes(original)

    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    entry_mock = MagicMock()
    entry_mock.content_b64 = base64.b64encode(content).decode()
    entry_mock.hash = hashlib.sha256(content).hexdigest()
    entry_mock.mode = "not-an-octal-mode"
    entry_mock.uid = os.getuid()
    entry_mock.gid = os.getgid()
    baseline.read_entry.return_value = entry_mock

    change = _make_change(tmp_path, path=str(target))
    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload["action_failed"] is True
    assert payload["action_error"] == "no_baseline_metadata"
    assert target.read_bytes() == original


# ── rehidratación: action_error también viaja en el payload reidratado ───────


@pytest.mark.asyncio
async def test_rehydrate_action_error_propagates(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    entry_mock = MagicMock()
    entry_mock.content_b64 = None
    entry_mock.snapshots = []
    baseline.read_entry.return_value = entry_mock

    journal.write_pending("evt-rehy-003", str(tmp_path / "target.txt"), "auto_restore")

    publisher = MagicMock()
    publisher.publish = AsyncMock()

    await engine.rehydrate(publisher)

    payload = publisher.publish.call_args[0][0]
    assert payload["action_failed"] is True
    assert payload["action_error"] == "no_restorable_content"
    # D49/RN-143 (5.3): la rehidratación no atribuye contexto de proceso — el
    # proceso original ya no existe por definición en esta ruta.
    assert payload["process_uid"] is None
    assert payload["process_pid"] is None


# ── funciones puras: parse_baseline_mode (D36/RN-130 D-6) ────────────────────


def test_parse_baseline_mode_prefixed_octal() -> None:
    assert parse_baseline_mode("0o644") == 0o644


def test_parse_baseline_mode_bare_octal() -> None:
    assert parse_baseline_mode("644") == 0o644


def test_parse_baseline_mode_none() -> None:
    assert parse_baseline_mode(None) is None


def test_parse_baseline_mode_garbage() -> None:
    assert parse_baseline_mode("not-a-mode") is None
    assert parse_baseline_mode("") is None


def test_parse_baseline_mode_preserves_setuid_setgid_sticky() -> None:
    """S_IMODE cubre 0o7777 — setuid, setgid y sticky viajan en el baseline."""
    assert parse_baseline_mode("0o4755") == 0o4755
    assert parse_baseline_mode("0o2755") == 0o2755
    assert parse_baseline_mode("0o1755") == 0o1755


# ── funciones puras: action_error_from_oserror (D36/RN-130 D-7) ──────────────


def test_action_error_from_oserror_erofs_maps_to_read_only_mount() -> None:
    exc = OSError(errno.EROFS, "Read-only file system")
    assert action_error_from_oserror(exc, fallback="write_failed") == "read_only_mount"


def test_action_error_from_oserror_eacces_maps_to_permission_denied() -> None:
    exc = OSError(errno.EACCES, "Permission denied")
    assert action_error_from_oserror(exc, fallback="write_failed") == "permission_denied"


def test_action_error_from_oserror_eperm_maps_to_permission_denied() -> None:
    exc = OSError(errno.EPERM, "Operation not permitted")
    assert action_error_from_oserror(exc, fallback="write_failed") == "permission_denied"


def test_action_error_from_oserror_other_uses_fallback() -> None:
    exc = OSError(errno.ENOSPC, "No space left on device")
    assert action_error_from_oserror(exc, fallback="write_failed") == "write_failed"
    assert action_error_from_oserror(exc, fallback="move_failed") == "move_failed"


def test_action_error_from_oserror_does_not_leak_message() -> None:
    exc = OSError(errno.EROFS, "Read-only file system: /etc/shadow")
    result = action_error_from_oserror(exc, fallback="write_failed")
    assert result == "read_only_mount"
    assert "/etc/shadow" not in result


# ── quarantine ────────────────────────────────────────────────────────────────

def test_decision_quarantine_success(tmp_path: Path) -> None:
    target = tmp_path / "evil.sh"
    target.write_bytes(b"rm -rf /")

    engine, journal, baseline = _make_engine(tmp_path, action="quarantine")

    change = _make_change(tmp_path, path=str(target))
    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload.get("action_failed") is not True
    assert "quarantine_path" in payload
    assert not target.exists()  # archivo movido
    q_path = Path(payload["quarantine_path"])
    assert q_path.exists()
    assert q_path.read_bytes() == b"rm -rf /"

    commit_fn()
    # BUG-10 fix: commit_fn deletes the journal file after mark_completed
    assert not (tmp_path / "journal" / "test-event-001.json").exists(), (
        "journal file must be deleted after successful quarantine commit"
    )


def test_decision_quarantine_file_gone(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="quarantine")
    non_existent = str(tmp_path / "ghost.sh")

    change = _make_change(tmp_path, path=non_existent)
    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload["action_failed"] is True
    commit_fn()
    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["error"] == "file_not_found"


# ── alert_only / manual_review ────────────────────────────────────────────────

def test_decision_alert_only(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="alert_only")
    change = _make_change(tmp_path)
    payload, commit_fn = engine.evaluate_and_act(change)

    assert "action_failed" not in payload
    assert payload["action"] == "alert_only"
    commit_fn()
    # BUG-10 fix: commit_fn deletes the journal file after mark_completed
    assert not (tmp_path / "journal" / "test-event-001.json").exists()


def test_decision_manual_review(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="manual_review")
    change = _make_change(tmp_path)
    payload, commit_fn = engine.evaluate_and_act(change)

    assert "action_failed" not in payload
    assert payload["action"] == "manual_review"
    commit_fn()
    # BUG-10 fix: commit_fn deletes the journal file after mark_completed
    assert not (tmp_path / "journal" / "test-event-001.json").exists()


# ── rehidratación ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rehydrate_auto_restore_pending(tmp_path: Path) -> None:
    content = b"original content"
    content_b64 = base64.b64encode(content).decode()
    content_hash = hashlib.sha256(content).hexdigest()

    target = tmp_path / "etc_hosts"
    target.write_bytes(b"tampered")

    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    entry_mock = MagicMock()
    entry_mock.content_b64 = content_b64
    entry_mock.hash = content_hash
    _metadata(entry_mock)
    baseline.read_entry.return_value = entry_mock

    # Simular entrada pending del arranque anterior
    journal.write_pending("evt-rehy-001", str(target), "auto_restore")

    publisher = MagicMock()
    publisher.publish = AsyncMock()

    await engine.rehydrate(publisher)

    assert target.read_bytes() == content
    publisher.publish.assert_called_once()
    payload = publisher.publish.call_args[0][0]
    # D35/RN-129 (C40): event_type conserva el valor del journal, no se
    # sobrescribe con el resultado de la acción.
    assert payload["event_type"] == "file_modified"
    assert payload["action"] == "auto_restore"
    assert payload.get("action_failed") is not True
    # D49/RN-143 (5.3): la rehidratación no atribuye contexto de proceso.
    assert payload["process_uid"] is None
    assert payload["process_pid"] is None
    assert not (tmp_path / "journal" / "evt-rehy-001.json").exists()  # eliminado


@pytest.mark.asyncio
async def test_rehydrate_keeps_journal_pending_when_durable_enqueue_fails(
    tmp_path: Path,
) -> None:
    """A recovered action remains retryable until publish durably enqueues it."""
    content = b"original content"
    target = tmp_path / "recoverable"
    target.write_bytes(b"tampered")

    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    entry_mock = MagicMock()
    entry_mock.content_b64 = base64.b64encode(content).decode()
    entry_mock.hash = hashlib.sha256(content).hexdigest()
    _metadata(entry_mock)
    baseline.read_entry.return_value = entry_mock
    journal.write_pending("evt-enqueue-failure", str(target), "auto_restore")

    publisher = MagicMock()
    publisher.publish = AsyncMock(side_effect=OSError("queue unavailable"))

    await engine.rehydrate(publisher)

    journal_data = json.loads(
        (tmp_path / "journal" / "evt-enqueue-failure.json").read_text()
    )
    assert journal_data["state"] == "pending"
    assert target.read_bytes() == content


@pytest.mark.asyncio
async def test_rehydrate_manual_review_pending(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="manual_review")

    journal.write_pending("evt-rehy-002", "/some/file", "manual_review")

    publisher = MagicMock()
    publisher.publish = AsyncMock()

    await engine.rehydrate(publisher)

    publisher.publish.assert_called_once()
    payload = publisher.publish.call_args[0][0]
    assert payload["action"] == "alert_only"  # re-publicado como alert_only
    # D49/RN-143 (5.3): la rehidratación no atribuye contexto de proceso.
    assert payload["process_uid"] is None
    assert payload["process_pid"] is None

    data = json.loads((tmp_path / "journal" / "evt-rehy-002.json").read_text())
    assert data["state"] == "failed"
    assert data["error"] == "rehydrated_without_action"


@pytest.mark.asyncio
async def test_rehydrate_no_pending(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path)

    publisher = MagicMock()
    publisher.publish = AsyncMock()

    await engine.rehydrate(publisher)

    publisher.publish.assert_not_called()
