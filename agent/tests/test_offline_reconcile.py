"""D80/RN-174: offline reconcile on start (Change 62).

Unit tests of `BaselineEngine.reconcile_on_start` plus end-to-end tests that emit
its findings through a real `FanotifyDetector` and a real `DecisionEngine`.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.baseline import (
    BaselineEngine,
    BaselineIntegrityError,
    OfflineFinding,
    _candidate_path,
    _entry_path,
)
from agent.config import AgentConfig, StorageConfig
from agent.decision import DecisionEngine
from agent.detector import FanotifyDetector, FanotifyEvent
from agent.journal import JournalManager
from agent.rules import RulesCache


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def root(tmp_path: Path) -> Path:
    r = tmp_path / "watched"
    r.mkdir()
    return r


@pytest.fixture()
def engine(tmp_path: Path, root: Path) -> BaselineEngine:
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    storage = StorageConfig(
        baseline_dir=str(tmp_path / "baseline"),
        queue_dir=str(tmp_path / "queue"),
        journal_dir=str(tmp_path / "journal"),
        secrets_dir=str(secrets),
        certs_dir=str(tmp_path / "certs"),
    )
    cfg = AgentConfig(
        agent_id="agent-offline",
        backend_url="http://localhost:8000",
        valkey_url="redis://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=[str(root)],
        storage=storage,
    )
    return BaselineEngine(cfg, os.urandom(32))


def _plan(engine: BaselineEngine, root: Path):
    return engine.reconcile_on_start([str(root)], [str(root)])


def _classes(plan) -> dict[str, str]:
    return {f.path: f.event_class for f in plan.findings}


def _blobs(engine: BaselineEngine) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for d in (engine._baseline_dir, engine._candidate_dir):
        for f in sorted(d.rglob("*")):
            if f.is_file():
                out[str(f)] = f.read_bytes()
    return out


def _stage_candidate(engine: BaselineEngine, path: Path, event_id: str = "ev-1") -> None:
    h = _sha(path.read_bytes())
    assert engine.stage_approval_candidate(event_id, str(path), h, "present")


# ── 3.9 reconcile_on_start ────────────────────────────────────────────────────

def test_modified_file_is_reported(engine: BaselineEngine, root: Path) -> None:
    f = root / "a.txt"
    f.write_text("v1")
    engine.init_scan([str(root)])
    f.write_text("v2")

    plan = _plan(engine, root)

    assert _classes(plan) == {str(f): "file_modified"}


def test_deleted_file_is_reported(engine: BaselineEngine, root: Path) -> None:
    f = root / "a.txt"
    f.write_text("v1")
    engine.init_scan([str(root)])
    f.unlink()

    assert _classes(_plan(engine, root)) == {str(f): "file_deleted"}


def test_absent_entry_that_reappears_is_created(engine: BaselineEngine, root: Path) -> None:
    f = root / "a.txt"
    f.write_text("v1")
    engine.init_scan([str(root)])
    engine.mark_absent(str(f))

    assert _classes(_plan(engine, root)) == {str(f): "file_created"}


def test_absent_entry_still_missing_yields_nothing(engine: BaselineEngine, root: Path) -> None:
    f = root / "a.txt"
    f.write_text("v1")
    engine.init_scan([str(root)])
    f.unlink()
    engine.mark_absent(str(f))

    plan = _plan(engine, root)

    assert plan.findings == []


def test_quarantined_entry_with_missing_file_is_not_reported(
    engine: BaselineEngine, root: Path
) -> None:
    """D82/RN-176: the absence is the recorded consequence of the agent's own
    quarantine; no finding and the entry is not mutated."""
    f = root / "a.txt"
    f.write_text("v1")
    engine.init_scan([str(root)])
    f.unlink()
    engine.mark_quarantined(str(f), "evt-q1")
    before = _blobs(engine)

    plan = _plan(engine, root)

    assert plan.findings == []
    assert _blobs(engine) == before
    entry = engine.read_entry(str(f))
    assert entry is not None and entry.status == "quarantined"


def test_present_entry_with_missing_file_still_reports_deleted(
    engine: BaselineEngine, root: Path
) -> None:
    """Counterpart of the quarantine guard: a genuine deletion keeps reporting."""
    quarantined, present = root / "q.txt", root / "p.txt"
    for f in (quarantined, present):
        f.write_text("v1")
    engine.init_scan([str(root)])
    engine.mark_quarantined(str(quarantined), "evt-q1")
    quarantined.unlink()
    present.unlink()

    assert _classes(_plan(engine, root)) == {str(present): "file_deleted"}


def test_new_file_without_entry_in_initialized_root_is_created(
    engine: BaselineEngine, root: Path
) -> None:
    (root / "a.txt").write_text("v1")
    engine.init_scan([str(root)])
    new = root / "sub" / "new.txt"
    new.parent.mkdir()
    new.write_text("fresh")

    assert _classes(_plan(engine, root)) == {str(new): "file_created"}


def test_unchanged_files_are_counted(engine: BaselineEngine, root: Path) -> None:
    (root / "a.txt").write_text("v1")
    (root / "b.txt").write_text("v2")
    engine.init_scan([str(root)])

    plan = _plan(engine, root)

    assert plan.findings == []
    assert plan.unchanged == 2


def test_symlink_to_regular_type_change_is_modified(engine: BaselineEngine, root: Path) -> None:
    target = root / "target.txt"
    target.write_text("same")
    link = root / "link"
    link.symlink_to(target)
    engine.init_scan([str(root)])
    # Replace the symlink by a regular file with the hash of the link string.
    link.unlink()
    link.write_text(str(target))

    plan = _plan(engine, root)

    assert _classes(plan)[str(link)] == "file_modified"


def test_regular_to_symlink_type_change_is_modified(engine: BaselineEngine, root: Path) -> None:
    f = root / "f"
    f.write_text("x")
    engine.init_scan([str(root)])
    f.unlink()
    f.symlink_to("/nonexistent/elsewhere")

    assert _classes(_plan(engine, root))[str(f)] == "file_modified"


def test_symlink_retarget_is_modified(engine: BaselineEngine, root: Path) -> None:
    link = root / "link"
    link.symlink_to("/etc/passwd")
    engine.init_scan([str(root)])
    link.unlink()
    link.symlink_to("/etc/shadow")

    assert _classes(_plan(engine, root)) == {str(link): "file_modified"}


def test_uninitialized_root_has_no_findings(engine: BaselineEngine, root: Path) -> None:
    f = root / "a.txt"
    f.write_text("v1")
    engine.init_scan([str(root)])
    f.write_text("v2")
    (root / "new.txt").write_text("n")

    plan = engine.reconcile_on_start([str(root)], [])

    assert plan.findings == []


def test_invalid_entry_counts_error_and_continues(engine: BaselineEngine, root: Path) -> None:
    bad, good = root / "a.txt", root / "b.txt"
    bad.write_text("1")
    good.write_text("1")
    engine.init_scan([str(root)])
    good.write_text("2")
    real_read = engine.read_entry

    def flaky(path: str):
        if path == str(bad):
            raise BaselineIntegrityError(path)
        return real_read(path)

    with patch.object(engine, "read_entry", side_effect=flaky):
        plan = _plan(engine, root)

    assert plan.errors == 1
    assert _classes(plan) == {str(good): "file_modified"}


def test_findings_are_sorted_and_deduplicated(engine: BaselineEngine, root: Path) -> None:
    for n in ("c", "a", "b"):
        (root / n).write_text("1")
    engine.init_scan([str(root)])
    for n in ("c", "a", "b"):
        (root / n).write_text("2")

    plan = engine.reconcile_on_start([str(root), str(root)], [str(root)])

    assert [f.path for f in plan.findings] == [str(root / n) for n in ("a", "b", "c")]


def test_reconcile_does_not_modify_any_blob(engine: BaselineEngine, root: Path) -> None:
    mod, dele, absent = root / "mod", root / "del", root / "abs"
    for f in (mod, dele, absent):
        f.write_text("1")
    engine.init_scan([str(root)])
    engine.mark_absent(str(absent))
    mod.write_text("2")
    _stage_candidate(engine, mod)
    dele.unlink()
    (root / "new").write_text("n")
    before = _blobs(engine)

    plan = _plan(engine, root)

    assert _classes(plan) == {
        str(dele): "file_deleted",
        str(absent): "file_created",
        str(root / "new"): "file_created",
    }
    assert plan.suppressed_already_reported == 1
    assert _blobs(engine) == before


# ── 3.10 suppression of an already reported modification ─────────────────────

def test_candidate_with_same_hash_suppresses_modification(
    engine: BaselineEngine, root: Path
) -> None:
    f = root / "a.txt"
    f.write_text("v1")
    engine.init_scan([str(root)])
    f.write_text("v2")
    _stage_candidate(engine, f)

    plan = _plan(engine, root)

    assert plan.findings == []
    assert plan.suppressed_already_reported == 1


def test_candidate_with_other_hash_does_not_suppress(engine: BaselineEngine, root: Path) -> None:
    f = root / "a.txt"
    f.write_text("v1")
    engine.init_scan([str(root)])
    f.write_text("v2")
    _stage_candidate(engine, f)
    f.write_text("v3")

    plan = _plan(engine, root)

    assert _classes(plan) == {str(f): "file_modified"}
    assert plan.suppressed_already_reported == 0


def test_unreadable_candidate_does_not_suppress(engine: BaselineEngine, root: Path) -> None:
    f = root / "a.txt"
    f.write_text("v1")
    engine.init_scan([str(root)])
    f.write_text("v2")
    _stage_candidate(engine, f)
    cp = _candidate_path(engine._candidate_dir, str(f))
    data = bytearray(cp.read_bytes())
    data[-1] ^= 0xFF
    cp.write_bytes(bytes(data))

    plan = _plan(engine, root)

    assert _classes(plan) == {str(f): "file_modified"}
    assert engine.read_approval_candidate(str(f)) is None
    assert cp.exists()  # reading never deletes the candidate


def test_candidate_with_same_hash_does_not_suppress_deleted_or_created(
    engine: BaselineEngine, root: Path
) -> None:
    gone, reborn = root / "gone", root / "reborn"
    gone.write_text("1")
    reborn.write_text("1")
    engine.init_scan([str(root)])
    _stage_candidate(engine, gone)  # same hash as the baseline's
    gone.unlink()
    engine.mark_absent(str(reborn))
    _stage_candidate(engine, reborn)

    plan = _plan(engine, root)

    assert _classes(plan) == {str(gone): "file_deleted", str(reborn): "file_created"}
    assert plan.suppressed_already_reported == 0


def test_candidate_object_type_mismatch_does_not_suppress(
    engine: BaselineEngine, root: Path
) -> None:
    f = root / "f"
    f.write_text("x")
    engine.init_scan([str(root)])
    f.write_text("y")
    _stage_candidate(engine, f)
    # Same hash as the candidate's content cannot be a symlink hash; use a
    # candidate recorded as a symlink for a path that is now a regular file.
    cp = _candidate_path(engine._candidate_dir, str(f))
    cand = engine.read_approval_candidate(str(f))
    assert cand is not None
    cand.symlink_target = "/somewhere"
    import dataclasses
    import json

    from agent.baseline import _atomic_write, _encrypt

    _atomic_write(cp, _encrypt(engine._key, json.dumps(dataclasses.asdict(cand)).encode()))

    assert _classes(_plan(engine, root)) == {str(f): "file_modified"}


# ── end-to-end through the real detector ──────────────────────────────────────

def _build_detector(
    tmp_path: Path,
    engine: BaselineEngine,
    root: Path,
    *,
    rules: list[dict] | None = None,
    decision: object | None = None,
):
    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0
    if decision is None:
        journal_dir = tmp_path / "jdir"
        journal_dir.mkdir(exist_ok=True)
        qdir = tmp_path / "qdir"
        qdir.mkdir(exist_ok=True)
        cache = RulesCache(tmp_path / "rules-state.json")
        if rules:
            cache.load({"rules": rules})
        decision = DecisionEngine(
            rules=cache,
            journal=JournalManager(journal_dir, shared_secret=b"test-secret-32-bytes-xxxxxxxxxx!"),
            baseline=engine,
            quarantine_dir=qdir,
        )
    detector = FanotifyDetector(
        agent_id="agent-offline",
        watch_paths=[str(root)],
        baseline=engine,
        publisher=publisher,
        stop_event=asyncio.Event(),
        decision_engine=decision,
    )
    return detector, publisher


async def _restart(engine: BaselineEngine, detector: FanotifyDetector, root: Path):
    """Simulate the start-up reconcile and emit its findings."""
    plan = await asyncio.to_thread(engine.reconcile_on_start, [str(root)], [str(root)])
    for finding in plan.findings:
        await detector.emit_offline(finding)
    return plan


def _published(publisher: MagicMock) -> list[dict]:
    return [c.args[0] for c in publisher.publish.call_args_list]


@pytest.mark.asyncio
async def test_offline_modification_emits_one_event(
    tmp_path: Path, engine: BaselineEngine, root: Path
) -> None:
    f = root / "a.txt"
    f.write_text("one")
    engine.init_scan([str(root)])
    h1, h2 = _sha(b"one"), _sha(b"two")
    f.write_text("two")
    detector, publisher = _build_detector(tmp_path, engine, root)

    await _restart(engine, detector, root)

    events = _published(publisher)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "file_modified"
    assert ev["detected_offline"] is True
    assert ev["hash_detected"] == h2
    assert ev["hash_expected"] == h1
    assert ev["process_pid"] is None
    assert ev["process_uid"] is None
    assert ev["process_exe"] is None
    # BUG-03: the active baseline hash is not replaced by unapproved content.
    assert engine.read_entry(str(f)).hash == h1


@pytest.mark.asyncio
async def test_offline_deletion_emits_one_event_and_marks_absent(
    tmp_path: Path, engine: BaselineEngine, root: Path
) -> None:
    f = root / "a.txt"
    f.write_text("one")
    engine.init_scan([str(root)])
    f.unlink()
    detector, publisher = _build_detector(tmp_path, engine, root)

    await _restart(engine, detector, root)

    events = _published(publisher)
    assert len(events) == 1
    assert events[0]["event_type"] == "file_deleted"
    assert events[0]["detected_offline"] is True
    assert engine.read_entry(str(f)).status == "absent"


@pytest.mark.asyncio
async def test_identical_recreation_after_reported_offline_deletion_is_created(
    tmp_path: Path, engine: BaselineEngine, root: Path
) -> None:
    f = root / "a.txt"
    f.write_text("one")
    engine.init_scan([str(root)])
    f.unlink()
    detector, publisher = _build_detector(tmp_path, engine, root)
    await _restart(engine, detector, root)
    publisher.publish.reset_mock()

    f.write_text("one")  # identical content
    await detector._process_event(
        FanotifyEvent(path=str(f), pid=7, uid=0, exe="/bin/touch", timestamp="2026-01-01T00:00:00+00:00"),
        forced_class="file_created",
    )

    events = _published(publisher)
    assert len(events) == 1
    assert events[0]["event_type"] == "file_created"
    assert events[0]["detected_offline"] is False


@pytest.mark.asyncio
async def test_offline_creation_emits_created_and_baselines_file(
    tmp_path: Path, engine: BaselineEngine, root: Path
) -> None:
    (root / "a.txt").write_text("one")
    engine.init_scan([str(root)])
    new = root / "new.txt"
    new.write_text("fresh")
    detector, publisher = _build_detector(tmp_path, engine, root)

    await _restart(engine, detector, root)

    events = _published(publisher)
    assert len(events) == 1
    assert events[0]["event_type"] == "file_created"
    assert events[0]["detected_offline"] is True
    assert engine.read_entry(str(new)).status == "present"


@pytest.mark.asyncio
async def test_absent_entry_reappearing_emits_created(
    tmp_path: Path, engine: BaselineEngine, root: Path
) -> None:
    f = root / "a.txt"
    f.write_text("one")
    engine.init_scan([str(root)])
    engine.mark_absent(str(f))
    detector, publisher = _build_detector(tmp_path, engine, root)

    await _restart(engine, detector, root)

    events = _published(publisher)
    assert [e["event_type"] for e in events] == ["file_created"]
    assert events[0]["detected_offline"] is True


@pytest.mark.asyncio
async def test_already_reported_modification_is_not_reemitted(
    tmp_path: Path, engine: BaselineEngine, root: Path
) -> None:
    f = root / "a.txt"
    f.write_text("one")
    engine.init_scan([str(root)])
    f.write_text("two")
    detector, publisher = _build_detector(tmp_path, engine, root)
    await _restart(engine, detector, root)
    assert len(_published(publisher)) == 1
    publisher.publish.reset_mock()

    plan = await _restart(engine, detector, root)  # second start, nothing approved

    assert _published(publisher) == []
    assert plan.suppressed_already_reported == 1

    f.write_text("three")
    await _restart(engine, detector, root)  # third start, new content
    events = _published(publisher)
    assert [e["event_type"] for e in events] == ["file_modified"]
    assert events[0]["hash_detected"] == _sha(b"three")


@pytest.mark.asyncio
async def test_reconcile_publishes_only_through_decision_engine(
    tmp_path: Path, engine: BaselineEngine, root: Path
) -> None:
    for n in ("a", "b"):
        (root / n).write_text("1")
    engine.init_scan([str(root)])
    (root / "a").write_text("2")
    (root / "b").unlink()
    order: list[str] = []
    marker = {"marker": True, "action": None}
    decision = MagicMock()
    decision.evaluate_and_act.side_effect = lambda change: (
        marker,
        lambda: order.append("commit"),
    )
    detector, publisher = _build_detector(tmp_path, engine, root, decision=decision)
    publisher.publish.side_effect = lambda payload: order.append("publish")

    await _restart(engine, detector, root)

    assert publisher.publish.call_count == decision.evaluate_and_act.call_count == 2
    assert all(c.args[0] is marker for c in publisher.publish.call_args_list)
    assert order == ["publish", "commit", "publish", "commit"]


@pytest.mark.asyncio
async def test_auto_restore_rule_applies_to_offline_modification(
    tmp_path: Path, engine: BaselineEngine, root: Path
) -> None:
    f = root / "a.txt"
    f.write_text("one")
    engine.init_scan([str(root)])
    f.write_text("tampered")
    detector, publisher = _build_detector(
        tmp_path, engine, root, rules=[{"pattern": str(root / "*"), "action": "auto_restore"}]
    )

    await _restart(engine, detector, root)

    events = _published(publisher)
    assert len(events) == 1
    assert events[0]["action"] == "auto_restore"
    assert events[0]["detected_offline"] is True
    assert f.read_text() == "one"


@pytest.mark.asyncio
async def test_live_event_keeps_process_context_and_not_offline(
    tmp_path: Path, engine: BaselineEngine, root: Path
) -> None:
    f = root / "a.txt"
    f.write_text("one")
    engine.init_scan([str(root)])
    f.write_text("two")
    detector, publisher = _build_detector(tmp_path, engine, root)

    await detector._process_event(
        FanotifyEvent(path=str(f), pid=4242, uid=1000, exe="/usr/bin/vim", timestamp="2026-01-01T00:00:00+00:00"),
        forced_class="close_write",
    )

    ev = _published(publisher)[0]
    assert ev["detected_offline"] is False
    assert ev["process_pid"] == 4242
    assert ev["process_uid"] == 1000
    assert ev["process_exe"] == "/usr/bin/vim"


# ── 5.x start-up helper ───────────────────────────────────────────────────────

def _cfg(root: Path) -> SimpleNamespace:
    return SimpleNamespace(watch_paths=[str(root)])


@pytest.mark.asyncio
async def test_run_offline_reconcile_failure_is_logged_not_raised(root: Path) -> None:
    from agent.__main__ import _run_offline_reconcile
    from agent.state import AgentState

    engine = MagicMock()
    engine.reconcile_on_start.side_effect = RuntimeError("boom")
    detector = MagicMock()
    detector.emit_offline = AsyncMock()

    with patch("agent.__main__.log") as log:
        await _run_offline_reconcile(engine, detector, AgentState(initialized_roots=[str(root)]), _cfg(root))

    log.error.assert_called_once_with("baseline.reconcile.failed", error="RuntimeError")
    detector.emit_offline.assert_not_called()


@pytest.mark.asyncio
async def test_run_offline_reconcile_logs_counts(root: Path) -> None:
    from agent.__main__ import _run_offline_reconcile
    from agent.baseline import ReconcilePlan
    from agent.state import AgentState

    plan = ReconcilePlan(
        findings=[
            OfflineFinding(str(root / "a"), "file_deleted"),
            OfflineFinding(str(root / "b"), "file_modified"),
            OfflineFinding(str(root / "c"), "file_created"),
        ],
        unchanged=4,
        suppressed_already_reported=2,
        errors=1,
    )
    engine = MagicMock()
    engine.reconcile_on_start.return_value = plan
    detector = MagicMock()
    detector.emit_offline = AsyncMock()

    with patch("agent.__main__.log") as log:
        await _run_offline_reconcile(engine, detector, AgentState(initialized_roots=[str(root)]), _cfg(root))

    assert [c.args[0].event_class for c in detector.emit_offline.call_args_list] == [
        "file_deleted",
        "file_modified",
        "file_created",
    ]
    args, kwargs = log.info.call_args
    assert args == ("baseline.reconcile.complete",)
    assert (kwargs["deleted"], kwargs["modified"], kwargs["created"]) == (1, 1, 1)
    assert kwargs["suppressed_already_reported"] == 2
    assert kwargs["unchanged"] == 4
    assert kwargs["errors"] == 1
    assert "duration_ms" in kwargs


@pytest.mark.asyncio
async def test_start_sequence_rehydrate_then_reconcile_then_detector(root: Path) -> None:
    """5.5: `main` is not testable without a refactor; the order is covered by the
    diff location of `_run_offline_reconcile` in `main` (after `rehydrate`, before
    `gather`). Here we only assert that emissions precede anything the caller
    does afterwards, i.e. `_run_offline_reconcile` completes all emissions before
    returning (so `gather(detector.start())` cannot interleave with them)."""
    from agent.__main__ import _run_offline_reconcile
    from agent.baseline import ReconcilePlan
    from agent.state import AgentState

    order: list[str] = []
    engine = MagicMock()
    engine.reconcile_on_start.return_value = ReconcilePlan(
        findings=[OfflineFinding(str(root / "a"), "file_deleted")]
    )
    detector = MagicMock()

    async def emit(_finding) -> None:
        await asyncio.sleep(0)
        order.append("emit")

    detector.emit_offline = emit
    await _run_offline_reconcile(engine, detector, AgentState(initialized_roots=[str(root)]), _cfg(root))
    order.append("start")

    assert order == ["emit", "start"]
