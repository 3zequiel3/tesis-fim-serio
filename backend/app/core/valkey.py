"""
Singletons del cliente Valkey para FIM Platform.

Sync (init_valkey / get_valkey_client): usado por servicios de negocio y health.
Async (init_async_valkey / get_async_valkey_client): usado por dependencias FastAPI
  (get_current_user, rate limit) para no bloquear el event loop.

Ambos se inicializan en el lifespan de FastAPI (startup).
Las conexiones son lazy — from_url no abre sockets hasta el primer comando.

mTLS (D17/RN-115, L8): los esquemas `valkeys://` / `rediss://` activan
ssl_check_hostname=True y requieren certificado de cliente. El backend
reutiliza su propio cert/key emitidos por la CA (settings.backend_cert_path /
settings.backend_key_path — el mismo par que usa como servidor mTLS de
agentes en app/core/pki.py) como identidad de cliente Valkey, y
settings.ca_cert_path como trust anchor. Evita emitir un segundo certificado
sólo para este propósito. Los esquemas en texto plano (`valkey://` /
`redis://`) no cambian de comportamiento.
"""

from __future__ import annotations

from urllib.parse import urlparse

import valkey as _valkey_pkg
import valkey.asyncio as _valkey_async_pkg

from app.core.config import settings

_TLS_SCHEMES = {"valkeys", "rediss"}

_client: _valkey_pkg.Valkey | None = None
_async_client: _valkey_async_pkg.Valkey | None = None


def _tls_kwargs(url: str) -> dict[str, object]:
    """Build the ssl_* kwargs for from_url() when the scheme requires mTLS.

    Returns {} for plaintext schemes (valkey:// / redis://) — no behavior
    change. Raises RuntimeError fast when the scheme is valkeys:// / rediss://
    but the required cert settings are not configured, instead of letting the
    underlying client fail later with a confusing low-level TLS error.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in _TLS_SCHEMES:
        return {}

    required = (
        ("ca_cert_path", settings.ca_cert_path),
        ("backend_cert_path", settings.backend_cert_path),
        ("backend_key_path", settings.backend_key_path),
    )
    missing = [name for name, value in required if not value]
    if missing:
        raise RuntimeError(
            f"Valkey TLS scheme '{scheme}://' requires cert settings that are "
            f"not configured: {', '.join(missing)} (D17/RN-115)"
        )

    return {
        "ssl_certfile": settings.backend_cert_path,
        "ssl_keyfile": settings.backend_key_path,
        "ssl_ca_certs": settings.ca_cert_path,
        "ssl_check_hostname": True,
    }


def build_async_valkey_client(url: str) -> _valkey_async_pkg.Valkey:
    """Factory shared by init_async_valkey() and the dedicated consumer client
    in app.main (one per asyncio consumer task, outside the FastAPI DI client).
    """
    return _valkey_async_pkg.Valkey.from_url(url, decode_responses=True, **_tls_kwargs(url))


def init_valkey(url: str) -> None:
    global _client
    _client = _valkey_pkg.Valkey.from_url(url, decode_responses=True, **_tls_kwargs(url))


def close_valkey() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_valkey_client() -> _valkey_pkg.Valkey:
    if _client is None:
        raise RuntimeError("Valkey client not initialized — init_valkey() not called")
    return _client


def init_async_valkey(url: str) -> None:
    global _async_client
    _async_client = build_async_valkey_client(url)


async def close_async_valkey() -> None:
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None


def get_async_valkey_client() -> _valkey_async_pkg.Valkey:
    if _async_client is None:
        raise RuntimeError("Async Valkey client not initialized — init_async_valkey() not called")
    return _async_client
