"""
Singleton del cliente Valkey para FIM Platform.

init_valkey() se llama en el lifespan de FastAPI (startup).
get_valkey_client() se usa como dependency de FastAPI.
La conexión es lazy — from_url no abre sockets hasta el primer comando.
"""

from __future__ import annotations

import valkey as _valkey_pkg

_client: _valkey_pkg.Valkey | None = None


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
