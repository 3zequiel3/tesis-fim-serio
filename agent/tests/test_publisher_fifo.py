"""
Tests for Change 61 — agent-publisher-fifo-reconnect (D79/RN-173, RN-39).

Order is asserted on the sequence of XADDs the stream *accepted*, not on the
calls: repeated failed attempts on the head event are expected and correct.

Covers:
  5.1  Valkey fails the first N XADDs and recovers mid-pass (strict FIFO)
  5.2  A failure in the middle of a pass stops it
  5.3  A new event never overtakes the unsent backlog
  5.4  Concurrent publishes never interleave their XADDs
  5.5  A failing start-up drain stops at the first error
  5.6  Journal rehydration does not overtake the disk backlog
  5.7  Without a disk backlog the fast path before run() is kept
  5.8  A failed XADD does not wait for the ACK timeout
  5.9  0.5 s polling while there is a backlog
  5.10 Purge on event_ack
  5.11 Purge on capacity eviction
  5.12 Purge on max_attempts_exceeded
  5.13 Purge on terminal event_nack
  5.14 Backpressure with a backlog
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import agent.publisher as publisher_module
import agent.queue as queue_module
from agent.config import AgentConfig, PublisherConfig, StorageConfig
from agent.publisher import _BACKLOG_POLL_S, Publisher
from agent.queue import EventQueue
from agent.streams import sign_payload
from agent.tests.conftest import TEST_MASTER_SECRET, decrypt_queue_file


# ── fake Valkey ───────────────────────────────────────────────────────────────


class FakeValkey:
    """xadd driven by a script of outcomes; records the accepted event order.

    Outcome precedence per call: `script` (True accepts, False raises), then
    `fail_all`, then accept. `gate`, when set, blocks every xadd until the
    event is set. Events are identified by the `path` field of the payload.
    """

    def __init__(self) -> None:
        self.accepted: list[str] = []
        self.log: list[tuple[str, str]] = []
        self.calls = 0
        self.fail_all = False
        self.script: deque[bool] = deque()
        self.gate: asyncio.Event | None = None
        self.in_flight = 0
        self.max_in_flight = 0

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.gate is not None:
                await self.gate.wait()
            label = json.loads(fields["data"])["path"]
            ok = self.script.popleft() if self.script else not self.fail_all
            if not ok:
                self.log.append(("fail", label))
                raise ConnectionError("valkey down")
            self.log.append(("ok", label))
            self.accepted.append(label)
            return "1-0"
        finally:
            self.in_flight -= 1


# ── fixtures / helpers ────────────────────────────────────────────────────────


@pytest.fixture()
def shared_secret(tmp_path: Path) -> bytes:
    secret = os.urandom(32)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o700)
    fd = os.open(str(secrets_dir / "shared_secret"), os.O_CREAT | os.O_WRONLY, 0o400)
    with os.fdopen(fd, "wb") as f:
        f.write(secret)
    return secret


def _make_config(tmp_path: Path, **publisher_kwargs: Any) -> AgentConfig:
    return AgentConfig(
        agent_id="test-agent-01",
        backend_url="http://localhost:8000",
        valkey_url="redis://localhost:6379",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/tmp"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(tmp_path / "secrets"),
            certs_dir=str(tmp_path / "certs"),
            discard_dir=str(tmp_path / "discarded"),
        ),
        publisher=PublisherConfig(**publisher_kwargs),
    )


@pytest.fixture()
def config(tmp_path: Path, shared_secret: bytes) -> AgentConfig:
    return _make_config(tmp_path)


def _make_publisher(config: AgentConfig) -> tuple[Publisher, FakeValkey, EventQueue]:
    queue = EventQueue(
        config.storage.queue_dir,
        master_secret=TEST_MASTER_SECRET,
        agent_id=config.agent_id,
        discard_dir=config.storage.discard_dir,
    )
    client = FakeValkey()
    return Publisher(config, queue, client), client, queue  # type: ignore[arg-type]


_clock = itertools.count()


def _ev(label: str) -> dict[str, Any]:
    # The on-disk queue orders by millisecond-resolution detected_at; events
    # built back-to-back would tie, so give each a distinct millisecond.
    detected_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=next(_clock))
    return {"path": label, "hash_detected": "h", "detected_at": detected_at.isoformat()}


def _unsent_labels(pub: Publisher) -> list[str]:
    return [p["path"] for p in pub._unsent.values()]


def _pending_labels(pub: Publisher) -> list[str]:
    return [p["path"] for _, p in pub._pending.values()]


def _id_of(pub: Publisher, label: str) -> str:
    for eid, payload in pub._unsent.items():
        if payload["path"] == label:
            return eid
    for eid, (_, payload) in pub._pending.items():
        if payload["path"] == label:
            return eid
    raise KeyError(label)


async def _run_passes(pub: Publisher, client: FakeValkey, n: int) -> None:
    """Run exactly `n` passes of _retry_loop, marking pass boundaries in client.log."""
    stop = asyncio.Event()
    calls = {"n": 0}

    async def fake_wait(_stop: asyncio.Event) -> None:
        calls["n"] += 1
        client.log.append(("pass", ""))
        if calls["n"] > n:
            stop.set()

    pub._wait_for_next_pass = fake_wait  # type: ignore[method-assign]
    await pub._retry_loop(stop)


def _passes(client: FakeValkey) -> list[list[tuple[str, str]]]:
    """Split client.log into the segments between pass markers (first marker opens pass 1)."""
    segments: list[list[tuple[str, str]]] = []
    for kind, label in client.log:
        if kind == "pass":
            segments.append([])
        elif segments:
            segments[-1].append((kind, label))
    return segments


# ── 5.1 ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valkey_recovers_mid_pass_keeps_strict_fifo(config: AgentConfig) -> None:
    """The measured defect: with `continue`, e4..e10 were accepted before e1..e3."""
    pub, client, _ = _make_publisher(config)
    labels = [f"e{i}" for i in range(1, 11)]
    client.fail_all = True
    for label in labels:
        await pub.publish(_ev(label))
    assert _unsent_labels(pub) == labels

    client.fail_all = False
    client.script = deque([False, False, False])  # the next 3 attempts fail
    await _run_passes(pub, client, 6)

    assert client.accepted == labels
    for segment in _passes(client):
        fails = [i for i, (kind, _) in enumerate(segment) if kind == "fail"]
        # A pass with an error emits exactly one failed XADD, and it is its last.
        assert len(fails) <= 1
        if fails:
            assert fails[0] == len(segment) - 1
    assert len(pub._unsent) == 0
    assert _pending_labels(pub) == labels


# ── 5.2 ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failure_mid_pass_stops_the_pass(config: AgentConfig) -> None:
    pub, client, _ = _make_publisher(config)
    labels = [f"e{i}" for i in range(1, 7)]
    client.fail_all = True
    for label in labels:
        await pub.publish(_ev(label))
    client.fail_all = False
    client.script = deque([True, True, False])  # accept, accept, fail, then accept

    await _run_passes(pub, client, 1)

    assert client.accepted == ["e1", "e2"]
    assert _unsent_labels(pub)[0] == "e3"
    assert "e4" not in [label for _, label in client.log]

    await _run_passes(pub, client, 1)
    assert client.accepted == labels


# ── 5.3 ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_event_does_not_overtake_unsent_backlog(config: AgentConfig) -> None:
    pub, client, _ = _make_publisher(config)
    client.fail_all = True
    await pub.publish(_ev("e1"))
    await pub.publish(_ev("e2"))
    before = client.calls

    await pub.publish(_ev("e3"))

    assert client.calls == before
    assert _unsent_labels(pub) == ["e1", "e2", "e3"]

    client.fail_all = False
    await _run_passes(pub, client, 3)
    assert client.accepted == ["e1", "e2", "e3"]


# ── 5.4 ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_publishes_never_interleave_xadd(config: AgentConfig) -> None:
    pub, client, _ = _make_publisher(config)
    client.gate = asyncio.Event()

    first = asyncio.create_task(pub.publish(_ev("first")))
    for _ in range(5):
        await asyncio.sleep(0)  # let `first` reach its XADD and block on the gate
    assert client.in_flight == 1

    await pub.publish(_ev("second"))  # must not block nor emit its own XADD
    assert client.calls == 1

    client.gate.set()
    await first
    await _run_passes(pub, client, 2)

    assert client.accepted == ["first", "second"]
    assert client.max_in_flight == 1


# ── 5.5 ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_startup_drain_stops_at_first_error(config: AgentConfig) -> None:
    pub1, c1, _ = _make_publisher(config)
    c1.fail_all = True
    for label in ("e1", "e2", "e3"):
        await pub1.publish(_ev(label))

    pub2, client, _ = _make_publisher(config)
    client.script = deque([True, False])
    await pub2._drain_queue()

    assert client.accepted == ["e1"]
    assert _pending_labels(pub2) == ["e1"]
    assert _unsent_labels(pub2) == ["e2", "e3"]
    assert client.calls == 2  # e1 ok, e2 failed, no XADD for e3


# ── 5.6 ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rehydration_does_not_overtake_disk_backlog(config: AgentConfig) -> None:
    pub0, c0, _ = _make_publisher(config)
    c0.fail_all = True
    await pub0.publish(_ev("e1"))
    await pub0.publish(_ev("e2"))

    pub, client, _ = _make_publisher(config)  # fresh process, run() not started
    await pub.publish(_ev("r1"))

    assert client.calls == 0
    assert _unsent_labels(pub) == ["e1", "e2", "r1"]

    await pub._drain_queue()
    assert client.accepted == ["e1", "e2", "r1"]


# ── 5.7 ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_disk_backlog_keeps_fast_path_before_run(config: AgentConfig) -> None:
    pub, client, _ = _make_publisher(config)

    await pub.publish(_ev("e1"))

    assert client.calls == 1
    assert client.accepted == ["e1"]
    assert _pending_labels(pub) == ["e1"]
    assert len(pub._unsent) == 0


# ── 5.8 ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_xadd_does_not_wait_for_ack_timeout(config: AgentConfig) -> None:
    pub, client, _ = _make_publisher(config)
    client.fail_all = True
    await pub.publish(_ev("e1"))
    client.fail_all = False

    assert publisher_module._ACK_TIMEOUT_S == 60.0
    await _run_passes(pub, client, 1)

    assert client.accepted == ["e1"]


# ── 5.9 ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_polls_every_half_second_with_backlog(config: AgentConfig) -> None:
    pub, client, _ = _make_publisher(config)
    client.fail_all = True
    await pub.publish(_ev("e1"))
    loop = asyncio.get_running_loop()

    # Previous pass failed: plain sleep of _BACKLOG_POLL_S, wake-ups ignored.
    pub._last_pass_failed = True
    pub._wake.set()
    t0 = loop.time()
    await pub._wait_for_next_pass(asyncio.Event())
    assert _BACKLOG_POLL_S * 0.8 <= loop.time() - t0 < 1.0

    # Previous pass clean, backlog present, nobody wakes us: times out at 0.5 s.
    pub._last_pass_failed = False
    t0 = loop.time()
    await pub._wait_for_next_pass(asyncio.Event())
    assert _BACKLOG_POLL_S * 0.8 <= loop.time() - t0 < 1.0

    # An event left in _unsent wakes the loop without waiting the full period.
    pub._wake.set()
    t0 = loop.time()
    await pub._wait_for_next_pass(asyncio.Event())
    assert loop.time() - t0 < 0.1
    assert pub._wake.is_set() is False


# ── 5.10 ──────────────────────────────────────────────────────────────────────


def _signed(secret: bytes, payload: dict[str, Any]) -> dict[str, str]:
    full = {**payload, "signature": sign_payload(secret, payload)}
    return {"data": json.dumps(full, sort_keys=True, separators=(",", ":"))}


@pytest.mark.asyncio
async def test_ack_for_unsent_event_purges_it(config: AgentConfig, shared_secret: bytes) -> None:
    pub, client, queue = _make_publisher(config)
    client.fail_all = True
    await pub.publish(_ev("e1"))
    event_id = _id_of(pub, "e1")

    ack = pub._verify_and_parse(_signed(shared_secret, {"type": "event_ack", "event_id": event_id}))
    await pub._handle_command_async(ack)

    assert event_id not in pub._unsent
    assert event_id not in pub._pending
    assert queue.contains(event_id) is False

    client.fail_all = False
    await _run_passes(pub, client, 2)
    assert client.accepted == []


# ── 5.11 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capacity_eviction_purges_unsent(
    config: AgentConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    pub, client, queue = _make_publisher(config)
    client.fail_all = True
    await pub.publish(_ev("same"))
    evicted_id = _id_of(pub, "same")
    first_size = queue._total_bytes()

    # Each event fits independently, but the pair does not.
    monkeypatch.setattr(queue_module, "_MAX_BYTES", first_size + 1)
    await pub.publish(_ev("same"))

    assert queue.contains(evicted_id) is False
    assert evicted_id not in pub._unsent
    assert evicted_id not in pub._pending

    client.fail_all = False
    await _run_passes(pub, client, 2)
    assert len(client.accepted) == 1  # only the survivor


# ── 5.12 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attempt_ceiling_discard_purges_both(tmp_path: Path, shared_secret: bytes) -> None:
    cfg = _make_config(tmp_path, max_publish_attempts=2)
    pub, client, queue = _make_publisher(cfg)
    await pub.publish(_ev("e1"))
    event_id = _id_of(pub, "e1")
    queue.bump_attempts(event_id)  # attempts == 2 == ceiling
    old_time, payload = pub._pending[event_id]
    pub._pending[event_id] = (old_time - publisher_module._ACK_TIMEOUT_S - 1, payload)
    client.accepted.clear()
    calls_before = client.calls

    await _run_passes(pub, client, 1)

    assert event_id not in pub._unsent
    assert event_id not in pub._pending
    assert client.calls == calls_before
    discarded = list(queue._discard_dir.glob("*.json"))
    assert len(discarded) == 1
    assert decrypt_queue_file(discarded[0])["discard_reason"] == "max_attempts_exceeded"


# ── 5.13 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terminal_nack_purges_unsent(config: AgentConfig, shared_secret: bytes) -> None:
    pub, client, queue = _make_publisher(config)
    client.fail_all = True
    await pub.publish(_ev("e1"))
    event_id = _id_of(pub, "e1")

    nack = pub._verify_and_parse(
        _signed(shared_secret, {"type": "event_nack", "event_id": event_id, "reason": "clock_skew"})
    )
    await pub._handle_command_async(nack)

    assert event_id not in pub._unsent
    assert event_id not in pub._pending

    client.fail_all = False
    await _run_passes(pub, client, 2)
    assert client.accepted == []


# ── 5.14 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_backpressure_with_backlog_blocks_then_drains_in_order(config: AgentConfig) -> None:
    pub, client, _ = _make_publisher(config)
    client.fail_all = True
    await pub.publish(_ev("e1"))
    await pub.publish(_ev("e2"))
    client.fail_all = False
    calls_before = client.calls

    pub._paused_until = asyncio.get_running_loop().time() + 60.0
    await _run_passes(pub, client, 2)
    assert client.calls == calls_before

    pub._paused_until = 0.0
    await _run_passes(pub, client, 1)
    assert client.accepted == ["e1", "e2"]
