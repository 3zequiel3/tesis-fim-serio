"""
Tests of D82/RN-176 (Change 64, quarantine-baseline-preservation): quarantining
a file must not destroy the approved version it was meant to protect, and the
quarantine's own `unlink` must not produce events.

Real bench, same pattern as `test_restore_feedback_loop.py`: `BaselineEngine`,
`DecisionEngine`, `JournalManager` and `QuarantineStore` are real over
`tmp_path`. Only the publisher (a payload collector) and the arrival of
fanotify events (injected through `_process_event`) are simulated. No
`MagicMock` for the baseline, the filesystem or the engine.

Each test asserts FIRST that the action really happened (artifact addressed by
the agent's event_id, source gone, journal closed) and only then the effect on
the baseline and the event stream: a test that only counts events also passes
when the quarantine silently failed.

The two entry paths are parametrized: `automatic` (a `quarantine` rule plus an
injected `FAN_CLOSE_WRITE`) and `operator` (`handle_quarantine_file` with an
`agent_event_id`). Both start from the same approved version.
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
from unittest.mock import AsyncMock

import pytest

from agent._fanotify import (
    FAN_CLOSE_WRITE,
    FAN_CREATE,
    FAN_DELETE,
    FAN_MOVED_FROM,
    FAN_MOVED_TO,
)
from agent.baseline import (
    BaselineEngine,
    BaselineEntry,
    _atomic_write,
    _encrypt,
    _entry_path,
    select_restorable_content,
)
from agent.config import AgentConfig, StorageConfig
from agent.decision import DecisionEngine
from agent.detector import FanotifyDetector, FanotifyEvent
from agent.journal import JournalManager
from agent.quarantine import QuarantineStore, quarantine_and_record
from agent.rules import RulesCache

_SHARED_SECRET = b"test-secret-32-bytes-xxxxxxxxxx!"
_APPROVED = b"approved baseline content\n"
_TAMPERED = b"TAMPERED CONTENT\n"
_PATH_KINDS = ["automatic", "operator"]


# ── Doubles: only the network client is simulated ────────────────────────────


class _CollectingPublisher:
    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def publish(self, payload: dict[str, Any]) -> None:
        self.payloads.append(payload)


class _ObservingJournal(JournalManager):
    """Real journal that also remembers which keys went through completion
    (`evaluate_and_act` deletes the entry right after completing it)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.completed_event_ids: list[str] = []

    def mark_completed(self, event_id: str) -> None:
        self.completed_event_ids.append(event_id)
        super().mark_completed(event_id)


class _FailingMarkBaseline(BaselineEngine):
    """Real engine that fails only `mark_quarantined`."""

    def mark_quarantined(self, path: str, action_id: str) -> BaselineEntry:
        raise OSError("disk full while marking")


class _ExplodingStore(QuarantineStore):
    """Real store whose `quarantine` raises an unexpected error carrying the path."""

    def quarantine(self, action_id: str, source_path: str):  # type: ignore[override]
        raise RuntimeError(f"unexpected failure on {source_path}")


@dataclasses.dataclass
class Rig:
    tmp_path: Path
    watch_dir: Path
    config: AgentConfig
    baseline: BaselineEngine
    rules: RulesCache
    journal: _ObservingJournal
    store: QuarantineStore
    engine: DecisionEngine
    detector: FanotifyDetector
    publisher: _CollectingPublisher
    target: Path
    known_entry: BaselineEntry
    mark_absent_calls: list[str]
    traces: list[tuple[str, dict[str, Any]]]
    journal_dir: Path

    def set_rule(self, action: str) -> None:
        self.rules.load(
            {"rules": [{"pattern": f"{self.watch_dir}/**", "action": action, "negated": False}]}
        )

    def journal_files(self) -> int:
        return len(list(self.journal_dir.glob("*.json")))


def _build_rig(
    tmp_path: Path,
    *,
    rule: str = "alert_only",
    approved: bytes = _APPROVED,
    baseline_cls: type[BaselineEngine] = BaselineEngine,
    store_cls: type[QuarantineStore] = QuarantineStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Rig:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o700)
    master_secret = os.urandom(32)
    (secrets_dir / "master_secret").write_bytes(master_secret)
    (secrets_dir / "shared_secret").write_bytes(_SHARED_SECRET)

    config = AgentConfig(
        agent_id="qbp-agent",
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
    baseline = baseline_cls(config, master_secret)

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ruleset_version": 1, "rules": []}))
    rules = RulesCache(state_path)

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    journal = _ObservingJournal(journal_dir, shared_secret=_SHARED_SECRET)
    store = store_cls(tmp_path / "quarantine", master_secret, config.agent_id)
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

    mark_absent_calls: list[str] = []
    real_mark_absent = baseline.mark_absent

    def _spy_mark_absent(path: str) -> BaselineEntry:
        mark_absent_calls.append(path)
        return real_mark_absent(path)

    monkeypatch.setattr(baseline, "mark_absent", _spy_mark_absent)

    traces: list[tuple[str, dict[str, Any]]] = []
    real_trace = detector._trace_record

    def _spy_trace(stage: str, **fields: Any) -> None:
        traces.append((stage, fields))
        real_trace(stage, **fields)

    monkeypatch.setattr(detector, "_trace_record", _spy_trace)

    target = watch_dir / "target.conf"
    target.write_bytes(approved)
    os.chmod(target, 0o640)
    known_entry = baseline.write_entry(str(target))
    assert select_restorable_content(known_entry) is not None, "rig seed must be restorable"

    rig = Rig(
        tmp_path=tmp_path,
        watch_dir=watch_dir,
        config=config,
        baseline=baseline,
        rules=rules,
        journal=journal,
        store=store,
        engine=engine,
        detector=detector,
        publisher=publisher,
        target=target,
        known_entry=known_entry,
        mark_absent_calls=mark_absent_calls,
        traces=traces,
        journal_dir=journal_dir,
    )
    rig.set_rule(rule)
    return rig


@pytest.fixture()
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    return _build_rig(tmp_path, monkeypatch=monkeypatch)


async def _inject(rig: Rig, path: Path, mask: int, *, pid: int = 4242) -> None:
    await rig.detector._process_event(
        FanotifyEvent(
            path=str(path),
            pid=pid,
            uid=0,
            exe=None,
            timestamp="2026-01-01T00:00:00+00:00",
            mask=mask,
        )
    )


async def _operator_quarantine(
    rig: Rig, *, agent_event_id: str | None, path: Path | None = None
) -> dict[str, Any]:
    """Run `handle_quarantine_file`; return the published ack payload."""
    from agent import commands

    valkey = AsyncMock()
    valkey.xadd = AsyncMock()
    cmd: dict[str, Any] = {
        "command_id": f"cmd-{uuid.uuid4()}",
        "event_id": 77,
        "path": str(path or rig.target),
    }
    if agent_event_id is not None:
        cmd["agent_event_id"] = agent_event_id
    await commands.handle_quarantine_file(
        command=cmd,
        baseline_engine=rig.baseline,
        journal=rig.journal,
        valkey_client=valkey,
        config=rig.config,
        quarantine_store=rig.store,
    )
    valkey.xadd.assert_called_once()
    return json.loads(valkey.xadd.call_args[0][1]["data"])


async def _quarantine(rig: Rig, kind: str) -> str:
    """Quarantine the seeded target through one of the two entry paths and
    assert the action happened. Returns the agent's event_id."""
    rig.target.write_bytes(_TAMPERED)
    if kind == "automatic":
        rig.set_rule("quarantine")
        await _inject(rig, rig.target, FAN_CLOSE_WRITE)
        assert len(rig.publisher.payloads) == 1
        payload = rig.publisher.payloads[0]
        assert payload["action"] == "quarantine"
        assert not payload.get("action_failed")
        event_id = payload["event_id"]
        assert event_id in rig.journal.completed_event_ids
    else:
        event_id = str(uuid.uuid4())
        ack = await _operator_quarantine(rig, agent_event_id=event_id)
        assert ack["status"] == "ok"
        entry = rig.journal._read(event_id)
        assert entry is not None and entry.state == "completed"
    assert not rig.target.exists()
    assert rig.store.artifact_path(event_id, str(rig.target)).exists()
    return event_id


def _entry(rig: Rig) -> BaselineEntry:
    entry = rig.baseline.read_entry(str(rig.target))
    assert entry is not None
    return entry


def _suppressed_reasons(rig: Rig) -> list[str]:
    return [
        f.get("reason", "")
        for stage, f in rig.traces
        if stage == "decision_suppressed" and f.get("reason") == "quarantined_by_agent"
    ]


# ══════════════════════════════════════════════════════════════════════════
# Quarantine keeps a restorable baseline (both entry paths)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_path", _PATH_KINDS)
async def test_quarantine_preserves_a_restorable_baseline(rig: Rig, entry_path: str) -> None:
    event_id = await _quarantine(rig, entry_path)

    entry = _entry(rig)
    prev = rig.known_entry
    assert entry.status == "quarantined"
    assert entry.quarantine_action_id == event_id
    assert (entry.hash, entry.content_b64, entry.size, entry.mode, entry.uid, entry.gid) == (
        prev.hash, prev.content_b64, prev.size, prev.mode, prev.uid, prev.gid,
    )
    assert entry.mtime == prev.mtime
    assert entry.snapshots == prev.snapshots
    restorable = select_restorable_content(entry)
    assert restorable is not None
    assert restorable[0] == _APPROVED
    assert rig.mark_absent_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_path", _PATH_KINDS)
@pytest.mark.parametrize("echo_mask", [FAN_DELETE, FAN_MOVED_FROM])
async def test_own_unlink_echo_is_suppressed(rig: Rig, entry_path: str, echo_mask: int) -> None:
    await _quarantine(rig, entry_path)
    payloads_before = len(rig.publisher.payloads)
    journal_before = rig.journal_files()
    entry_before = _entry(rig).to_json_bytes()
    pending_before = dict(rig.detector._pending)

    await _inject(rig, rig.target, echo_mask)

    assert len(rig.publisher.payloads) == payloads_before
    assert rig.journal_files() == journal_before
    assert rig.mark_absent_calls == []
    assert _entry(rig).to_json_bytes() == entry_before
    assert rig.detector._pending == pending_before
    assert _suppressed_reasons(rig) == ["quarantined_by_agent"]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_path", _PATH_KINDS)
async def test_generic_branch_absence_echo_is_suppressed(rig: Rig, entry_path: str) -> None:
    """An unclassified event on a vanished path becomes `file_absent`; same rule."""
    await _quarantine(rig, entry_path)
    payloads_before = len(rig.publisher.payloads)

    await _inject(rig, rig.target, 0)

    assert len(rig.publisher.payloads) == payloads_before
    assert rig.mark_absent_calls == []
    assert _entry(rig).status == "quarantined"
    assert _suppressed_reasons(rig) == ["quarantined_by_agent"]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_path", _PATH_KINDS)
async def test_auto_restore_rule_does_not_undo_the_quarantine(rig: Rig, entry_path: str) -> None:
    await _quarantine(rig, entry_path)
    payloads_before = len(rig.publisher.payloads)
    rig.set_rule("auto_restore")

    await _inject(rig, rig.target, FAN_DELETE)

    assert not rig.target.exists()
    assert len(rig.publisher.payloads) == payloads_before
    assert _entry(rig).status == "quarantined"


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_path", _PATH_KINDS)
async def test_operator_restore_after_quarantine_returns_to_present(
    rig: Rig, entry_path: str
) -> None:
    from agent import commands

    await _quarantine(rig, entry_path)
    payloads_before = len(rig.publisher.payloads)
    valkey = AsyncMock()
    valkey.xadd = AsyncMock()

    await commands.handle_restore_file(
        command={"command_id": "cmd-restore", "event_id": 78, "path": str(rig.target)},
        baseline_engine=rig.baseline,
        journal=rig.journal,
        valkey_client=valkey,
        config=rig.config,
    )

    ack = json.loads(valkey.xadd.call_args[0][1]["data"])
    assert ack["status"] == "ok"
    assert rig.target.read_bytes() == _APPROVED
    st = rig.target.stat()
    assert (stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid) == (
        0o640, rig.known_entry.uid, rig.known_entry.gid,
    )
    entry = _entry(rig)
    assert entry.status == "present"
    assert entry.quarantine_action_id is None
    assert entry.hash == rig.known_entry.hash
    assert entry.content_b64 == rig.known_entry.content_b64

    await _inject(rig, rig.target, FAN_MOVED_TO)
    assert len(rig.publisher.payloads) == payloads_before


@pytest.mark.asyncio
async def test_failed_restore_keeps_the_entry_quarantined(rig: Rig) -> None:
    from agent import commands

    await _quarantine(rig, "operator")
    # An orphan temp file makes the restore fail (O_EXCL).
    Path(str(rig.target) + ".fim_restore_tmp").write_bytes(b"orphan")
    valkey = AsyncMock()
    valkey.xadd = AsyncMock()

    await commands.handle_restore_file(
        command={"command_id": "cmd-restore-fail", "event_id": 79, "path": str(rig.target)},
        baseline_engine=rig.baseline,
        journal=rig.journal,
        valkey_client=valkey,
        config=rig.config,
    )

    ack = json.loads(valkey.xadd.call_args[0][1]["data"])
    assert ack["status"] == "error"
    entry = _entry(rig)
    assert entry.status == "quarantined"
    assert select_restorable_content(entry) is not None


# ══════════════════════════════════════════════════════════════════════════
# Rehydration (crash window between the unlink and the marking)
# ══════════════════════════════════════════════════════════════════════════


def _crash_window(rig: Rig) -> str:
    """Journal pending + artifact present + source gone + entry still present."""
    event_id = str(uuid.uuid4())
    rig.journal.write_pending(event_id, str(rig.target), "quarantine")
    rig.store.quarantine(event_id, str(rig.target))
    assert not rig.target.exists()
    assert _entry(rig).status == "present"
    return event_id


@pytest.mark.asyncio
async def test_rehydrate_closes_the_crash_window(rig: Rig) -> None:
    event_id = _crash_window(rig)
    artifacts_before = sorted((rig.tmp_path / "quarantine").glob("*.fimq"))

    await rig.engine.rehydrate(rig.publisher)

    assert sorted((rig.tmp_path / "quarantine").glob("*.fimq")) == artifacts_before
    entry = _entry(rig)
    assert entry.status == "quarantined"
    assert entry.quarantine_action_id == event_id
    assert select_restorable_content(entry) is not None
    assert len(rig.publisher.payloads) == 1
    assert rig.publisher.payloads[0]["event_id"] == event_id
    assert rig.journal.load_pending() == []


@pytest.mark.asyncio
async def test_rehydrate_publish_failure_keeps_the_journal_pending(rig: Rig) -> None:
    event_id = _crash_window(rig)

    class _Failing:
        async def publish(self, payload: dict[str, Any]) -> None:
            raise ConnectionError("valkey down")

    await rig.engine.rehydrate(_Failing())  # type: ignore[arg-type]

    assert [e.event_id for e in rig.journal.load_pending()] == [event_id]
    assert _entry(rig).status == "quarantined"


# ══════════════════════════════════════════════════════════════════════════
# file_created branch
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_quarantine_without_previous_entry_records_a_null_quarantined_entry(
    rig: Rig,
) -> None:
    rig.set_rule("quarantine")
    fresh = rig.watch_dir / "fresh.sh"
    fresh.write_bytes(b"#!/bin/sh\nevil\n")

    await _inject(rig, fresh, FAN_CREATE)

    payload = rig.publisher.payloads[0]
    assert payload["action"] == "quarantine" and not payload.get("action_failed")
    assert not fresh.exists()
    entry = rig.baseline.read_entry(str(fresh))
    assert entry is not None
    assert entry.status == "quarantined"
    assert entry.hash is None and entry.content_b64 is None and entry.snapshots == []
    assert select_restorable_content(entry) is None
    assert rig.mark_absent_calls == []


@pytest.mark.asyncio
async def test_file_created_quarantine_keeps_the_previous_approved_content(rig: Rig) -> None:
    """Prior `present` entry + quarantine in the `file_created` branch: the entry
    keeps the approved content, not the quarantined file's."""
    rig.set_rule("quarantine")
    rig.target.write_bytes(_TAMPERED)

    await _inject(rig, rig.target, FAN_CREATE)

    assert not rig.target.exists()
    entry = _entry(rig)
    assert entry.status == "quarantined"
    assert entry.content_b64 == rig.known_entry.content_b64
    assert rig.mark_absent_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_path", _PATH_KINDS)
async def test_new_file_with_other_content_is_reported_and_never_overwrites(
    rig: Rig, entry_path: str
) -> None:
    await _quarantine(rig, entry_path)
    rig.set_rule("alert_only")
    payloads_before = len(rig.publisher.payloads)

    rig.target.write_bytes(b"something else entirely\n")
    await _inject(rig, rig.target, FAN_CREATE)

    assert len(rig.publisher.payloads) == payloads_before + 1
    assert rig.publisher.payloads[-1]["event_type"] == "file_created"
    entry = _entry(rig)
    assert entry.status == "quarantined"
    assert entry.hash == rig.known_entry.hash
    assert entry.content_b64 == rig.known_entry.content_b64


@pytest.mark.asyncio
async def test_create_then_delete_reports_the_creation_but_not_the_deletion(rig: Rig) -> None:
    """Accepted risk of RN-176, pinned so it cannot change without a decision."""
    await _quarantine(rig, "operator")
    rig.set_rule("alert_only")
    payloads_before = len(rig.publisher.payloads)

    rig.target.write_bytes(b"different\n")
    await _inject(rig, rig.target, FAN_CREATE)
    assert len(rig.publisher.payloads) == payloads_before + 1

    rig.target.unlink()
    await _inject(rig, rig.target, FAN_DELETE)

    assert len(rig.publisher.payloads) == payloads_before + 1
    assert _entry(rig).status == "quarantined"
    assert _suppressed_reasons(rig) == ["quarantined_by_agent"]


# ══════════════════════════════════════════════════════════════════════════
# Identical recreation (D-10)
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_path", _PATH_KINDS)
@pytest.mark.parametrize("mask", [FAN_CREATE, FAN_CLOSE_WRITE])
async def test_identical_recreation_returns_to_present_and_a_later_delete_is_reported(
    rig: Rig, entry_path: str, mask: int
) -> None:
    await _quarantine(rig, entry_path)
    rig.set_rule("alert_only")
    payloads_before = len(rig.publisher.payloads)

    rig.target.write_bytes(_APPROVED)  # default mode differs from the approved 0o640
    await _inject(rig, rig.target, mask)

    assert len(rig.publisher.payloads) == payloads_before
    entry = _entry(rig)
    assert entry.status == "present"
    assert entry.quarantine_action_id is None
    assert entry.hash == rig.known_entry.hash
    assert entry.content_b64 == rig.known_entry.content_b64
    assert entry.mode == rig.known_entry.mode  # approved metadata, not adopted from disk
    assert rig.mark_absent_calls == []

    rig.target.unlink()
    await _inject(rig, rig.target, FAN_DELETE)

    assert len(rig.publisher.payloads) == payloads_before + 1
    assert rig.publisher.payloads[-1]["event_type"] == "file_deleted"


@pytest.mark.asyncio
async def test_symlink_with_matching_hash_does_not_trigger_the_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`file_created` requires the same object type: a symlink whose target string
    hashes like the approved regular content is reported, not adopted."""
    link_target = "/nowhere/approved-target"
    rig = _build_rig(tmp_path, approved=link_target.encode(), monkeypatch=monkeypatch)
    await _quarantine(rig, "operator")
    payloads_before = len(rig.publisher.payloads)

    os.symlink(link_target, rig.target)
    await _inject(rig, rig.target, FAN_CREATE)

    assert len(rig.publisher.payloads) == payloads_before + 1
    assert _entry(rig).status == "quarantined"


# ══════════════════════════════════════════════════════════════════════════
# Rule changes and genuine absences
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rule_switch_to_auto_restore_recovers_a_quarantined_path(rig: Rig) -> None:
    await _quarantine(rig, "automatic")
    rig.set_rule("auto_restore")
    payloads_before = len(rig.publisher.payloads)

    rig.target.write_bytes(b"altered again\n")
    await _inject(rig, rig.target, FAN_CLOSE_WRITE)

    assert len(rig.publisher.payloads) == payloads_before + 1
    payload = rig.publisher.payloads[-1]
    assert payload["action"] == "auto_restore"
    assert not payload.get("action_failed")
    assert rig.target.read_bytes() == _APPROVED
    entry = _entry(rig)
    assert entry.status == "present" and entry.quarantine_action_id is None

    # The restore's own echoes settle within a bounded number of iterations.
    for mask in (FAN_MOVED_TO, FAN_CLOSE_WRITE, FAN_MOVED_TO):
        await _inject(rig, rig.target, mask)
    assert len(rig.publisher.payloads) == payloads_before + 1


@pytest.mark.asyncio
async def test_genuine_absence_is_still_reported_and_marked_absent(rig: Rig) -> None:
    rig.target.unlink()

    await _inject(rig, rig.target, FAN_DELETE)

    assert len(rig.publisher.payloads) == 1
    assert rig.publisher.payloads[0]["event_type"] == "file_deleted"
    assert rig.mark_absent_calls == [str(rig.target)]
    assert _entry(rig).status == "absent"


# ══════════════════════════════════════════════════════════════════════════
# Failures and vocabulary
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_path", _PATH_KINDS)
async def test_baseline_mark_failed_keeps_the_artifact_and_fails_the_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_path: str
) -> None:
    rig = _build_rig(tmp_path, baseline_cls=_FailingMarkBaseline, monkeypatch=monkeypatch)
    rig.target.write_bytes(_TAMPERED)

    if entry_path == "automatic":
        rig.set_rule("quarantine")
        await _inject(rig, rig.target, FAN_CLOSE_WRITE)
        payload = rig.publisher.payloads[0]
        assert payload["action_failed"] is True
        assert payload["action_error"] == "baseline_mark_failed"
        event_id = payload["event_id"]
    else:
        event_id = str(uuid.uuid4())
        ack = await _operator_quarantine(rig, agent_event_id=event_id)
        assert ack["status"] == "error"
        assert ack["error"] == "baseline_mark_failed"

    assert rig.store.artifact_path(event_id, str(rig.target)).exists()
    assert not rig.target.exists()
    entry = rig.journal._read(event_id)
    assert entry is not None
    assert entry.state == "failed"
    assert entry.error == "baseline_mark_failed"


@pytest.mark.asyncio
async def test_operator_command_without_agent_event_id_does_nothing(rig: Rig) -> None:
    rig.target.write_bytes(_TAMPERED)

    ack = await _operator_quarantine(rig, agent_event_id=None)

    assert ack["status"] == "error"
    assert ack["error"] == "quarantine_identity_missing"
    assert rig.target.read_bytes() == _TAMPERED
    assert rig.journal_files() == 0
    assert list((rig.tmp_path / "quarantine").glob("*.fimq")) == []
    assert _entry(rig).status == "present"


@pytest.mark.asyncio
async def test_unexpected_exception_does_not_leak_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _build_rig(tmp_path, store_cls=_ExplodingStore, monkeypatch=monkeypatch)
    rig.target.write_bytes(_TAMPERED)
    event_id = str(uuid.uuid4())

    ack = await _operator_quarantine(rig, agent_event_id=event_id)

    assert ack["status"] == "error"
    assert ack["error"] == "quarantine_failed"
    assert str(rig.target) not in json.dumps(ack)
    entry = rig.journal._read(event_id)
    assert entry is not None and entry.state == "failed"
    assert entry.error == "quarantine_failed"
    assert str(rig.target) not in (entry.error or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_path", _PATH_KINDS)
async def test_hardlink_reports_the_same_cause_on_both_paths(rig: Rig, entry_path: str) -> None:
    alias = rig.watch_dir / "alias.conf"
    os.link(rig.target, alias)
    rig.target.write_bytes(_TAMPERED)

    if entry_path == "automatic":
        rig.set_rule("quarantine")
        await _inject(rig, rig.target, FAN_CLOSE_WRITE)
        payload = rig.publisher.payloads[0]
        assert payload["action_failed"] is True
        assert payload["action_error"] == "hardlink_not_isolatable"
    else:
        ack = await _operator_quarantine(rig, agent_event_id=str(uuid.uuid4()))
        assert ack["status"] == "error"
        assert ack["error"] == "hardlink_not_isolatable"
    assert rig.target.exists() and alias.exists()


@pytest.mark.asyncio
async def test_quarantine_and_record_does_not_close_the_journal(rig: Rig) -> None:
    event_id = str(uuid.uuid4())
    rig.target.write_bytes(_TAMPERED)

    outcome = quarantine_and_record(
        store=rig.store,
        baseline=rig.baseline,
        journal=rig.journal,
        action_id=event_id,
        path=str(rig.target),
    )

    assert outcome.error is None and outcome.artifact is not None
    entry = rig.journal._read(event_id)
    assert entry is not None and entry.state == "pending"


# ══════════════════════════════════════════════════════════════════════════
# Units: BaselineEngine and JournalManager
# ══════════════════════════════════════════════════════════════════════════


def test_ensure_pending_does_not_touch_an_existing_entry(rig: Rig) -> None:
    rig.journal.write_pending("evt-1", "/p", "quarantine")
    first = rig.journal._read("evt-1")
    assert first is not None

    rig.journal.ensure_pending("evt-1", "/other", "auto_restore")

    again = rig.journal._read("evt-1")
    assert again == first
    assert again.created_at == first.created_at and again.path == "/p"


def test_ensure_pending_creates_a_missing_entry(rig: Rig) -> None:
    rig.journal.ensure_pending("evt-new", "/p", "quarantine")

    entry = rig.journal._read("evt-new")
    assert entry is not None
    assert (entry.state, entry.action, entry.path) == ("pending", "quarantine", "/p")


def test_mark_quarantined_preserves_content_and_snapshots(rig: Rig) -> None:
    path = str(rig.target)
    rig.target.write_bytes(b"v2\n")
    assert rig.baseline.add_snapshot(path)
    rig.baseline.write_entry(path)
    rig.target.write_bytes(b"v3\n")
    assert rig.baseline.add_snapshot(path)
    rig.baseline.write_entry(path)
    before = _entry(rig)
    assert len(before.snapshots) == 2

    marked = rig.baseline.mark_quarantined(path, "evt-q")

    after = _entry(rig)
    assert after == marked
    assert after.status == "quarantined" and after.quarantine_action_id == "evt-q"
    assert after.snapshots == before.snapshots
    assert (after.hash, after.content_b64, after.mode, after.uid, after.gid) == (
        before.hash, before.content_b64, before.mode, before.uid, before.gid,
    )
    assert select_restorable_content(after) is not None


def test_second_quarantine_updates_only_the_action_id(rig: Rig) -> None:
    path = str(rig.target)
    first = rig.baseline.mark_quarantined(path, "evt-1")

    second = rig.baseline.mark_quarantined(path, "evt-2")

    assert second.quarantine_action_id == "evt-2"
    assert dataclasses.replace(second, quarantine_action_id="evt-1", captured_at=first.captured_at) == first


def test_add_snapshot_operates_on_a_quarantined_entry(rig: Rig) -> None:
    path = str(rig.target)
    rig.baseline.mark_quarantined(path, "evt-1")

    assert rig.baseline.add_snapshot(path) is True
    assert rig.baseline.add_snapshot(path) is False  # dedup, same as present
    assert len(_entry(rig).snapshots) == 1


def test_clear_quarantine_only_changes_status_and_action_id(rig: Rig) -> None:
    path = str(rig.target)
    rig.baseline.mark_quarantined(path, "evt-1")
    quarantined = _entry(rig)
    rig.target.unlink()  # it must not read the disk

    cleared = rig.baseline.clear_quarantine(path)

    assert cleared is not None
    assert cleared == dataclasses.replace(
        quarantined, status="present", quarantine_action_id=None
    )
    assert _entry(rig) == cleared


def test_clear_quarantine_is_a_noop_for_other_states(rig: Rig) -> None:
    path = str(rig.target)
    before = _entry(rig).to_json_bytes()

    assert rig.baseline.clear_quarantine(path) is None
    assert _entry(rig).to_json_bytes() == before
    assert rig.baseline.clear_quarantine(str(rig.watch_dir / "unknown")) is None


def test_update_from_command_from_quarantined_ends_present_without_the_mark(rig: Rig) -> None:
    path = str(rig.target)
    rig.baseline.mark_quarantined(path, "evt-q")
    new_bytes = b"approved candidate\n"
    rig.target.write_bytes(new_bytes)
    digest = hashlib.sha256(new_bytes).hexdigest()
    assert rig.baseline.stage_approval_candidate("evt-approve", path, digest, "present")

    entry = rig.baseline.update_from_command(path, digest, "present", "evt-approve")

    assert entry.status == "present"
    assert entry.quarantine_action_id is None
    assert entry.hash == digest
    assert _entry(rig).quarantine_action_id is None


def test_entry_written_before_the_new_key_reads_as_null(rig: Rig) -> None:
    path = str(rig.target)
    legacy = dataclasses.asdict(_entry(rig))
    legacy.pop("quarantine_action_id")
    blob = _encrypt(rig.baseline._key, json.dumps(legacy).encode())
    _atomic_write(_entry_path(rig.baseline._baseline_dir, path), blob)

    entry = _entry(rig)

    assert entry.quarantine_action_id is None
    assert entry.status == "present"
