"""
Unit tests — L8: mTLS del backend hacia Valkey (D17/RN-115, D20 alcance backend).

Cubre app.core.valkey._tls_kwargs() y los tres puntos de construcción de
cliente que dependen de ella (init_valkey, init_async_valkey,
build_async_valkey_client — este último usado por app.main para el cliente
dedicado de los consumers). Todas las llamadas a from_url están mockeadas:
no requieren un Valkey real corriendo (ese caso vive en
test_valkey_tls_integration.py, gateado por TEST_VALKEY_TLS=1).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")


@pytest.fixture(autouse=True)
def _configured_certs():
    """Point settings at plausible (non-existent-on-disk, that's fine — these
    tests never touch the filesystem) cert paths for the TLS-happy-path cases.

    Deliberately reads `app.core.valkey.settings` (the reference _tls_kwargs()
    actually closes over) instead of doing a fresh `from app.core.config import
    settings`. Another test module (test_notification_settings.py) does
    `importlib.reload(app.core.config)`, which rebinds `app.core.config.settings`
    to a NEW instance for the rest of the session — a fresh import here would
    silently pick up that new object while app.core.valkey keeps the one it
    imported at its own module load time, and the two would drift apart.
    """
    import app.core.valkey as valkey_mod

    settings = valkey_mod.settings
    original = (settings.ca_cert_path, settings.backend_cert_path, settings.backend_key_path)
    settings.ca_cert_path = "/certs/ca.pem"
    settings.backend_cert_path = "/certs/backend.pem"
    settings.backend_key_path = "/certs/backend-key.pem"
    yield settings
    settings.ca_cert_path, settings.backend_cert_path, settings.backend_key_path = original


# ── _tls_kwargs: scheme handling ─────────────────────────────────────────────


@pytest.mark.parametrize("scheme", ["valkey", "redis"])
def test_plaintext_schemes_get_no_tls_kwargs(scheme):
    from app.core.valkey import _tls_kwargs

    assert _tls_kwargs(f"{scheme}://localhost:6379") == {}


@pytest.mark.parametrize("scheme", ["valkeys", "rediss"])
def test_tls_schemes_get_ssl_kwargs_from_settings(scheme):
    from app.core.valkey import _tls_kwargs

    kwargs = _tls_kwargs(f"{scheme}://valkey:6380")

    assert kwargs == {
        "ssl_certfile": "/certs/backend.pem",
        "ssl_keyfile": "/certs/backend-key.pem",
        "ssl_ca_certs": "/certs/ca.pem",
        "ssl_check_hostname": True,
    }


@pytest.mark.parametrize("scheme", ["valkeys", "rediss"])
@pytest.mark.parametrize(
    "missing_field",
    ["ca_cert_path", "backend_cert_path", "backend_key_path"],
)
def test_tls_scheme_missing_any_cert_setting_raises(scheme, missing_field):
    import app.core.valkey as valkey_mod
    from app.core.valkey import _tls_kwargs

    setattr(valkey_mod.settings, missing_field, "")

    with pytest.raises(RuntimeError, match=missing_field):
        _tls_kwargs(f"{scheme}://valkey:6380")


def test_tls_scheme_missing_all_certs_raises_with_all_names():
    import app.core.valkey as valkey_mod
    from app.core.valkey import _tls_kwargs

    valkey_mod.settings.ca_cert_path = ""
    valkey_mod.settings.backend_cert_path = ""
    valkey_mod.settings.backend_key_path = ""

    with pytest.raises(RuntimeError) as exc_info:
        _tls_kwargs("valkeys://valkey:6380")

    message = str(exc_info.value)
    assert "ca_cert_path" in message
    assert "backend_cert_path" in message
    assert "backend_key_path" in message


# ── init_valkey / init_async_valkey / build_async_valkey_client wiring ───────


def test_init_valkey_passes_tls_kwargs_to_from_url():
    import app.core.valkey as valkey_mod

    with patch.object(valkey_mod._valkey_pkg.Valkey, "from_url") as mock_from_url:
        mock_from_url.return_value = MagicMock()
        valkey_mod.init_valkey("valkeys://valkey:6380")

    mock_from_url.assert_called_once_with(
        "valkeys://valkey:6380",
        decode_responses=True,
        ssl_certfile="/certs/backend.pem",
        ssl_keyfile="/certs/backend-key.pem",
        ssl_ca_certs="/certs/ca.pem",
        ssl_check_hostname=True,
    )
    valkey_mod.close_valkey()


def test_init_valkey_plaintext_unchanged():
    import app.core.valkey as valkey_mod

    with patch.object(valkey_mod._valkey_pkg.Valkey, "from_url") as mock_from_url:
        mock_from_url.return_value = MagicMock()
        valkey_mod.init_valkey("valkey://localhost:6379")

    mock_from_url.assert_called_once_with("valkey://localhost:6379", decode_responses=True)
    valkey_mod.close_valkey()


def test_init_async_valkey_passes_tls_kwargs_to_from_url():
    import app.core.valkey as valkey_mod

    with patch.object(valkey_mod._valkey_async_pkg.Valkey, "from_url") as mock_from_url:
        mock_from_url.return_value = MagicMock()
        valkey_mod.init_async_valkey("rediss://valkey:6380")

    mock_from_url.assert_called_once_with(
        "rediss://valkey:6380",
        decode_responses=True,
        ssl_certfile="/certs/backend.pem",
        ssl_keyfile="/certs/backend-key.pem",
        ssl_ca_certs="/certs/ca.pem",
        ssl_check_hostname=True,
    )
    valkey_mod._async_client = None


def test_build_async_valkey_client_used_by_main_dedicated_consumer_client():
    """app.main builds one extra async client (outside the DI singleton) for
    the asyncio consumers — it must share the same TLS wiring."""
    import app.core.valkey as valkey_mod

    with patch.object(valkey_mod._valkey_async_pkg.Valkey, "from_url") as mock_from_url:
        mock_from_url.return_value = MagicMock()
        client = valkey_mod.build_async_valkey_client("valkeys://valkey:6380")

    assert client is mock_from_url.return_value
    mock_from_url.assert_called_once_with(
        "valkeys://valkey:6380",
        decode_responses=True,
        ssl_certfile="/certs/backend.pem",
        ssl_keyfile="/certs/backend-key.pem",
        ssl_ca_certs="/certs/ca.pem",
        ssl_check_hostname=True,
    )


def test_init_valkey_missing_certs_raises_and_never_calls_from_url():
    import app.core.valkey as valkey_mod

    valkey_mod.settings.backend_cert_path = ""

    with patch.object(valkey_mod._valkey_pkg.Valkey, "from_url") as mock_from_url:
        with pytest.raises(RuntimeError, match="backend_cert_path"):
            valkey_mod.init_valkey("valkeys://valkey:6380")

    mock_from_url.assert_not_called()
