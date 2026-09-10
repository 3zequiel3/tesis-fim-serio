from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.__main__ import (
    _quarantine_maintenance_loop,
    _run_quarantine_maintenance,
)
from agent.config import StorageConfig
from agent.quarantine import QuarantineStore

MASTER = b"m" * 32
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _store(tmp_path: Path, days: int = 30) -> QuarantineStore:
    return QuarantineStore(
        tmp_path / "quarantine", MASTER, "agent-test", retention_days=days
    )


def _encrypted_at(store: QuarantineStore, tmp_path: Path, name: str, at: datetime) -> Path:
    source = tmp_path / name
    source.write_bytes(name.encode())

    class CapturedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return at if tz is not None else at.replace(tzinfo=None)

    with patch("agent.quarantine.datetime", CapturedDateTime):
        return store.quarantine(f"action-{name}", str(source)).path


@pytest.mark.parametrize("value", [0, 366, True, "30"])
def test_retention_config_rejects_values_outside_integer_range(value) -> None:
    with pytest.raises(ValueError, match="quarantine_retention_days"):
        StorageConfig(
            baseline_dir="/baseline",
            queue_dir="/queue",
            journal_dir="/journal",
            quarantine_retention_days=value,
        )


def test_retention_defaults_to_30_days() -> None:
    config = StorageConfig(
        baseline_dir="/baseline", queue_dir="/queue", journal_dir="/journal"
    )
    assert config.quarantine_retention_days == 30


def test_cleanup_deletes_at_boundary_and_retains_newer(tmp_path: Path) -> None:
    store = _store(tmp_path)
    boundary = _encrypted_at(store, tmp_path, "boundary", NOW - timedelta(days=30))
    newer = _encrypted_at(
        store, tmp_path, "newer", NOW - timedelta(days=30) + timedelta(microseconds=1)
    )

    report = store.cleanup_expired(now=NOW)

    assert report.deleted == 1
    assert report.retained == 1
    assert not boundary.exists()
    assert newer.exists()
    assert not report.degraded


def test_cleanup_is_repeatable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _encrypted_at(store, tmp_path, "old", NOW - timedelta(days=31))

    assert store.cleanup_expired(now=NOW).deleted == 1
    repeated = store.cleanup_expired(now=NOW)
    assert repeated.deleted == 0
    assert repeated.retained == 0


def test_corrupt_artifact_is_preserved_and_degrades_report(tmp_path: Path) -> None:
    store = _store(tmp_path)
    artifact = _encrypted_at(store, tmp_path, "corrupt", NOW - timedelta(days=31))
    os.chmod(artifact, 0o600)
    raw = bytearray(artifact.read_bytes())
    raw[-1] ^= 1
    artifact.write_bytes(raw)

    report = store.cleanup_expired(now=NOW)

    assert report.corrupt == 1
    assert report.degraded
    assert artifact.exists()


def test_cleanup_unlink_failure_is_preserved_and_degraded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    artifact = _encrypted_at(store, tmp_path, "undeletable", NOW - timedelta(days=31))
    real_unlink = os.unlink

    def fail_artifact(path, *args, **kwargs):
        if os.fspath(path) == str(artifact):
            raise OSError("injected")
        return real_unlink(path, *args, **kwargs)

    with patch("agent.quarantine.os.unlink", side_effect=fail_artifact):
        report = store.cleanup_expired(now=NOW)

    assert report.failed == 1
    assert report.degraded
    assert artifact.exists()


def test_migrates_automatic_legacy_plaintext_without_leak(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy = store.directory / "12345678-1234-1234-1234-123456789abc_secret.txt"
    marker = b"legacy-plaintext-marker"
    legacy.write_bytes(marker)
    os.utime(legacy, (NOW.timestamp(), NOW.timestamp()))

    report = store.migrate_legacy(now=NOW)

    assert report.migrated == 1
    assert not legacy.exists()
    artifact_path = next(store.directory.glob("*.fimq"))
    assert marker not in artifact_path.read_bytes()
    artifact = store.read_artifact(artifact_path)
    assert artifact.content == marker
    assert artifact.metadata["legacy_format"] == "automatic"
    assert artifact.metadata["original_path"] is None
    assert artifact.metadata["original_path_known"] is False


def test_migrates_command_legacy_timestamp(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy = store.directory / "payload.bin.20260910T115900"
    legacy.write_bytes(b"command legacy")

    report = store.migrate_legacy(now=NOW)

    assert report.migrated == 1
    artifact = store.read_artifact(next(store.directory.glob("*.fimq")))
    assert artifact.content == b"command legacy"
    assert artifact.metadata["legacy_format"] == "command"
    assert artifact.metadata["quarantined_at"] == "2026-09-10T11:59:00+00:00"


def test_unknown_legacy_is_preserved_as_pending(tmp_path: Path) -> None:
    store = _store(tmp_path)
    unknown = store.directory / "unknown-format"
    unknown.write_bytes(b"do not guess")

    report = store.migrate_legacy(now=NOW)

    assert report.pending == 1
    assert unknown.read_bytes() == b"do not guess"
    maintenance = store.maintain(now=NOW)
    assert maintenance.migration.pending == 1
    assert maintenance.degraded


def test_legacy_symlink_captures_target_text_without_following(tmp_path: Path) -> None:
    store = _store(tmp_path)
    target = tmp_path / "target"
    target.write_bytes(b"target content")
    legacy = store.directory / "12345678-1234-1234-1234-123456789abc_link"
    legacy.symlink_to(target)

    report = store.migrate_legacy(now=NOW)

    assert report.migrated == 1
    artifact = store.read_artifact(next(store.directory.glob("*.fimq")))
    assert artifact.metadata["kind"] == "symlink"
    assert artifact.content == str(target).encode()
    assert target.read_bytes() == b"target content"
    assert not os.path.lexists(legacy)


def test_legacy_hardlink_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy = store.directory / "12345678-1234-1234-1234-123456789abc_hard"
    alias = tmp_path / "alias"
    legacy.write_bytes(b"shared inode")
    os.link(legacy, alias)

    report = store.migrate_legacy(now=NOW)

    assert report.failed == 1
    assert legacy.exists() and alias.exists()
    assert not list(store.directory.glob("*.fimq"))


def test_restart_completes_migration_after_source_unlink_failure(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy = store.directory / "payload.20260910T115900"
    legacy.write_bytes(b"survive restart")
    real_unlink = os.unlink

    def fail_legacy(path, *args, **kwargs):
        if os.fspath(path) == str(legacy):
            raise OSError("crash boundary")
        return real_unlink(path, *args, **kwargs)

    with patch("agent.quarantine.os.unlink", side_effect=fail_legacy):
        first = store.migrate_legacy(now=NOW)
    assert first.failed == 1
    assert legacy.exists()
    assert len(list(store.directory.glob("*.fimq"))) == 1

    restarted = _store(tmp_path)
    second = restarted.migrate_legacy(now=NOW)
    assert second.skipped == 1
    assert not legacy.exists()
    assert len(list(store.directory.glob("*.fimq"))) == 1


def test_migration_never_overwrites_existing_destination(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy = store.directory / "payload.20260910T115900"
    legacy.write_bytes(b"legacy must remain")
    destination = store._legacy_artifact_path(legacy.name)
    destination.write_bytes(b"untrusted existing bytes")

    report = store.migrate_legacy(now=NOW)

    assert report.failed == 1
    assert legacy.read_bytes() == b"legacy must remain"
    assert destination.read_bytes() == b"untrusted existing bytes"

def test_maintenance_migrates_before_applying_retention(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy = store.directory / "payload.20260801T120000"
    legacy.write_bytes(b"expired plaintext")

    report = store.maintain(now=NOW)

    assert report.migration.migrated == 1
    assert report.cleanup.deleted == 1
    assert not legacy.exists()
    assert not list(store.directory.glob("*.fimq"))


def test_run_maintenance_logs_only_aggregate_counts() -> None:
    report = MagicMock(degraded=True)
    report.migration.migrated = 1
    report.migration.skipped = 2
    report.migration.failed = 3
    report.migration.pending = 4
    report.cleanup.deleted = 5
    report.cleanup.retained = 6
    report.cleanup.corrupt = 7
    report.cleanup.failed = 8
    store = MagicMock()
    store.maintain.return_value = report

    with patch("agent.__main__.log") as logger:
        _run_quarantine_maintenance(store)

    fields = logger.warning.call_args.kwargs
    assert fields == {
        "migrated": 1,
        "migration_skipped": 2,
        "migration_failed": 3,
        "migration_pending": 4,
        "retention_deleted": 5,
        "retention_retained": 6,
        "retention_corrupt": 7,
        "retention_failed": 8,
    }


@pytest.mark.asyncio
async def test_periodic_maintenance_stops_cleanly() -> None:
    store = MagicMock()
    store.maintain.return_value = MagicMock(degraded=False)
    stop = asyncio.Event()
    task = asyncio.create_task(
        _quarantine_maintenance_loop(store, stop, interval_s=0.005)
    )
    await asyncio.sleep(0.025)
    stop.set()
    await asyncio.wait_for(task, timeout=0.2)
    assert store.maintain.call_count >= 1
