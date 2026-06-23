"""
Regression tests C22/C6 — Token-type enforcement.

Verifica que:
- create_access_token incluye type=access en el payload.
- Un refresh token presentado como Bearer → 401 token_type_invalid.
- Un token sin claim type → 401 token_type_invalid.
- Un access token válido (type=access) pasa la validación.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from jose import jwt as jose_jwt

from app.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
    decode_token,
)


# ── create_access_token lleva type=access ─────────────────────────────────────


def test_create_access_token_lleva_type_access() -> None:
    token = create_access_token(user_id=1, username="admin", must_change_password=False, jti=str(uuid.uuid4()))
    payload = decode_token(token)
    assert payload.get("type") == "access"


def test_create_access_token_scope_password_change_only_sigue_teniendo_type_access() -> None:
    token = create_access_token(user_id=1, username="admin", must_change_password=True, jti=str(uuid.uuid4()))
    payload = decode_token(token)
    assert payload.get("type") == "access"
    assert payload.get("scope") == "password_change_only"


def test_create_refresh_token_sigue_teniendo_type_refresh() -> None:
    """create_refresh_token no debe verse afectado por el cambio en C6."""
    token = create_refresh_token(user_id=1, jti=str(uuid.uuid4()))
    payload = decode_token(token)
    assert payload.get("type") == "refresh"


# ── get_current_user rechaza tokens con type != access ───────────────────────


@pytest.mark.asyncio
async def test_refresh_token_como_bearer_retorna_401_token_type_invalid() -> None:
    """Un refresh token presentado como Bearer debe ser rechazado con 401."""
    from httpx import ASGITransport, AsyncClient

    from app.core.valkey import get_valkey_client
    from app.main import app

    mock_valkey = MagicMock()
    mock_valkey.incr.return_value = 1
    mock_valkey.expire.return_value = True
    mock_valkey.exists.return_value = 0

    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey

    refresh_token = create_refresh_token(user_id=1, jti=str(uuid.uuid4()))

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as ac:
            resp = await ac.get("/events", headers={"Authorization": f"Bearer {refresh_token}"})
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)

    assert resp.status_code == 401
    assert resp.json().get("detail") == "token_type_invalid"


@pytest.mark.asyncio
async def test_token_sin_type_claim_retorna_401_token_type_invalid() -> None:
    """Un token sin claim type (formato pre-C6) debe ser rechazado."""
    from httpx import ASGITransport, AsyncClient

    from app.core.config import settings
    from app.core.valkey import get_valkey_client
    from app.main import app

    mock_valkey = MagicMock()
    mock_valkey.incr.return_value = 1
    mock_valkey.expire.return_value = True
    mock_valkey.exists.return_value = 0

    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey

    # Token sin claim type — simula tokens emitidos antes de C6
    now = datetime.now(timezone.utc)
    payload_sin_type = {
        "sub": "1",
        "username": "admin",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    token_sin_type = jose_jwt.encode(payload_sin_type, settings.jwt_secret_current, algorithm="HS256")

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as ac:
            resp = await ac.get("/events", headers={"Authorization": f"Bearer {token_sin_type}"})
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)

    assert resp.status_code == 401
    assert resp.json().get("detail") == "token_type_invalid"


@pytest.mark.asyncio
async def test_access_token_valido_pasa_validacion_de_type() -> None:
    """Un access token válido con type=access debe pasar la validación de tipo."""
    from httpx import ASGITransport, AsyncClient
    from sqlmodel import Session, SQLModel, create_engine

    from app.core.database import get_session
    from app.core.deps import get_current_user, require_full_access
    from app.core.valkey import get_valkey_client
    from app.main import app
    from app.modules.auth.models import User

    mock_valkey = MagicMock()
    mock_valkey.incr.return_value = 1
    mock_valkey.expire.return_value = True
    mock_valkey.exists.return_value = 0

    mem_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(mem_engine)

    def _fake_session():
        with Session(mem_engine) as session:
            yield session

    async def _fake_user():
        return User(id=1, username="admin", password_hash="x", role="admin", is_active=True)

    access_token = create_access_token(
        user_id=1, username="admin", must_change_password=False, jti=str(uuid.uuid4())
    )

    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey
    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_current_user] = _fake_user
    app.dependency_overrides[require_full_access] = _fake_user

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as ac:
            resp = await ac.get("/events", headers={"Authorization": f"Bearer {access_token}"})
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_full_access, None)

    assert resp.status_code != 401 or resp.json().get("detail") != "token_type_invalid"
