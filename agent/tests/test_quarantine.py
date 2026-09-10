from __future__ import annotations

import hashlib
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.commands import handle_quarantine_file
from agent.config import AgentConfig, StorageConfig
from agent.decision import DecisionEngine
from agent.journal import JournalManager
from agent.quarantine import (
    QuarantineError,
    QuarantineIntegrityError,
    QuarantineStore,
    derive_quarantine_key,
)
from agent.rules import RulesCache
from agent.streams import sign_payload

MASTER = b"m" * 32
SHARED = b"s" * 32


def _store(tmp_path: Path) -> QuarantineStore:
    return QuarantineStore(tmp_path / "quarantine", MASTER, "agent-test")


def test_quarantine_directory_must_not_be_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "quarantine"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(QuarantineError, match="quarantine_directory_invalid"):
        QuarantineStore(link, MASTER, "agent-test")


def test_authenticated_roundtrip_is_opaque_at_rest(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "private-name.txt"
    marker = b"plaintext-marker-that-must-not-leak"
    source.write_bytes(marker)

    result = store.quarantine("event-1", str(source))

    raw = result.path.read_bytes()
    assert marker not in raw
    assert str(source).encode() not in raw
    assert source.name.encode() not in result.path.name.encode()
    restored = store.read_artifact(result.path)
    assert restored.content == marker
    assert restored.metadata["original_path"] == str(source)
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o400
    assert not source.exists()


def test_quarantine_key_is_domain_separated_from_baseline(tmp_path: Path) -> None:
    from agent.baseline import derive_baseline_key

    assert derive_quarantine_key(MASTER, "agent-test") != derive_baseline_key(
        MASTER, "agent-test"
    )


@pytest.mark.parametrize("position", [20, -1])
def test_tampered_artifact_is_rejected(tmp_path: Path, position: int) -> None:
    store = _store(tmp_path)
    source = tmp_path / "sample"
    source.write_bytes(b"safe copy")
    artifact = store.quarantine("event-tamper", str(source)).path
    raw = bytearray(artifact.read_bytes())
    raw[position] ^= 1
    os.chmod(artifact, 0o600)
    artifact.write_bytes(raw)

    with pytest.raises(QuarantineIntegrityError, match="quarantine_integrity_failure"):
        store.read_artifact(artifact)


def test_concurrent_same_identity_creates_one_artifact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "racy"
    source.write_bytes(b"one source")

    def run() -> Path:
        return store.quarantine("event-concurrent", str(source)).path

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))

    assert results[0] == results[1]
    assert len(list(store.directory.glob("*.fimq"))) == 1
    assert not list(store.directory.glob("*.tmp"))


def test_same_basename_and_action_in_different_paths_do_not_collide(tmp_path: Path) -> None:
    store = _store(tmp_path)
    left = tmp_path / "left" / "same.bin"
    right = tmp_path / "right" / "same.bin"
    left.parent.mkdir()
    right.parent.mkdir()
    left.write_bytes(b"left")
    right.write_bytes(b"right")

    first = store.quarantine("shared-action", str(left))
    second = store.quarantine("shared-action", str(right))

    assert first.path != second.path
    assert len(list(store.directory.glob("*.fimq"))) == 2


@pytest.mark.parametrize("failure", ["fsync", "fchmod", "replace"])
def test_durable_write_failure_never_removes_source_or_reports_success(
    tmp_path: Path, failure: str
) -> None:
    store = _store(tmp_path)
    source = tmp_path / failure
    source.write_bytes(b"must survive")
    target = f"agent.quarantine.os.{failure}"
    with patch(target, side_effect=OSError("injected")):
        with pytest.raises(QuarantineError):
            store.quarantine(f"event-{failure}", str(source))
    assert source.read_bytes() == b"must survive"


def test_failed_readback_verification_keeps_source(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "verify"
    source.write_bytes(b"must survive failed verification")
    with patch.object(
        store,
        "_read_artifact",
        side_effect=QuarantineIntegrityError("quarantine_integrity_failure"),
    ):
        with pytest.raises(QuarantineIntegrityError):
            store.quarantine("event-verify", str(source))
    assert source.read_bytes() == b"must survive failed verification"


def test_retry_after_remove_failure_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "retry"
    source.write_bytes(b"stable")
    real_unlink = os.unlink

    def fail_source_only(path: str | os.PathLike[str], *args, **kwargs) -> None:
        if os.fspath(path) == str(source):
            raise OSError("crash boundary")
        real_unlink(path, *args, **kwargs)

    with patch("agent.quarantine.os.unlink", side_effect=fail_source_only):
        with pytest.raises(QuarantineError, match="quarantine_source_remove_failed"):
            store.quarantine("event-retry", str(source))

    first = store.artifact_path("event-retry", str(source))
    assert first.exists() and source.exists()
    retried = store.quarantine("event-retry", str(source))
    assert retried.path == first
    assert not source.exists()
    assert len(list(store.directory.glob("*.fimq"))) == 1


def test_retry_never_deletes_recreated_path(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "recreated"
    source.write_bytes(b"original")
    real_unlink = os.unlink

    def fail_source_only(path: str | os.PathLike[str], *args, **kwargs) -> None:
        if os.fspath(path) == str(source):
            raise OSError("crash boundary")
        real_unlink(path, *args, **kwargs)

    with patch("agent.quarantine.os.unlink", side_effect=fail_source_only):
        with pytest.raises(QuarantineError):
            store.quarantine("event-recreated", str(source))
    source.unlink()
    source.write_bytes(b"new file")

    with pytest.raises(QuarantineError, match="quarantine_source_changed"):
        store.quarantine("event-recreated", str(source))
    assert source.read_bytes() == b"new file"


def test_symlink_is_encrypted_as_object_not_preserved_live(tmp_path: Path) -> None:
    store = _store(tmp_path)
    target = tmp_path / "secret-target"
    target.write_bytes(b"target bytes must not be read")
    link = tmp_path / "link"
    link.symlink_to(target)

    artifact = store.quarantine("event-link", str(link))

    assert not os.path.lexists(link)
    assert target.read_bytes() == b"target bytes must not be read"
    assert artifact.metadata["kind"] == "symlink"
    assert store.read_artifact(artifact.path).content == str(target).encode()
    assert not artifact.path.is_symlink()


def test_hardlink_rejected_without_false_isolation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "source"
    alias = tmp_path / "alias"
    source.write_bytes(b"shared inode")
    os.link(source, alias)

    with pytest.raises(QuarantineError, match="hardlink_not_isolatable"):
        store.quarantine("event-hardlink", str(source))
    assert source.exists() and alias.exists()
    assert not list(store.directory.glob("*.fimq"))


def test_hardlink_added_during_capture_prevents_source_removal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = tmp_path / "source-race"
    alias = tmp_path / "late-alias"
    source.write_bytes(b"shared after capture")
    real_write = store._write_encrypted

    def write_then_link(*args, **kwargs) -> None:
        real_write(*args, **kwargs)
        os.link(source, alias)

    with patch.object(store, "_write_encrypted", side_effect=write_then_link):
        with pytest.raises(QuarantineError, match="quarantine_source_changed"):
            store.quarantine("event-hardlink-race", str(source))
    assert source.exists() and alias.exists()


def _config(tmp_path: Path) -> AgentConfig:
    secrets = tmp_path / "secrets"
    secrets.mkdir(exist_ok=True)
    (secrets / "master_secret").write_bytes(MASTER)
    (secrets / "shared_secret").write_bytes(SHARED)
    return AgentConfig(
        agent_id="agent-test",
        backend_url="https://backend",
        valkey_url="valkey://valkey",
        ca_cert_path="/ca",
        watch_paths=[str(tmp_path)],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(secrets),
        ),
        allow_plaintext_valkey=True,
    )


def test_automatic_quarantine_uses_shared_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    journal = JournalManager(tmp_path / "journal", SHARED)
    rules = MagicMock(spec=RulesCache)
    rules.evaluate.return_value = "quarantine"
    engine = DecisionEngine(
        rules, journal, MagicMock(), quarantine_store=store
    )
    source = tmp_path / "automatic"
    source.write_bytes(b"automatic bytes")
    change = MagicMock(event_id="event-auto", path=str(source))
    change.to_event_data.return_value = {"event_id": "event-auto", "path": str(source)}

    payload, _commit = engine.evaluate_and_act(change)

    assert not payload.get("action_failed")
    assert store.read_artifact(payload["quarantine_path"]).content == b"automatic bytes"


@pytest.mark.asyncio
async def test_automatic_quarantine_rehydrates_idempotently_after_publish_gap(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    journal = JournalManager(tmp_path / "journal-rehydrate", SHARED)
    rules = MagicMock(spec=RulesCache)
    rules.evaluate.return_value = "quarantine"
    engine = DecisionEngine(rules, journal, MagicMock(), quarantine_store=store)
    source = tmp_path / "rehydrate"
    source.write_bytes(b"captured once")
    change = MagicMock(event_id="event-rehydrate", path=str(source))
    change.to_event_data.return_value = {
        "event_id": "event-rehydrate",
        "path": str(source),
    }

    engine.evaluate_and_act(change)  # simulate crash before returned commit callback
    assert len(list(store.directory.glob("*.fimq"))) == 1
    publisher = MagicMock()
    publisher.publish = AsyncMock()

    await engine.rehydrate(publisher)

    publisher.publish.assert_awaited_once()
    assert len(list(store.directory.glob("*.fimq"))) == 1
    assert journal.load_pending() == []


@pytest.mark.asyncio
async def test_command_quarantine_uses_supplied_shared_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = _config(tmp_path)
    journal = JournalManager(tmp_path / "journal-command", SHARED)
    source = tmp_path / "commanded"
    source.write_bytes(b"command bytes")
    command = {
        "type": "quarantine_file",
        "command_id": "command-1",
        "event_id": 9,
        "target_agent_id": config.agent_id,
        "path": str(source),
    }
    command["signature"] = sign_payload(SHARED, command)
    valkey = AsyncMock()

    await handle_quarantine_file(
        command, journal, valkey, config, quarantine_store=store
    )

    ack = json.loads(valkey.xadd.call_args.args[1]["data"])
    assert ack["status"] == "ok"
    artifact = store.artifact_path("command-1", str(source))
    assert store.read_artifact(artifact).content == b"command bytes"


@pytest.mark.asyncio
async def test_command_hardlink_failure_is_not_acknowledged_as_success(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = _config(tmp_path)
    journal = JournalManager(tmp_path / "journal-hardlink", SHARED)
    source = tmp_path / "command-hardlink"
    alias = tmp_path / "command-hardlink-alias"
    source.write_bytes(b"shared")
    os.link(source, alias)
    command = {
        "type": "quarantine_file",
        "command_id": "command-hardlink",
        "event_id": 10,
        "target_agent_id": config.agent_id,
        "path": str(source),
    }
    command["signature"] = sign_payload(SHARED, command)
    valkey = AsyncMock()

    await handle_quarantine_file(
        command, journal, valkey, config, quarantine_store=store
    )

    ack = json.loads(valkey.xadd.call_args.args[1]["data"])
    assert ack["status"] == "error"
    assert ack["error"] == "hardlink_not_isolatable"
    assert source.exists() and alias.exists()
