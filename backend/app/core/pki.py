"""
PKI propia del backend FIM — CA Ed25519, emisión de certs de agentes,
revocación y servidor mTLS en puerto 8443 (RN-78, C6).
"""

from __future__ import annotations

import datetime
import os
import ssl
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.core.logging import log

if TYPE_CHECKING:
    from sqlmodel import Session

_CA_VALIDITY_DAYS = 365 * 10
_CERT_VALIDITY_DAYS = 90


def _write_pem(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
    except Exception:
        raise
    os.chmod(path, mode)


def ensure_ca(
    cert_path: str,
    key_path: str,
    backend_cert_path: str = "",
    backend_key_path: str = "",
) -> None:
    """Genera la CA raíz si no existe y el cert del backend para mTLS."""
    if not cert_path or not key_path:
        log.warning("pki.ensure_ca.skipped", reason="CA_CERT_PATH or CA_KEY_PATH not set")
        return

    p_cert = Path(cert_path)
    p_key = Path(key_path)

    if not p_key.exists():
        ca_key = Ed25519PrivateKey.generate()
        _write_pem(p_key, ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ), mode=0o400)

        now = datetime.datetime.now(datetime.timezone.utc)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "FIM Platform CA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FIM Platform"),
        ])
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=_CA_VALIDITY_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(ca_key, None)  # type: ignore[arg-type]  # Ed25519 has no hash
        )
        _write_pem(p_cert, ca_cert.public_bytes(serialization.Encoding.PEM), mode=0o644)
        log.info("pki.ca.initialized", cert_path=cert_path)
    else:
        log.info("pki.ca.loaded", cert_path=cert_path)

    if backend_cert_path and backend_key_path:
        _ensure_backend_cert(cert_path, key_path, backend_cert_path, backend_key_path)


def _ensure_backend_cert(
    ca_cert_path: str,
    ca_key_path: str,
    cert_path: str,
    key_path: str,
) -> None:
    p_key = Path(key_path)
    p_cert = Path(cert_path)

    if p_key.exists():
        return

    ca_key = serialization.load_pem_private_key(Path(ca_key_path).read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())

    backend_key = Ed25519PrivateKey.generate()
    _write_pem(p_key, backend_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ), mode=0o400)

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fim-backend")]))
        .issuer_name(ca_cert.subject)
        .public_key(backend_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, None)  # type: ignore[arg-type]
    )
    _write_pem(p_cert, cert.public_bytes(serialization.Encoding.PEM), mode=0o644)
    log.info("pki.backend_cert.generated", cert_path=cert_path)


def issue_certificate(csr_pem: str, ca_cert_path: str, ca_key_path: str) -> str:
    """Firma un CSR con la CA y retorna el cert PEM."""
    ca_key = serialization.load_pem_private_key(Path(ca_key_path).read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())
    csr = x509.load_pem_x509_csr(csr_pem.encode())

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(ca_key, None)  # type: ignore[arg-type]
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def is_revoked(serial: int, session: "Session") -> bool:
    """Consulta la tabla revoked_certificates por número de serie."""
    from sqlmodel import select

    from app.modules.agents.models import RevokedCertificate

    result = session.exec(
        select(RevokedCertificate).where(RevokedCertificate.serial_number == str(serial))
    ).first()
    return result is not None


def start_mtls_server(
    app: object,
    ca_cert_path: str,
    cert_path: str,
    key_path: str,
) -> "uvicorn.Server | None":
    """
    Construye un servidor uvicorn para puerto 8443 con mTLS (CERT_REQUIRED)
    y lo retorna sin arrancarlo. El caller es responsable de lanzar
    asyncio.create_task(server.serve()) en el lifespan (C10).

    Retorna None cuando los certificados no están disponibles.
    """
    import uvicorn

    if not all([ca_cert_path, cert_path, key_path]):
        log.warning("pki.mtls_server.skipped", reason="cert paths not configured")
        return None

    if not Path(cert_path).exists() or not Path(key_path).exists():
        log.warning("pki.mtls_server.skipped", reason="cert or key file not found")
        return None

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8443,
        ssl_keyfile=key_path,
        ssl_certfile=cert_path,
        ssl_ca_certs=ca_cert_path,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        log_level="info",
        lifespan="off",
    )
    config.install_signal_handlers = False
    server = uvicorn.Server(config)
    log.info("pki.mtls_server.configured", port=8443)
    return server
