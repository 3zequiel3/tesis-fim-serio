"""
Tests de SEMÁNTICA real del rate limiter contra un Valkey vivo (C34, M1).

A diferencia de test_rate_limit_load.py (que usa AsyncMock y solo comprueba
que el helper INVOCA expire), estos tests verifican el efecto observable de
`EXPIRE ... NX` contra un broker real:

  1. fixed-window: si la key ya tiene un TTL, un nuevo incremento NO lo
     reescribe (no desliza la ventana). El bug original de M1 usaba EXPIRE
     incondicional, que reseteaba el TTL a la ventana completa en cada
     request y hacía que la ventana nunca expirara mientras llegaran
     requests (sliding-window de facto).
  2. auto-reparación: si la key quedó SIN TTL (-1), el próximo incremento le
     asigna uno, evitando el lockout permanente.

Requiere un Valkey en VALKEY_URL (el efímero del harness C33). Se saltea con
skip si no hay broker alcanzable, siguiendo el patrón opt-in del repo.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from app.core.rate_limit import API_RL_PREFIX, check_api_rate_limit


@pytest.fixture
async def live_async_valkey():
    """Cliente async real contra VALKEY_URL; skip si no hay broker."""
    import valkey.asyncio as valkey_async

    client = valkey_async.Valkey.from_url(os.environ["VALKEY_URL"], decode_responses=True)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Valkey no disponible en VALKEY_URL — test de semántica opt-in")
    try:
        yield client
    finally:
        await client.aclose()


async def test_expire_nx_no_desliza_la_ventana(live_async_valkey) -> None:
    """M1: con un TTL ya presente, un incremento NO lo reescribe (fixed-window).

    Pre-seteamos la key con un TTL corto (5s). Tras el incremento, el TTL
    debe seguir siendo ~5s y NUNCA saltar a la ventana completa (60s). Con el
    bug original (EXPIRE incondicional) el TTL habría vuelto a 60s.
    """
    user_id = 987654
    key = f"{API_RL_PREFIX}{user_id}"
    await live_async_valkey.delete(key)
    # Estado inicial: la key existe con un TTL corto de 5s.
    await live_async_valkey.set(key, 1, ex=5)

    ttl_antes = await live_async_valkey.ttl(key)
    assert 0 < ttl_antes <= 5

    # Incremento dentro de la ventana → expire(..., nx=True) NO debe tocar el TTL.
    await check_api_rate_limit(user_id=user_id, valkey_client=live_async_valkey)

    ttl_despues = await live_async_valkey.ttl(key)
    # El TTL sigue acotado por la ventana corta original, no se resetea a 60s.
    assert 0 < ttl_despues <= 5, (
        f"EXPIRE NX no debe deslizar la ventana: ttl={ttl_despues}s "
        "(el bug de sliding-window lo habría reseteado a ~60s)"
    )
    await live_async_valkey.delete(key)


async def test_expire_nx_autorepara_key_sin_ttl(live_async_valkey) -> None:
    """M1: una key persistente (sin TTL, -1) recibe un TTL en el próximo incremento."""
    user_id = 987655
    key = f"{API_RL_PREFIX}{user_id}"
    await live_async_valkey.delete(key)
    # Estado corrupto: key sin expiración (simula un EXPIRE previo fallido).
    await live_async_valkey.set(key, 3)
    assert await live_async_valkey.ttl(key) == -1  # sin TTL

    await check_api_rate_limit(user_id=user_id, valkey_client=live_async_valkey)

    ttl_reparado = await live_async_valkey.ttl(key)
    assert 0 < ttl_reparado <= 60  # EXPIRE NX asignó la ventana → sin lockout permanente
    await live_async_valkey.delete(key)
