"""
Tests of the `ingest-drain-resilience-and-throughput` change (D87/RN-181).

Covers: `consumer.timing` profiling, Valkey client timeouts, the 5 s agent
authentication cache, the batched `event_ack` + `XACK`, `NOGROUP` recovery in
the events and command_ack consumers (unit with client doubles, plus opt-in
integration against a real Valkey) and the compose AOF flags.

Same fixture pattern as test_ingest_offload_blocking_db.py (SQLite in-memory).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)

import app.modules.agents.command_ack_consumer as ack_mod
import app.modules.events.consumer as consumer_mod
import app.modules.events.service as service_mod
from app.core import valkey as valkey_mod
from app.core.config import Settings, settings
from app.core.streams import (
    CONSUMER_GROUP,
    SCHEMA_VERSION,
    STREAM_COMMANDS,
    STREAM_EVENT_ACK,
    STREAM_EVENTS,
    sign_payload,
)
from app.modules.agents.models import Agent, AgentStatus
from app.modules.events.models import Event

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture()
def shared_secret() -> bytes:
    return os.urandom(32)


def _add_agent(engine, secret: bytes, agent_id: str = "agent-drain-res") -> None:
    with Session(engine) as session:
        session.add(
            Agent(agent_id=agent_id, status=AgentStatus.offline, shared_secret_hex=secret.hex())
        )
        session.commit()


@pytest.fixture()
def agent(mem_engine, shared_secret):
    _add_agent(mem_engine, shared_secret)
    return "agent-drain-res"


def _msg(payload: dict) -> dict:
    return {"data": json.dumps(payload, sort_keys=True, separators=(",", ":"))}


def _payload(secret: bytes, agent_id: str = "agent-drain-res", path: str = "/etc/x", seq: int = 0) -> dict:
    payload = {
        "event_id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "detected_at": (datetime.now(timezone.utc) + timedelta(seconds=seq)).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "path": path,
        "hash_detected": "abc123",
        "process_pid": 1,
        "process_uid": 0,
        "process_exe": "/usr/bin/test",
    }
    payload["signature"] = sign_payload(secret, payload)
    return payload


def _patch_engines(mem_engine):
    return (
        patch.object(consumer_mod, "engine", mem_engine),
        patch.object(service_mod, "engine", mem_engine),
    )


class _RecordingPipeline:
    """Sync pipeline double (redis-py style): xadd/xack queue, execute is async."""

    def __init__(self, calls: list, fail: bool = False) -> None:
        self._calls = calls
        self._fail = fail
        self.ops: list[tuple] = []

    def xadd(self, stream, fields):
        self.ops.append(("xadd", stream, fields))

    def xack(self, stream, group, *ids):
        self.ops.append(("xack", stream, group, ids))

    async def execute(self):
        if self._fail:
            raise ConnectionError("valkey down at flush")
        self._calls.append(self.ops)


def _pipeline_client(messages, *, fail_pipeline: bool = False):
    client = MagicMock()
    client.xreadgroup = AsyncMock(return_value=[(STREAM_EVENTS, messages)])
    client.xack = AsyncMock()
    client.xadd = AsyncMock()
    pipelines: list[_RecordingPipeline] = []
    executed: list[list[tuple]] = []

    def factory(transaction=True):
        pipe = _RecordingPipeline(executed, fail=fail_pipeline)
        pipelines.append(pipe)
        return pipe

    client.pipeline = factory
    return client, pipelines, executed


# ── 1. consumer.timing ────────────────────────────────────────────────────────

async def _run_one_event_with_logs(mem_engine, secret, profile: bool):
    msg = _msg(_payload(secret))
    client, _pipes, _executed = _pipeline_client([("1-0", msg)])
    cfg = settings.model_copy(update={"fim_profile_ingest": profile})
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "settings", cfg), structlog.testing.capture_logs() as cap:
        with patch.object(consumer_mod, "log", structlog.get_logger()):
            await consumer_mod._process_batch(client, ">")
    return [r for r in cap if r.get("event") == "consumer.timing"]


async def test_timing_emitted_per_event_and_per_batch_when_flag_active(mem_engine, agent, shared_secret) -> None:
    records = await _run_one_event_with_logs(mem_engine, shared_secret, profile=True)

    by_scope = {r["scope"]: r for r in records}
    assert set(by_scope) == {"event", "batch"}
    ev = by_scope["event"]
    for key in ("event_id", "agent_id", "auth_ms", "auth_cache_hit", "validation_ms", "ingest_ms", "total_ms"):
        assert key in ev
    assert ev["agent_id"] == agent
    assert ev["auth_cache_hit"] is False
    assert ev["total_ms"] >= ev["ingest_ms"] >= 0
    batch = by_scope["batch"]
    assert batch["batch_size"] == 1 and "ack_flush_ms" in batch
    # Amplification of 2026-10-03 of D87/RN-181 (D-8, D-10): keys added by the batch transaction.
    assert batch["candidates"] == 1
    assert batch["ingest_db_ms"] >= 0 and batch["commit_ms"] >= 0
    # The per-event `ingest_ms` is its share of the batch transaction (the COMMIT is in the batch log).
    assert "commit_ms" not in ev
    # No payload, signature or secret in the profiling logs.
    for rec in records:
        assert "signature" not in json.dumps(rec, default=str)
        assert "payload" not in rec and "shared_secret" not in rec


async def test_per_event_path_reports_commit_ms_inside_ingest_ms(mem_engine, agent, shared_secret) -> None:
    """Task 1.4 of `ingest-batched-persistence`: the per-event path measures its COMMIT."""
    msg = _msg(_payload(shared_secret))
    cfg = settings.model_copy(update={"fim_profile_ingest": True})
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "settings", cfg), structlog.testing.capture_logs() as cap:
        with patch.object(consumer_mod, "log", structlog.get_logger()):
            # Outside a batch: the per-event path (as `_handle_message` direct calls).
            client, _pipes, _executed = _pipeline_client([])
            await consumer_mod._handle_message(client, "1-0", msg)
    ev = next(r for r in cap if r.get("event") == "consumer.timing" and r["scope"] == "event")
    assert 0 <= ev["commit_ms"] <= ev["ingest_ms"]


def test_ingest_outcome_carries_the_commit_time_of_the_per_event_path(mem_engine) -> None:
    now = datetime.now(timezone.utc)
    with patch.object(service_mod, "engine", mem_engine):
        outcome = service_mod._ingest_event_outcome(
            {"event_id": str(uuid.uuid4()), "agent_id": "a", "path": "/x", "hash_detected": "h"}, now, now
        )
        duplicate = service_mod._ingest_event_outcome(
            {"event_id": outcome.event.event_id, "agent_id": "a", "path": "/x"}, now, now
        )
    assert outcome.commit_ms is not None and outcome.commit_ms >= 0
    assert duplicate.disposition == service_mod.IngestDisposition.duplicate and duplicate.commit_ms is None


async def test_timing_not_emitted_when_flag_inactive(mem_engine, agent, shared_secret) -> None:
    assert await _run_one_event_with_logs(mem_engine, shared_secret, profile=False) == []


def test_profile_flag_defaults_to_off_and_reads_env(monkeypatch) -> None:
    assert Settings.model_fields["fim_profile_ingest"].default is False
    monkeypatch.setenv("FIM_PROFILE_INGEST", "1")
    assert Settings().fim_profile_ingest is True


async def test_timing_omitted_on_early_rejection(mem_engine, agent, shared_secret) -> None:
    bad = _payload(shared_secret)
    bad["signature"] = "0" * 64
    client, _p, _e = _pipeline_client([("1-0", _msg(bad))])
    cfg = settings.model_copy(update={"fim_profile_ingest": True})
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "settings", cfg), structlog.testing.capture_logs() as cap:
        with patch.object(consumer_mod, "log", structlog.get_logger()):
            await consumer_mod._process_batch(client, ">")
    assert [r for r in cap if r.get("event") == "consumer.timing" and r["scope"] == "event"] == []


# ── 2. Valkey client timeouts ─────────────────────────────────────────────────

_TIMEOUT_KEYS = ("socket_timeout", "socket_connect_timeout", "health_check_interval")


def _expected_timeouts() -> dict:
    return {
        "socket_timeout": settings.valkey_socket_timeout_seconds,
        "socket_connect_timeout": settings.valkey_socket_connect_timeout_seconds,
        "health_check_interval": settings.valkey_health_check_interval_seconds,
    }


def test_timeout_defaults_are_5_10_15() -> None:
    assert Settings.model_fields["valkey_socket_connect_timeout_seconds"].default == 5.0
    assert Settings.model_fields["valkey_socket_timeout_seconds"].default == 10.0
    assert Settings.model_fields["valkey_health_check_interval_seconds"].default == 15


@pytest.mark.parametrize("builder", ["async", "sync"])
def test_plaintext_clients_get_the_three_timeouts(builder) -> None:
    pkg = valkey_mod._valkey_async_pkg if builder == "async" else valkey_mod._valkey_pkg
    with patch.object(pkg.Valkey, "from_url") as from_url:
        if builder == "async":
            valkey_mod.build_async_valkey_client("valkey://localhost:6379")
        else:
            try:
                valkey_mod.init_valkey("valkey://localhost:6379")
            finally:
                valkey_mod._client = None
    kwargs = from_url.call_args.kwargs
    for key, value in _expected_timeouts().items():
        assert kwargs[key] == value
    assert not any(k.startswith("ssl_") for k in kwargs)


@pytest.mark.parametrize("builder", ["async", "sync"])
def test_tls_clients_keep_ssl_kwargs_and_get_timeouts(builder, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ca_cert_path", "/certs/ca.pem")
    monkeypatch.setattr(settings, "backend_cert_path", "/certs/b.pem")
    monkeypatch.setattr(settings, "backend_key_path", "/certs/b-key.pem")
    pkg = valkey_mod._valkey_async_pkg if builder == "async" else valkey_mod._valkey_pkg
    with patch.object(pkg.Valkey, "from_url") as from_url:
        if builder == "async":
            valkey_mod.build_async_valkey_client("valkeys://valkey:6380")
        else:
            try:
                valkey_mod.init_valkey("valkeys://valkey:6380")
            finally:
                valkey_mod._client = None
    kwargs = from_url.call_args.kwargs
    for key, value in _expected_timeouts().items():
        assert kwargs[key] == value
    assert kwargs["ssl_certfile"] == "/certs/b.pem"
    assert kwargs["ssl_keyfile"] == "/certs/b-key.pem"
    assert kwargs["ssl_ca_certs"] == "/certs/ca.pem"
    assert kwargs["ssl_check_hostname"] is True


def test_socket_timeout_exceeds_every_blocking_read() -> None:
    from app.modules.agents import heartbeat_consumer

    for mod in (consumer_mod, heartbeat_consumer, ack_mod):
        assert settings.valkey_socket_timeout_seconds * 1000 > mod._BLOCK_MS, mod.__name__


# ── 3. Authentication cache ───────────────────────────────────────────────────

def _counting_get_agent_auth():
    calls: list[str] = []
    original = consumer_mod._get_agent_auth

    def wrapper(agent_id):
        calls.append(agent_id)
        return original(agent_id)

    return calls, wrapper


async def test_two_events_within_ttl_query_the_db_once(mem_engine, agent, shared_secret) -> None:
    calls, wrapper = _counting_get_agent_auth()
    client, _p, executed = _pipeline_client(
        [("1-0", _msg(_payload(shared_secret, path="/a"))), ("2-0", _msg(_payload(shared_secret, path="/b")))]
    )
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_get_agent_auth", wrapper):
        await consumer_mod._process_batch(client, ">")
    assert calls == [agent]
    with Session(mem_engine) as session:
        assert len(session.exec(select(Event)).all()) == 2
    assert len(executed[0]) == 3  # 2 xadd + 1 xack: both validated with the same secret


async def test_cache_expires_after_ttl(mem_engine, agent, shared_secret) -> None:
    calls, wrapper = _counting_get_agent_auth()
    now = [1000.0]
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_get_agent_auth", wrapper), \
            patch.object(consumer_mod, "_auth_clock", lambda: now[0]):
        await consumer_mod._resolve_agent_auth(agent)
        now[0] += 4.9
        await consumer_mod._resolve_agent_auth(agent)
        assert calls == [agent]
        now[0] += 0.2  # 5.1 s since it was cached
        await consumer_mod._resolve_agent_auth(agent)
    assert calls == [agent, agent]


async def test_unknown_agent_is_not_cached_and_enrolment_is_picked_up(mem_engine, shared_secret) -> None:
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2:
        client, _p, _e = _pipeline_client([("1-0", _msg(_payload(shared_secret, agent_id="late-agent")))])
        await consumer_mod._process_batch(client, ">")
        assert "late-agent" not in consumer_mod._agent_auth_cache
        with Session(mem_engine) as session:
            assert session.exec(select(Event)).all() == []

        _add_agent(mem_engine, shared_secret, "late-agent")
        client, _p, executed = _pipeline_client(
            [("2-0", _msg(_payload(shared_secret, agent_id="late-agent")))]
        )
        await consumer_mod._process_batch(client, ">")
    with Session(mem_engine) as session:
        assert len(session.exec(select(Event)).all()) == 1
    assert "late-agent" in consumer_mod._agent_auth_cache
    assert executed


async def test_cache_hit_skips_session_and_executor(mem_engine, agent, shared_secret) -> None:
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2:
        await consumer_mod._resolve_agent_auth(agent)
        loop = asyncio.get_running_loop()
        with patch.object(loop, "run_in_executor", side_effect=AssertionError("executor used on a hit")), \
                patch.object(consumer_mod, "_get_agent_auth", side_effect=AssertionError("db used on a hit")):
            auth, hit = await consumer_mod._resolve_agent_auth_with_hit(agent)
    assert hit is True and auth.shared_secret == shared_secret


async def test_cache_stores_the_unwrapped_secret_only(mem_engine, agent, shared_secret) -> None:
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2:
        await consumer_mod._resolve_agent_auth(agent)
    cached_auth, _expires = consumer_mod._agent_auth_cache[agent]
    assert cached_auth.shared_secret == shared_secret
    # The wrapped value is never a cache field: _AgentAuth only has (secret, revoked).
    assert set(cached_auth.__dataclass_fields__) == {"shared_secret", "revoked"}


async def test_reject_path_uses_the_cache(mem_engine, agent, shared_secret) -> None:
    calls, wrapper = _counting_get_agent_auth()
    stale = _payload(shared_secret)
    stale["detected_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    stale["sent_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    stale["signature"] = sign_payload(shared_secret, {k: v for k, v in stale.items() if k != "signature"})
    client, _p, _e = _pipeline_client([])
    client.xadd = AsyncMock()
    client.xack = AsyncMock()
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(consumer_mod, "_get_agent_auth", wrapper):
        await consumer_mod._handle_message(client, "1-0", _msg(stale))  # clock_skew → nack
        await consumer_mod._handle_message(client, "2-0", _msg(stale))
    assert calls == [agent]
    assert client.xadd.await_count == 2  # both nacks were signed with the cached secret


# ── 4. Batched XACK + event_ack ───────────────────────────────────────────────

async def test_batch_of_valid_events_flushes_one_pipeline(mem_engine, agent, shared_secret) -> None:
    n = 5
    messages = [(f"{i}-0", _msg(_payload(shared_secret, path=f"/f{i}", seq=i))) for i in range(n)]
    client, pipelines, executed = _pipeline_client(messages)
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2:
        await consumer_mod._process_batch(client, ">")

    with Session(mem_engine) as session:
        assert len(session.exec(select(Event)).all()) == n
    assert len(pipelines) == 1 and len(executed) == 1
    ops = executed[0]
    assert [op[0] for op in ops] == ["xadd"] * n + ["xack"]
    xack = ops[-1]
    assert xack[1:3] == (STREAM_EVENTS, CONSUMER_GROUP)
    assert xack[3] == tuple(f"{i}-0" for i in range(n))
    assert all(op[1] == STREAM_COMMANDS for op in ops[:n])
    client.xack.assert_not_called()  # nothing was emitted individually
    client.xadd.assert_not_called()


async def test_each_ack_is_appended_after_the_commit_of_its_event(mem_engine, agent, shared_secret) -> None:
    """
    Rewritten under the amplification of 2026-10-03 of D87/RN-181 (change
    `ingest-batched-persistence`, D-10): the events of a batch are persisted in one
    transaction, so every append to the ACK accumulator follows the COMMIT of the batch.
    """
    order: list[str] = []
    original_build = consumer_mod._build_event_ack
    original_commit = Session.commit

    def spy_commit(self, *args, **kwargs):
        result = original_commit(self, *args, **kwargs)
        order.append("commit")
        return result

    def spy_build(event_id, agent_id, secret):
        order.append("appended")
        return original_build(event_id, agent_id, secret)

    messages = [(f"{i}-0", _msg(_payload(shared_secret, path=f"/f{i}", seq=i))) for i in range(3)]
    client, _p, _e = _pipeline_client(messages)
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(Session, "commit", spy_commit), \
            patch.object(consumer_mod, "_build_event_ack", spy_build):
        await consumer_mod._process_batch(client, ">")
    assert order == ["commit", "appended", "appended", "appended"]


async def test_transient_db_error_in_the_middle_leaves_only_that_event_in_the_pel(
    mem_engine, agent, shared_secret,
) -> None:
    """
    Rewritten under the amplification of 2026-10-03 of D87/RN-181 (D-10): a transient
    error of the batch transaction leaves ALL its events in the PEL, with no XACK and no
    reply. The deterministic-error case (only the offending event stays) is covered in
    `test_ingest_batched_persistence_consumer.py`.
    """
    messages = [(f"{i}-0", _msg(_payload(shared_secret, path=f"/f{i}", seq=i))) for i in range(3)]
    client, pipelines, executed = _pipeline_client(messages)
    boom = OperationalError("COMMIT", {}, Exception("connection refused"))
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2, patch.object(Session, "commit", side_effect=boom), \
            structlog.testing.capture_logs() as cap, patch.object(consumer_mod, "log", structlog.get_logger()):
        await consumer_mod._process_batch(client, ">")

    assert executed == [] and pipelines == []
    client.xack.assert_not_called()
    client.xadd.assert_not_called()
    with Session(mem_engine) as session:
        assert session.exec(select(Event)).all() == []
    errors = [r for r in cap if r["event"] == "consumer.batch_db_error"]
    assert len(errors) == 1 and errors[0]["candidates"] == 3


async def test_pipeline_failure_keeps_rows_without_xack_and_redelivery_does_not_duplicate(
    mem_engine, agent, shared_secret,
) -> None:
    messages = [(f"{i}-0", _msg(_payload(shared_secret, path=f"/f{i}", seq=i))) for i in range(3)]
    failing, _p, executed = _pipeline_client(messages, fail_pipeline=True)
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2:
        with structlog.testing.capture_logs() as cap, patch.object(consumer_mod, "log", structlog.get_logger()):
            with pytest.raises(ConnectionError):
                await consumer_mod._process_batch(failing, ">")
        assert any(r["event"] == "consumer.ack_flush_error" for r in cap)
        assert executed == [] and failing.xack.await_count == 0

        with Session(mem_engine) as session:
            assert len(session.exec(select(Event)).all()) == 3

        # PEL re-delivery of the same entries: dedup answers with event_ack, no new row.
        retry, _p2, executed2 = _pipeline_client(messages)
        await consumer_mod._process_batch(retry, "0")
    with Session(mem_engine) as session:
        events = session.exec(select(Event)).all()
    assert len(events) == 3 and len({e.event_id for e in events}) == 3
    assert executed2[0][-1][3] == ("0-0", "1-0", "2-0")


async def test_fakes_without_pipeline_publish_then_ack_once(mem_engine, agent, shared_secret) -> None:
    calls: list[str] = []
    client = AsyncMock()
    client.xreadgroup = AsyncMock(
        return_value=[(STREAM_EVENTS, [(f"{i}-0", _msg(_payload(shared_secret, path=f"/f{i}", seq=i))) for i in range(2)])]
    )
    client.xadd = AsyncMock(side_effect=lambda *a, **k: calls.append("xadd"))
    client.xack = AsyncMock(side_effect=lambda *a, **k: calls.append("xack"))
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2:
        await consumer_mod._process_batch(client, ">")
    assert calls == ["xadd", "xadd", "xack"]
    assert client.xack.await_args.args[2:] == ("0-0", "1-0")


async def test_empty_batch_emits_nothing() -> None:
    client = AsyncMock()
    client.xreadgroup = AsyncMock(return_value=[])
    await consumer_mod._process_batch(client, ">")
    client.xack.assert_not_called()
    client.pipeline.assert_not_called()


async def test_rejections_keep_their_immediate_xack_inside_a_batch(mem_engine, agent, shared_secret) -> None:
    bad = _payload(shared_secret)
    bad["signature"] = "0" * 64
    client, _p, executed = _pipeline_client([("1-0", _msg(bad))])
    e1, e2 = _patch_engines(mem_engine)
    with e1, e2:
        await consumer_mod._process_batch(client, ">")
    client.xack.assert_awaited_once_with(STREAM_EVENTS, CONSUMER_GROUP, "1-0")
    assert executed == []


def test_handle_message_signature_is_unchanged() -> None:
    assert list(inspect.signature(consumer_mod._handle_message).parameters) == ["client", "msg_id", "msg_data"]


# ── 5. NOGROUP recovery (unit, client doubles) ────────────────────────────────

def _nogroup() -> Exception:
    return Exception("NOGROUP No such key 'events' or consumer group 'fim-backend' in XREADGROUP with GROUP option")


def _scripted_client(script: list, stop: asyncio.Event):
    """xreadgroup answers from `script` (exception → raise, else return); stops the loop at the end."""
    client = AsyncMock()
    seen: list[str] = []

    async def xreadgroup(group, consumer, streams, count=None, block=None):
        seen.append(next(iter(streams.values())))
        if not script:
            stop.set()
            return []
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    client.xreadgroup = xreadgroup
    client.xgroup_create = AsyncMock()
    return client, seen


async def test_events_loop_recreates_the_group_on_nogroup() -> None:
    stop = asyncio.Event()
    # startup PEL read, then main loop: NOGROUP, PEL re-read after the recreation, then new reads.
    client, seen = _scripted_client([[], _nogroup(), [], []], stop)
    with structlog.testing.capture_logs() as cap, patch.object(consumer_mod, "log", structlog.get_logger()):
        with patch.object(asyncio, "sleep", AsyncMock()) as sleep:
            await asyncio.wait_for(consumer_mod.run_consumer(client, stop), 5)
    assert client.xgroup_create.await_count == 2  # startup + recreation
    client.xgroup_create.assert_awaited_with(STREAM_EVENTS, CONSUMER_GROUP, id="0", mkstream=True)
    assert seen[:4] == ["0", ">", "0", ">"]  # PEL, NOGROUP read, PEL re-read, keeps reading
    events = [r["event"] for r in cap]
    assert "consumer.group_recreated" in events and "consumer.loop_error" not in events
    sleep.assert_not_awaited()


async def test_events_loop_other_error_keeps_the_generic_treatment() -> None:
    stop = asyncio.Event()
    client, _seen = _scripted_client([[], ConnectionError("boom"), []], stop)
    with structlog.testing.capture_logs() as cap, patch.object(consumer_mod, "log", structlog.get_logger()):
        with patch.object(asyncio, "sleep", AsyncMock()) as sleep:
            await asyncio.wait_for(consumer_mod.run_consumer(client, stop), 5)
    assert client.xgroup_create.await_count == 1  # startup only
    assert any(r["event"] == "consumer.loop_error" for r in cap)
    assert not any(r["event"] == "consumer.group_recreated" for r in cap)
    sleep.assert_awaited_once_with(1)


async def test_events_loop_survives_a_failing_recreation() -> None:
    stop = asyncio.Event()
    client, _seen = _scripted_client([[], _nogroup(), _nogroup(), [], []], stop)
    attempts = {"n": 0}

    async def flaky_create(*a, **k):
        attempts["n"] += 1
        if attempts["n"] == 2:  # the first recreation attempt: Valkey not answering yet
            raise ConnectionError("valkey not ready")

    client.xgroup_create = flaky_create
    with structlog.testing.capture_logs() as cap, patch.object(consumer_mod, "log", structlog.get_logger()):
        with patch.object(asyncio, "sleep", AsyncMock()) as sleep:
            await asyncio.wait_for(consumer_mod.run_consumer(client, stop), 5)
    assert attempts["n"] == 3
    assert any(r["event"] == "consumer.loop_error" for r in cap)
    assert any(r["event"] == "consumer.group_recreated" for r in cap)
    sleep.assert_awaited_once_with(1)


async def test_command_ack_loop_recreates_the_group_on_nogroup() -> None:
    stop = asyncio.Event()
    client, seen = _scripted_client([[], _nogroup(), [], []], stop)
    with structlog.testing.capture_logs() as cap, patch.object(ack_mod, "log", structlog.get_logger()):
        with patch.object(asyncio, "sleep", AsyncMock()) as sleep:
            await asyncio.wait_for(ack_mod._reader_loop(client, stop), 5)
    assert client.xgroup_create.await_count == 2
    client.xgroup_create.assert_awaited_with(
        STREAM_EVENT_ACK, ack_mod.CONSUMER_GROUP_COMMAND_ACK, id="0", mkstream=True
    )
    assert seen[:4] == ["0", ">", "0", ">"]
    events = [r["event"] for r in cap]
    assert "command_ack_consumer.group_recreated" in events
    assert "command_ack_consumer.loop_error" not in events
    sleep.assert_not_awaited()


async def test_command_ack_loop_other_error_keeps_the_generic_treatment() -> None:
    stop = asyncio.Event()
    client, _seen = _scripted_client([[], ConnectionError("boom"), []], stop)
    with structlog.testing.capture_logs() as cap, patch.object(ack_mod, "log", structlog.get_logger()):
        with patch.object(asyncio, "sleep", AsyncMock()) as sleep:
            await asyncio.wait_for(ack_mod._reader_loop(client, stop), 5)
    assert client.xgroup_create.await_count == 1
    assert any(r["event"] == "command_ack_consumer.loop_error" for r in cap)
    sleep.assert_awaited_once_with(1)


def test_sweep_loop_and_gather_are_untouched() -> None:
    src = inspect.getsource(ack_mod.run_command_ack_consumer)
    assert "_reader_loop(client, stop_event)" in src and "_sweep_loop(stop_event)" in src
    assert "asyncio.gather" in src
    assert "NOGROUP" not in inspect.getsource(ack_mod._sweep_loop)


# ── 5.4 / 5.8 NOGROUP recovery against a real Valkey (opt-in) ────────────────

async def _real_client():
    client = valkey_mod.build_async_valkey_client(os.environ["VALKEY_URL"])
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("no real Valkey reachable at VALKEY_URL")
    for key in (STREAM_EVENTS, STREAM_COMMANDS, STREAM_EVENT_ACK):
        await client.delete(key)
    return client


async def _wait_for(predicate, timeout: float = 10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.1)
    return False


@pytest.mark.integration
async def test_events_consumer_recovers_from_a_destroyed_group_against_real_valkey(
    mem_engine, agent, shared_secret,
) -> None:
    client = await _real_client()
    stop = asyncio.Event()
    e1, e2 = _patch_engines(mem_engine)
    try:
        with e1, e2:
            task = asyncio.create_task(consumer_mod.run_consumer(client, stop))
            first = _payload(shared_secret, path="/before")
            assert await _wait_for(lambda: _group_exists(client, STREAM_EVENTS, CONSUMER_GROUP))
            await client.xadd(STREAM_EVENTS, {"data": json.dumps(first)})
            assert await _wait_for(lambda: _xlen_is(client, STREAM_COMMANDS, 1))

            await client.xgroup_destroy(STREAM_EVENTS, CONSUMER_GROUP)
            second = _payload(shared_secret, path="/after")
            await client.xadd(STREAM_EVENTS, {"data": json.dumps(second)})
            assert await _wait_for(lambda: _xlen_is(client, STREAM_COMMANDS, 2), timeout=15.0)

            stop.set()
            await asyncio.wait_for(task, 10)
        with Session(mem_engine) as session:
            paths = {e.path for e in session.exec(select(Event)).all()}
        assert paths == {"/before", "/after"}
        assert await _group_exists(client, STREAM_EVENTS, CONSUMER_GROUP)
    finally:
        stop.set()
        for key in (STREAM_EVENTS, STREAM_COMMANDS):
            await client.delete(key)
        await client.aclose()


@pytest.mark.integration
async def test_command_ack_consumer_recovers_from_a_destroyed_group_against_real_valkey(
    mem_engine, agent, shared_secret,
) -> None:
    from app.modules.rules.models import PublishedCommand

    client = await _real_client()
    stop = asyncio.Event()
    with Session(mem_engine) as session:
        session.add(
            PublishedCommand(
                command_id="cmd-nogroup", command_type="update_config", target_agent_id=agent,
                payload="{}", ack_status="pending", ruleset_version=1,
            )
        )
        session.commit()
    try:
        with patch.object(ack_mod, "engine", mem_engine):
            task = asyncio.create_task(ack_mod._reader_loop(client, stop))
            assert await _wait_for(
                lambda: _group_exists(client, STREAM_EVENT_ACK, ack_mod.CONSUMER_GROUP_COMMAND_ACK)
            )
            await client.xgroup_destroy(STREAM_EVENT_ACK, ack_mod.CONSUMER_GROUP_COMMAND_ACK)
            ack = {"command_id": "cmd-nogroup", "agent_id": agent, "status": "ok"}
            ack["signature"] = sign_payload(shared_secret, ack)
            await client.xadd(STREAM_EVENT_ACK, {"data": json.dumps(ack)})

            async def acked() -> bool:
                with Session(mem_engine) as session:
                    cmd = session.exec(
                        select(PublishedCommand).where(PublishedCommand.command_id == "cmd-nogroup")
                    ).first()
                    return cmd is not None and cmd.ack_status == "acked"

            assert await _wait_for(acked, timeout=15.0)
            stop.set()
            await asyncio.wait_for(task, 10)
    finally:
        stop.set()
        await client.delete(STREAM_EVENT_ACK)
        await client.aclose()


async def _group_exists(client, stream: str, group: str) -> bool:
    try:
        return any(g["name"] == group for g in await client.xinfo_groups(stream))
    except Exception:
        return False


async def _xlen_is(client, stream: str, n: int) -> bool:
    return await client.xlen(stream) >= n


# ── 6. Compose AOF flags ──────────────────────────────────────────────────────

def test_base_compose_valkey_runs_with_aof() -> None:
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    assert re.search(
        r'command:\s*\["valkey-server",\s*"--appendonly",\s*"yes",\s*"--appendfsync",\s*"everysec"\]', text
    )


def test_tls_override_repeats_aof_and_keeps_tls_flags() -> None:
    text = (REPO_ROOT / "docker-compose.tls.yml").read_text()
    block = text.split("command: >", 1)[1].split("healthcheck:", 1)[0]
    for flag in ("--appendonly yes", "--appendfsync everysec", "--port 0", "--tls-port 6380"):
        assert flag in block
