"""
Regression tests C22/C10 — mTLS server on the main event loop.

Verifica:
- start_mtls_server retorna un Server con install_signal_handlers=False.
- start_mtls_server no spawna ningún Thread.
- start_mtls_server retorna None cuando los cert paths no existen.
"""

from __future__ import annotations

import os
import threading

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")


# ── start_mtls_server retorna Server con install_signal_handlers=False ────────


def test_start_mtls_server_retorna_server_con_install_signal_handlers_false(tmp_path) -> None:
    """Con certs presentes, retorna uvicorn.Server con install_signal_handlers=False."""
    import uvicorn
    from fastapi import FastAPI

    from app.core.pki import start_mtls_server

    # Crear archivos dummy de certificados
    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"
    ca_file = tmp_path / "ca.pem"
    cert_file.write_text("CERT")
    key_file.write_text("KEY")
    ca_file.write_text("CA")

    app = FastAPI()
    server = start_mtls_server(
        app,
        ca_cert_path=str(ca_file),
        cert_path=str(cert_file),
        key_path=str(key_file),
    )

    assert server is not None
    assert isinstance(server, uvicorn.Server)
    assert server.config.install_signal_handlers is False


def test_start_mtls_server_no_spawna_thread(tmp_path) -> None:
    """La función no debe crear ningún threading.Thread."""
    from fastapi import FastAPI

    from app.core.pki import start_mtls_server

    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"
    ca_file = tmp_path / "ca.pem"
    cert_file.write_text("CERT")
    key_file.write_text("KEY")
    ca_file.write_text("CA")

    threads_before = set(t.name for t in threading.enumerate())

    app = FastAPI()
    start_mtls_server(
        app,
        ca_cert_path=str(ca_file),
        cert_path=str(cert_file),
        key_path=str(key_file),
    )

    threads_after = set(t.name for t in threading.enumerate())
    new_threads = threads_after - threads_before

    # No debe haber nuevos threads relacionados con mTLS
    assert not any("mtls" in name.lower() or "fim" in name.lower() for name in new_threads), (
        f"start_mtls_server spawneó threads inesperados: {new_threads}"
    )


# ── start_mtls_server retorna None cuando faltan cert paths ──────────────────


def test_start_mtls_server_retorna_none_cuando_cert_no_existe(tmp_path) -> None:
    """Si los archivos de cert no existen, retorna None."""
    from fastapi import FastAPI

    from app.core.pki import start_mtls_server

    app = FastAPI()
    result = start_mtls_server(
        app,
        ca_cert_path=str(tmp_path / "noexiste_ca.pem"),
        cert_path=str(tmp_path / "noexiste_cert.pem"),
        key_path=str(tmp_path / "noexiste_key.pem"),
    )

    assert result is None


def test_start_mtls_server_retorna_none_cuando_paths_vacios() -> None:
    """Si los paths están vacíos, retorna None sin excepciones."""
    from fastapi import FastAPI

    from app.core.pki import start_mtls_server

    app = FastAPI()
    result = start_mtls_server(app, ca_cert_path="", cert_path="", key_path="")
    assert result is None
