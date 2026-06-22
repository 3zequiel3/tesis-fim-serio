"""
Tests de carga del rate limiter (C20).

Verifica que el sliding-window implementado en core/rate_limit.py respeta los
buckets configurados: N requests dentro del límite no son rechazados, N+1
retorna 429, y la ventana se resetea tras expirar.

Usa mocks de Valkey — no requiere conexión real.
Compatible con Windows (no depende de psycopg/libpq).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, call, patch

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

def _make_valkey(incr_value: int) -> MagicMock:
    """Mock de Valkey que siempre retorna incr_value en incr()."""
    m = MagicMock()
    m.incr.return_value = incr_value
    m.expire.return_value = True
    return m


# ── Tests: API rate limit ─────────────────────────────────────────────────────

def test_api_n_requests_dentro_del_bucket_no_rechazados() -> None:
    """Exactamente en el límite (API_MAX = 100): no lanza HTTPException."""
    from app.core.config import settings

    limit = settings.rate_limit_api_per_minute
    valkey = _make_valkey(incr_value=limit)  # exactamente en el límite
    # No debe lanzar
    check_api_rate_limit(user_id=1, valkey_client=valkey)
    valkey.incr.assert_called_once()


def test_api_n_mas_1_request_retorna_429() -> None:
    """Un request por encima del límite API lanza HTTPException 429."""
    from app.core.config import settings

    limit = settings.rate_limit_api_per_minute
    valkey = _make_valkey(incr_value=limit + 1)
    with pytest.raises(HTTPException) as exc_info:
        check_api_rate_limit(user_id=1, valkey_client=valkey)
    assert exc_info.value.status_code == 429


def test_api_ventana_se_resetea_en_primer_request() -> None:
    """Primer request de la ventana (count=1) activa expire() con 60s."""
    valkey = _make_valkey(incr_value=1)
    check_api_rate_limit(user_id=42, valkey_client=valkey)
    valkey.expire.assert_called_once()
    args = valkey.expire.call_args[0]
    # Segundo argumento es el TTL (60 segundos)
    assert args[1] == 60


def test_api_ventana_no_resetea_en_requests_subsiguientes() -> None:
    """Requests >1 en la ventana no llaman expire() nuevamente."""
    valkey = _make_valkey(incr_value=5)
    check_api_rate_limit(user_id=42, valkey_client=valkey)
    valkey.expire.assert_not_called()


# ── Tests: Login rate limit ───────────────────────────────────────────────────

def test_login_n_requests_dentro_del_bucket_no_rechazados() -> None:
    """Exactamente en el límite de login: no lanza HTTPException."""
    from app.core.config import settings

    limit = settings.rate_limit_login_attempts
    valkey = _make_valkey(incr_value=limit)  # exactamente en el límite
    check_login_rate_limit(username="user@fim.local", ip="127.0.0.1", valkey_client=valkey)


def test_login_n_mas_1_request_retorna_429() -> None:
    """Superar el límite de login lanza HTTPException 429 con Retry-After."""
    from app.core.config import settings

    limit = settings.rate_limit_login_attempts
    valkey = _make_valkey(incr_value=limit + 1)
    with pytest.raises(HTTPException) as exc_info:
        check_login_rate_limit(username="user@fim.local", ip="127.0.0.1", valkey_client=valkey)
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_login_ventana_se_resetea_en_primer_request() -> None:
    """Primer intento de login (count=1) activa expire() con la ventana configurada."""
    from app.core.config import settings

    window = settings.rate_limit_login_window_seconds
    valkey = _make_valkey(incr_value=1)
    check_login_rate_limit(username="user@fim.local", ip="10.0.0.1", valkey_client=valkey)
    valkey.expire.assert_called_once()
    args = valkey.expire.call_args[0]
    assert args[1] == window
