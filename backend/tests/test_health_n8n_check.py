"""
M9 — regression tests: health check de n8n reporta status HTTP correctamente (C34).

Antes del fix, `_check_n8n` (core/health.py) usaba `client.head()` sin
`raise_for_status()` y comparaba `status_code < 500`: cualquier 4xx (p. ej.
405 Method Not Allowed) se reportaba como `ok`, y el `except
httpx.HTTPStatusError` era dead code porque `head()` nunca lo lanzaba sin
`raise_for_status()`. Tampoco había fallback real a GET cuando HEAD fallaba
o no estaba soportado.

El fix usa `raise_for_status()` para tratar cualquier 4xx/5xx como `down`,
con la excepción de 405 (método no soportado) que dispara un fallback a GET
antes de decidir el resultado final.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.health import _check_n8n


def _patched_async_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Reemplaza httpx.AsyncClient para que use un MockTransport determinista."""
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


async def test_n8n_ok_on_200_head(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        return httpx.Response(200)

    _patched_async_client(monkeypatch, handler)
    result = await _check_n8n("http://n8n.local/webhook/fim")
    assert result == "ok"


async def test_n8n_down_on_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """M9: un 500 se reporta `down`, nunca `ok` (antes: bug de status_code < 500)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    _patched_async_client(monkeypatch, handler)
    result = await _check_n8n("http://n8n.local/webhook/fim")
    assert result == "down"


async def test_n8n_down_on_404_not_method_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """M9: un 404 (no es 405) se reporta down directo, sin fallback a GET."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(404)

    _patched_async_client(monkeypatch, handler)
    result = await _check_n8n("http://n8n.local/webhook/fim")
    assert result == "down"
    assert calls == ["HEAD"], "un 404 no debe disparar el fallback a GET"


async def test_n8n_fallback_to_get_when_head_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """M9: HEAD devuelve 405 (no soportado) → fallback a GET, que decide el resultado."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(200)

    _patched_async_client(monkeypatch, handler)
    result = await _check_n8n("http://n8n.local/webhook/fim")
    assert result == "ok"
    assert calls == ["HEAD", "GET"]


async def test_n8n_fallback_to_get_still_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """M9: HEAD no soportado (405) y el fallback GET también falla (500) → down."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(500)

    _patched_async_client(monkeypatch, handler)
    result = await _check_n8n("http://n8n.local/webhook/fim")
    assert result == "down"


async def test_n8n_fallback_to_get_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """M9: HEAD falla por error de conexión (no HTTPStatusError) → fallback a GET."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "HEAD":
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200)

    _patched_async_client(monkeypatch, handler)
    result = await _check_n8n("http://n8n.local/webhook/fim")
    assert result == "ok"
    assert calls == ["HEAD", "GET"]


async def test_n8n_degraded_when_not_configured() -> None:
    result = await _check_n8n("")
    assert result == "degraded"
