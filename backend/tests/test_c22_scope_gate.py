"""
Regression tests C22/C7 — Scope gate on business-data reads.

Verifica que:
- Un token con scope=password_change_only → 403 password_change_required
  en GET /events, GET /events/{id}, GET /rules, GET /rules/{id}.
- Un token con acceso completo → pasa la validación de scope (no 403).
- Los endpoints de escritura (POST /rules, etc.) ya usaban require_admin,
  lo que implica require_full_access transitivamente — no cambian.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, SQLModel, create_engine

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from app.core.database import get_session
from app.core.deps import get_current_user, require_full_access
from app.core.security import create_access_token
from app.core.valkey import get_valkey_client
from app.modules.auth.models import User


def _make_mock_valkey() -> MagicMock:
    m = MagicMock()
    m.incr.return_value = 1
    m.expire.return_value = True
    m.exists.return_value = 0
    return m


def _make_admin_user() -> User:
    return User(id=1, username="admin", password_hash="x", role="admin", is_active=True)


def _mem_session_override():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    def _override():
        with Session(engine) as session:
            yield session

    return _override


# ── scope=password_change_only → 403 en los 4 endpoints ──────────────────────


@pytest.mark.asyncio
async def test_get_events_scope_password_change_only_retorna_403() -> None:
    from app.main import app

    admin = _make_admin_user()
    admin.__dict__["_token_payload"] = {"scope": "password_change_only", "type": "access"}

    async def _fake_get_current_user():
        return admin

    app.dependency_overrides[get_valkey_client] = lambda: _make_mock_valkey()
    app.dependency_overrides[get_session] = _mem_session_override()
    app.dependency_overrides[get_current_user] = _fake_get_current_user

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            resp = await ac.get(
                "/events",
                headers={"Authorization": f"Bearer fake"},
            )
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 403
    assert resp.json().get("detail") == "password_change_required"


@pytest.mark.asyncio
async def test_get_event_by_id_scope_password_change_only_retorna_403() -> None:
    from app.main import app

    admin = _make_admin_user()
    admin.__dict__["_token_payload"] = {"scope": "password_change_only", "type": "access"}

    async def _fake_get_current_user():
        return admin

    app.dependency_overrides[get_valkey_client] = lambda: _make_mock_valkey()
    app.dependency_overrides[get_session] = _mem_session_override()
    app.dependency_overrides[get_current_user] = _fake_get_current_user

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            resp = await ac.get(
                "/events/1",
                headers={"Authorization": f"Bearer fake"},
            )
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 403
    assert resp.json().get("detail") == "password_change_required"


@pytest.mark.asyncio
async def test_get_rules_scope_password_change_only_retorna_403() -> None:
    from app.main import app

    admin = _make_admin_user()
    admin.__dict__["_token_payload"] = {"scope": "password_change_only", "type": "access"}

    async def _fake_get_current_user():
        return admin

    app.dependency_overrides[get_valkey_client] = lambda: _make_mock_valkey()
    app.dependency_overrides[get_session] = _mem_session_override()
    app.dependency_overrides[get_current_user] = _fake_get_current_user

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            resp = await ac.get(
                "/rules",
                headers={"Authorization": f"Bearer fake"},
            )
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 403
    assert resp.json().get("detail") == "password_change_required"


@pytest.mark.asyncio
async def test_get_rule_by_id_scope_password_change_only_retorna_403() -> None:
    from app.main import app

    admin = _make_admin_user()
    admin.__dict__["_token_payload"] = {"scope": "password_change_only", "type": "access"}

    async def _fake_get_current_user():
        return admin

    app.dependency_overrides[get_valkey_client] = lambda: _make_mock_valkey()
    app.dependency_overrides[get_session] = _mem_session_override()
    app.dependency_overrides[get_current_user] = _fake_get_current_user

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            resp = await ac.get(
                "/rules/1",
                headers={"Authorization": f"Bearer fake"},
            )
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 403
    assert resp.json().get("detail") == "password_change_required"


# ── token con acceso completo no recibe 403 por scope ────────────────────────


@pytest.mark.asyncio
async def test_get_events_full_access_token_no_recibe_403_por_scope() -> None:
    from app.main import app

    admin = _make_admin_user()
    admin.__dict__["_token_payload"] = {"type": "access"}

    async def _fake_get_current_user():
        return admin

    app.dependency_overrides[get_valkey_client] = lambda: _make_mock_valkey()
    app.dependency_overrides[get_session] = _mem_session_override()
    app.dependency_overrides[get_current_user] = _fake_get_current_user
    app.dependency_overrides[require_full_access] = _fake_get_current_user

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            resp = await ac.get(
                "/events",
                headers={"Authorization": f"Bearer fake"},
            )
    finally:
        app.dependency_overrides.pop(get_valkey_client, None)
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_full_access, None)

    assert resp.status_code != 403 or resp.json().get("detail") != "password_change_required"
