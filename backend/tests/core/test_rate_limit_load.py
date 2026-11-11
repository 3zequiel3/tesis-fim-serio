"""
Tests de carga del rate limiter (C20, M1).

Verifica que el fixed-window implementado en core/rate_limit.py respeta los
buckets configurados: N requests dentro del límite no son rechazados, N+1
retorna 429, y la ventana se resetea tras expirar. También verifica (M1) que
el TTL se fija con `EXPIRE ... NX` (nx=True): el primer incremento fija la
ventana y los siguientes NO la reescriben, preservando la semántica
fixed-window (no sliding-window) y auto-reparando keys sin TTL.

Usa mocks de Valkey (AsyncMock) — no requiere conexión real.
Compatible con Windows (no depende de psycopg/libpq).

NOTA: la semántica REAL (que un EXPIRE NX no desliza la ventana) se verifica
contra un Valkey vivo en tests/core/test_rate_limit_semantics.py; los mocks
de acá solo comprueban que el helper invoca `expire(..., nx=True)`.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

# Variables de entorno mínimas para importar settings.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from app.core.rate_limit import (
    check_api_rate_limit,
    clear_login_attempts,
    login_retry_after,
    record_failed_login,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_valkey(incr_value: int) -> AsyncMock:
    """AsyncMock de Valkey que siempre retorna incr_value en incr()."""
    m = AsyncMock()
    m.incr.return_value = incr_value
    m.expire.return_value = True
    return m


# ── Tests: API rate limit ─────────────────────────────────────────────────────

async def test_api_n_requests_dentro_del_bucket_no_rechazados() -> None:
    """Exactamente en el límite (API_MAX = 100): no lanza HTTPException."""
    from app.core.config import settings

    limit = settings.rate_limit_api_per_minute
    valkey = _make_valkey(incr_value=limit)  # exactamente en el límite
    # No debe lanzar
    await check_api_rate_limit(user_id=1, valkey_client=valkey)
    valkey.incr.assert_called_once()


async def test_api_n_mas_1_request_retorna_429() -> None:
    """Un request por encima del límite API lanza HTTPException 429."""
    from app.core.config import settings

    limit = settings.rate_limit_api_per_minute
    valkey = _make_valkey(incr_value=limit + 1)
    with pytest.raises(HTTPException) as exc_info:
        await check_api_rate_limit(user_id=1, valkey_client=valkey)
    assert exc_info.value.status_code == 429


async def test_api_ventana_se_resetea_en_primer_request() -> None:
    """Primer request de la ventana (count=1) activa expire() con 60s."""
    valkey = _make_valkey(incr_value=1)
    await check_api_rate_limit(user_id=42, valkey_client=valkey)
    valkey.expire.assert_called_once()
    args = valkey.expire.call_args[0]
    # Segundo argumento es el TTL (60 segundos)
    assert args[1] == 60


async def test_api_expire_usa_nx_en_requests_subsiguientes() -> None:
    """M1: requests >1 en la ventana también invocan expire(), pero con nx=True
    para NO reescribir el TTL (fixed-window, no sliding-window)."""
    valkey = _make_valkey(incr_value=5)
    await check_api_rate_limit(user_id=42, valkey_client=valkey)
    valkey.expire.assert_called_once()
    args = valkey.expire.call_args[0]
    kwargs = valkey.expire.call_args[1]
    assert args[1] == 60
    assert kwargs.get("nx") is True


# ── Tests: Login rate limit (D92/RN-186: sólo fallidos) ──────────────────────
#
# D92/RN-186 replaced `check_login_rate_limit` (INCR before verifying, so successes
# counted too) with login_retry_after / record_failed_login / clear_login_attempts.
# The tests below keep the original intent (limit boundary, window set on first
# failure, TTL always present) on the new helpers.

def _make_login_valkey(count: int | None, ttl: int = 600) -> AsyncMock:
    m = AsyncMock()
    m.get.return_value = None if count is None else str(count).encode()
    m.ttl.return_value = ttl
    m.incr.return_value = (count or 0) + 1
    m.expire.return_value = True
    return m


async def test_login_exactamente_en_el_limite_menos_uno_no_esta_bloqueado() -> None:
    from app.core.config import settings

    valkey = _make_login_valkey(settings.rate_limit_login_attempts - 1)
    assert await login_retry_after("user@fim.local", "127.0.0.1", valkey_client=valkey) is None
    valkey.incr.assert_not_called()  # consultar nunca incrementa


async def test_login_sin_key_no_esta_bloqueado() -> None:
    valkey = _make_login_valkey(None)
    assert await login_retry_after("user@fim.local", "127.0.0.1", valkey_client=valkey) is None
    valkey.ttl.assert_not_called()


async def test_login_en_el_limite_devuelve_el_ttl_restante() -> None:
    from app.core.config import settings

    valkey = _make_login_valkey(settings.rate_limit_login_attempts, ttl=421)
    assert await login_retry_after("user@fim.local", "127.0.0.1", valkey_client=valkey) == 421
    valkey.get.assert_awaited_once_with("fim:rl:login:user@fim.local:127.0.0.1")


async def test_login_retry_after_nunca_baja_de_1() -> None:
    from app.core.config import settings

    valkey = _make_login_valkey(settings.rate_limit_login_attempts, ttl=0)
    assert await login_retry_after("u", "1.1.1.1", valkey_client=valkey) == 1


async def test_login_key_sin_ttl_se_repara_con_expire_nx() -> None:
    from app.core.config import settings

    valkey = _make_login_valkey(settings.rate_limit_login_attempts, ttl=-1)
    result = await login_retry_after("u", "1.1.1.1", valkey_client=valkey)
    assert result == settings.rate_limit_login_window_seconds
    valkey.expire.assert_awaited_once()
    assert valkey.expire.call_args[1].get("nx") is True


async def test_login_key_expirada_entre_get_y_ttl_no_bloquea() -> None:
    from app.core.config import settings

    valkey = _make_login_valkey(settings.rate_limit_login_attempts, ttl=-2)
    assert await login_retry_after("u", "1.1.1.1", valkey_client=valkey) is None


async def test_login_primer_fallo_activa_expire_con_la_ventana_configurada() -> None:
    from app.core.config import settings

    valkey = _make_login_valkey(None)
    await record_failed_login("user@fim.local", "10.0.0.1", valkey_client=valkey)
    valkey.incr.assert_awaited_once_with("fim:rl:login:user@fim.local:10.0.0.1")
    valkey.expire.assert_awaited_once()
    assert valkey.expire.call_args[0][1] == settings.rate_limit_login_window_seconds


async def test_login_clear_borra_la_key() -> None:
    valkey = _make_login_valkey(3)
    await clear_login_attempts("user@fim.local", "10.0.0.1", valkey_client=valkey)
    valkey.delete.assert_awaited_once_with("fim:rl:login:user@fim.local:10.0.0.1")


# ── M1: TTL idempotente — no deja la key sin expiración (C34) ──────────────────

async def test_login_ttl_siempre_presente_tras_fallos_con_count_mayor_a_1() -> None:
    """
    M1: un fallo con count > 1 siempre deja la key con un TTL acotado (EXPIRE NX
    auto-repara cualquier estado previo sin TTL, sin deslizar la ventana).
    """
    from app.core.config import settings

    window = settings.rate_limit_login_window_seconds
    valkey = _make_login_valkey(2)  # el incremento devuelve 3 — count > 1
    await record_failed_login("user@fim.local", "10.0.0.1", valkey_client=valkey)

    valkey.expire.assert_awaited_once()
    key_arg, ttl_arg = valkey.expire.call_args[0]
    assert key_arg == "fim:rl:login:user@fim.local:10.0.0.1"
    assert ttl_arg == window
    assert ttl_arg > 0  # nunca "-1" (sin expiración)
    assert valkey.expire.call_args[1].get("nx") is True


async def test_api_ttl_siempre_presente_tras_incrementos_count_mayor_a_1() -> None:
    """M1: misma garantía de TTL idempotente para el rate limit de API."""
    valkey = _make_valkey(incr_value=42)  # count > 1
    await check_api_rate_limit(user_id=7, valkey_client=valkey)

    valkey.expire.assert_called_once()
    key_arg, ttl_arg = valkey.expire.call_args[0]
    assert key_arg == "fim:rl:api:7"
    assert ttl_arg == 60
    assert ttl_arg > 0
    assert valkey.expire.call_args[1].get("nx") is True  # EXPIRE NX auto-repara sin deslizar
