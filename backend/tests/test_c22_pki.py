"""
Regression tests C22/C10 — mTLS server on the main event loop.

Verifica:
- start_mtls_server retorna un Server con install_signal_handlers=False.
- start_mtls_server no spawna ningún Thread.
- start_mtls_server retorna None cuando los cert paths no existen.
"""

from __future__ import annotations

import datetime
import os
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")


# ── start_mtls_server retorna Server con install_signal_handlers=False ────────


def _real_cert_paths(tmp_path):
    from app.core.pki import ensure_ca

    ca_file = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"
    ensure_ca(str(ca_file), str(ca_key), str(cert_file), str(key_file))
    return ca_file, cert_file, key_file


def test_ensure_ca_creates_strict_ca_key_usage(tmp_path) -> None:
    from app.core.pki import ensure_ca

    ca_file = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    ensure_ca(str(ca_file), str(ca_key))

    certificate = x509.load_pem_x509_certificate(ca_file.read_bytes())
    key_usage = certificate.extensions.get_extension_for_class(x509.KeyUsage)
    assert key_usage.critical is True
    assert key_usage.value.key_cert_sign is True
    assert key_usage.value.crl_sign is True
    certificate.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)


def test_ensure_ca_rejects_legacy_ca_without_key_usage_without_rewriting(tmp_path) -> None:
    from app.core.pki import ensure_ca

    now = datetime.datetime.now(datetime.timezone.utc)
    key = Ed25519PrivateKey.generate()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "legacy-ca")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, None)
    )
    ca_file = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    original_cert = certificate.public_bytes(serialization.Encoding.PEM)
    original_key = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    ca_file.write_bytes(original_cert)
    ca_key.write_bytes(original_key)

    with pytest.raises(RuntimeError, match="rotate the CA and re-enroll"):
        ensure_ca(str(ca_file), str(ca_key))

    assert ca_file.read_bytes() == original_cert
    assert ca_key.read_bytes() == original_key


def test_start_mtls_server_retorna_server_con_install_signal_handlers_false(tmp_path) -> None:
    """Con certs presentes, retorna uvicorn.Server con install_signal_handlers=False."""
    import uvicorn
    from fastapi import FastAPI

    from app.core.pki import start_mtls_server

    ca_file, cert_file, key_file = _real_cert_paths(tmp_path)

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
    assert server.config.ssl.minimum_version.name == "TLSv1_3"


def test_start_mtls_server_no_spawna_thread(tmp_path) -> None:
    """La función no debe crear ningún threading.Thread."""
    from fastapi import FastAPI

    from app.core.pki import start_mtls_server

    ca_file, cert_file, key_file = _real_cert_paths(tmp_path)

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
