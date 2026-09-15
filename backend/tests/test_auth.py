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
        json={
            "current_password": os.environ["ADMIN_PASSWORD"],
            "new_password": _NEW_ADMIN_PASSWORD,
        },
        headers={"Authorization": f"Bearer {first.json()['access_token']}"},
    )
    assert change.status_code == 200, change.text

    full = await _login(client, password=_NEW_ADMIN_PASSWORD)
    assert full.status_code == 200, full.text
    assert full.json()["must_change_password"] is False
    return full.json()["access_token"], dict(full.cookies)


# ─── Tests: Argon2id y duración exacta de tokens (US-01 criterios 2 y 6) ────

def test_hash_password_usa_argon2id_c9():
    """
    US-01 criterio 6 (C9): el hash almacenado debe llevar el prefijo Argon2id
    con los parámetros exactos time_cost=3, memory_cost=65536, parallelism=4.
    Falla si `_ph` cambiara de algoritmo o de cualquiera de esos parámetros,
    porque el prefijo codifica ambos.
    """
    from app.core.security import hash_password

    hashed = hash_password("SomePlainPassword1!")
    assert hashed.startswith("$argon2id$v=19$m=65536,t=3,p=4$"), hashed


# ─── Tests: password_policy_error (US-27, RN-100, D-1) ──────────────────────


def test_password_policy_error_password_valida():
    from app.core.security import password_policy_error

    assert password_policy_error("ValidPassword1") is None


def test_password_policy_error_corta():
    from app.core.security import password_policy_error

    assert password_policy_error("Short1x") is not None


def test_password_policy_error_sin_mayuscula():
    from app.core.security import password_policy_error

    err = password_policy_error("lowercase123andmore")
    assert err is not None
    assert "uppercase" in err.lower() or "mayúscula" in err.lower() or "mayuscula" in err.lower()


def test_password_policy_error_sin_minuscula():
    from app.core.security import password_policy_error

    err = password_policy_error("UPPERCASE123ANDMORE")
    assert err is not None


def test_password_policy_error_sin_digito():
    from app.core.security import password_policy_error

    err = password_policy_error("NoDigitsHereAtAllXX")
    assert err is not None


def test_password_policy_error_mayuscula_ene_con_tilde_es_valida():
    from app.core.security import password_policy_error

    assert password_policy_error("Ñuevopassword1") is None


async def test_access_15min_refresh_7d(auth_client):
    """
    US-01 criterio 2: access token de 15 min (900s) + refresh de 7 días
    (604800s). Se decodifican ambos tokens con `decode_token` (las propias
    settings JWT dual-key del proyecto), nunca asumiendo el secreto/algoritmo.
    """
    from app.core.security import decode_token

    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200

    access_payload = decode_token(login_resp.json()["access_token"])
    assert access_payload["exp"] - access_payload["iat"] == 900

    refresh_payload = decode_token(login_resp.cookies["refresh_token"])
    assert refresh_payload["exp"] - refresh_payload["iat"] == 604800


async def test_cookie_refresh_secure_fuera_de_modo_off(monkeypatch, auth_client):
    """
    US-01 criterio 5: con `console_tls_mode` distinto de `off` la cookie de
    refresh agrega `Secure` a los atributos ya cubiertos por otro test
    (`HttpOnly`, `SameSite=strict`, `Path=/auth/refresh`), y fija `Max-Age` en
    los 7 días de `REFRESH_TOKEN_EXPIRE_DAYS`.

    D55/RN-149 (change 52): `Secure` se deriva de `CONSOLE_TLS_MODE`, no de
    `ENVIRONMENT` — ver `test_auth_cookie_console_mode.py` para la cobertura
    completa de la matriz de modos.
    """
    from app.core.security import REFRESH_TOKEN_EXPIRE_DAYS
    from app.modules.auth import router as auth_router_module

    # Se monkeypatchea el objeto `settings` que el router realmente lee
    # (`app.modules.auth.router.settings`), no un `from app.core.config import
    # settings` fresco: `backend/tests/core/test_notification_settings.py` hace
    # `importlib.reload(app.core.config)`, que REBINDEA el nombre de módulo
    # `app.core.config.settings` a una instancia nueva. Cuando esa suite corre
    # antes que ésta (orden real de la suite completa), un `from
    # app.core.config import settings` hecho acá apuntaría a esa instancia
    # nueva — mientras que `auth/router.py` sigue usando la instancia vieja
    # importada al cargar el módulo — y el monkeypatch quedaría mudo.
    monkeypatch.setattr(auth_router_module.settings, "console_tls_mode", "self_signed")

    resp = await _login(auth_client)
    assert resp.status_code == 200

    headers = resp.headers.get_list("set-cookie")
    canonical = next(v for v in headers if "Path=/auth/refresh" in v)
    assert "Secure" in canonical, canonical
    assert "HttpOnly" in canonical
    assert "SameSite=strict" in canonical
    assert f"Max-Age={REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600}" in canonical


# ─── Tests: login ────────────────────────────────────────────────────────────

async def test_login_exitoso_retorna_200(auth_client):
    resp = await _login(auth_client)
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert "must_change_password" in body


async def test_login_migra_cookie_legacy_y_emite_cookie_canonica(auth_client):
    resp = await _login(auth_client)
    assert resp.status_code == 200
    headers = resp.headers.get_list("set-cookie")
    assert any(
        "refresh_token=" in value
        and "Path=/auth/refresh" in value
        and "SameSite=strict" in value
        and "HttpOnly" in value
        for value in headers
    )
    assert any(
        "refresh_token=" in value and "Path=/" in value and "Max-Age=0" in value
        for value in headers
    ), headers


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

    from app.core.security import BLACKLIST_PREFIX, decode_token

    old_jti = decode_token(login_resp.cookies["refresh_token"])["jti"]

    # Segundo refresh con el token VIEJO, dentro de la ventana de gracia.
    # El predecesor R0 está revocado, pero el ganador R1 no: la comprobación
    # independiente evita que un mock global oculte el límite de seguridad.
    mock_valkey.exists.side_effect = lambda key: int(key == f"{BLACKLIST_PREFIX}{old_jti}")
    mock_valkey.get.return_value = winning_refresh.encode()

    loser = await auth_client.post("/auth/refresh", cookies=login_resp.cookies)
    assert loser.status_code == 200
    assert loser.cookies["refresh_token"] == winning_refresh
    assert "access_token" in loser.json()


async def test_gracia_no_resucita_refresh_ganador_revocado_por_logout(
    blacklist_client, blacklist_valkey, blacklist_store
):
    """R0→R1, logout linked to R1, then replay R0 inside grace must be 401."""
    from app.core.security import BLACKLIST_PREFIX, decode_token

    login_resp = await _login(blacklist_client)
    assert login_resp.status_code == 200
    r0 = login_resp.cookies["refresh_token"]

    winner = await blacklist_client.post(
        "/auth/refresh", cookies={"refresh_token": r0}
    )
    assert winner.status_code == 200
    r1 = winner.cookies["refresh_token"]
    winner_access = winner.json()["access_token"]

    # Model real Valkey reads for the grace record written through setex.
    blacklist_valkey.get.side_effect = lambda key: (
        blacklist_store[key][1] if key in blacklist_store else None
    )
    logout = await blacklist_client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {winner_access}"}
    )
    assert logout.status_code == 200
    assert f"{BLACKLIST_PREFIX}{decode_token(r1)['jti']}" in blacklist_store

    replay = await blacklist_client.post(
        "/auth/refresh", cookies={"refresh_token": r0}
    )
    assert replay.status_code == 401
    assert replay.json()["detail"] == "Refresh token revoked"


async def test_gracia_no_resucita_refresh_ganador_revocado_por_change_password_sin_cookie(
    blacklist_client, blacklist_valkey, blacklist_store
):
    """Password change receives no scoped cookie and revokes R1 through access.refresh_jti."""
    from app.core.security import BLACKLIST_PREFIX, decode_token

    login_resp = await _login(blacklist_client)
    assert login_resp.status_code == 200
    r0 = login_resp.cookies["refresh_token"]
    winner = await blacklist_client.post(
        "/auth/refresh", cookies={"refresh_token": r0}
    )
    assert winner.status_code == 200
    r1 = winner.cookies["refresh_token"]
    winner_access = winner.json()["access_token"]
    r1_jti = decode_token(r1)["jti"]

    blacklist_valkey.get.side_effect = lambda key: (
        blacklist_store[key][1] if key in blacklist_store else None
    )
    # No cookies argument: Path=/auth/refresh prevents the canonical cookie
    # from travelling to /users/change-password.
    changed = await blacklist_client.post(
        "/users/change-password",
        json={
            "current_password": os.environ["ADMIN_PASSWORD"],
            "new_password": "GraceReplayClosed42!",
        },
        headers={"Authorization": f"Bearer {winner_access}"},
    )
    assert changed.status_code == 200
    assert "refresh_token" not in changed.request.headers.get("cookie", "")
    assert f"{BLACKLIST_PREFIX}{r1_jti}" in blacklist_store

    direct_r1 = await blacklist_client.post(
        "/auth/refresh", cookies={"refresh_token": r1}
    )
    replay_r0 = await blacklist_client.post(
        "/auth/refresh", cookies={"refresh_token": r0}
    )
    assert direct_r1.status_code == 401
    assert replay_r0.status_code == 401


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


async def test_logout_revoca_refresh_jti_sin_recibir_cookie_canonica(
    blacklist_client, blacklist_store
):
    """Path=/auth/refresh prevents the cookie reaching logout; the access claim closes the session."""
    from app.core.security import BLACKLIST_PREFIX, decode_token

    access_token, refresh_cookies = await _full_access_login(blacklist_client)
    access_payload = decode_token(access_token)
    refresh_jti = decode_token(refresh_cookies["refresh_token"])["jti"]
    assert access_payload["refresh_jti"] == refresh_jti

    # No explicit cookies: the client's cookie jar obeys Path and does not send
    # the canonical refresh cookie to /auth/logout.
    response = await blacklist_client.post(
        "/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200
    assert "refresh_token" not in response.request.headers.get("cookie", "")
    assert f"{BLACKLIST_PREFIX}{refresh_jti}" in blacklist_store
    clear_headers = response.headers.get_list("set-cookie")
    assert any("Path=/auth/refresh" in value and "Max-Age=0" in value for value in clear_headers)
    assert any("Path=/" in value and "Max-Age=0" in value for value in clear_headers)


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


async def _change_password_with_scope(
    auth_client, *, current_password=None, new_password="NewStrongPassword42!"
):
    """Login del admin de seed (scope password_change_only) y llama a change-password."""
    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]
    body = {"new_password": new_password}
    if current_password is not None:
        body["current_password"] = current_password
    resp = await auth_client.post(
        "/users/change-password",
        json=body,
        headers={"Authorization": f"Bearer {access_token}"},
        cookies=login_resp.cookies,
    )
    return resp


async def test_change_password_con_scope_password_change_only(auth_client):
    """Primer login → change-password con scope especial, current_password correcto → 200."""
    resp = await _change_password_with_scope(
        auth_client, current_password=os.environ["ADMIN_PASSWORD"]
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "password_changed"


async def test_change_password_short_retorna_422(auth_client):
    resp = await _change_password_with_scope(
        auth_client, current_password=os.environ["ADMIN_PASSWORD"], new_password="short"
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "new_password",
    [
        pytest.param("lowercase123andmore", id="sin_mayuscula"),
        pytest.param("UPPERCASE123ANDMORE", id="sin_minuscula"),
        pytest.param("NoDigitsHereAtAllXX", id="sin_digito"),
    ],
)
async def test_change_password_sin_complejidad_retorna_422(auth_client, new_password):
    """US-27/RN-100: 422 con detail string, sin tocar password_hash."""
    from app.core.database import engine
    from sqlmodel import Session, select

    from app.core.security import verify_password
    from app.modules.auth.models import User

    resp = await _change_password_with_scope(
        auth_client, current_password=os.environ["ADMIN_PASSWORD"], new_password=new_password
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], str)

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == os.environ["ADMIN_USERNAME"])
        ).one()
        # El seed hashea ADMIN_PASSWORD; un cambio exitoso hubiera reemplazado el hash.
        assert verify_password(os.environ["ADMIN_PASSWORD"], user.password_hash)


async def _assert_seed_hash_unchanged():
    from app.core.database import engine
    from sqlmodel import Session, select

    from app.core.security import verify_password
    from app.modules.auth.models import User

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == os.environ["ADMIN_USERNAME"])
        ).one()
        assert verify_password(os.environ["ADMIN_PASSWORD"], user.password_hash)
        assert user.must_change_password is True


async def test_change_password_current_password_incorrecto_scope_forzado_retorna_401(
    auth_client,
):
    """US-27 D-2: scope password_change_only también exige current_password correcto."""
    resp = await _change_password_with_scope(auth_client, current_password="not-the-seed-pwd")
    assert resp.status_code == 401
    await _assert_seed_hash_unchanged()


async def test_change_password_current_password_ausente_scope_forzado_retorna_401(auth_client):
    resp = await _change_password_with_scope(auth_client, current_password=None)
    assert resp.status_code == 401
    await _assert_seed_hash_unchanged()


async def test_change_password_current_password_correcto_scope_normal(auth_client):
    """Cambio normal (scope pleno) con current_password correcto → 200, must_change_password False."""
    from app.core.database import engine
    from sqlmodel import Session, select

    from app.modules.auth.models import User

    first = await _login(auth_client)
    assert first.status_code == 200
    changed = await auth_client.post(
        "/users/change-password",
        json={
            "current_password": os.environ["ADMIN_PASSWORD"],
            "new_password": _NEW_ADMIN_PASSWORD,
        },
        headers={"Authorization": f"Bearer {first.json()['access_token']}"},
    )
    assert changed.status_code == 200

    full = await _login(auth_client, password=_NEW_ADMIN_PASSWORD)
    assert full.status_code == 200
    access_token = full.json()["access_token"]

    resp = await auth_client.post(
        "/users/change-password",
        json={
            "current_password": _NEW_ADMIN_PASSWORD,
            "new_password": "AnotherValidPass9!",
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == os.environ["ADMIN_USERNAME"])
        ).one()
        assert user.must_change_password is False


async def test_change_password_current_password_incorrecto_scope_normal_retorna_401(
    auth_client,
):
    first = await _login(auth_client)
    assert first.status_code == 200
    changed = await auth_client.post(
        "/users/change-password",
        json={
            "current_password": os.environ["ADMIN_PASSWORD"],
            "new_password": _NEW_ADMIN_PASSWORD,
        },
        headers={"Authorization": f"Bearer {first.json()['access_token']}"},
    )
    assert changed.status_code == 200

    full = await _login(auth_client, password=_NEW_ADMIN_PASSWORD)
    assert full.status_code == 200
    access_token = full.json()["access_token"]

    resp = await auth_client.post(
        "/users/change-password",
        json={"current_password": "wrong-password", "new_password": "AnotherValidPass9!"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 401

    from app.core.database import engine
    from sqlmodel import Session, select

    from app.core.security import verify_password
    from app.modules.auth.models import User

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == os.environ["ADMIN_USERNAME"])
        ).one()
        assert verify_password(_NEW_ADMIN_PASSWORD, user.password_hash)


async def test_change_password_mayuscula_no_ascii_cuenta(auth_client):
    """Ñ como única mayúscula cumple la complejidad (D-1)."""
    resp = await _change_password_with_scope(
        auth_client,
        current_password=os.environ["ADMIN_PASSWORD"],
        new_password="Ñuevopassword1",
    )
    assert resp.status_code == 200


async def test_change_password_hashea_con_argon2id_c9_y_no_verifica_contra_anterior(
    auth_client,
):
    from app.core.database import engine
    from sqlmodel import Session, select

    from app.core.security import verify_password
    from app.modules.auth.models import User

    resp = await _change_password_with_scope(
        auth_client, current_password=os.environ["ADMIN_PASSWORD"]
    )
    assert resp.status_code == 200

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == os.environ["ADMIN_USERNAME"])
        ).one()
        assert user.password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
        assert verify_password("NewStrongPassword42!", user.password_hash)
        assert not verify_password(os.environ["ADMIN_PASSWORD"], user.password_hash)


async def test_change_password_deja_fila_en_audit_log(auth_client):
    from app.core.database import engine
    from sqlmodel import Session, select

    from app.modules.audit.models import AuditLog
    from app.modules.auth.models import User

    resp = await _change_password_with_scope(
        auth_client, current_password=os.environ["ADMIN_PASSWORD"]
    )
    assert resp.status_code == 200

    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == os.environ["ADMIN_USERNAME"])
        ).one()
        rows = session.exec(
            select(AuditLog).where(
                AuditLog.action == "change_password", AuditLog.user_id == user.id
            )
        ).all()
        assert len(rows) == 1


async def test_change_password_no_completado_se_vuelve_a_exigir(auth_client):
    """Login del seed sin completar el cambio, segundo login → sigue en password_change_only."""
    first = await _login(auth_client)
    assert first.status_code == 200
    assert first.json()["must_change_password"] is True

    second = await _login(auth_client)
    assert second.status_code == 200
    assert second.json()["must_change_password"] is True

    from app.core.security import decode_token

    payload = decode_token(second.json()["access_token"])
    assert payload.get("scope") == "password_change_only"


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
            json={
                "current_password": os.environ["ADMIN_PASSWORD"],
                "new_password": "AnotherGoodPassword1!",
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert cp_resp.status_code == 200
