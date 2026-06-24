"""Tests de DecisionEngine (acciones y rehidratación) (C10, tasks 10.1–11.3)."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.decision import DecisionEngine
from agent.journal import JournalManager
from agent.rules import RulesCache


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
        "previous_hash": None,
        "current_hash": None,
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
    baseline.read_entry.return_value = entry_mock

    change = _make_change(tmp_path, path=str(target))
    payload = engine.evaluate_and_act(change)

    assert payload["event_type"] == "auto_restored"
    assert payload.get("action_failed") is not True
    assert target.read_bytes() == content  # archivo restaurado

    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["state"] == "completed"


def test_decision_auto_restore_no_content(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="auto_restore")
    entry_mock = MagicMock()
    entry_mock.content_b64 = None
    entry_mock.snapshots = []  # sin snapshots utilizables
    baseline.read_entry.return_value = entry_mock

    change = _make_change(tmp_path)
    payload = engine.evaluate_and_act(change)

    assert payload["action_failed"] is True
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
    baseline.read_entry.return_value = entry_mock

    change = _make_change(tmp_path, path=str(target))
    payload = engine.evaluate_and_act(change)

    assert payload["action_failed"] is True
    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["error"] == "hash_mismatch_after_restore"


# ── quarantine ────────────────────────────────────────────────────────────────

def test_decision_quarantine_success(tmp_path: Path) -> None:
    target = tmp_path / "evil.sh"
    target.write_bytes(b"rm -rf /")

    engine, journal, baseline = _make_engine(tmp_path, action="quarantine")

    change = _make_change(tmp_path, path=str(target))
    payload = engine.evaluate_and_act(change)

    assert payload.get("action_failed") is not True
    assert "quarantine_path" in payload
    assert not target.exists()  # archivo movido
    q_path = Path(payload["quarantine_path"])
    assert q_path.exists()
    assert q_path.read_bytes() == b"rm -rf /"

    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["state"] == "completed"


def test_decision_quarantine_file_gone(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="quarantine")
    non_existent = str(tmp_path / "ghost.sh")

    change = _make_change(tmp_path, path=non_existent)
    payload = engine.evaluate_and_act(change)

    assert payload["action_failed"] is True
    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["error"] == "file_not_found"


# ── alert_only / manual_review ────────────────────────────────────────────────

def test_decision_alert_only(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="alert_only")
    change = _make_change(tmp_path)
    payload = engine.evaluate_and_act(change)

    assert "action_failed" not in payload
    assert payload["action"] == "alert_only"
    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["state"] == "completed"


def test_decision_manual_review(tmp_path: Path) -> None:
    engine, journal, baseline = _make_engine(tmp_path, action="manual_review")
    change = _make_change(tmp_path)
    payload = engine.evaluate_and_act(change)

    assert "action_failed" not in payload
    assert payload["action"] == "manual_review"
    data = json.loads((tmp_path / "journal" / "test-event-001.json").read_text())
    assert data["state"] == "completed"


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
    baseline.read_entry.return_value = entry_mock

    # Simular entrada pending del arranque anterior
    journal.write_pending("evt-rehy-001", str(target), "auto_restore")

    publisher = MagicMock()
    publisher.publish = AsyncMock()

    await engine.rehydrate(publisher)

    assert target.read_bytes() == content
    publisher.publish.assert_called_once()
    payload = publisher.publish.call_args[0][0]
    assert payload["event_type"] == "auto_restored"
    assert not (tmp_path / "journal" / "evt-rehy-001.json").exists()  # eliminado


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
