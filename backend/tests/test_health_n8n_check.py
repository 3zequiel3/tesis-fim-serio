"""
Health check de n8n — M9 (C34) reescrito para D43/RN-137 (C46).

QUÉ CAMBIÓ Y POR QUÉ ESTE ARCHIVO SE REESCRIBIÓ EN VEZ DE BORRARSE

  Hasta C46 el check apuntaba a `settings.n8n_webhook_url`. De ahí salía todo
  el baile HEAD→GET que este archivo verificaba: se prefería HEAD porque un GET
  a un webhook puede disparar el workflow, y se caía a GET igual ante 404/405
  porque eso es lo que responde un webhook n8n sano a un HEAD. El fallback
  terminaba haciendo justo lo que el HEAD buscaba evitar.

  D43/RN-137 apunta el check a un endpoint de salud propio (`n8n_health_url`).
  Con eso el GET es la operación correcta y sin efectos secundarios, y toda la
  heurística de 404/405 deja de tener sentido — de hecho pasa a ser incorrecta:
  un endpoint de salud que responde 404 está mal configurado, no sano.

  Lo que M9 arregló SIGUE VIGENTE y se conserva abajo: cualquier 4xx/5xx se
  reporta `down`. La regresión original era comparar `status_code < 500`, que
  trataba un 405 como `ok`. Esos tests no desaparecen, cambian de forma.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.health import _check_n8n

_HEALTH_URL = "http://n8n.local/healthz"
_WEBHOOK_URL = "http://n8n.local/webhook/fim-alert"


def _patched_async_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Reemplaza httpx.AsyncClient para que use un MockTransport determinista."""
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


async def test_n8n_ok_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        return httpx.Response(200)

    _patched_async_client(monkeypatch, handler)
    assert await _check_n8n(_HEALTH_URL) == "ok"
    assert calls == [("GET", _HEALTH_URL)], "un endpoint de salud se consulta con GET, una vez"


async def test_health_check_never_touches_the_webhook_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    D43/RN-137 — la razón de ser del cambio.

    Con el enrutador `fim-alert` operativo (change 47), un request contra la URL
    del webhook DISPARA el workflow. Un health check que corre cada 10 s se
    convertiría en un emisor de notificaciones espurias. Este test es el que
    impide que un "fallback conveniente" reintroduzca ese comportamiento.
    """
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200)

    _patched_async_client(monkeypatch, handler)
    await _check_n8n(_HEALTH_URL)

    assert urls == [_HEALTH_URL]
    assert _WEBHOOK_URL not in urls
    assert not any("webhook" in u for u in urls)


@pytest.mark.parametrize("status_code", [400, 403, 404, 405, 500, 502, 503])
async def test_any_error_status_is_down(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    """
    M9 conservado: cualquier 4xx/5xx es `down`. La regresión original comparaba
    `status_code < 500` y reportaba `ok` ante un 405.

    Nota sobre 404/405: antes disparaban un fallback a GET porque un WEBHOOK
    sano responde así a un HEAD. Contra un endpoint de SALUD no hay nada que
    excusar — un 404 ahí significa mal configurado, y `down` es la respuesta
    correcta.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    _patched_async_client(monkeypatch, handler)
    assert await _check_n8n(_HEALTH_URL) == "down"


async def test_no_retry_on_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """El check es una sola consulta: sin fallback, sin segundo intento."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(404)

    _patched_async_client(monkeypatch, handler)
    assert await _check_n8n(_HEALTH_URL) == "down"
    assert calls == ["GET"], "no debe haber fallback: el baile HEAD→GET se eliminó"


async def test_n8n_down_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patched_async_client(monkeypatch, handler)
    assert await _check_n8n(_HEALTH_URL) == "down"


async def test_n8n_degraded_when_not_configured() -> None:
    """Sin URL de salud no se puede afirmar que n8n esté sano."""
    assert await _check_n8n("") == "degraded"


async def test_check_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """RN-101: el check reporta estado, nunca propaga una excepción."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("algo totalmente inesperado")

    _patched_async_client(monkeypatch, handler)
    assert await _check_n8n(_HEALTH_URL) == "down"
