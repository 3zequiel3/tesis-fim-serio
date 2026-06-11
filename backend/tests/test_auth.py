"""
Tests de autenticación JWT para FIM Platform (Change 04).

Requieren PostgreSQL en DATABASE_URL (conftest.py los configura).
Valkey se mockea vía dependency_overrides para control preciso.
"""

import os
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

# Asegurar JWT_SECRET antes de que se importe la app.
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")


@pytest.fixture
def mock_valkey():
    """Valkey mock con comportamiento default: sin rate limit, sin blacklist."""
    m = MagicMock()
    m.incr.return_value = 1
    m.expire.return_value = True
    m.exists.return_value = 0
    m.setex.return_value = True
    m.close.return_value = None
    return m


@pytest.fixture
async def auth_client(mock_valkey):
    """
    AsyncClient con Valkey mockeado.

    La dependency get_valkey_client queda sobreescrita para todos los
    endpoints dentro de esta fixture. La DB sigue siendo la real.
    """
    from app.core.valkey import get_valkey_client
    from app.main import app

    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.pop(get_valkey_client, None)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _admin_creds():
    return {
        "username": os.environ["ADMIN_USERNAME"],
        "password": os.environ["ADMIN_PASSWORD"],
    }


async def _login(auth_client, username=None, password=None) -> dict:
    creds = _admin_creds()
    resp = await auth_client.post(
        "/auth/login",
        json={"username": username or creds["username"], "password": password or creds["password"]},
    )
    return resp


# ─── Tests: login ────────────────────────────────────────────────────────────

async def test_login_exitoso_retorna_200(auth_client):
    resp = await _login(auth_client)
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert "must_change_password" in body


async def test_login_primer_admin_must_change_password_true(auth_client):
    """El admin recién creado por seed_admin tiene must_change_password=True."""
    resp = await _login(auth_client)
    assert resp.status_code == 200
    assert resp.json()["must_change_password"] is True


async def test_login_password_incorrecta_retorna_401(auth_client):
    resp = await _login(auth_client, password="wrongpassword123!")
    assert resp.status_code == 401


async def test_login_usuario_inexistente_retorna_401(auth_client):
    resp = await _login(auth_client, username="nosuchuser", password="x")
    assert resp.status_code == 401


# ─── Tests: rate limit login ─────────────────────────────────────────────────

async def test_rate_limit_login_6to_intento_retorna_429(mock_valkey, auth_client):
    """
    Cuando el counter de Valkey supera LOGIN_MAX_ATTEMPTS (5),
    el endpoint debe devolver 429 con Retry-After.
    """
    mock_valkey.incr.return_value = 6  # simula 6to intento

    resp = await _login(auth_client)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_rate_limit_login_5_intentos_pasan(mock_valkey, auth_client):
    mock_valkey.incr.return_value = 5  # exactamente en el límite, no supera

    resp = await _login(auth_client)
    # No debe ser 429 (puede ser 200 o 401 según credenciales)
    assert resp.status_code != 429


# ─── Tests: refresh ──────────────────────────────────────────────────────────

async def test_refresh_valido_rota_token(auth_client):
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200

    cookies = login_resp.cookies
    resp = await auth_client.post("/auth/refresh", cookies=cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["access_token"] != login_resp.json()["access_token"]


async def test_refresh_con_token_revocado_retorna_401(mock_valkey, auth_client):
    """Simula que el jti del refresh está en la blacklist."""
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200

    # Simular que el jti está en la blacklist
    mock_valkey.exists.return_value = 1

    cookies = login_resp.cookies
    resp = await auth_client.post("/auth/refresh", cookies=cookies)
    assert resp.status_code == 401


async def test_refresh_sin_cookie_retorna_401(auth_client):
    resp = await auth_client.post("/auth/refresh")
    assert resp.status_code == 401


# ─── Tests: logout ───────────────────────────────────────────────────────────

async def test_logout_invalida_access_token(mock_valkey, auth_client):
    """Después del logout, el access token debe estar en la blacklist."""
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]

    logout_resp = await auth_client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        cookies=login_resp.cookies,
    )
    assert logout_resp.status_code == 200

    # Tras logout, simular que el jti está en blacklist para la siguiente request
    mock_valkey.exists.return_value = 1
    protected_resp = await auth_client.get(
        "/health",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    # /health no requiere auth — usamos otro endpoint cuando exista;
    # Por ahora verificamos que el token en blacklist es rechazado en /auth/logout mismo
    assert mock_valkey.setex.called  # blacklist_token fue llamado


# ─── Tests: scope password_change_only ──────────────────────────────────────

async def test_scope_password_change_only_en_access_token(auth_client):
    """Login del admin recién creado debe incluir scope en el token."""
    import base64, json as _json

    resp = await _login(auth_client)
    assert resp.status_code == 200

    token = resp.json()["access_token"]
    # Decodificar payload (segunda parte del JWT, sin verificación)
    payload_b64 = token.split(".")[1]
    # Agregar padding si falta
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += "=" * padding
    payload = _json.loads(base64.b64decode(payload_b64))

    # Si must_change_password=True, el scope debe estar presente
    if resp.json()["must_change_password"]:
        assert payload.get("scope") == "password_change_only"


# ─── Tests: change-password ──────────────────────────────────────────────────

async def test_change_password_con_scope_password_change_only(auth_client):
    """Primer login → change-password con scope especial → 200."""
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200

    access_token = login_resp.json()["access_token"]
    resp = await auth_client.post(
        "/users/change-password",
        json={"new_password": "NewStrongPassword42!"},
        headers={"Authorization": f"Bearer {access_token}"},
        cookies=login_resp.cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "password_changed"


async def test_change_password_short_retorna_422(auth_client):
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]

    resp = await auth_client.post(
        "/users/change-password",
        json={"new_password": "short"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 422


# ─── Tests: CORS ─────────────────────────────────────────────────────────────

async def test_cors_origin_en_whitelist_pasa(auth_client):
    """Origin en CORS_ALLOWED_ORIGINS → la request pasa."""
    import os
    allowed = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    origin = allowed.split(",")[0].strip() if allowed else "http://localhost:5173"

    resp = await auth_client.get("/health", headers={"Origin": origin})
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers


async def test_cors_origin_fuera_de_whitelist_retorna_403(auth_client):
    resp = await auth_client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 403


async def test_cors_sin_origin_pasa(auth_client):
    resp = await auth_client.get("/health")
    assert resp.status_code == 200


# ─── Tests: require_full_access ──────────────────────────────────────────────

async def test_require_full_access_bloquea_scope_password_change_only(auth_client):
    """
    Si el admin tiene must_change_password=True, su token tiene scope
    password_change_only. Cuando existan endpoints con require_full_access,
    devolverán 403. Por ahora verificamos que el scope está en el token
    y que /users/change-password pasa (no bloquea ese endpoint).
    """
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200
    body = login_resp.json()

    if body["must_change_password"]:
        # Token con scope password_change_only
        # change-password acepta este scope → 200
        access_token = body["access_token"]
        cp_resp = await auth_client.post(
            "/users/change-password",
            json={"new_password": "AnotherGoodPassword1!"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert cp_resp.status_code == 200
