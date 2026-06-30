"""
Singletons del cliente Valkey para FIM Platform.

Sync (init_valkey / get_valkey_client): usado por servicios de negocio y health.
Async (init_async_valkey / get_async_valkey_client): usado por dependencias FastAPI
  (get_current_user, rate limit) para no bloquear el event loop.

Ambos se inicializan en el lifespan de FastAPI (startup).
Las conexiones son lazy — from_url no abre sockets hasta el primer comando.
"""

from __future__ import annotations

import valkey as _valkey_pkg
import valkey.asyncio as _valkey_async_pkg

_client: _valkey_pkg.Valkey | None = None
_async_client: _valkey_async_pkg.Valkey | None = None


def init_valkey(url: str) -> None:
    global _client
    _client = _valkey_pkg.Valkey.from_url(url, decode_responses=True)


def close_valkey() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_valkey_client() -> _valkey_pkg.Valkey:
    if _client is None:
        raise RuntimeError("Valkey client not initialized — init_valkey() not called")
    return _client


def init_async_valkey(url: str) -> None:
    global _async_client
    _async_client = _valkey_async_pkg.Valkey.from_url(url, decode_responses=True)


async def close_async_valkey() -> None:
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None


def get_async_valkey_client() -> _valkey_async_pkg.Valkey:
    if _async_client is None:
        raise RuntimeError("Async Valkey client not initialized — init_async_valkey() not called")
    return _async_client
