"""
Tests de autenticación JWT para FIM Platform (Change 04).

Requieren PostgreSQL en DATABASE_URL (conftest.py los configura).
Valkey se mockea vía dependency_overrides para control preciso.
"""

import os
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import ACCESS_TOKEN_EXPIRE_MINUTES


@pytest.fixture
def mock_valkey():
    """Valkey mock con comportamiento default: sin rate limit, sin blacklist, sin gracia."""
    m = MagicMock()
    m.incr.return_value = 1
    m.expire.return_value = True
    m.exists.return_value = 0
    m.setex.return_value = True
    m.close.return_value = None
    # GET sobre una clave inexistente devuelve None en Valkey. Sin este default el
    # MagicMock devuelve otro MagicMock (truthy) y la ventana de gracia del refresh
    # (fim:refresh_grace:<jti>) parece SIEMPRE activa.
    m.get.return_value = None
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
        base_url="https://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.pop(get_valkey_client, None)


# ─── Blacklist compartida entre el cliente sync y el async ──────────────────
#
# `logout` escribe la blacklist con el cliente SYNC (dependency get_valkey_client)
# y `get_current_user` la consulta con el ASYNC (get_async_valkey_client). Con dos
# mocks independientes —como hacía el test viejo de logout— la escritura nunca es
# leída y el token revocado sigue pasando. Estos fixtures les dan un único store.

_NEW_ADMIN_PASSWORD = "LogoutTestAdmin1!"


@pytest.fixture
def blacklist_store() -> dict:
    """{key: (ttl, value)} — lo que `setex` escribió."""
    return {}


@pytest.fixture
def blacklist_valkey(blacklist_store, _patch_async_valkey):
    """Cliente sync fake que escribe en `blacklist_store`; el async fake lo lee."""
    m = MagicMock()
    m.incr.return_value = 1
    m.expire.return_value = True
    m.get.return_value = None
    m.close.return_value = None

    def _setex(key, ttl, value):
        blacklist_store[key] = (ttl, value)
        return True

    m.setex.side_effect = _setex
    m.exists.side_effect = lambda key: 1 if key in blacklist_store else 0
    # get_current_user consulta la blacklist por el cliente ASYNC.
    _patch_async_valkey.exists.side_effect = lambda key: 1 if key in blacklist_store else 0
    return m


@pytest.fixture
async def blacklist_client(blacklist_valkey):
    from app.core.valkey import get_valkey_client
    from app.main import app

    app.dependency_overrides[get_valkey_client] = lambda: blacklist_valkey
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://testserver",
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


async def _full_access_login(client) -> tuple[str, dict]:
    """
    Completa el cambio de password forzado y devuelve (access_token, cookies)
    con scope pleno — el admin sembrado nace con must_change_password=True, y
    su primer token sólo sirve para /users/change-password.
    """
    first = await _login(client)
    assert first.status_code == 200, first.text
    change = await client.post(
        "/users/change-password",
        json={"new_password": _NEW_ADMIN_PASSWORD},
        headers={"Authorization": f"Bearer {first.json()['access_token']}"},
    )
    assert change.status_code == 200, change.text

    full = await _login(client, password=_NEW_ADMIN_PASSWORD)
    assert full.status_code == 200, full.text
    assert full.json()["must_change_password"] is False
    return full.json()["access_token"], dict(full.cookies)


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


async def test_login_incluye_objeto_user(auth_client):
    """C38 (FIX-01): LoginResponse embebe el usuario autenticado."""
    resp = await _login(auth_client)
    assert resp.status_code == 200
    user = resp.json()["user"]
    assert user["username"] == os.environ["ADMIN_USERNAME"]
    assert user["role"] == "admin"
    assert user["must_change_password"] is True
    assert isinstance(user["id"], int)


async def test_login_password_incorrecta_retorna_401(auth_client):
    resp = await _login(auth_client, password="wrongpassword123!")
    assert resp.status_code == 401


async def test_login_usuario_inexistente_retorna_401(auth_client):
    resp = await _login(auth_client, username="nosuchuser", password="x")
    assert resp.status_code == 401


async def test_login_error_es_identico_para_password_mala_y_usuario_inexistente(auth_client):
    """
    US-01 (anexo §7, nivel 1 #9): el error de login no debe permitir enumerar
    usuarios. Hasta ahora sólo se comparaba el código 401; acá se compara el
    cuerpo completo de las dos respuestas, que es donde podría filtrarse la
    diferencia entre "esa contraseña no es" y "ese usuario no existe".
    """
    bad_password = await _login(auth_client, password="ThisIsNotThePassword1!")
    unknown_user = await _login(
        auth_client, username="nosuchuser", password="ThisIsNotThePassword1!"
    )

    assert bad_password.status_code == 401
    assert unknown_user.status_code == 401
    assert bad_password.json() == unknown_user.json()
    assert bad_password.json()["detail"] == "Incorrect username or password"
    # El mensaje tampoco nombra al usuario probado.
    assert "nosuchuser" not in unknown_user.text
    assert os.environ["ADMIN_USERNAME"] not in bad_password.json()["detail"]


# ─── Tests: rate limit login ─────────────────────────────────────────────────

async def test_rate_limit_login_6to_intento_retorna_429(_patch_async_valkey, auth_client):
    """
    Cuando el counter de Valkey supera LOGIN_MAX_ATTEMPTS (5),
    el endpoint debe devolver 429 con Retry-After.

    check_login_rate_limit usa el cliente async (get_async_valkey_client),
    mockeado por el fixture autouse _patch_async_valkey del conftest.
    """
    _patch_async_valkey.incr.return_value = 6  # simula 6to intento

    resp = await _login(auth_client)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


async def test_rate_limit_login_5_intentos_pasan(_patch_async_valkey, auth_client):
    _patch_async_valkey.incr.return_value = 5  # exactamente en el límite, no supera

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


async def test_refresh_incluye_objeto_user(auth_client):
    """C38 (FIX-01): RefreshResponse embebe el usuario autenticado."""
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200

    resp = await auth_client.post("/auth/refresh", cookies=login_resp.cookies)
    assert resp.status_code == 200
    user = resp.json()["user"]
    assert user["username"] == os.environ["ADMIN_USERNAME"]
    assert user["role"] == "admin"
    assert "must_change_password" in user


async def test_refresh_con_token_revocado_retorna_401(mock_valkey, auth_client):
    """Reuso real: el jti está blacklisteado y la ventana de gracia ya venció."""
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200

    # Simular que el jti está en la blacklist y que la gracia ya expiró
    # (fim:refresh_grace:<jti> ausente → GET devuelve None).
    mock_valkey.exists.return_value = 1
    mock_valkey.get.return_value = None

    cookies = login_resp.cookies
    resp = await auth_client.post("/auth/refresh", cookies=cookies)
    assert resp.status_code == 401


async def test_refresh_concurrente_dentro_de_gracia_reusa_la_sesion_rotada(
    mock_valkey, auth_client
):
    """
    Refresh concurrente: el jti viejo está blacklisteado pero la ventana de gracia
    (10 s) sigue viva → el perdedor recibe la sesión que rotó el ganador, no 401.
    """
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200

    # Primer refresh: gana y rota. Guardamos el refresh emitido.
    winner = await auth_client.post("/auth/refresh", cookies=login_resp.cookies)
    assert winner.status_code == 200
    winning_refresh = winner.cookies["refresh_token"]

    # Segundo refresh con el token VIEJO, dentro de la ventana de gracia.
    mock_valkey.exists.return_value = 1
    mock_valkey.get.return_value = winning_refresh.encode()

    loser = await auth_client.post("/auth/refresh", cookies=login_resp.cookies)
    assert loser.status_code == 200
    assert loser.cookies["refresh_token"] == winning_refresh
    assert "access_token" in loser.json()


async def test_refresh_sin_cookie_retorna_401(auth_client):
    resp = await auth_client.post("/auth/refresh")
    assert resp.status_code == 401


# ─── Tests: logout ───────────────────────────────────────────────────────────

async def test_logout_invalida_access_token(blacklist_client, blacklist_store):
    """
    US-02 (anexo §7, nivel 2 #15): el criterio central de la historia es que un
    token invalidado sea RECHAZADO. Se ejercita contra `GET /events`, que exige
    autenticación real (`require_full_access`), y se comprueba que la misma
    request pasa antes del logout y falla con 401 después.

    La versión anterior de este test consultaba `GET /health` —público, sin
    auth—, nunca miraba esa respuesta y su única aserción real era que
    `setex` había sido llamado: verificaba que Valkey recibió *una* escritura,
    no que el token dejara de servir.
    """
    from app.core.security import BLACKLIST_PREFIX, decode_token

    access_token, refresh_cookies = await _full_access_login(blacklist_client)
    auth_header = {"Authorization": f"Bearer {access_token}"}

    # Precondición: con el token vivo, el endpoint protegido responde.
    before = await blacklist_client.get("/events", headers=auth_header)
    assert before.status_code == 200, before.text

    logout_resp = await blacklist_client.post(
        "/auth/logout", headers=auth_header, cookies=refresh_cookies
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["message"] == "logged_out"

    # El criterio de la historia: el mismo token ya no sirve.
    after = await blacklist_client.get("/events", headers=auth_header)
    assert after.status_code == 401, "el access token revocado sigue siendo aceptado"

    # La entrada de blacklist existe y su TTL es el remanente del token, no eterno.
    access_jti = decode_token(access_token)["jti"]
    access_key = f"{BLACKLIST_PREFIX}{access_jti}"
    assert access_key in blacklist_store, "el jti del access token no se blacklisteó"
    access_ttl = blacklist_store[access_key][0]
    assert 0 < access_ttl <= ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert access_ttl > ACCESS_TOKEN_EXPIRE_MINUTES * 60 - 60  # recién emitido


async def test_logout_invalida_tambien_el_refresh_token(blacklist_client, blacklist_store):
    """
    US-02: el logout revoca los DOS tokens. El refresh revocado no puede
    reabrir la sesión, y su TTL de blacklist es el de 7 días del refresh.
    """
    from app.core.security import BLACKLIST_PREFIX, REFRESH_TOKEN_EXPIRE_DAYS, decode_token

    access_token, refresh_cookies = await _full_access_login(blacklist_client)
    refresh_token = refresh_cookies["refresh_token"]

    logout_resp = await blacklist_client.post(
        "/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        cookies=refresh_cookies,
    )
    assert logout_resp.status_code == 200

    refresh_jti = decode_token(refresh_token)["jti"]
    refresh_key = f"{BLACKLIST_PREFIX}{refresh_jti}"
    assert refresh_key in blacklist_store, "el jti del refresh token no se blacklisteó"
    refresh_ttl = blacklist_store[refresh_key][0]
    expected = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    assert expected - 60 < refresh_ttl <= expected

    # Y el refresh revocado ya no rota la sesión (fuera de la ventana de gracia).
    reuse = await blacklist_client.post(
        "/auth/refresh", cookies={"refresh_token": refresh_token}
    )
    assert reuse.status_code == 401


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
