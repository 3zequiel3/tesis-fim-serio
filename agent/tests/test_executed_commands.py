"""Tests of ExecutedCommandRegistry (D83/RN-177 D-9, tasks 2.1-2.3)."""
from __future__ import annotations

import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.executed_commands import ExecutedCommandRegistry


def test_record_and_get(tmp_path: Path) -> None:
    reg = ExecutedCommandRegistry(tmp_path / "executed_commands.json")
    assert reg.get("c1") is None
    reg.record("c1", "release_quarantine", False, "path_occupied")
    got = reg.get("c1")
    assert got is not None
    assert (got["type"], got["ok"], got["error"]) == ("release_quarantine", False, "path_occupied")
    assert "executed_at" in got


def test_persists_between_instances_with_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "executed_commands.json"
    ExecutedCommandRegistry(path).record("c1", "release_quarantine", True, None)
    again = ExecutedCommandRegistry(path)
    assert again.get("c1") is not None and again.get("c1")["ok"] is True
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_prunes_entries_older_than_retention(tmp_path: Path) -> None:
    reg = ExecutedCommandRegistry(tmp_path / "e.json", retention_days=30)
    now = datetime.now(timezone.utc)
    reg.record("old", "release_quarantine", True, None, now=now - timedelta(days=31))
    reg.record("new", "release_quarantine", True, None, now=now)
    assert reg.get("old") is None
    assert ExecutedCommandRegistry(tmp_path / "e.json").get("old") is None
    assert reg.get("new") is not None


def test_corrupt_file_is_treated_as_empty_and_never_raises(tmp_path: Path) -> None:
    path = tmp_path / "e.json"
    path.write_text("{not json")
    reg = ExecutedCommandRegistry(path)
    assert reg.get("c1") is None
    reg.record("c1", "release_quarantine", True, None)
    assert ExecutedCommandRegistry(path).get("c1") is not None


def test_record_failure_does_not_raise(tmp_path: Path) -> None:
    reg = ExecutedCommandRegistry(tmp_path / "missing_dir" / "e.json")
    reg.record("c1", "release_quarantine", True, None)  # must not raise
    assert reg.get("c1") is not None
