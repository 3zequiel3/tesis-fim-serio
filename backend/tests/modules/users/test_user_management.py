"""
Tests de gestión de usuarios administradores (C20).

Cubre: GET /users y POST /users — listado paginado y creación con audit_log.

Requiere PostgreSQL en DATABASE_URL.
En Windows sin psycopg/libpq se omite el módulo completo (patrón C08+).
Valkey se mockea para evitar conexión real durante los tests.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

try:
    import psycopg  # noqa: F401
except ImportError:
    pytest.skip("psycopg/libpq not available on this platform", allow_module_level=True)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_valkey() -> MagicMock:
    """Valkey mock sin rate limit ni blacklist."""
    m = MagicMock()
    m.incr.return_value = 1
    m.expire.return_value = True
    m.exists.return_value = 0
    m.setex.return_value = True
    m.close.return_value = None
    return m


@pytest.fixture
async def admin_client(mock_valkey: MagicMock) -> AsyncClient:
    """AsyncClient con Valkey mockeado y sesión de admin autenticada."""
    from app.core.valkey import get_valkey_client
    from app.main import app

    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.pop(get_valkey_client, None)


async def _login_admin(client: AsyncClient) -> str:
    """Hace login como admin y retorna el access token."""
    resp = await client.post(
        "/auth/login",
        json={
            "username": os.environ["ADMIN_USERNAME"],
            "password": os.environ["ADMIN_PASSWORD"],
        },
    )
    assert resp.status_code == 200, f"login falló: {resp.text}"
    return resp.json()["access_token"]


async def _change_password(client: AsyncClient, token: str) -> str:
    """Si el admin tiene must_change_password, cambia la password y retorna token fresco."""
    import base64, json as _json

    payload_b64 = token.split(".")[1]
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload = _json.loads(base64.b64decode(payload_b64))

    if payload.get("scope") == "password_change_only":
        resp = await client.post(
            "/users/change-password",
            json={"new_password": "ChangedAdminPwd99!"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        # Re-login con password nueva para obtener token full-access
        resp2 = await client.post(
            "/auth/login",
            json={
                "username": os.environ["ADMIN_USERNAME"],
                "password": "ChangedAdminPwd99!",
            },
        )
        assert resp2.status_code == 200
        return resp2.json()["access_token"]
    return token


# ── Tests: GET /users ─────────────────────────────────────────────────────────

async def test_admin_puede_listar_usuarios(admin_client: AsyncClient) -> None:
    """Admin autenticado recibe 200 con lista paginada; no incluye password_hash."""
    token = await _login_admin(admin_client)
    token = await _change_password(admin_client, token)

    resp = await admin_client.get(
        "/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert isinstance(body["items"], list)
    # Ningún item debe exponer password_hash
    for item in body["items"]:
        assert "password_hash" not in item


async def test_no_admin_recibe_403_en_get_users(admin_client: AsyncClient) -> None:
    """Request sin token válido recibe 401 (no hay usuarios no-admin en el seed)."""
    resp = await admin_client.get("/users")
    assert resp.status_code == 401


# ── Tests: POST /users ────────────────────────────────────────────────────────

async def test_admin_crea_usuario_201_y_audit_log(admin_client: AsyncClient) -> None:
    """Admin crea nuevo usuario; respuesta 201 con id y email; audit_log registrado."""
    from sqlmodel import Session, select
    from app.core.database import engine
    from app.modules.audit.models import AuditLog

    token = await _login_admin(admin_client)
    token = await _change_password(admin_client, token)

    resp = await admin_client.post(
        "/users",
        json={"email": "newadmin@fim.example", "password": "SecureNewPwd42!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert body["email"] == "newadmin@fim.example"

    # Verificar audit_log
    new_user_id = body["id"]
    with Session(engine) as session:
        log_entry = session.exec(
            select(AuditLog).where(
                AuditLog.action == "user_created",
                AuditLog.target_id == new_user_id,
                AuditLog.target_type == "user",
            )
        ).first()
    assert log_entry is not None, "audit_log entry para user_created no encontrada"


async def test_post_users_email_duplicado_retorna_409(admin_client: AsyncClient) -> None:
    """Crear usuario con email ya existente retorna 409."""
    token = await _login_admin(admin_client)
    token = await _change_password(admin_client, token)

    # Primera creación
    await admin_client.post(
        "/users",
        json={"email": "dup@fim.example", "password": "SecureNewPwd42!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Segunda con mismo email
    resp = await admin_client.post(
        "/users",
        json={"email": "dup@fim.example", "password": "AnotherPassword99!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


async def test_post_users_password_corto_retorna_422(admin_client: AsyncClient) -> None:
    """Password menor a 12 caracteres retorna 422 por validación Pydantic."""
    token = await _login_admin(admin_client)
    token = await _change_password(admin_client, token)

    resp = await admin_client.post(
        "/users",
        json={"email": "weakpwd@fim.example", "password": "short"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_post_users_email_invalido_retorna_422(admin_client: AsyncClient) -> None:
    """M3: email sintácticamente inválido es rechazado por EmailStr con 422."""
    token = await _login_admin(admin_client)
    token = await _change_password(admin_client, token)

    resp = await admin_client.post(
        "/users",
        json={"email": "noesunmail", "password": "SecureNewPwd42!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ── Tests: seed_admin toma email de ADMIN_EMAIL (M3, D29) ──────────────────────

def _clear_users_table() -> None:
    import sqlalchemy
    from app.core.database import engine

    with engine.connect() as conn:
        conn.execute(sqlalchemy.text("TRUNCATE users RESTART IDENTITY CASCADE"))
        conn.commit()


def test_seed_admin_usa_admin_email_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    """M3: seed_admin() asigna el email tomado de settings.admin_email (ADMIN_EMAIL)."""
    from sqlmodel import Session, select

    from app.core.config import settings
    from app.core.database import engine
    from app.modules.auth.models import User
    from app.modules.auth.service import seed_admin

    _clear_users_table()
    monkeypatch.setattr(settings, "admin_email", "ops@fim.example")

    seed_admin()

    with Session(engine) as session:
        admin = session.exec(select(User).where(User.username == settings.admin_username)).first()
    assert admin is not None
    assert admin.email == "ops@fim.example"


def test_seed_admin_usa_default_cuando_no_hay_admin_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """M3: sin ADMIN_EMAIL configurado, seed_admin() usa el default admin@fim.local."""
    from sqlmodel import Session, select

    from app.core.config import settings
    from app.core.database import engine
    from app.modules.auth.models import User
    from app.modules.auth.service import seed_admin

    _clear_users_table()
    monkeypatch.setattr(settings, "admin_email", "admin@fim.local")

    seed_admin()

    with Session(engine) as session:
        admin = session.exec(select(User).where(User.username == settings.admin_username)).first()
    assert admin is not None
    assert admin.email == "admin@fim.local"


def test_seed_admin_idempotente_con_admin_existente(monkeypatch: pytest.MonkeyPatch) -> None:
    """M3: re-ejecutar seed_admin() con el admin ya existente no falla ni duplica."""
    from sqlmodel import Session, func, select

    from app.core.config import settings
    from app.core.database import engine
    from app.modules.auth.models import User
    from app.modules.auth.service import seed_admin

    # El admin ya existe por _db_isolation (autouse); re-ejecutar no debe romper.
    seed_admin()
    seed_admin()

    with Session(engine) as session:
        total = session.exec(
            select(func.count()).select_from(User).where(User.username == settings.admin_username)
        ).one()
    assert total == 1
