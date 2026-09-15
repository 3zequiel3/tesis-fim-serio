"""US-21 (W16): the agent publishes a heartbeat every 10 seconds.

The backend derives `offline` (30 s) and `dead` (5 min) from missing
heartbeats, so the publication interval is part of the contract, not an
implementation detail. These tests pin the interval without sleeping.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent import heartbeat as heartbeat_module
from agent.heartbeat import HeartbeatPublisher


def test_heartbeat_interval_is_ten_seconds() -> None:
    assert heartbeat_module._INTERVAL_S == 10.0


@pytest.mark.asyncio
async def test_run_waits_the_interval_between_publications() -> None:
    publisher = HeartbeatPublisher(
        config=MagicMock(),
        queue=MagicMock(),
        state=MagicMock(),
        client=MagicMock(),
    )
    publisher._publish = AsyncMock()  # type: ignore[method-assign]
    stop_event = asyncio.Event()
    observed_timeouts: list[float] = []

    async def fake_wait_for(awaitable, timeout):  # noqa: ANN001
        observed_timeouts.append(timeout)
        if asyncio.iscoroutine(awaitable):
            awaitable.close()
        if len(observed_timeouts) >= 2:
            stop_event.set()
        raise asyncio.TimeoutError

    fake_asyncio = SimpleNamespace(wait_for=fake_wait_for, TimeoutError=asyncio.TimeoutError)
    with patch.object(heartbeat_module, "asyncio", fake_asyncio):
        await publisher.run(stop_event)

    assert observed_timeouts == [10.0, 10.0]
    assert publisher._publish.await_count == 2
