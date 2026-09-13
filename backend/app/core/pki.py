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
_CERT_RENEWAL_THRESHOLD_DAYS = 15
PEER_CERT_SCOPE_KEY = "mtls_peer_certificate_der"


def _validate_ca_profile(ca_cert: x509.Certificate) -> None:
    """Reject persisted CAs that cannot act as a strict TLS trust anchor."""
    try:
        basic_constraints = ca_cert.extensions.get_extension_for_class(
            x509.BasicConstraints
        )
        key_usage = ca_cert.extensions.get_extension_for_class(x509.KeyUsage)
        ca_cert.extensions.get_extension_for_class(x509.SubjectKeyIdentifier)
    except x509.ExtensionNotFound as exc:
        raise RuntimeError(
            "existing CA certificate lacks required BasicConstraints, critical "
            "KeyUsage, or SubjectKeyIdentifier; rotate the CA and re-enroll agents "
            "administratively"
        ) from exc

    if not basic_constraints.critical or not basic_constraints.value.ca:
        raise RuntimeError(
            "existing CA certificate does not have critical CA BasicConstraints; "
            "rotate the CA and re-enroll agents administratively"
        )
    if (
        not key_usage.critical
        or not key_usage.value.key_cert_sign
        or not key_usage.value.crl_sign
    ):
        raise RuntimeError(
            "existing CA certificate does not have critical KeyUsage with "
            "keyCertSign and cRLSign; rotate the CA and re-enroll agents "
            "administratively"
        )


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

    if p_cert.exists() != p_key.exists():
        raise RuntimeError(
            "CA certificate and private key must both exist or both be absent; "
            "restore the missing file or rotate the CA administratively"
        )

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
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                critical=False,
            )
            .sign(ca_key, None)  # type: ignore[arg-type]  # Ed25519 has no hash
        )
        _write_pem(p_cert, ca_cert.public_bytes(serialization.Encoding.PEM), mode=0o644)
        log.info("pki.ca.initialized", cert_path=cert_path)
    else:
        log.info("pki.ca.loaded", cert_path=cert_path)

    try:
        _validate_ca_profile(x509.load_pem_x509_certificate(p_cert.read_bytes()))
    except (ValueError, RuntimeError) as exc:
        log.error("pki.ca.profile_invalid", cert_path=cert_path, reason=str(exc))
        raise

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

    ca_key = serialization.load_pem_private_key(Path(ca_key_path).read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())
    required_dns_names = {"backend", "fim-backend", "localhost"}

    if p_key.exists():
        backend_key = serialization.load_pem_private_key(p_key.read_bytes(), password=None)
        if p_cert.exists():
            existing = x509.load_pem_x509_certificate(p_cert.read_bytes())
            try:
                existing.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
                san = existing.extensions.get_extension_for_class(x509.SubjectAlternativeName)
                existing_dns_names = set(san.value.get_values_for_type(x509.DNSName))
            except x509.ExtensionNotFound:
                existing_dns_names = set()
            if required_dns_names <= existing_dns_names:
                return
    else:
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
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(name) for name in sorted(required_dns_names)]
            ),
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
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
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


def issue_certificate_for_public_key(
    subject: x509.Name,
    public_key: object,
    ca_cert_path: str,
    ca_key_path: str,
) -> str:
    """Issue a fresh client certificate while retaining the agent public key."""
    ca_key = serialization.load_pem_private_key(Path(ca_key_path).read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(public_key)  # type: ignore[arg-type]
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
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
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(ca_key, None)  # type: ignore[arg-type]
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def validate_client_certificate(cert: x509.Certificate, ca_cert_path: str) -> None:
    """Validate CA signature, client usage and the current validity window."""
    ca_cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())
    if cert.issuer != ca_cert.subject:
        raise ValueError("certificate issuer mismatch")
    ca_public_key = ca_cert.public_key()
    ca_public_key.verify(cert.signature, cert.tbs_certificate_bytes)  # type: ignore[call-arg,union-attr]
    now = datetime.datetime.now(datetime.timezone.utc)
    if now < cert.not_valid_before_utc or now >= cert.not_valid_after_utc:
        raise ValueError("certificate is not currently valid")
    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    if ExtendedKeyUsageOID.CLIENT_AUTH not in eku:
        raise ValueError("certificate is not valid for client authentication")


def is_revoked(serial: int, session: "Session") -> bool:
    """Consulta la tabla revoked_certificates por número de serie."""
    from sqlmodel import select

    from app.modules.agents.models import RevokedCertificate

    result = session.exec(
        select(RevokedCertificate).where(RevokedCertificate.serial_number == str(serial))
    ).first()
    return result is not None


def _finalize_tls_server(config: "uvicorn.Config") -> "uvicorn.Server":
    """Shared hardening for every agent-facing TLS listener (8443 and 8444):
    load the config, pin TLS 1.3 as the floor, and disable uvicorn's own
    signal handlers so it can run as a cooperative asyncio task inside the
    backend's lifespan instead of owning the process (C10)."""
    import uvicorn

    config.load()
    assert config.ssl is not None
    config.ssl.minimum_version = ssl.TLSVersion.TLSv1_3
    config.install_signal_handlers = False
    return uvicorn.Server(config)


def start_mtls_server(
    app: object,
    ca_cert_path: str,
    cert_path: str,
    key_path: str,
    host: str = "0.0.0.0",
    port: int = 8443,
) -> "uvicorn.Server | None":
    """
    Construye un servidor uvicorn para puerto 8443 con mTLS (CERT_REQUIRED)
    y lo retorna sin arrancarlo. El caller es responsable de lanzar
    asyncio.create_task(server.serve()) en el lifespan (C10).

    Retorna None cuando los certificados no están disponibles.
    """
    import uvicorn
    from uvicorn.protocols.http.h11_impl import H11Protocol

    class PeerCertificateH11Protocol(H11Protocol):
        """Copy the TLS-authenticated peer certificate into per-connection ASGI state."""

        def connection_made(self, transport):  # type: ignore[no-untyped-def,override]
            self.app_state = self.app_state.copy()
            ssl_object = transport.get_extra_info("ssl_object")
            if ssl_object is not None:
                peer_der = ssl_object.getpeercert(binary_form=True)
                if peer_der:
                    self.app_state[PEER_CERT_SCOPE_KEY] = peer_der
            super().connection_made(transport)

    if not all([ca_cert_path, cert_path, key_path]):
        log.warning("pki.mtls_server.skipped", reason="cert paths not configured")
        return None

    if not Path(cert_path).exists() or not Path(key_path).exists():
        log.warning("pki.mtls_server.skipped", reason="cert or key file not found")
        return None

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        ssl_keyfile=key_path,
        ssl_certfile=cert_path,
        ssl_ca_certs=ca_cert_path,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        http=PeerCertificateH11Protocol,
        log_level="info",
        lifespan="off",
    )
    server = _finalize_tls_server(config)
    log.info("pki.mtls_server.configured", port=port)
    return server


def start_bootstrap_server(
    app: object,
    cert_path: str,
    key_path: str,
    host: str = "0.0.0.0",
    port: int = 8444,
) -> "uvicorn.Server | None":
    """
    Construye un servidor uvicorn dedicado para `POST /agents/bootstrap` en el
    puerto 8444 (D52/RN-146). Autentica solo el certificado de SERVIDOR del
    backend (TLS 1.3, sin exigir cert de cliente — `ssl.CERT_NONE`): un agente
    que recién arranca todavía no tiene certificado propio, así que no puede
    completar el handshake CERT_REQUIRED del listener 8443. El canal queda
    igualmente cifrado y con el backend autenticado, cerrando el hueco de
    RN-114 (bootstrap en texto plano por el puerto 8000 sin TLS).

    Mismo contrato que start_mtls_server: retorna None cuando los certs no
    están disponibles y no arranca el servidor — el caller lanza
    asyncio.create_task(server.serve()) en el lifespan.
    """
    import uvicorn

    if not cert_path or not key_path:
        log.warning("pki.bootstrap_tls_server.skipped", reason="cert paths not configured")
        return None

    if not Path(cert_path).exists() or not Path(key_path).exists():
        log.warning("pki.bootstrap_tls_server.skipped", reason="cert or key file not found")
        return None

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        ssl_keyfile=key_path,
        ssl_certfile=cert_path,
        ssl_cert_reqs=ssl.CERT_NONE,
        log_level="info",
        lifespan="off",
    )
    server = _finalize_tls_server(config)
    log.info("pki.bootstrap_tls_server.configured", port=port)
    return server
