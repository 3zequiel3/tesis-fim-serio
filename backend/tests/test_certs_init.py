"""
`backend/app/core/certs_init.py` — servicio one-shot `certs-init` (D53/RN-147,
D-1). Ejercita `main()` directamente (equivalente a `python -m
app.core.certs_init`) sobre directorios temporales, sin depender de correr
como root: `_chown` es un no-op fuera de root (ver comentario en el módulo),
así que estos tests verifican contenido y estructura, no ownership real —
eso lo cubre la integración de contenedor (tarea 3.5, fuera de este batch).
"""

from __future__ import annotations

import os

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")


@pytest.fixture()
def certs_init_env(tmp_path, monkeypatch):
    backend_certs = tmp_path / "backend_certs"
    valkey_tls = tmp_path / "valkey_tls"
    console_tls = tmp_path / "console_tls_generated"
    backend_certs.mkdir()

    monkeypatch.setenv("CA_CERT_PATH", str(backend_certs / "ca.pem"))
    monkeypatch.setenv("CA_KEY_PATH", str(backend_certs / "ca-key.pem"))
    monkeypatch.setenv("BACKEND_CERT_PATH", str(backend_certs / "backend.pem"))
    monkeypatch.setenv("BACKEND_KEY_PATH", str(backend_certs / "backend-key.pem"))
    monkeypatch.setenv("BACKEND_VALKEY_CERT_PATH", str(backend_certs / "backend-valkey.pem"))
    monkeypatch.setenv("BACKEND_VALKEY_KEY_PATH", str(backend_certs / "backend-valkey-key.pem"))
    monkeypatch.setenv("VALKEY_TLS_DIR", str(valkey_tls))
    monkeypatch.setenv("CONSOLE_TLS_GENERATED_DIR", str(console_tls))
    monkeypatch.delenv("FIM_PUBLIC_HOSTS", raising=False)
    monkeypatch.setenv("CONSOLE_TLS_MODE", "off")
    return {
        "backend_certs": backend_certs,
        "valkey_tls": valkey_tls,
        "console_tls": console_tls,
    }


def test_arranque_limpio_crea_todo(certs_init_env) -> None:
    from app.core.certs_init import main

    assert main() == 0

    backend_certs = certs_init_env["backend_certs"]
    valkey_tls = certs_init_env["valkey_tls"]
    assert (backend_certs / "ca.pem").exists()
    assert (backend_certs / "ca-key.pem").exists()
    assert (backend_certs / "backend.pem").exists()
    assert (backend_certs / "backend-key.pem").exists()
    assert (backend_certs / "backend-valkey.pem").exists()
    assert (backend_certs / "backend-valkey-key.pem").exists()
    assert (valkey_tls / "valkey.pem").exists()
    assert (valkey_tls / "valkey-key.pem").exists()
    assert (valkey_tls / "ca.pem").exists()
    # off (default): no console cert.
    assert not certs_init_env["console_tls"].exists()


def test_segunda_corrida_no_reescribe_nada(certs_init_env) -> None:
    from app.core.certs_init import main

    assert main() == 0
    backend_certs = certs_init_env["backend_certs"]
    valkey_tls = certs_init_env["valkey_tls"]

    serials_before = {
        name: x509.load_pem_x509_certificate((backend_certs / name).read_bytes()).serial_number
        for name in ["ca.pem", "backend.pem", "backend-valkey.pem"]
    }
    serials_before["valkey.pem"] = x509.load_pem_x509_certificate(
        (valkey_tls / "valkey.pem").read_bytes()
    ).serial_number

    assert main() == 0

    serials_after = {
        name: x509.load_pem_x509_certificate((backend_certs / name).read_bytes()).serial_number
        for name in ["ca.pem", "backend.pem", "backend-valkey.pem"]
    }
    serials_after["valkey.pem"] = x509.load_pem_x509_certificate(
        (valkey_tls / "valkey.pem").read_bytes()
    ).serial_number
    assert serials_before == serials_after


def test_host_invalido_exit_distinto_de_cero_certificado_dependiente_no_se_escribe(
    certs_init_env, monkeypatch
) -> None:
    from app.core.certs_init import main

    monkeypatch.setenv("FIM_PUBLIC_HOSTS", "bad_host!")
    assert main() != 0

    backend_certs = certs_init_env["backend_certs"]
    assert not (backend_certs / "backend.pem").exists()
    assert not (backend_certs / "backend-valkey.pem").exists()
    assert not certs_init_env["valkey_tls"].exists() or not list(
        certs_init_env["valkey_tls"].iterdir()
    )


def test_modo_off_no_emite_certificado_de_consola(certs_init_env) -> None:
    from app.core.certs_init import main

    assert main() == 0
    assert not certs_init_env["console_tls"].exists()


def test_modo_self_signed_emite_certificado_de_consola(certs_init_env, monkeypatch) -> None:
    from app.core.certs_init import main

    monkeypatch.setenv("CONSOLE_TLS_MODE", "self_signed")
    assert main() == 0

    console_tls = certs_init_env["console_tls"]
    assert (console_tls / "console.pem").exists()
    assert (console_tls / "console-key.pem").exists()

    # D62/RN-156: standalone self-signed, ECDSA P-256 — never the CA's Ed25519.
    cert = x509.load_pem_x509_certificate((console_tls / "console.pem").read_bytes())
    assert cert.issuer == cert.subject
    ca_cert = x509.load_pem_x509_certificate(
        (certs_init_env["backend_certs"] / "ca.pem").read_bytes()
    )
    assert cert.issuer != ca_cert.subject
    public_key = cert.public_key()
    assert isinstance(public_key, ec.EllipticCurvePublicKey)
    assert isinstance(public_key.curve, ec.SECP256R1)


def test_directorio_de_valkey_no_contiene_ca_key(certs_init_env) -> None:
    from app.core.certs_init import main

    assert main() == 0
    valkey_tls = certs_init_env["valkey_tls"]
    names = {p.name for p in valkey_tls.iterdir()}
    assert "ca-key.pem" not in names
    assert names == {"valkey.pem", "valkey-key.pem", "ca.pem"}


def test_modo_console_tls_invalido_exit_distinto_de_cero(certs_init_env, monkeypatch) -> None:
    from app.core.certs_init import main

    monkeypatch.setenv("CONSOLE_TLS_MODE", "https")
    assert main() != 0
