"""US-21 (W3), D72/RN-166: el heartbeat agrega el flag booleano
`queue_pressure_high`, derivado en el agente de una sola lectura del ratio
`queue_pressure` contra `QUEUE_PRESSURE_HIGH_THRESHOLD` (agent/queue.py).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.heartbeat import HeartbeatPublisher
from agent.queue import QUEUE_PRESSURE_HIGH_THRESHOLD
from agent.streams import verify_payload


class _CountingPressureQueue:
    """Fake de EventQueue cuyo `queue_pressure` cuenta cuántas veces se lee."""

    def __init__(self, pressure: float) -> None:
        self._pressure = pressure
        self.queue_size = 0
        self.reads = 0

    @property
    def queue_pressure(self) -> float:
        self.reads += 1
        return self._pressure


def _make_state() -> MagicMock:
    state = MagicMock()
    state.ruleset_version = 1
    return state


def _make_client() -> MagicMock:
    client = MagicMock()
    client.xadd = AsyncMock(return_value="1-0")
    return client


async def _publish_and_get_payload(queue: _CountingPressureQueue, shared_secret: bytes | None = None) -> dict:
    client = _make_client()
    hb = HeartbeatPublisher(
        config=MagicMock(agent_id="agent-qph-test"),
        queue=queue,
        state=_make_state(),
        client=client,
        shared_secret=shared_secret,
    )
    await hb._publish(shutdown=False)
    return json.loads(client.xadd.call_args[0][1]["data"])


@pytest.mark.asyncio
async def test_pressure_above_threshold_flag_true() -> None:
    queue = _CountingPressureQueue(0.85)
    data = await _publish_and_get_payload(queue)
    assert data["queue_pressure_high"] is True
    assert data["queue_pressure"] == 0.85
    assert queue.reads == 1


@pytest.mark.asyncio
async def test_pressure_well_below_threshold_flag_false() -> None:
    queue = _CountingPressureQueue(0.5)
    data = await _publish_and_get_payload(queue)
    assert data["queue_pressure_high"] is False
    assert queue.reads == 1


@pytest.mark.asyncio
async def test_pressure_exactly_at_threshold_flag_false() -> None:
    """Comparación estricta (`>`): al superar 0.8, no al alcanzarlo."""
    queue = _CountingPressureQueue(QUEUE_PRESSURE_HIGH_THRESHOLD)
    data = await _publish_and_get_payload(queue)
    assert data["queue_pressure_high"] is False
    assert queue.reads == 1


@pytest.mark.asyncio
async def test_flag_is_bool_not_int() -> None:
    """El JSON serializado lleva `true`, no `1` (bool JSON, no entero)."""
    queue = _CountingPressureQueue(0.9)
    client = _make_client()
    hb = HeartbeatPublisher(
        config=MagicMock(agent_id="agent-qph-test"),
        queue=queue,
        state=_make_state(),
        client=client,
    )
    await hb._publish(shutdown=False)
    raw = client.xadd.call_args[0][1]["data"]
    assert '"queue_pressure_high":true' in raw
    data = json.loads(raw)
    assert data["queue_pressure_high"] is True


@pytest.mark.asyncio
async def test_signature_verifies_over_payload_with_new_key() -> None:
    shared_secret = b"x" * 32
    queue = _CountingPressureQueue(0.85)
    data = await _publish_and_get_payload(queue, shared_secret=shared_secret)
    assert "queue_pressure_high" in data
    assert "signature" in data
    assert verify_payload(shared_secret, data)
