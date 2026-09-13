"""
D55/RN-149 (change 52) — atributo `Secure` de la cookie de refresh derivado
de `CONSOLE_TLS_MODE`, no de `ENVIRONMENT`.
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock


@pytest.fixture
def mock_valkey():
    m = MagicMock()
    m.incr.return_value = 1
    m.expire.return_value = True
    m.exists.return_value = 0
    m.setex.return_value = True
    m.close.return_value = None
    m.get.return_value = None
    return m


@pytest.fixture
async def auth_client(mock_valkey):
    from app.core.valkey import get_valkey_client
    from app.main import app

    app.dependency_overrides[get_valkey_client] = lambda: mock_valkey
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_valkey_client, None)


async def _login(auth_client):
    return await auth_client.post(
        "/auth/login",
        json={
            "username": os.environ["ADMIN_USERNAME"],
            "password": os.environ["ADMIN_PASSWORD"],
        },
    )


def _canonical_cookie(resp) -> str:
    headers = resp.headers.get_list("set-cookie")
    return next(v for v in headers if "Path=/auth/refresh" in v)


# ── Login ──────────────────────────────────────────────────────────────────


async def test_off_con_environment_prod_sin_secure(monkeypatch, auth_client) -> None:
    from app.modules.auth import router as auth_router_module

    monkeypatch.setattr(auth_router_module.settings, "console_tls_mode", "off")
    monkeypatch.setattr(auth_router_module.settings, "environment", "prod")

    resp = await _login(auth_client)
    assert resp.status_code == 200
    assert "Secure" not in _canonical_cookie(resp)


async def test_self_signed_con_environment_dev_con_secure(monkeypatch, auth_client) -> None:
    from app.modules.auth import router as auth_router_module

    monkeypatch.setattr(auth_router_module.settings, "console_tls_mode", "self_signed")
    monkeypatch.setattr(auth_router_module.settings, "environment", "dev")

    resp = await _login(auth_client)
    assert resp.status_code == 200
    assert "Secure" in _canonical_cookie(resp)


# ── Refresh ────────────────────────────────────────────────────────────────


async def test_rotacion_en_refresh_con_provided_lleva_secure(monkeypatch, auth_client) -> None:
    from app.modules.auth import router as auth_router_module

    monkeypatch.setattr(auth_router_module.settings, "console_tls_mode", "provided")

    login_resp = await _login(auth_client)
    assert login_resp.status_code == 200
    refresh_cookie = login_resp.cookies.get("refresh_token")
    assert refresh_cookie

    refresh_resp = await auth_client.post(
        "/auth/refresh", cookies={"refresh_token": refresh_cookie}
    )
    assert refresh_resp.status_code == 200
    assert "Secure" in _canonical_cookie(refresh_resp)


# ── Validación de Settings ─────────────────────────────────────────────────


def test_console_tls_mode_invalido_lanza_validation_error(monkeypatch) -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    env = dict(os.environ)
    env["CONSOLE_TLS_MODE"] = "https"
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError, match="console_tls_mode"):
        Settings()


# ── Log de arranque ────────────────────────────────────────────────────────
#
# `_log_console_tls_mode` está extraída de `lifespan` justamente para que
# esto no tenga que levantar el lifespan completo (Valkey, CA, consumers,
# servidores mTLS/bootstrap) sólo para observar un log de arranque.


def test_advertencia_en_modo_off(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "console_tls_mode", "off")
    fake_log = MagicMock()
    monkeypatch.setattr(main_module, "log", fake_log)

    main_module._log_console_tls_mode()

    fake_log.warning.assert_called_once()
    args, kwargs = fake_log.warning.call_args
    assert args[0] == "backend.console_tls_mode"
    assert kwargs["console_tls_mode"] == "off"
    fake_log.info.assert_not_called()


def test_sin_advertencia_fuera_de_modo_off(monkeypatch) -> None:
    from unittest.mock import MagicMock

    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "console_tls_mode", "self_signed")
    fake_log = MagicMock()
    monkeypatch.setattr(main_module, "log", fake_log)

    main_module._log_console_tls_mode()

    fake_log.info.assert_called_once()
    args, kwargs = fake_log.info.call_args
    assert args[0] == "backend.console_tls_mode"
    assert kwargs["console_tls_mode"] == "self_signed"
    fake_log.warning.assert_not_called()
