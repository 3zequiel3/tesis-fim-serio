"""
Phase B of `ingest-batched-persistence` (amplification of 2026-10-03 of D87/RN-181):
consumer-level tests of the batched persistence through `_process_batch`.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import structlog
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, select

import app.modules.events.consumer as consumer_mod
import app.modules.events.service as service_mod
from app.modules.events.models import Event, EventStatus
from app.modules.events.service import InvalidTransitionError

from tests.test_ingest_drain_resilience import (  # noqa: F401  (fixtures + helpers)
    _msg,
    _patch_engines,
    _payload,
    _pipeline_client,
    agent,
    mem_engine,
    shared_secret,
)


def _rows(engine) -> list[Event]:
    with Session(engine) as session:
        return list(session.exec(select(Event).order_by(Event.id)).all())


def _acked_event_ids(executed) -> list[str]:
    return [json.loads(op[2]["data"])["event_id"] for pipe in executed for op in pipe if op[0] == "xadd"]


# ── 5.9 RateLimiter.refund ────────────────────────────────────────────────────

def test_refund_returns_tokens_without_exceeding_burst_or_creating_state() -> None:
    limiter = consumer_mod._RateLimiter(rate_per_s=1.0, burst=10, clock=lambda: 0.0)
    for _ in range(4):
        assert limiter.check("a")
    limiter.refund("a", 3)
    assert limiter._buckets["a"].tokens == 9
    limiter.refund("a", 50)
    assert limiter._buckets["a"].tokens == 10  # never above burst
    limiter.refund("unknown", 5)
    assert "unknown" not in limiter._buckets


# ── 5.19 chain through _process_batch ─────────────────────────────────────────

async def test_two_events_of_the_same_path_in_a_batch_form_a_chain(mem_engine, agent, shared_secret) -> None:
    messages = [(f"{i}-0", _msg(_payload(shared_secret, path="/etc/x", seq=i))) for i in range(2)]
    client, pipelines, executed = _pipeline_client(messages)
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2:
        await consumer_mod._process_batch(client, ">")
    first, second = _rows(mem_engine)
    assert first.status == EventStatus.superseded
    assert (second.status, second.parent_event_id) == (EventStatus.pending, first.id)
    assert len(pipelines) == 1 and [op[0] for op in executed[0]] == ["xadd", "xadd", "xack"]
    assert executed[0][-1][3] == ("0-0", "1-0")


# ── 5.20 deterministic error: only the offending event stays in the PEL ───────

async def test_integrity_error_caused_by_the_middle_event_leaves_only_that_event(
    mem_engine, agent, shared_secret,
) -> None:
    payloads = [_payload(shared_secret, path=f"/f{i}", seq=i) for i in range(3)]
    messages = [(f"{i}-0", _msg(p)) for i, p in enumerate(payloads)]
    original_ingest = consumer_mod._ingest

    def poisoned(payload, received_at, detected_at, agent_id):
        if payload["path"] == "/f1":
            raise IntegrityError("INSERT", {}, Exception("value too long"))
        return original_ingest(payload, received_at, detected_at, agent_id)

    client, _p, executed = _pipeline_client(messages)
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, structlog.testing.capture_logs() as cap, patch.object(consumer_mod, "log", structlog.get_logger()), \
            patch.object(consumer_mod, "_ingest_batch", side_effect=IntegrityError("INSERT", {}, Exception("x"))), \
            patch.object(consumer_mod, "_ingest", poisoned):
        await consumer_mod._process_batch(client, ">")

    assert any(r["event"] == "consumer.batch_replayed_per_event" and r["candidates"] == 3 for r in cap)
    assert [r.event_id for r in _rows(mem_engine)] == [payloads[0]["event_id"], payloads[2]["event_id"]]
    assert executed[0][-1][3] == ("0-0", "2-0")
    assert set(_acked_event_ids(executed)) == {payloads[0]["event_id"], payloads[2]["event_id"]}


# ── 5.21 effects wait for the COMMIT and keep the stream order ────────────────

class _ScriptedLimiter:
    def __init__(self, answers: list[bool]) -> None:
        self._answers = list(answers)

    def check(self, key: str) -> bool:
        return self._answers.pop(0)

    def refund(self, key: str, n: int) -> None:
        pass

    def seconds_until_available(self, key: str) -> float:
        return 1.0


async def test_effects_follow_the_commit_in_stream_order(mem_engine, agent, shared_secret) -> None:
    order: list[str] = []
    messages = [
        ("0-0", _msg(_payload(shared_secret, path="/a", seq=0))),  # persisted
        ("1-0", _msg(_payload(shared_secret, path="/b", seq=1))),  # rate limited
        ("2-0", _msg(_payload(shared_secret, path="/a", seq=2))),  # supersedes /a -> invalid transition
    ]
    original_commit = Session.commit
    original_reject = consumer_mod._reject
    original_invalid = consumer_mod._reject_invalid_transition
    original_ack = consumer_mod._ack_or_defer

    def spy_commit(self, *a, **k):
        result = original_commit(self, *a, **k)
        order.append("commit")
        return result

    async def spy_reject(*a, **k):
        order.append("reject")
        return await original_reject(*a, **k)

    async def spy_invalid(*a, **k):
        order.append("invalid")
        return await original_invalid(*a, **k)

    async def spy_ack(*a, **k):
        order.append("ack")
        return await original_ack(*a, **k)

    async def noop():
        return None

    def spy_notify(event):
        order.append("notify")
        return noop()

    client, _p, executed = _pipeline_client(messages)
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_rate_limiter", _ScriptedLimiter([True, False, True])), \
            patch.object(Session, "commit", spy_commit), \
            patch.object(consumer_mod, "_reject", spy_reject), \
            patch.object(consumer_mod, "_reject_invalid_transition", spy_invalid), \
            patch.object(consumer_mod, "_ack_or_defer", spy_ack), \
            patch.object(consumer_mod, "notify_if_applicable", spy_notify), \
            patch.object(
                service_mod, "validate_transition",
                side_effect=InvalidTransitionError(EventStatus.pending, EventStatus.superseded),
            ):
        await consumer_mod._process_batch(client, ">")

    # The audit rows of the rejected events are written through Session.commit too, but only
    # AFTER the batch COMMIT: the first "commit" is the batch's, and nothing precedes it.
    assert order[0] == "commit"
    assert [x for x in order if x != "commit"] == ["ack", "notify", "reject", "invalid"]
    assert [r.path for r in _rows(mem_engine)] == ["/a"]
    assert _acked_event_ids(executed) == [json.loads(messages[0][1]["data"])["event_id"]]


# ── 5.22 validation rejections stay immediate ─────────────────────────────────

async def test_invalid_signature_is_acked_before_the_batch_commit(mem_engine, agent, shared_secret) -> None:
    order: list[str] = []
    bad = _payload(shared_secret, path="/bad", seq=0)
    bad["signature"] = "0" * 64
    messages = [("0-0", _msg(bad)), ("1-0", _msg(_payload(shared_secret, path="/ok", seq=1)))]
    client, _p, _e = _pipeline_client(messages)
    client.xack.side_effect = lambda *a, **k: order.append("xack")
    original_commit = Session.commit

    def spy_commit(self, *a, **k):
        order.append("commit")
        return original_commit(self, *a, **k)

    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(Session, "commit", spy_commit):
        await consumer_mod._process_batch(client, ">")
    # order: [audit-row commit of the rejection, its XACK, the batch COMMIT]
    assert order[-1] == "commit" and order.index("xack") < len(order) - 1
    assert [r.path for r in _rows(mem_engine)] == ["/ok"]


# ── 5.23 transient error + PEL re-delivery ────────────────────────────────────

async def test_transient_error_then_redelivery_persists_once_and_refunds_tokens(
    mem_engine, agent, shared_secret,
) -> None:
    limiter = consumer_mod._RateLimiter(rate_per_s=1.0, burst=100, clock=lambda: 0.0)
    messages = [(f"{i}-0", _msg(_payload(shared_secret, path=f"/f{i}", seq=i))) for i in range(3)]
    original_commit = Session.commit
    calls = {"n": 0}

    def flaky_commit(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OperationalError("COMMIT", {}, Exception("connection refused"))
        return original_commit(self, *a, **k)

    first, _p, executed1 = _pipeline_client(messages)
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_rate_limiter", limiter), patch.object(Session, "commit", flaky_commit):
        await consumer_mod._process_batch(first, ">")
        assert executed1 == [] and _rows(mem_engine) == []
        assert limiter._buckets[agent].tokens == 100  # the first attempt's tokens came back

        retry, _p2, executed2 = _pipeline_client(messages)
        await consumer_mod._process_batch(retry, "0")
    assert len(_rows(mem_engine)) == 3
    assert executed2[0][-1][3] == ("0-0", "1-0", "2-0")
    assert limiter._buckets[agent].tokens == 97  # one admission per event, as if nothing failed


# ── 5.24 compacted events are not notified ────────────────────────────────────

async def test_event_deleted_by_compaction_of_the_same_batch_is_not_notified(
    mem_engine, agent, shared_secret,
) -> None:
    notified: list[str] = []

    async def noop():
        return None

    def spy_notify(event):
        notified.append(event.event_id)
        return noop()

    payloads = [_payload(shared_secret, path="/etc/x", seq=i) for i in range(12)]
    messages = [(f"{i}-0", _msg(p)) for i, p in enumerate(payloads)]
    client, _p, executed = _pipeline_client(messages)
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "notify_if_applicable", spy_notify):
        await consumer_mod._process_batch(client, ">")
    assert len(_rows(mem_engine)) == 11
    assert payloads[0]["event_id"] not in notified
    assert notified == [p["event_id"] for p in payloads[1:]]
    # The compacted event is still acknowledged: it was persisted (and later compacted).
    assert len(_acked_event_ids(executed)) == 12


# ── Fixes after the independent verification ──────────────────────────────────

import asyncio
import threading

import pytest


async def _noop():
    return None


async def test_a_failing_effect_does_not_stop_the_notification_of_later_committed_events(
    mem_engine, agent, shared_secret,
) -> None:
    """W1: [e1 rate-limited whose _reject raises, e2 new] -> e2 is acked and notified."""
    notified: list[str] = []

    def spy_notify(event):
        notified.append(event.event_id)
        return _noop()

    p1 = _payload(shared_secret, path="/a", seq=0)
    p2 = _payload(shared_secret, path="/b", seq=1)
    messages = [("0-0", _msg(p1)), ("1-0", _msg(p2))]
    client, _p, executed = _pipeline_client(messages)

    async def broken_reject(*a, **k):
        raise ConnectionError("valkey down while XACKing the rejection")

    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_rate_limiter", _ScriptedLimiter([False, True])), \
            patch.object(consumer_mod, "_reject", broken_reject), \
            patch.object(consumer_mod, "notify_if_applicable", spy_notify), \
            structlog.testing.capture_logs() as cap, patch.object(consumer_mod, "log", structlog.get_logger()):
        await consumer_mod._process_batch(client, ">")

    assert [r.event_id for r in _rows(mem_engine)] == [p2["event_id"]]
    assert notified == [p2["event_id"]]
    assert _acked_event_ids(executed) == [p2["event_id"]]
    assert executed[0][-1][3] == ("1-0",)  # e1 stays in the PEL
    assert any(r["event"] == "consumer.effect_error" and r["event_id"] == p1["event_id"] for r in cap)


async def test_a_failing_ack_does_not_lose_the_alert_of_a_committed_event(
    mem_engine, agent, shared_secret,
) -> None:
    notified: list[str] = []

    def spy_notify(event):
        notified.append(event.event_id)
        return _noop()

    payloads = [_payload(shared_secret, path=f"/f{i}", seq=i) for i in range(3)]
    client, _p, executed = _pipeline_client([(f"{i}-0", _msg(p)) for i, p in enumerate(payloads)])
    original_ack = consumer_mod._ack_or_defer
    calls = {"n": 0}

    async def flaky_ack(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("boom")
        return await original_ack(*a, **k)

    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_ack_or_defer", flaky_ack), \
            patch.object(consumer_mod, "notify_if_applicable", spy_notify):
        await consumer_mod._process_batch(client, ">")
    assert notified == [p["event_id"] for p in payloads]  # all three alerts scheduled
    assert executed[0][-1][3] == ("1-0", "2-0")


async def test_path_of_the_wrong_type_is_rejected_without_touching_its_neighbours(
    mem_engine, agent, shared_secret,
) -> None:
    """W3: an HMAC-valid payload with a non-string path is rejected at validation, isolated."""
    bad_int = _payload(shared_secret, path=5, seq=1)
    bad_list = _payload(shared_secret, path=["/x"], seq=2)
    ok1, ok2 = _payload(shared_secret, path="/a", seq=0), _payload(shared_secret, path="/b", seq=3)
    messages = [("0-0", _msg(ok1)), ("1-0", _msg(bad_int)), ("2-0", _msg(bad_list)), ("3-0", _msg(ok2))]
    client, _p, executed = _pipeline_client(messages)
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2:
        await consumer_mod._process_batch(client, ">")
    assert [r.event_id for r in _rows(mem_engine)] == [ok1["event_id"], ok2["event_id"]]
    assert executed[0][-1][3] == ("0-0", "3-0")
    acked = {c.args[2] for c in client.xack.await_args_list}
    assert acked == {"1-0", "2-0"}  # the rejections were XACKed immediately


async def test_unexpected_exception_in_the_batch_is_replayed_per_event(
    mem_engine, agent, shared_secret,
) -> None:
    """W3 (defensive): a non-database exception behaves like IntegrityError: neighbours progress."""
    payloads = [_payload(shared_secret, path=f"/f{i}", seq=i) for i in range(3)]
    client, _p, executed = _pipeline_client([(f"{i}-0", _msg(p)) for i, p in enumerate(payloads)])
    original_ingest = consumer_mod._ingest

    def poisoned(payload, received_at, detected_at, agent_id):
        if payload["path"] == "/f1":
            raise TypeError("unexpected payload shape")
        return original_ingest(payload, received_at, detected_at, agent_id)

    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_ingest_batch", side_effect=TypeError("boom")), \
            patch.object(consumer_mod, "_ingest", poisoned):
        await consumer_mod._process_batch(client, ">")
    assert [r.event_id for r in _rows(mem_engine)] == [payloads[0]["event_id"], payloads[2]["event_id"]]
    assert executed[0][-1][3] == ("0-0", "2-0")


async def test_cancellation_mid_batch_still_completes_persistence_and_effects(
    mem_engine, agent, shared_secret,
) -> None:
    """W2: shutdown cancels the consumer while the executor commits: effects still run, then CancelledError."""
    started = threading.Event()
    original = consumer_mod._ingest_batch

    def slow(*a, **k):
        started.set()
        import time
        time.sleep(0.3)
        return original(*a, **k)

    payloads = [_payload(shared_secret, path=f"/f{i}", seq=i) for i in range(3)]
    client, _p, executed = _pipeline_client([(f"{i}-0", _msg(p)) for i, p in enumerate(payloads)])
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_ingest_batch", slow):
        task = asyncio.create_task(consumer_mod._process_batch(client, ">"))
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(_rows(mem_engine)) == 3
    assert executed[0][-1][3] == ("0-0", "1-0", "2-0")  # acked despite the cancellation


# ── W4 ────────────────────────────────────────────────────────────────────────

async def test_repeated_event_id_in_a_batch_acks_both_entries_after_the_commit(
    mem_engine, agent, shared_secret,
) -> None:
    order: list[str] = []
    dup = _payload(shared_secret, path="/etc/x")
    client, pipelines, executed = _pipeline_client([("0-0", _msg(dup)), ("1-0", _msg(dup))])
    original_commit = Session.commit
    original_build = consumer_mod._build_event_ack

    def spy_commit(self, *a, **k):
        result = original_commit(self, *a, **k)
        order.append("commit")
        return result

    def spy_build(*a, **k):
        order.append("append")
        return original_build(*a, **k)

    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(Session, "commit", spy_commit), patch.object(consumer_mod, "_build_event_ack", spy_build):
        await consumer_mod._process_batch(client, ">")
    assert len(_rows(mem_engine)) == 1
    assert order == ["commit", "append", "append"]
    assert [op[0] for op in executed[0]] == ["xadd", "xadd", "xack"]
    assert executed[0][-1][3] == ("0-0", "1-0")


async def test_real_mid_batch_integrity_error_rolls_back_refunds_and_replays_per_event(
    mem_engine, agent, shared_secret,
) -> None:
    """W4: a real constraint violation (trigger) raised by the middle event, no patching of `_ingest_batch`."""
    with mem_engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TRIGGER poison BEFORE INSERT ON events WHEN NEW.path = '/f1' "
            "BEGIN SELECT RAISE(ABORT, 'poisoned'); END"
        )
    limiter = consumer_mod._RateLimiter(rate_per_s=1.0, burst=100, clock=lambda: 0.0)
    refunds: list[tuple[str, int]] = []
    real_refund = limiter.refund
    limiter.refund = lambda key, n: (refunds.append((key, n)), real_refund(key, n))[1]  # type: ignore[method-assign]

    payloads = [_payload(shared_secret, path=f"/f{i}", seq=i) for i in range(3)]
    client, _p, executed = _pipeline_client([(f"{i}-0", _msg(p)) for i, p in enumerate(payloads)])
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_rate_limiter", limiter), \
            structlog.testing.capture_logs() as cap, patch.object(consumer_mod, "log", structlog.get_logger()):
        await consumer_mod._process_batch(client, ">")

    assert any(r["event"] == "consumer.batch_replayed_per_event" for r in cap)
    assert refunds == [(agent, 2)]  # the batch spent e1 and e2 before failing, and gave them back
    assert [r.event_id for r in _rows(mem_engine)] == [payloads[0]["event_id"], payloads[2]["event_id"]]
    assert executed[0][-1][3] == ("0-0", "2-0")  # e2 stays in the PEL
    # the replay decided again: e1, e2 and e3 each spent one token
    assert limiter._buckets[agent].tokens == 97
