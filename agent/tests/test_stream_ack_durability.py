"""Tests de stream-ack-durability (Change 42, D37/RN-131) — agente.

Cubre tasks.md secciones 1-5 y 13:
  - Config: discard_dir, techos de reintento/retry_after/descarte (1.2).
  - Cola: sobre con metadata de intentos, tolerancia al formato anterior,
    directorio de descarte (2, 13.1-13.3).
  - Publisher: sent_at + firma al publicar, respuesta tipada, backpressure,
    techo de reintentos, contención D-4 (3, 4, 13.4-13.12).
  - Heartbeat: discarded_events firmado (5, 13.13).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent.config import AgentConfig, PublisherConfig, StorageConfig
from agent.heartbeat import HeartbeatPublisher
from agent.publisher import _ACK_TIMEOUT_S, _MIN_RETRY_AFTER_S, Publisher
from agent.queue import EventQueue, _iso_to_epoch_ms
from agent.state import AgentState
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


def _make_config(tmp_path: Path, **publisher_kwargs: object) -> AgentConfig:
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
            discard_dir=str(tmp_path / "discarded"),
        ),
        publisher=PublisherConfig(**publisher_kwargs),  # type: ignore[arg-type]
    )


@pytest.fixture()
def config(tmp_path: Path, shared_secret: bytes) -> AgentConfig:
    return _make_config(tmp_path)


@pytest.fixture()
def queue(config: AgentConfig) -> EventQueue:
    return EventQueue(
        config.storage.queue_dir,
        discard_dir=config.storage.discard_dir,
        max_discard_files=config.publisher.max_discard_files,
    )


@pytest.fixture()
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.xadd = AsyncMock(return_value="1-0")
    client.xread = AsyncMock(return_value=[])
    return client


@pytest.fixture()
def publisher(config: AgentConfig, queue: EventQueue, mock_client: AsyncMock) -> Publisher:
    return Publisher(config, queue, mock_client)


def _make_signed_msg(secret: bytes, payload: dict) -> dict[str, str]:
    sig = sign_payload(secret, payload)
    full = {**payload, "signature": sig}
    return {"data": json.dumps(full, sort_keys=True, separators=(",", ":"))}


def _event(event_id: str, detected_at: str | None = None) -> dict:
    return {
        "event_id": event_id,
        "detected_at": detected_at or datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "path": "/etc/passwd",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 13.1-13.3 — Cola: sobre, tolerancia legacy, descarte
# ═══════════════════════════════════════════════════════════════════════════


def test_enqueue_writes_envelope_without_signature_or_sent_at(queue: EventQueue) -> None:
    path = queue.enqueue(_event("e1"))
    raw = json.loads(path.read_bytes())
    assert raw["attempts"] == 0
    assert raw["first_attempt_at"] is None
    assert "signature" not in raw["payload"]
    assert "sent_at" not in raw["payload"]


def test_legacy_bare_payload_file_wrapped_as_zero_attempts(queue: EventQueue) -> None:
    legacy = _event("legacy1", "2026-01-01T00:00:00+00:00")
    f = queue._dir / f"{_iso_to_epoch_ms(legacy['detected_at']):016d}_legacy1.json"
    f.write_text(json.dumps(legacy))

    entries = queue.iter_entries()
    assert len(entries) == 1
    assert entries[0]["attempts"] == 0
    assert entries[0]["first_attempt_at"] is None
    assert entries[0]["payload"]["event_id"] == "legacy1"


def test_mixed_queue_directory_drains_in_fifo_order(queue: EventQueue) -> None:
    t_old, t_new = "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"
    legacy = _event("old1", t_old)
    legacy_file = queue._dir / f"{_iso_to_epoch_ms(t_old):016d}_old1.json"
    legacy_file.write_text(json.dumps(legacy))  # formato anterior, escrito a mano

    queue.enqueue(_event("new1", t_new))  # formato con sobre

    assert [e["event_id"] for e in queue.iter_fifo()] == ["old1", "new1"]
    assert all(e["attempts"] == 0 for e in queue.iter_entries())


def test_bump_attempts_persists_increment_and_survives_reread(queue: EventQueue) -> None:
    queue.enqueue(_event("e2"))
    assert queue.bump_attempts("e2") == 1
    assert queue.bump_attempts("e2") == 2
    assert queue.get_attempts("e2") == 2


def test_bump_attempts_sets_first_attempt_at_once(queue: EventQueue) -> None:
    queue.enqueue(_event("e3"))
    queue.bump_attempts("e3")
    f = queue._find_file("e3")
    assert f is not None
    first = json.loads(f.read_bytes())["first_attempt_at"]
    assert first is not None
    queue.bump_attempts("e3")
    assert json.loads(f.read_bytes())["first_attempt_at"] == first


def test_bump_attempts_nonexistent_returns_zero_without_creating(queue: EventQueue) -> None:
    assert queue.bump_attempts("ghost") == 0
    assert queue.queue_size == 0


def test_get_attempts_nonexistent_is_zero(queue: EventQueue) -> None:
    assert queue.get_attempts("ghost") == 0


def test_discard_moves_event_with_reason_and_timestamp(queue: EventQueue) -> None:
    queue.enqueue(_event("d1"))
    assert queue.discard("d1", "clock_skew") is True
    assert queue.queue_size == 0
    assert queue.contains("d1") is False

    discarded = list(queue._discard_dir.glob("*.json"))
    assert len(discarded) == 1
    record = json.loads(discarded[0].read_bytes())
    assert record["discard_reason"] == "clock_skew"
    assert record["discarded_at"] is not None
    assert record["payload"]["event_id"] == "d1"


def test_discard_nonexistent_returns_false(queue: EventQueue) -> None:
    assert queue.discard("ghost", "clock_skew") is False


def test_discard_does_not_affect_queue_pressure_or_total_bytes(queue: EventQueue) -> None:
    queue.enqueue(_event("d2"))
    queue.enqueue(_event("d3"))
    queue.discard("d2", "invalid_schema")

    assert queue.queue_size == 1
    # Sobrevive solo d3: la presión refleja únicamente la cola, nunca el
    # directorio de descarte.
    assert list(queue._discard_dir.glob("*.json"))
    assert queue.queue_pressure == pytest.approx(queue._total_bytes() / (100 * 1024 * 1024))


def test_discard_directory_drops_oldest_past_bound(tmp_path: Path) -> None:
    q = EventQueue(tmp_path / "queue", discard_dir=tmp_path / "discarded", max_discard_files=2)
    for i in range(3):
        eid = f"e{i}"
        q.enqueue(_event(eid, f"2026-01-0{i + 1}T00:00:00+00:00"))
        q.discard(eid, "clock_skew")

    remaining = {
        json.loads(f.read_bytes())["payload"]["event_id"] for f in q._discard_dir.glob("*.json")
    }
    assert len(remaining) == 2
    assert "e0" not in remaining  # el más antiguo se descarta primero


def test_sweep_orphaned_tmp_covers_discard_dir(tmp_path: Path) -> None:
    discard_dir = tmp_path / "discarded"
    discard_dir.mkdir(parents=True)
    orphan = discard_dir / "1234_abc.json.tmp"
    orphan.write_text("{}")

    EventQueue(tmp_path / "queue", discard_dir=discard_dir)

    assert not orphan.exists()


def test_discard_dir_created_on_demand(tmp_path: Path) -> None:
    q = EventQueue(tmp_path / "queue", discard_dir=tmp_path / "discarded")
    assert not q._discard_dir.exists()
    q.enqueue(_event("d4"))
    q.discard("d4", "clock_skew")
    assert q._discard_dir.exists()


def test_remove_still_works_on_envelope_format(queue: EventQueue) -> None:
    queue.enqueue(_event("r1"))
    assert queue.remove("r1") is True
    assert queue.queue_size == 0


# ═══════════════════════════════════════════════════════════════════════════
# 13.4 — Firma al publicar: sent_at distinto, ambas firmas válidas
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_two_transmissions_have_different_sent_at_and_both_verify(
    publisher: Publisher, shared_secret: bytes
) -> None:
    await publisher.publish({"path": "/etc/hosts", "hash_detected": "aaa"})
    event_id = next(iter(publisher._pending))
    _, payload = publisher._pending[event_id]

    await publisher._xadd(payload)  # segunda transmisión (simula un reintento)

    calls = publisher._client.xadd.call_args_list
    assert len(calls) == 2
    first = json.loads(calls[0][0][1]["data"])
    second = json.loads(calls[1][0][1]["data"])
    assert first["sent_at"] != second["sent_at"]
    assert verify_payload(shared_secret, first)
    assert verify_payload(shared_secret, second)
    assert first["detected_at"] == second["detected_at"]


def test_queued_payload_has_no_signature_or_sent_at(publisher: Publisher, queue: EventQueue) -> None:
    asyncio.run(publisher.publish({"path": "/etc/hosts", "hash_detected": "bbb"}))
    entries = queue.iter_entries()
    assert len(entries) == 1
    stored = entries[0]["payload"]
    assert "signature" not in stored
    assert "sent_at" not in stored


@pytest.mark.asyncio
async def test_secret_rotation_next_transmission_signs_with_new_secret(
    publisher: Publisher, shared_secret: bytes
) -> None:
    await publisher.publish({"path": "/etc/hosts", "hash_detected": "ccc"})
    event_id = next(iter(publisher._pending))
    _, payload = publisher._pending[event_id]

    new_secret = os.urandom(32)
    publisher._shared_secret = new_secret  # simula rotación + recarga

    await publisher._xadd(payload)

    data = json.loads(publisher._client.xadd.call_args_list[-1][0][1]["data"])
    assert verify_payload(new_secret, data)
    assert not verify_payload(shared_secret, data)


# ═══════════════════════════════════════════════════════════════════════════
# 13.6 / 13.11 — Respuesta tipada, D-4 containment
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_terminal_nack_discards_event_with_reason(
    publisher: Publisher, queue: EventQueue, shared_secret: bytes
) -> None:
    await publisher.publish({"path": "/etc/hosts", "hash_detected": "ddd"})
    event_id = next(iter(publisher._pending))

    nack = {"type": "event_nack", "event_id": event_id, "reason": "clock_skew"}
    verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, nack))
    await publisher._handle_command_async(verified)

    assert queue.contains(event_id) is False
    assert event_id not in publisher._pending
    assert publisher.discarded_events == 1
    discarded = list(queue._discard_dir.glob("*.json"))
    assert len(discarded) == 1
    assert json.loads(discarded[0].read_bytes())["discard_reason"] == "clock_skew"


@pytest.mark.asyncio
async def test_rate_limited_nack_retains_event_and_applies_backpressure(
    publisher: Publisher, queue: EventQueue, shared_secret: bytes
) -> None:
    await publisher.publish({"path": "/etc/hosts", "hash_detected": "eee"})
    event_id = next(iter(publisher._pending))
    attempts_before = queue.get_attempts(event_id)

    nack = {
        "type": "event_nack",
        "event_id": event_id,
        "reason": "rate_limited",
        "retry_after": 5.0,
    }
    verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, nack))
    await publisher._handle_command_async(verified)

    assert queue.contains(event_id) is True
    assert queue.get_attempts(event_id) == attempts_before
    assert publisher._is_paused() is True
    assert publisher.discarded_events == 0

    calls_before = publisher._client.xadd.call_count
    await publisher.publish({"path": "/etc/shadow", "hash_detected": "fff"})
    assert publisher._client.xadd.call_count == calls_before  # sigue pausado: no XADD
    assert queue.queue_size == 2  # pero el nuevo evento se encoló igual


@pytest.mark.asyncio
async def test_schema_version_unsupported_nack_is_retainable_like_rate_limited(
    publisher: Publisher, queue: EventQueue, shared_secret: bytes
) -> None:
    """D37 amendment: schema_version_unsupported comparte tratamiento con
    rate_limited — lo que decide es la presencia de retry_after, no el
    motivo literal (cross-layer contract del apply)."""
    await publisher.publish({"path": "/etc/hosts", "hash_detected": "sss"})
    event_id = next(iter(publisher._pending))

    nack = {
        "type": "event_nack",
        "event_id": event_id,
        "reason": "schema_version_unsupported",
        "retry_after": 3.0,
    }
    verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, nack))
    await publisher._handle_command_async(verified)

    assert queue.contains(event_id) is True
    assert publisher._is_paused() is True
    assert publisher.discarded_events == 0


@pytest.mark.asyncio
async def test_nack_for_unknown_event_id_is_ignored(
    publisher: Publisher, queue: EventQueue, shared_secret: bytes
) -> None:
    stray_id = str(uuid.uuid4())
    nack = {"type": "event_nack", "event_id": stray_id, "reason": "clock_skew"}
    verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, nack))

    await publisher._handle_command_async(verified)

    assert queue.queue_size == 0
    assert list(queue._discard_dir.glob("*.json")) == []
    assert publisher.discarded_events == 0


@pytest.mark.asyncio
async def test_rate_limited_nack_for_unknown_event_id_does_not_apply_backpressure(
    publisher: Publisher, shared_secret: bytes
) -> None:
    stray_id = str(uuid.uuid4())
    nack = {
        "type": "event_nack",
        "event_id": stray_id,
        "reason": "rate_limited",
        "retry_after": 5.0,
    }
    verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, nack))

    await publisher._handle_command_async(verified)

    assert publisher._is_paused() is False


@pytest.mark.asyncio
async def test_ack_for_unknown_event_id_is_ignored(
    publisher: Publisher, queue: EventQueue, shared_secret: bytes
) -> None:
    stray_id = str(uuid.uuid4())
    ack = {"type": "event_ack", "event_id": stray_id}
    verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, ack))

    await publisher._handle_command_async(verified)

    assert queue.queue_size == 0  # no-op: nada que borrar, nada que crear


@pytest.mark.asyncio
async def test_unknown_message_type_is_noop(
    publisher: Publisher, queue: EventQueue, shared_secret: bytes
) -> None:
    await publisher.publish({"path": "/etc/hosts", "hash_detected": "iii"})
    event_id = next(iter(publisher._pending))
    size_before = queue.queue_size

    weird = {"type": "some_future_type", "event_id": event_id}
    verified = publisher._verify_and_parse(_make_signed_msg(shared_secret, weird))
    await publisher._handle_command_async(verified)

    assert queue.queue_size == size_before
    assert event_id in publisher._pending


# ═══════════════════════════════════════════════════════════════════════════
# 13.8 — retry_after: techo y piso
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_retry_after_clamped_to_ceiling(publisher: Publisher) -> None:
    effective = publisher._apply_backpressure(999999.0)
    assert effective == publisher._config.publisher.max_retry_after_s


@pytest.mark.asyncio
async def test_retry_after_missing_negative_or_non_numeric_uses_floor(publisher: Publisher) -> None:
    assert publisher._apply_backpressure(None) == _MIN_RETRY_AFTER_S
    assert publisher._apply_backpressure(-5) == _MIN_RETRY_AFTER_S
    assert publisher._apply_backpressure(0) == _MIN_RETRY_AFTER_S
    assert publisher._apply_backpressure("not-a-number") == _MIN_RETRY_AFTER_S


# ═══════════════════════════════════════════════════════════════════════════
# 13.7 / 13.9 — Backpressure global y techo de reintentos
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_drain_and_xadd_suppressed_while_paused(
    publisher: Publisher, queue: EventQueue
) -> None:
    queue.enqueue(_event("paused1"))
    publisher._paused_until = asyncio.get_running_loop().time() + 60.0

    await publisher._drain_queue()

    assert publisher._client.xadd.call_count == 0
    assert "paused1" in publisher._pending  # sembrado, pero sin transmitir


@pytest.mark.asyncio
async def test_attempt_ceiling_discards_via_retry_loop(
    tmp_path: Path, shared_secret: bytes
) -> None:
    cfg = _make_config(tmp_path, max_publish_attempts=2)
    queue = EventQueue(
        cfg.storage.queue_dir,
        discard_dir=cfg.storage.discard_dir,
        max_discard_files=cfg.publisher.max_discard_files,
    )
    client = AsyncMock()
    client.xadd = AsyncMock(return_value="1-0")
    pub = Publisher(cfg, queue, client)

    await pub.publish({"path": "/etc/hosts", "hash_detected": "ggg"})
    event_id = next(iter(pub._pending))
    old_time, payload = pub._pending[event_id]
    pub._pending[event_id] = (old_time - _ACK_TIMEOUT_S - 1, payload)

    stop_event = asyncio.Event()
    calls = {"n": 0}

    async def _fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] >= 4:
            stop_event.set()
        if event_id in pub._pending:
            t, p = pub._pending[event_id]
            pub._pending[event_id] = (t - _ACK_TIMEOUT_S - 1, p)

    original_sleep = asyncio.sleep
    asyncio.sleep = _fake_sleep  # type: ignore[assignment]
    try:
        await pub._retry_loop(stop_event)
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]

    assert event_id not in pub._pending
    assert queue.contains(event_id) is False
    discarded = list(queue._discard_dir.glob("*.json"))
    assert len(discarded) == 1
    assert json.loads(discarded[0].read_bytes())["discard_reason"] == "max_attempts_exceeded"
    assert pub.discarded_events == 1


# ═══════════════════════════════════════════════════════════════════════════
# 13.10 — El contador de intentos sobrevive a un reinicio simulado
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_attempt_count_survives_simulated_restart(
    tmp_path: Path, shared_secret: bytes
) -> None:
    cfg = _make_config(tmp_path)
    queue1 = EventQueue(cfg.storage.queue_dir, discard_dir=cfg.storage.discard_dir)
    client1 = AsyncMock()
    client1.xadd = AsyncMock(return_value="1-0")
    pub1 = Publisher(cfg, queue1, client1)

    await pub1.publish({"path": "/etc/hosts", "hash_detected": "hhh"})
    event_id = next(iter(pub1._pending))
    queue1.bump_attempts(event_id)  # un intento extra antes del "crash"
    attempts_before = queue1.get_attempts(event_id)
    assert attempts_before == 2

    # "Reinicio": nueva EventQueue/Publisher sobre el mismo directorio.
    queue2 = EventQueue(cfg.storage.queue_dir, discard_dir=cfg.storage.discard_dir)
    assert queue2.get_attempts(event_id) == attempts_before

    client2 = AsyncMock()
    client2.xadd = AsyncMock(return_value="1-0")
    pub2 = Publisher(cfg, queue2, client2)
    await pub2._drain_queue()

    assert queue2.get_attempts(event_id) == attempts_before + 1


# ═══════════════════════════════════════════════════════════════════════════
# 13.13 — Heartbeat: discarded_events firmado
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_heartbeat_carries_discarded_events_and_is_signed(
    tmp_path: Path, shared_secret: bytes
) -> None:
    cfg = _make_config(tmp_path)
    queue = EventQueue(cfg.storage.queue_dir, discard_dir=cfg.storage.discard_dir)
    client = AsyncMock()
    client.xadd = AsyncMock(return_value="1-0")
    pub = Publisher(cfg, queue, client)

    await pub.publish({"path": "/etc/hosts", "hash_detected": "jjj"})
    event_id = next(iter(pub._pending))
    nack = {"type": "event_nack", "event_id": event_id, "reason": "clock_skew"}
    verified = pub._verify_and_parse(_make_signed_msg(shared_secret, nack))
    await pub._handle_command_async(verified)
    assert pub.discarded_events == 1

    state = AgentState(state_path=tmp_path / "state.json")
    hb_client = AsyncMock()
    hb_client.xadd = AsyncMock(return_value="1-0")
    hb = HeartbeatPublisher(cfg, queue, state, hb_client, publisher=pub, shared_secret=shared_secret)

    await hb._publish()

    data = json.loads(hb_client.xadd.call_args[0][1]["data"])
    assert data["discarded_events"] == 1
    assert verify_payload(shared_secret, data)


@pytest.mark.asyncio
async def test_heartbeat_reports_zero_discarded_events_by_default(
    tmp_path: Path, shared_secret: bytes
) -> None:
    cfg = _make_config(tmp_path)
    queue = EventQueue(cfg.storage.queue_dir, discard_dir=cfg.storage.discard_dir)
    client = AsyncMock()
    pub = Publisher(cfg, queue, client)
    state = AgentState(state_path=tmp_path / "state.json")
    hb_client = AsyncMock()
    hb_client.xadd = AsyncMock(return_value="1-0")
    hb = HeartbeatPublisher(cfg, queue, state, hb_client, publisher=pub, shared_secret=shared_secret)

    await hb._publish()

    data = json.loads(hb_client.xadd.call_args[0][1]["data"])
    assert data["discarded_events"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# Config — validadores de los parámetros nuevos (task 1.2)
# ═══════════════════════════════════════════════════════════════════════════


def test_publisher_config_defaults_match_d37_appendix() -> None:
    cfg = PublisherConfig()
    assert cfg.max_publish_attempts == 20
    assert cfg.max_retry_after_s == 60.0
    assert cfg.max_discard_files == 1000


@pytest.mark.parametrize("field,value", [
    ("max_publish_attempts", 0),
    ("max_publish_attempts", -1),
    ("max_discard_files", 0),
    ("max_retry_after_s", 0.0),
    ("max_retry_after_s", -1.0),
])
def test_publisher_config_rejects_non_positive(field: str, value: object) -> None:
    with pytest.raises(Exception):
        PublisherConfig(**{field: value})


def test_storage_config_discard_dir_default() -> None:
    cfg = StorageConfig(baseline_dir="/a", queue_dir="/b", journal_dir="/c")
    assert cfg.discard_dir == "/var/lib/fim-agent/discarded"


def test_storage_config_discard_dir_rejects_empty() -> None:
    with pytest.raises(Exception):
        StorageConfig(baseline_dir="/a", queue_dir="/b", journal_dir="/c", discard_dir="  ")
