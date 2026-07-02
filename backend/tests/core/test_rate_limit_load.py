"""
Tests de carga del rate limiter (C20, M1).

Verifica que el fixed-window implementado en core/rate_limit.py respeta los
buckets configurados: N requests dentro del límite no son rechazados, N+1
retorna 429, y la ventana se resetea tras expirar. También verifica (M1) que
el TTL se fija de forma idempotente en cada incremento, no solo en el primero.

Usa mocks de Valkey (AsyncMock) — no requiere conexión real.
Compatible con Windows (no depende de psycopg/libpq).
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

from app.core.rate_limit import check_api_rate_limit, check_login_rate_limit


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


async def test_api_ventana_reafirma_ttl_en_requests_subsiguientes() -> None:
    """M1: requests >1 en la ventana también llaman expire() (TTL idempotente)."""
    valkey = _make_valkey(incr_value=5)
    await check_api_rate_limit(user_id=42, valkey_client=valkey)
    valkey.expire.assert_called_once()
    args = valkey.expire.call_args[0]
    assert args[1] == 60


# ── Tests: Login rate limit ───────────────────────────────────────────────────

async def test_login_n_requests_dentro_del_bucket_no_rechazados() -> None:
    """Exactamente en el límite de login: no lanza HTTPException."""
    from app.core.config import settings

    limit = settings.rate_limit_login_attempts
    valkey = _make_valkey(incr_value=limit)  # exactamente en el límite
    await check_login_rate_limit(username="user@fim.local", ip="127.0.0.1", valkey_client=valkey)


async def test_login_n_mas_1_request_retorna_429() -> None:
    """Superar el límite de login lanza HTTPException 429 con Retry-After."""
    from app.core.config import settings

    limit = settings.rate_limit_login_attempts
    valkey = _make_valkey(incr_value=limit + 1)
    with pytest.raises(HTTPException) as exc_info:
        await check_login_rate_limit(username="user@fim.local", ip="127.0.0.1", valkey_client=valkey)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


async def test_login_ventana_se_resetea_en_primer_request() -> None:
    """Primer intento de login (count=1) activa expire() con la ventana configurada."""
    from app.core.config import settings

    window = settings.rate_limit_login_window_seconds
    valkey = _make_valkey(incr_value=1)
    await check_login_rate_limit(username="user@fim.local", ip="10.0.0.1", valkey_client=valkey)
    valkey.expire.assert_called_once()
    args = valkey.expire.call_args[0]
    assert args[1] == window


# ── M1: TTL idempotente — no deja la key sin expiración (C34) ──────────────────

async def test_login_ttl_siempre_presente_tras_incrementos_count_mayor_a_1() -> None:
    """
    M1: antes del fix, EXPIRE solo se llamaba cuando count == 1; si ese
    primer EXPIRE fallaba (o la key sobrevivía de un bug previo), la key
    quedaba sin TTL (-1) para siempre — lockout permanente del (user+IP).
    El fix llama EXPIRE en TODO incremento, así que un intento con count > 1
    siempre deja la key con un TTL acotado, auto-reparando cualquier estado
    previo sin TTL.
    """
    from app.core.config import settings

    window = settings.rate_limit_login_window_seconds
    valkey = _make_valkey(incr_value=3)  # tercer intento — count > 1
    await check_login_rate_limit(username="user@fim.local", ip="10.0.0.1", valkey_client=valkey)

    valkey.expire.assert_called_once()
    key_arg, ttl_arg = valkey.expire.call_args[0]
    assert key_arg == "fim:rl:login:user@fim.local:10.0.0.1"
    assert ttl_arg == window
    assert ttl_arg > 0  # nunca "-1" (sin expiración)


async def test_api_ttl_siempre_presente_tras_incrementos_count_mayor_a_1() -> None:
    """M1: misma garantía de TTL idempotente para el rate limit de API."""
    valkey = _make_valkey(incr_value=42)  # count > 1
    await check_api_rate_limit(user_id=7, valkey_client=valkey)

    valkey.expire.assert_called_once()
    key_arg, ttl_arg = valkey.expire.call_args[0]
    assert key_arg == "fim:rl:api:7"
    assert ttl_arg == 60
    assert ttl_arg > 0
