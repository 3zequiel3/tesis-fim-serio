"""Tests de JournalManager (C10, task 9.1–9.5)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.journal import JournalEntry, JournalManager


def _make_manager(tmp_path: Path) -> JournalManager:
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir()
    return JournalManager(journal_dir)


def test_journal_write_pending(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    entry = mgr.write_pending("evt-001", "/etc/hosts", "auto_restore")

    assert entry.state == "pending"
    assert entry.event_id == "evt-001"
    assert entry.action == "auto_restore"

    p = tmp_path / "journal" / "evt-001.json"
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["state"] == "pending"
    assert data["path"] == "/etc/hosts"


def test_journal_mark_completed(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.write_pending("evt-002", "/etc/passwd", "quarantine")
    mgr.mark_completed("evt-002")

    data = json.loads((tmp_path / "journal" / "evt-002.json").read_text())
    assert data["state"] == "completed"
    assert data["updated_at"] >= data["created_at"]


def test_journal_mark_failed(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.write_pending("evt-003", "/opt/app.py", "auto_restore")
    mgr.mark_failed("evt-003", "no_baseline_content")

    data = json.loads((tmp_path / "journal" / "evt-003.json").read_text())
    assert data["state"] == "failed"
    assert data["error"] == "no_baseline_content"


def test_journal_load_pending(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.write_pending("evt-010", "/a", "auto_restore")
    mgr.write_pending("evt-011", "/b", "alert_only")
    mgr.mark_completed("evt-011")  # este no debe aparecer

    pending = mgr.load_pending()
    assert len(pending) == 1
    assert pending[0].event_id == "evt-010"


def test_journal_delete(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.write_pending("evt-020", "/x", "quarantine")

    p = tmp_path / "journal" / "evt-020.json"
    assert p.exists()
    mgr.delete("evt-020")
    assert not p.exists()
