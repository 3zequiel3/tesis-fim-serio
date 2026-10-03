"""
Phase A of `ingest-batched-persistence` (amplification of 2026-10-03 of D87/RN-181):
the notification lane reuses ONE long-lived httpx client for n8n and the fallback
webhook. Covers reuse, lifecycle, TLS verification, connection reset recovery and
the per-channel timeout, against a tiny local asyncio HTTP server (no extra deps).
"""

from __future__ import annotations

import asyncio
import ssl
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app.modules.alerts import notifier
from app.modules.alerts.notifier import (
    close_notify_http_client,
    get_notify_http_client,
    init_notify_http_client,
    send_n8n,
    send_webhook_fallback,
)

APP_DIR = Path(__file__).resolve().parents[1] / "app"


class _Server:
    """Minimal HTTP/1.1 server. `mode`: ok | close_after_reply | hang."""

    def __init__(self, mode: str = "ok") -> None:
        self.mode = mode
        self.requests = 0
        self.connections = 0
        self._server: asyncio.AbstractServer | None = None
        self._handlers: set[asyncio.Task] = set()
        self.port = 0

    async def start(self, port: int = 0) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        for task in list(self._handlers):
            task.cancel()
        await asyncio.gather(*self._handlers, return_exceptions=True)
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/hook"

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._handlers.add(asyncio.current_task())
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                length = 0
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":")[1])
                if length:
                    await reader.readexactly(length)
                self.requests += 1
                if self.mode == "hang":
                    await asyncio.sleep(60)
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                await writer.drain()
                if self.mode == "close_after_reply":
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self._handlers.discard(asyncio.current_task())
            writer.close()


@pytest.fixture()
async def server():
    srv = _Server()
    await srv.start()
    yield srv
    await srv.stop()
    await close_notify_http_client()


async def test_consecutive_deliveries_share_one_client(server, monkeypatch) -> None:
    constructed: list[int] = []
    original_init = httpx.AsyncClient.__init__

    def spy(self, *args, **kwargs):
        constructed.append(1)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", spy)
    first = get_notify_http_client()
    assert await send_n8n({"a": 1}, server.url) is True
    assert await send_n8n({"a": 2}, server.url) is True
    assert await send_webhook_fallback({"a": 3}, server.url) is True
    assert get_notify_http_client() is first
    assert len(constructed) == 1
    assert server.requests == 3
    assert server.connections == 1  # keep-alive: one TCP connection for the three deliveries


async def test_lifespan_closes_and_discards_the_client(monkeypatch) -> None:
    import app.main as main_module
    from tests.test_notify_isolate_executor_lifespan import _FakeAsyncValkey, _fake_noop_forever

    for name in ("init_valkey", "init_async_valkey", "ensure_ca", "start_mtls_server", "start_bootstrap_server"):
        monkeypatch.setattr(main_module, name, lambda *a, **k: None)
    monkeypatch.setattr(main_module.SQLModel.metadata, "create_all", lambda *a, **k: None)
    monkeypatch.setattr(main_module, "seed_admin", lambda: None)
    monkeypatch.setattr(main_module, "build_async_valkey_client", lambda *a, **k: _FakeAsyncValkey())
    monkeypatch.setattr(main_module, "close_async_valkey", AsyncMock())
    monkeypatch.setattr(main_module, "close_valkey", lambda: None)
    for name in ("run_consumer", "run_heartbeat_consumer", "run_command_ack_consumer"):
        monkeypatch.setattr(main_module, name, _fake_noop_forever)
    for name in ("retention_task", "outbox_publisher_task", "recover_pending_notifications", "rejected_events_retention_task"):
        monkeypatch.setattr(main_module, name, lambda: _fake_noop_forever())

    async with main_module.lifespan(main_module.app):
        client = notifier._notify_http_client
        assert client is not None and not client.is_closed
    assert client.is_closed
    assert notifier._notify_http_client is None


async def test_lazy_creation_without_lifespan_and_idempotent_init() -> None:
    assert notifier._notify_http_client is None
    client = get_notify_http_client()
    assert init_notify_http_client() is client
    await close_notify_http_client()
    assert client.is_closed and notifier._notify_http_client is None


async def test_tls_verification_stays_on() -> None:
    client = get_notify_http_client()
    try:
        ctx = client._transport._pool._ssl_context  # type: ignore[attr-defined]
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
    finally:
        await close_notify_http_client()


def test_no_verify_false_in_production_code() -> None:
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if "verify=False" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


async def test_pool_limits_follow_the_delivery_slot_and_expire_under_node_keepalive() -> None:
    from app.core.config import settings

    client = get_notify_http_client()
    try:
        pool = client._transport._pool  # type: ignore[attr-defined]
        assert pool._max_connections == settings.notify_max_concurrent_deliveries
        assert pool._max_keepalive_connections == settings.notify_max_concurrent_deliveries
        assert pool._keepalive_expiry == 4.0
    finally:
        await close_notify_http_client()


async def test_connection_reset_fails_at_most_one_delivery_and_the_next_recovers() -> None:
    srv = _Server(mode="close_after_reply")
    await srv.start()
    try:
        results = [await send_n8n({"i": i}, srv.url) for i in range(3)]
        # The server closes after each reply; a reused connection may fail once, never throw,
        # and the delivery after a failure must succeed on a fresh connection.
        assert results[0] is True
        for prev, cur in zip(results, results[1:]):
            assert not (prev is False and cur is False)
        assert results[-1] is True
    finally:
        await srv.stop()
        await close_notify_http_client()


async def test_delivery_after_server_restart_on_the_same_port_succeeds() -> None:
    srv = _Server()
    await srv.start()
    port = srv.port
    try:
        assert await send_n8n({"i": 1}, srv.url) is True
        await srv.stop()
        assert await send_n8n({"i": 2}, srv.url) is False  # n8n down: fails, does not raise
        srv2 = _Server()
        await srv2.start(port)
        try:
            assert await send_n8n({"i": 3}, srv2.url) is True
        finally:
            await srv2.stop()
    finally:
        await close_notify_http_client()


async def test_per_request_timeout_is_kept() -> None:
    srv = _Server(mode="hang")
    await srv.start()
    try:
        started = asyncio.get_running_loop().time()
        assert await send_n8n({"i": 1}, srv.url, timeout=0.3) is False
        assert asyncio.get_running_loop().time() - started < 5
    finally:
        await srv.stop()
        await close_notify_http_client()


async def test_after_close_a_straggler_delivery_fails_without_recreating_the_client(server) -> None:
    """S2: a fire-and-forget delivery that outlives the shutdown must not resurrect an unclosed client."""
    assert await send_n8n({"i": 1}, server.url) is True
    await close_notify_http_client()
    assert await send_n8n({"i": 2}, server.url) is False
    assert await send_webhook_fallback({"i": 3}, server.url) is False
    assert notifier._notify_http_client is None
    with pytest.raises(RuntimeError):
        get_notify_http_client()
    # An explicit init (next lifespan startup) re-opens the lane.
    client = init_notify_http_client()
    assert await send_n8n({"i": 4}, server.url) is True
    assert get_notify_http_client() is client
