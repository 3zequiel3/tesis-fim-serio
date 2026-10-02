"""
Tests of the `release_quarantine` command (Change 65, D83/RN-177).

Real bench: `BaselineEngine`, `JournalManager`, `QuarantineStore`,
`ExecutedCommandRegistry` and the real `FanotifyDetector` run over `tmp_path`.
Only the Valkey client (an ack collector) and the arrival of fanotify events
(injected through `_process_event`) are simulated.

Each test asserts the filesystem/baseline/artifact effect first and the ack
second; the echo tests assert that the relocation itself publishes nothing.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agent import commands
from agent._fanotify import FAN_CREATE, FAN_MOVED_TO
from agent.baseline import BaselineEngine, BaselineEntry
from agent.config import AgentConfig, StorageConfig
from agent.decision import DecisionEngine
from agent.detector import FanotifyDetector, FanotifyEvent
from agent.executed_commands import ExecutedCommandRegistry
from agent.journal import JournalManager
from agent.quarantine import QuarantineStore, quarantine_and_record
from agent.rules import RulesCache
from agent.state import AgentState
from agent.streams import sign_payload

_SHARED = b"test-secret-32-bytes-xxxxxxxxxx!"
_APPROVED = b"approved baseline content\n"
_QUARANTINED = b"suspicious content\n"
_QSHA = hashlib.sha256(_QUARANTINED).hexdigest()
_ASHA = hashlib.sha256(_APPROVED).hexdigest()


class _CollectingPublisher:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def publish(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


@dataclasses.dataclass
class Rig:
    tmp_path: Path
    watch_dir: Path
    config: AgentConfig
    baseline: BaselineEngine
    journal: JournalManager
    store: QuarantineStore
    registry: ExecutedCommandRegistry
    state: AgentState
    detector: FanotifyDetector
    engine: DecisionEngine
    publisher: _CollectingPublisher
    valkey: AsyncMock
    target: Path

    def acks(self) -> list[dict[str, Any]]:
        return [json.loads(c.args[1]["data"]) for c in self.valkey.xadd.call_args_list]


@pytest.fixture()
def rig(tmp_path: Path) -> Rig:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o700)
    master = os.urandom(32)
    (secrets_dir / "master_secret").write_bytes(master)
    (secrets_dir / "shared_secret").write_bytes(_SHARED)
    config = AgentConfig(
        agent_id="rel-agent",
        backend_url="https://localhost:8443",
        valkey_url="valkey://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=[str(watch_dir)],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(secrets_dir),
            certs_dir=str(tmp_path / "certs"),
        ),
    )
    baseline = BaselineEngine(config, master)
    (tmp_path / "journal").mkdir()
    journal = JournalManager(tmp_path / "journal", _SHARED)
    store = QuarantineStore(tmp_path / "quarantine", master, config.agent_id)
    registry = ExecutedCommandRegistry(tmp_path / "journal" / "executed_commands.json")
    state = AgentState(ruleset_version=1, state_path=secrets_dir / "state.json")
    state_path = tmp_path / "rules_state.json"
    state_path.write_text(json.dumps({"ruleset_version": 1, "rules": []}))
    rules = RulesCache(state_path)
    engine = DecisionEngine(rules=rules, journal=journal, baseline=baseline, quarantine_store=store)
    publisher = _CollectingPublisher()
    detector = FanotifyDetector(
        agent_id=config.agent_id,
        watch_paths=[str(watch_dir)],
        baseline=baseline,
        publisher=publisher,
        stop_event=asyncio.Event(),
        decision_engine=engine,
    )
    valkey = AsyncMock()
    valkey.xadd = AsyncMock()
    target = watch_dir / "target.conf"
    return Rig(
        tmp_path, watch_dir, config, baseline, journal, store, registry, state,
        detector, engine, publisher, valkey, target,
    )


def _quarantine(rig: Rig, *, mode: int = 0o640, approved: bool = True) -> str:
    """Seed an approved baseline (optional), swap the content and quarantine it
    through the real single implementation. Returns the agent event id."""
    if approved:
        rig.target.write_bytes(_APPROVED)
        os.chmod(rig.target, 0o640)
        rig.baseline.write_entry(str(rig.target))
    rig.target.write_bytes(_QUARANTINED)
    os.chmod(rig.target, mode)
    event_id = str(uuid.uuid4())
    outcome = quarantine_and_record(
        store=rig.store, baseline=rig.baseline, journal=rig.journal,
        action_id=event_id, path=str(rig.target),
    )
    assert outcome.error is None
    assert not rig.target.exists()
    assert rig.store.artifact_path(event_id, str(rig.target)).exists()
    return event_id


def _cmd(rig: Rig, event_id: str, mode: str, **over: Any) -> dict[str, Any]:
    cmd: dict[str, Any] = {
        "type": "release_quarantine",
        "command_id": f"cmd-{uuid.uuid4()}",
        "event_id": 7,
        "agent_event_id": event_id,
        "target_agent_id": rig.config.agent_id,
        "path": str(rig.target),
        "mode": mode,
        "expected_sha256": _QSHA,
        "issued_at": "2026-01-01T00:00:00+00:00",
    }
    if mode == "restore_original":
        cmd["ruleset_version"] = 5
    cmd.update(over)
    return cmd


async def _release(rig: Rig, cmd: dict[str, Any]) -> dict[str, Any]:
    """Run the handler and return the LAST published ack."""
    await commands.handle_release_quarantine(
        cmd,
        baseline_engine=rig.baseline,
        state=rig.state,
        journal=rig.journal,
        quarantine_store=rig.store,
        registry=rig.registry,
        valkey_client=rig.valkey,
        config=rig.config,
    )
    return rig.acks()[-1]


def _entry(rig: Rig) -> BaselineEntry:
    entry = rig.baseline.read_entry(str(rig.target))
    assert entry is not None
    return entry


def _artifact_exists(rig: Rig, event_id: str) -> bool:
    return rig.store.artifact_path(event_id, str(rig.target)).exists()


def _no_tmp(rig: Rig) -> None:
    assert not list(rig.watch_dir.glob("*.fim_restore_tmp"))


async def _inject(rig: Rig, mask: int) -> None:
    await rig.detector._process_event(
        FanotifyEvent(
            path=str(rig.target), pid=4242, uid=0, exe=None,
            timestamp="2026-01-01T00:00:00+00:00", mask=mask,
        )
    )


# ── restore_original ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_original_success(rig: Rig) -> None:
    event_id = _quarantine(rig, mode=0o4755)
    st = os.stat(rig.target.parent)
    cmd = _cmd(rig, event_id, "restore_original")
    ack = await _release(rig, cmd)

    assert rig.target.read_bytes() == _QUARANTINED
    st = os.lstat(rig.target)
    assert stat.S_IMODE(st.st_mode) == 0o755  # setuid stripped
    assert (st.st_uid, st.st_gid) == (os.getuid(), os.getgid())
    entry = _entry(rig)
    assert entry.status == "present" and entry.hash == _QSHA
    assert entry.quarantine_action_id is None
    assert entry.mode == oct(0o755)
    assert not _artifact_exists(rig, event_id)
    assert rig.state.ruleset_version == 5
    assert ack["status"] == "ok" and ack["command_type"] == "release_quarantine"
    assert ack["command_id"] == cmd["command_id"] and ack["event_id"] == 7
    assert rig.journal._read(cmd["command_id"]).state == "completed"
    assert rig.registry.get(cmd["command_id"])["ok"] is True
    _no_tmp(rig)


@pytest.mark.asyncio
async def test_restore_original_path_occupied_before_lstat(rig: Rig) -> None:
    event_id = _quarantine(rig)
    rig.target.write_bytes(b"someone else's file")
    ack = await _release(rig, _cmd(rig, event_id, "restore_original"))

    assert ack["status"] == "error" and ack["error"] == "path_occupied"
    assert rig.target.read_bytes() == b"someone else's file"
    assert _artifact_exists(rig, event_id)
    assert _entry(rig).status == "quarantined"
    assert rig.state.ruleset_version == 1
    _no_tmp(rig)


@pytest.mark.asyncio
async def test_restore_original_path_created_between_lstat_and_link(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_id = _quarantine(rig)

    def _racy_check(path: str) -> None:  # lstat saw nothing; then someone creates it
        Path(path).write_bytes(b"raced in")

    monkeypatch.setattr(commands, "_require_path_free", _racy_check)
    ack = await _release(rig, _cmd(rig, event_id, "restore_original"))

    assert ack["error"] == "path_occupied"
    assert rig.target.read_bytes() == b"raced in"
    assert _artifact_exists(rig, event_id)
    assert _entry(rig).status == "quarantined"
    _no_tmp(rig)


@pytest.mark.asyncio
async def test_restore_original_stale_version_has_no_effects(rig: Rig) -> None:
    event_id = _quarantine(rig)
    rig.state.ruleset_version = 9
    ack = await _release(rig, _cmd(rig, event_id, "restore_original", ruleset_version=3))

    assert ack["error"] == "stale_ruleset_version"
    assert not rig.target.exists()
    assert _artifact_exists(rig, event_id)
    assert _entry(rig).status == "quarantined"
    assert rig.state.ruleset_version == 9


@pytest.mark.asyncio
async def test_restore_original_symlink_artifact_is_unsupported(rig: Rig) -> None:
    rig.target.symlink_to("/etc/hostname")
    event_id = str(uuid.uuid4())
    outcome = quarantine_and_record(
        store=rig.store, baseline=rig.baseline, journal=rig.journal,
        action_id=event_id, path=str(rig.target),
    )
    assert outcome.error is None
    sha = outcome.artifact.metadata["sha256"]
    ack = await _release(rig, _cmd(rig, event_id, "restore_original", expected_sha256=sha))

    assert ack["error"] == "unsupported_file_type"
    assert not os.path.lexists(rig.target)
    assert _artifact_exists(rig, event_id)
    assert _entry(rig).status == "quarantined"


@pytest.mark.asyncio
async def test_restore_original_failed_reread_reverts_baseline(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_id = _quarantine(rig)
    before = _entry(rig)
    monkeypatch.setattr(
        "agent.decision.verify_restored_file", lambda *a, **k: "hash_mismatch_after_restore"
    )
    ack = await _release(rig, _cmd(rig, event_id, "restore_original"))

    assert ack["error"] == "hash_mismatch_after_restore"
    assert _artifact_exists(rig, event_id)
    after = _entry(rig)
    assert after == before and after.status == "quarantined"
    assert rig.state.ruleset_version == 1


# ── restore_baseline ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_baseline_success(rig: Rig) -> None:
    event_id = _quarantine(rig)
    ack = await _release(rig, _cmd(rig, event_id, "restore_baseline"))

    assert ack["status"] == "ok"
    assert rig.target.read_bytes() == _APPROVED
    assert stat.S_IMODE(os.lstat(rig.target).st_mode) == 0o640
    entry = _entry(rig)
    assert entry.status == "present" and entry.hash == _ASHA
    assert not _artifact_exists(rig, event_id)
    assert rig.state.ruleset_version == 1  # restore_baseline never moves it
    _no_tmp(rig)


@pytest.mark.asyncio
async def test_restore_baseline_path_occupied(rig: Rig) -> None:
    event_id = _quarantine(rig)
    rig.target.write_bytes(b"occupied")
    ack = await _release(rig, _cmd(rig, event_id, "restore_baseline"))

    assert ack["error"] == "path_occupied"
    assert rig.target.read_bytes() == b"occupied"
    assert _artifact_exists(rig, event_id)
    assert _entry(rig).status == "quarantined"
    _no_tmp(rig)


@pytest.mark.asyncio
async def test_restore_baseline_without_restorable_content(rig: Rig) -> None:
    event_id = _quarantine(rig, approved=False)  # entry with null fields
    ack = await _release(rig, _cmd(rig, event_id, "restore_baseline"))

    assert ack["error"] == "no_restorable_content"
    assert not rig.target.exists()
    assert _artifact_exists(rig, event_id)


# ── discard ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discard_removes_only_the_artifact(rig: Rig) -> None:
    event_id = _quarantine(rig)
    before = _entry(rig)
    ack = await _release(rig, _cmd(rig, event_id, "discard"))

    assert ack["status"] == "ok"
    assert not _artifact_exists(rig, event_id)
    assert not rig.target.exists()
    assert _entry(rig) == before and before.status == "quarantined"
    assert rig.state.ruleset_version == 1


# ── artifact errors, per mode ───────────────────────────────────────────────

_MODES = ["restore_original", "restore_baseline", "discard"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
async def test_artifact_expired(rig: Rig, mode: str) -> None:
    event_id = _quarantine(rig)
    rig.store.artifact_path(event_id, str(rig.target)).unlink()
    ack = await _release(rig, _cmd(rig, event_id, mode))

    assert ack["error"] == "artifact_not_found"
    assert not rig.target.exists()
    assert _entry(rig).status == "quarantined"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
async def test_legacy_artifact_named_by_command_id(rig: Rig, mode: str) -> None:
    rig.target.write_bytes(_QUARANTINED)
    rig.baseline.write_entry(str(rig.target))
    rig.store.quarantine("cmd-legacy", str(rig.target))
    ack = await _release(rig, _cmd(rig, str(uuid.uuid4()), mode))

    assert ack["error"] == "artifact_not_found"
    assert not rig.target.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
async def test_artifact_tampered(rig: Rig, mode: str) -> None:
    event_id = _quarantine(rig)
    path = rig.store.artifact_path(event_id, str(rig.target))
    os.chmod(path, 0o600)
    raw = bytearray(path.read_bytes())
    raw[40] ^= 0xFF
    path.write_bytes(bytes(raw))
    ack = await _release(rig, _cmd(rig, event_id, mode))

    assert ack["error"] == "artifact_integrity_failed"
    assert not rig.target.exists()
    assert path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", _MODES)
async def test_artifact_hash_mismatch(rig: Rig, mode: str) -> None:
    event_id = _quarantine(rig)
    ack = await _release(rig, _cmd(rig, event_id, mode, expected_sha256="0" * 64))

    assert ack["error"] == "artifact_hash_mismatch"
    assert not rig.target.exists()
    assert _artifact_exists(rig, event_id)


@pytest.mark.asyncio
async def test_path_outside_watch_paths(rig: Rig, tmp_path: Path) -> None:
    event_id = _quarantine(rig)
    ack = await _release(rig, _cmd(rig, event_id, "discard", path=str(tmp_path / "elsewhere")))

    assert ack["error"] == "path_outside_watch_paths"
    assert _artifact_exists(rig, event_id)


@pytest.mark.asyncio
async def test_invalid_mode_is_rejected(rig: Rig) -> None:
    event_id = _quarantine(rig)
    ack = await _release(rig, _cmd(rig, event_id, "wipe"))

    assert ack["status"] == "error" and ack["error"] == "invalid_release_command"
    assert _artifact_exists(rig, event_id)


# ── idempotency ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_same_delivery_twice_has_one_effect_and_identical_acks(rig: Rig) -> None:
    event_id = _quarantine(rig)
    cmd = _cmd(rig, event_id, "restore_original")
    first = await _release(rig, cmd)
    mtime = os.lstat(rig.target).st_mtime_ns
    with patch.object(commands, "_publish_without_overwrite") as publish:
        second = await _release(rig, cmd)
        publish.assert_not_called()

    assert os.lstat(rig.target).st_mtime_ns == mtime
    assert len(rig.acks()) == 2
    for key in ("status", "error", "command_id", "command_type", "event_id"):
        assert first[key] == second[key]


@pytest.mark.asyncio
async def test_failed_outcome_is_republished_not_retried(rig: Rig) -> None:
    event_id = _quarantine(rig)
    rig.target.write_bytes(b"occupied")
    cmd = _cmd(rig, event_id, "restore_original")
    await _release(rig, cmd)
    rig.target.unlink()  # the operator cleared the path, but this is the SAME command
    again = await _release(rig, cmd)

    assert again["error"] == "path_occupied"
    assert not rig.target.exists()
    assert _artifact_exists(rig, event_id)


class _CrashingRegistry(ExecutedCommandRegistry):
    def record(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("crash before the registry write")


@pytest.mark.asyncio
async def test_crash_between_remove_artifact_and_record_redelivery_is_ok(rig: Rig) -> None:
    event_id = _quarantine(rig)
    cmd = _cmd(rig, event_id, "restore_original")
    healthy = rig.registry
    rig.registry = _CrashingRegistry(rig.tmp_path / "journal" / "crash.json")
    with pytest.raises(RuntimeError):
        await _release(rig, cmd)
    assert not _artifact_exists(rig, event_id)
    assert rig.target.read_bytes() == _QUARANTINED
    mtime = os.lstat(rig.target).st_mtime_ns

    rig.registry = healthy
    rig.state.ruleset_version = 1  # the crash also lost the in-memory state write
    with patch.object(commands, "_publish_without_overwrite") as publish:
        ack = await _release(rig, cmd)
        publish.assert_not_called()

    assert ack["status"] == "ok"
    assert os.lstat(rig.target).st_mtime_ns == mtime
    assert rig.state.ruleset_version == 5


@pytest.mark.asyncio
async def test_rehydrate_does_not_publish_release_journal_entries(rig: Rig) -> None:
    rig.journal.write_pending("cmd-pending-release", str(rig.target), "release_quarantine")
    await rig.engine.rehydrate(rig.publisher)

    assert rig.publisher.payloads == []
    entry = rig.journal._read("cmd-pending-release")
    assert entry is not None and entry.state == "pending"


# ── echo suppression with the real detector ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("mask", [FAN_CREATE, FAN_MOVED_TO])
async def test_restore_original_publishes_no_integrity_event(rig: Rig, mask: int) -> None:
    event_id = _quarantine(rig)
    ack = await _release(rig, _cmd(rig, event_id, "restore_original"))
    assert ack["status"] == "ok" and rig.target.read_bytes() == _QUARANTINED

    await _inject(rig, mask)
    assert rig.publisher.payloads == []
    assert _entry(rig).status == "present"


@pytest.mark.asyncio
@pytest.mark.parametrize("mask", [FAN_CREATE, FAN_MOVED_TO])
async def test_restore_baseline_publishes_no_integrity_event(rig: Rig, mask: int) -> None:
    event_id = _quarantine(rig)
    ack = await _release(rig, _cmd(rig, event_id, "restore_baseline"))
    assert ack["status"] == "ok" and rig.target.read_bytes() == _APPROVED

    await _inject(rig, mask)
    assert rig.publisher.payloads == []
    assert _entry(rig).status == "present"


@pytest.mark.asyncio
async def test_restore_baseline_echo_is_dropped_even_while_entry_is_quarantined(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Open Question 1: the identical-hash discard applies to a `quarantined`
    entry, so the echo is safe whichever side of `clear_quarantine` it lands on."""
    event_id = _quarantine(rig)
    monkeypatch.setattr(rig.baseline, "clear_quarantine", lambda path: None)
    ack = await _release(rig, _cmd(rig, event_id, "restore_baseline"))
    assert ack["status"] == "ok"
    assert _entry(rig).status == "quarantined"

    await _inject(rig, FAN_CREATE)
    assert rig.publisher.payloads == []


# ── dispatch ────────────────────────────────────────────────────────────────


def _signed(rig: Rig, cmd: dict[str, Any]) -> dict[str, Any]:
    cmd = dict(cmd)
    cmd["signature"] = sign_payload(_SHARED, cmd)
    return cmd


async def _dispatch(rig: Rig, cmd: dict[str, Any]) -> None:
    await commands.dispatch(
        cmd,
        baseline_engine=rig.baseline,
        state=rig.state,
        valkey_client=rig.valkey,
        config=rig.config,
        journal=rig.journal,
        quarantine_store=rig.store,
        executed_commands=rig.registry,
    )


@pytest.mark.asyncio
async def test_dispatch_routes_signed_release_quarantine_to_the_handler(rig: Rig) -> None:
    event_id = _quarantine(rig)
    cmd = _signed(rig, _cmd(rig, event_id, "discard"))
    await _dispatch(rig, cmd)

    assert rig.acks()[-1]["status"] == "ok"
    assert not _artifact_exists(rig, event_id)


@pytest.mark.asyncio
async def test_dispatch_invalid_signature_has_no_effects(rig: Rig) -> None:
    event_id = _quarantine(rig)
    cmd = _signed(rig, _cmd(rig, event_id, "discard"))
    cmd["signature"] = "0" * 64
    await _dispatch(rig, cmd)

    assert rig.acks() == []
    assert _artifact_exists(rig, event_id)
    assert rig.registry.get(cmd["command_id"]) is None


@pytest.mark.asyncio
async def test_dispatch_foreign_target_has_no_effects(rig: Rig) -> None:
    event_id = _quarantine(rig)
    cmd = _signed(rig, _cmd(rig, event_id, "discard", target_agent_id="other-agent"))
    await _dispatch(rig, cmd)

    assert rig.acks() == []
    assert _artifact_exists(rig, event_id)


@pytest.mark.asyncio
async def test_dispatch_without_registry_does_nothing(rig: Rig) -> None:
    event_id = _quarantine(rig)
    cmd = _signed(rig, _cmd(rig, event_id, "discard"))
    await commands.dispatch(
        cmd, baseline_engine=rig.baseline, state=rig.state, valkey_client=rig.valkey,
        config=rig.config, journal=rig.journal, quarantine_store=rig.store,
    )
    assert rig.acks() == []
    assert _artifact_exists(rig, event_id)


# ── publisher whitelist ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publisher_routes_release_quarantine_to_commands_dispatch(rig: Rig) -> None:
    from agent.publisher import Publisher
    from agent.queue import EventQueue
    from agent.tests.conftest import TEST_MASTER_SECRET

    queue = EventQueue(
        rig.config.storage.queue_dir,
        master_secret=TEST_MASTER_SECRET,
        agent_id=rig.config.agent_id,
        discard_dir=str(rig.tmp_path / "discarded"),
        max_discard_files=10,
    )
    publisher = Publisher(rig.config, queue, rig.valkey)
    publisher.register_command_handlers(
        baseline_engine=rig.baseline,
        state=rig.state,
        journal=rig.journal,
        quarantine_store=rig.store,
        executed_commands=rig.registry,
    )
    event_id = _quarantine(rig)
    payload = _signed(rig, _cmd(rig, event_id, "discard"))
    await publisher._handle_command_async(payload)

    assert rig.acks()[-1]["command_type"] == "release_quarantine"
    assert rig.acks()[-1]["status"] == "ok"
    assert not _artifact_exists(rig, event_id)
