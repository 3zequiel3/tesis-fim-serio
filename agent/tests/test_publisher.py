"""Tests del publisher de eventos FIM (Change 08, task 9.2)."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.config import AgentConfig, StorageConfig
from agent.publisher import Publisher, _ACK_TIMEOUT_S
from agent.queue import EventQueue
from agent.streams import sign_payload, verify_payload


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def shared_secret(tmp_path: Path) -> bytes:
    secret = os.urandom(32)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o700)
    p = secrets_dir / "shared_secret"
    fd = os.open(str(p), os.O_CREAT | os.O_WRONLY, 0o400)
    with os.fdopen(fd, "wb") as f:
        f.write(secret)
    return secret


@pytest.fixture()
def config(tmp_path: Path, shared_secret: bytes) -> AgentConfig:
    secrets_dir = tmp_path / "secrets"
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
            secrets_dir=str(secrets_dir),
            certs_dir=str(tmp_path / "certs"),
        ),
    )


@pytest.fixture()
def queue(config: AgentConfig) -> EventQueue:
    return EventQueue(config.storage.queue_dir)


@pytest.fixture()
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.xadd = AsyncMock(return_value="1-0")
    client.xread = AsyncMock(return_value=[])
    return client


@pytest.fixture()
def publisher(config: AgentConfig, queue: EventQueue, mock_client: AsyncMock) -> Publisher:
    return Publisher(config, queue, mock_client)


# ── payload firmado verificable ───────────────────────────────────────────────

def test_publish_payload_has_valid_signature(
    publisher: Publisher, shared_secret: bytes
) -> None:
    asyncio.run(publisher.publish({"path": "/etc/hosts", "hash_detected": "aaa"}))
    xadd_call = publisher._client.xadd.call_args
    data_str = xadd_call[0][1]["data"]
    payload = json.loads(data_str)
    assert "signature" in payload
    assert verify_payload(shared_secret, payload)


def test_publish_includes_required_fields(publisher: Publisher) -> None:
    asyncio.run(publisher.publish({"path": "/etc/hosts", "hash_detected": "bbb"}))
    xadd_call = publisher._client.xadd.call_args
    data_str = xadd_call[0][1]["data"]
    payload = json.loads(data_str)
    for field in ("event_id", "agent_id", "detected_at", "schema_version", "signature"):
        assert field in payload, f"Missing field: {field}"


# ── encolar antes de XADD ─────────────────────────────────────────────────────

def test_publish_enqueues_before_xadd(publisher: Publisher, queue: EventQueue) -> None:
    """El archivo de cola debe existir aunque XADD falle."""
    publisher._client.xadd = AsyncMock(side_effect=Exception("Valkey down"))
    try:
        asyncio.run(publisher.publish({"path": "/etc/hosts", "hash_detected": "ccc"}))
    except Exception:
        pass
    assert queue.queue_size == 1


# ── drenaje FIFO ──────────────────────────────────────────────────────────────

def test_drain_queue_publishes_in_fifo_order(
    publisher: Publisher, queue: EventQueue
) -> None:
    now = datetime.now(timezone.utc)
    e1 = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "test-agent-01",
        "detected_at": (now - timedelta(hours=1)).isoformat(),
        "schema_version": 1,
        "path": "/a",
        "hash_detected": "h1",
        "signature": "",
    }
    e2 = {
        "event_id": str(uuid.uuid4()),
        "agent_id": "test-agent-01",
        "detected_at": now.isoformat(),
        "schema_version": 1,
        "path": "/b",
        "hash_detected": "h2",
        "signature": "",
    }
    queue.enqueue(e1)
    queue.enqueue(e2)

    asyncio.run(publisher._drain_queue())

    calls = publisher._client.xadd.call_args_list
    assert len(calls) == 2
    first = json.loads(calls[0][0][1]["data"])
    second = json.loads(calls[1][0][1]["data"])
    assert first["path"] == "/a"
    assert second["path"] == "/b"


# ── reintento a 60 s ──────────────────────────────────────────────────────────

def test_retry_republishes_after_timeout(publisher: Publisher) -> None:
    asyncio.run(publisher.publish({"path": "/etc/shadow", "hash_detected": "ddd"}))
    event_id = list(publisher._pending.keys())[0]

    # Simular que pasaron >60 s retrocediendo el timestamp
    old_time, payload = publisher._pending[event_id]
    publisher._pending[event_id] = (old_time - _ACK_TIMEOUT_S - 1, payload)

    # Ejecutar la lógica de retry directamente
    async def _do_retry() -> None:
        now = asyncio.get_event_loop().time()
        for eid, (published_at, pld) in list(publisher._pending.items()):
            if now - published_at >= _ACK_TIMEOUT_S:
                await publisher._xadd(pld)

    asyncio.run(_do_retry())

    # 2 llamadas: la publicación inicial + el reintento
    assert publisher._client.xadd.call_count == 2


@pytest.mark.asyncio
async def test_drop_oldest_event_is_removed_from_pending_and_never_retried(
    publisher: Publisher,
    queue: EventQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capacity eviction must retire the matching in-memory retry entry."""
    import agent.publisher as publisher_module
    import agent.queue as queue_module

    await publisher.publish({"path": "/same", "hash_detected": "same"})
    evicted_id = next(iter(publisher._pending))
    first_size = queue._total_bytes()

    # Each event fits independently, but the pair does not.
    monkeypatch.setattr(queue_module, "_MAX_BYTES", first_size + 1)
    await publisher.publish({"path": "/same", "hash_detected": "same"})

    assert queue.contains(evicted_id) is False
    assert evicted_id not in publisher._pending

    publisher._client.xadd.reset_mock()
    monkeypatch.setattr(publisher_module, "_ACK_TIMEOUT_S", 0)
    stop_event = asyncio.Event()

    async def stop_after_sleep(_delay: float) -> None:
        stop_event.set()

    monkeypatch.setattr(publisher_module.asyncio, "sleep", stop_after_sleep)
    await publisher._retry_loop(stop_event)

    retransmitted_ids = {
        json.loads(call.args[1]["data"])["event_id"]
        for call in publisher._client.xadd.call_args_list
    }
    assert evicted_id not in retransmitted_ids


# ── C2: HMAC verification en _verify_and_parse ───────────────────────────────

def _make_signed_msg(secret: bytes, payload: dict) -> dict[str, str]:
    """Construye un msg_data stream como lo haría el backend."""
    sig = sign_payload(secret, payload)
    full = {**payload, "signature": sig}
    return {"data": json.dumps(full, sort_keys=True, separators=(",", ":"))}


def test_verify_and_parse_accepts_valid_signature(
    publisher: Publisher, shared_secret: bytes
) -> None:
    payload = {"type": "event_ack", "event_id": str(uuid.uuid4()), "agent_id": "test-agent-01"}
    msg = _make_signed_msg(shared_secret, payload)
    result = publisher._verify_and_parse(msg)
    assert result is not None
    assert result["type"] == "event_ack"


def test_verify_and_parse_rejects_invalid_signature(publisher: Publisher) -> None:
    payload = {"type": "event_ack", "event_id": str(uuid.uuid4()), "signature": "badsig"}
    msg = {"data": json.dumps(payload)}
    result = publisher._verify_and_parse(msg)
    assert result is None


def test_verify_and_parse_rejects_missing_signature(publisher: Publisher) -> None:
    payload = {"type": "event_ack", "event_id": str(uuid.uuid4())}
    msg = {"data": json.dumps(payload)}
    result = publisher._verify_and_parse(msg)
    assert result is None


def test_verify_and_parse_rejects_malformed_json(publisher: Publisher) -> None:
    msg = {"data": "not-valid-json{{{"}
    result = publisher._verify_and_parse(msg)
    assert result is None


@pytest.mark.asyncio
async def test_invalid_hmac_command_does_not_modify_queue(
    publisher: Publisher, queue: EventQueue, shared_secret: bytes
) -> None:
    """Comando con firma inválida es descartado: queue no se modifica, callbacks no se invocan."""
    update_config_called: list[bool] = []
    publisher.register_callbacks(
        on_update_config=lambda paths: update_config_called.append(True),
    )

    # Enqueue un evento real para que queue_size > 0
    event_id = str(uuid.uuid4())
    queue.enqueue({
        "event_id": event_id, "agent_id": "test-agent-01",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1, "path": "/etc/hosts", "signature": "",
    })
    initial_size = queue.queue_size

    # Mensaje con firma inválida
    bad_msg = {"data": json.dumps({
        "type": "update_config", "watch_paths": ["/new/path"], "signature": "invalidsig"
    })}
    payload = publisher._verify_and_parse(bad_msg)
    assert payload is None  # rechazado en el chokepoint

    # Queue no fue modificada y callback no fue invocado
    assert queue.queue_size == initial_size
    assert update_config_called == []


@pytest.mark.asyncio
async def test_valid_event_ack_clears_pending(
    publisher: Publisher, shared_secret: bytes
) -> None:
    """Un event_ack correctamente firmado limpia el pending del publisher."""
    await publisher.publish({"path": "/etc/hosts", "hash_detected": "abc"})
    event_id = list(publisher._pending.keys())[0]

    ack_payload = {
        "type": "event_ack",
        "event_id": event_id,
        "agent_id": "test-agent-01",
    }
    msg = _make_signed_msg(shared_secret, ack_payload)
    verified = publisher._verify_and_parse(msg)
    assert verified is not None
    await publisher._handle_command_async(verified)

    assert event_id not in publisher._pending
