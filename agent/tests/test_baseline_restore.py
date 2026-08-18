"""Tests de select_restorable_content y restore_file con fallback a snapshots (F3)."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.baseline import BaselineEntry, Snapshot, select_restorable_content


def _metadata(entry_mock: MagicMock, *, mode: str = "0o644") -> None:
    """D36/RN-130 (D-6): fchown a la propia uid/gid es un no-op permitido sin
    CAP_CHOWN, así que estos tests restauran metadata sin privilegios."""
    entry_mock.mode = mode
    entry_mock.uid = os.getuid()
    entry_mock.gid = os.getgid()


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_entry(
    content: bytes | None,
    snapshots: list[Snapshot] | None = None,
    path: str = "/etc/test",
) -> BaselineEntry:
    content_b64 = base64.b64encode(content).decode() if content is not None else None
    content_hash = hashlib.sha256(content).hexdigest() if content is not None else None
    return BaselineEntry(
        path=path,
        status="present" if content is not None else "absent",
        hash=content_hash,
        size=len(content) if content is not None else None,
        mode="0o644",
        uid=0,
        gid=0,
        mtime="2026-01-01T00:00:00+00:00",
        captured_at="2026-01-01T00:00:00+00:00",
        snapshots=snapshots or [],
        content_b64=content_b64,
    )


def _gzip_b64(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data, compresslevel=6)).decode()


# ── select_restorable_content ─────────────────────────────────────────────────

def test_select_restorable_content_active() -> None:
    content = b"original file content"
    entry = _make_entry(content)
    result = select_restorable_content(entry)
    assert result is not None
    raw, expected_hash = result
    assert raw == content
    assert expected_hash == hashlib.sha256(content).hexdigest()


def test_select_restorable_content_from_snapshot() -> None:
    snap_content = b"snapshot content"
    snap_hash = hashlib.sha256(snap_content).hexdigest()
    snap = Snapshot(
        hash=snap_hash,
        captured_at="2026-01-01T00:00:00+00:00",
        gzip=False,
        content_b64=base64.b64encode(snap_content).decode(),
    )
    entry = _make_entry(None, snapshots=[snap])
    result = select_restorable_content(entry)
    assert result is not None
    raw, expected_hash = result
    assert raw == snap_content
    assert expected_hash == snap_hash


def test_select_restorable_content_from_gzip_snapshot() -> None:
    snap_content = b"compressed snapshot content"
    snap_hash = hashlib.sha256(snap_content).hexdigest()
    snap = Snapshot(
        hash=snap_hash,
        captured_at="2026-01-01T00:00:00+00:00",
        gzip=True,
        content_b64=_gzip_b64(snap_content),
    )
    entry = _make_entry(None, snapshots=[snap])
    result = select_restorable_content(entry)
    assert result is not None
    raw, expected_hash = result
    assert raw == snap_content
    assert expected_hash == snap_hash


def test_select_restorable_content_picks_most_recent_snapshot() -> None:
    old_content = b"old snapshot"
    new_content = b"new snapshot"
    old_snap = Snapshot(
        hash=hashlib.sha256(old_content).hexdigest(),
        captured_at="2026-01-01T00:00:00+00:00",
        gzip=False,
        content_b64=base64.b64encode(old_content).decode(),
    )
    new_snap = Snapshot(
        hash=hashlib.sha256(new_content).hexdigest(),
        captured_at="2026-01-02T00:00:00+00:00",
        gzip=False,
        content_b64=base64.b64encode(new_content).decode(),
    )
    entry = _make_entry(None, snapshots=[old_snap, new_snap])
    result = select_restorable_content(entry)
    assert result is not None
    raw, _ = result
    assert raw == new_content


def test_select_restorable_content_none() -> None:
    snap_no_content = Snapshot(
        hash="abc",
        captured_at="2026-01-01T00:00:00+00:00",
        gzip=False,
        content_b64=None,
    )
    entry = _make_entry(None, snapshots=[snap_no_content])
    assert select_restorable_content(entry) is None


def test_select_restorable_content_no_snapshots() -> None:
    entry = _make_entry(None, snapshots=[])
    assert select_restorable_content(entry) is None


def test_select_restorable_content_active_present_ignores_snapshots() -> None:
    active_content = b"active content"
    snap_content = b"older snapshot"
    snap = Snapshot(
        hash=hashlib.sha256(snap_content).hexdigest(),
        captured_at="2026-01-01T00:00:00+00:00",
        gzip=False,
        content_b64=base64.b64encode(snap_content).decode(),
    )
    entry = _make_entry(active_content, snapshots=[snap])
    result = select_restorable_content(entry)
    assert result is not None
    raw, _ = result
    assert raw == active_content


# ── auto_restore desde snapshot ───────────────────────────────────────────────

def test_auto_restore_absent_file_uses_snapshot(tmp_path: Path) -> None:
    from agent.decision import DecisionEngine
    from agent.journal import JournalManager
    from agent.rules import RulesCache

    snap_content = b"restored from snapshot"
    snap_hash = hashlib.sha256(snap_content).hexdigest()
    snap = Snapshot(
        hash=snap_hash,
        captured_at="2026-01-01T00:00:00+00:00",
        gzip=False,
        content_b64=base64.b64encode(snap_content).decode(),
    )

    target = tmp_path / "target.txt"
    target.write_bytes(b"tampered content")

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = "auto_restore"
    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")
    baseline = MagicMock()

    entry_mock = MagicMock()
    entry_mock.content_b64 = None
    entry_mock.hash = None
    entry_mock.snapshots = [snap]
    _metadata(entry_mock)
    baseline.read_entry.return_value = entry_mock

    engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline,
        quarantine_dir=quarantine_dir,
    )

    change = MagicMock()
    change.event_id = "test-snap-restore-001"
    change.path = str(target)
    change.event_type = "file_absent"
    change.to_event_data.return_value = {
        "event_id": change.event_id,
        "path": change.path,
        "event_type": "file_absent",
        "hash_expected": None,
        "hash_detected": None,
        "diff_text": None,
        "process_pid": 0,
        "process_uid": 0,
        "process_exe": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "parent_event_id": None,
    }

    payload, commit_fn = engine.evaluate_and_act(change)

    assert payload.get("action_failed") is not True
    # D35/RN-129 (C40): event_type conserva el tipo de operación de filesystem.
    assert payload["event_type"] == "file_absent"
    assert payload["action"] == "auto_restore"
    assert target.read_bytes() == snap_content


def test_auto_restore_no_restorable_content_fails(tmp_path: Path) -> None:
    from agent.decision import DecisionEngine
    from agent.journal import JournalManager
    from agent.rules import RulesCache

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    rules_cache = MagicMock(spec=RulesCache)
    rules_cache.evaluate.return_value = "auto_restore"
    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")
    baseline = MagicMock()

    entry_mock = MagicMock()
    entry_mock.content_b64 = None
    entry_mock.snapshots = []
    baseline.read_entry.return_value = entry_mock

    engine = DecisionEngine(
        rules=rules_cache,
        journal=journal,
        baseline=baseline,
        quarantine_dir=quarantine_dir,
    )

    change = MagicMock()
    change.event_id = "test-no-content-001"
    change.path = str(tmp_path / "ghost.txt")
    change.event_type = "file_absent"
    change.to_event_data.return_value = {
        "event_id": change.event_id,
        "path": change.path,
        "event_type": "file_absent",
        "hash_expected": None,
        "hash_detected": None,
        "diff_text": None,
        "process_pid": 0,
        "process_uid": 0,
        "process_exe": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "parent_event_id": None,
    }

    payload, commit_fn = engine.evaluate_and_act(change)
    assert payload["action_failed"] is True


# ── handle_restore_file con snapshots ────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_restore_file_from_snapshot(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock as _AM
    from agent.commands import handle_restore_file
    from agent.journal import JournalManager

    snap_content = b"snapshot restored"
    snap_hash = hashlib.sha256(snap_content).hexdigest()
    snap = Snapshot(
        hash=snap_hash,
        captured_at="2026-01-01T00:00:00+00:00",
        gzip=False,
        content_b64=base64.b64encode(snap_content).decode(),
    )

    target = tmp_path / "restore_target.txt"
    target.write_bytes(b"damaged")

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")

    entry_mock = MagicMock()
    entry_mock.content_b64 = None
    entry_mock.hash = None
    entry_mock.snapshots = [snap]
    _metadata(entry_mock)

    baseline = MagicMock()
    baseline.read_entry.return_value = entry_mock

    valkey_mock = MagicMock()
    valkey_mock.xadd = _AM(return_value="1-0")

    config_mock = MagicMock()
    config_mock.agent_id = "test-agent-001"
    # FIX-04 (D18): watch_paths must include the target path for containment check
    config_mock.watch_paths = [str(tmp_path)]

    command = {
        "command_id": "cmd-snap-restore-001",
        "event_id": "evt-001",
        "path": str(target),
    }

    await handle_restore_file(
        command=command,
        baseline_engine=baseline,
        journal=journal,
        valkey_client=valkey_mock,
        config=config_mock,
    )

    assert target.read_bytes() == snap_content


@pytest.mark.asyncio
async def test_handle_restore_file_no_restorable_content(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock as _AM
    from agent.commands import handle_restore_file
    from agent.journal import JournalManager

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    journal = JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!")

    entry_mock = MagicMock()
    entry_mock.content_b64 = None
    entry_mock.snapshots = []

    baseline = MagicMock()
    baseline.read_entry.return_value = entry_mock

    valkey_mock = MagicMock()
    valkey_mock.xadd = _AM(return_value="1-0")

    config_mock = MagicMock()
    config_mock.agent_id = "test-agent-001"
    # FIX-04 (D18): watch_paths must include the path for containment check.
    # Using /etc so the path /etc/nonexistent_fim_test passes; there is no baseline
    # for it so the test still hits the "no_restorable_content" error.
    config_mock.watch_paths = ["/etc"]

    command = {
        "command_id": "cmd-no-content-001",
        "event_id": "evt-002",
        "path": "/etc/nonexistent_fim_test_file",
    }

    await handle_restore_file(
        command=command,
        baseline_engine=baseline,
        journal=journal,
        valkey_client=valkey_mock,
        config=config_mock,
    )

    # El ack debe indicar error
    call_args = valkey_mock.xadd.call_args
    ack_data = json.loads(call_args[0][1]["data"])
    assert ack_data["status"] == "error"
    assert "no_restorable_content" in ack_data["error"]
