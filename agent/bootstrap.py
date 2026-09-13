"""
Bootstrap mTLS del agente FIM (Change 06, RN-78).

Flujo:
  1. is_bootstrapped() → si ya hay cert válido, saltar.
  2. generate_keypair() → genera clave Ed25519 si no existe.
  3. build_csr() → construye CSR con CN=agent_id.
  4. run() → POST /agents/bootstrap, persiste cert + CA + secrets.
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
import structlog
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509.oid import NameOID

if TYPE_CHECKING:
    from agent.config import AgentConfig

log = structlog.get_logger()

_AGENT_CERT = "agent-cert.pem"
_AGENT_KEY = "agent-key.pem"
_CA_CERT = "ca.pem"
_SHARED_SECRET = "shared_secret"
_MASTER_SECRET = "master_secret"


def _write_file(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
    except Exception:
        raise
    os.chmod(path, mode)


def is_bootstrapped(certs_dir: Path) -> bool:
    cert_path = certs_dir / _AGENT_CERT
    if not cert_path.exists():
        return False
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        now = datetime.datetime.now(datetime.timezone.utc)
        return cert.not_valid_after_utc > now
    except Exception:
        return False


def generate_keypair(key_path: Path) -> Ed25519PrivateKey:
    if key_path.exists():
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        return private_key  # type: ignore[return-value]

    private_key = Ed25519PrivateKey.generate()
    _write_file(
        key_path,
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        mode=0o600,
    )
    return private_key


def build_csr(private_key: Ed25519PrivateKey, agent_id: str) -> str:
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, agent_id)]))
        .sign(private_key, None)  # type: ignore[arg-type]  # Ed25519 has no hash
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


def verify_cert(
    cert_pem: str,
    ca_cert_pem: str,
    agent_id: str,
    private_key: "Ed25519PrivateKey | None" = None,
) -> x509.Certificate:
    """
    Verifica que cert_pem sea válido: CA firma + CN == agent_id + clave pública (opcional).

    Retorna el objeto Certificate si pasa todas las verificaciones.
    Lanza RuntimeError en cualquier fallo.
    """
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    ca_cert = x509.load_pem_x509_certificate(ca_cert_pem.encode())

    try:
        ca_cert.public_key().verify(cert.signature, cert.tbs_certificate_bytes)
    except InvalidSignature as exc:
        raise RuntimeError(f"cert not signed by CA: {exc}") from exc

    cn_values = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if not cn_values or cn_values[0].value != agent_id:
        got = cn_values[0].value if cn_values else "<none>"
        raise RuntimeError(f"cert CN mismatch: expected '{agent_id}', got '{got}'")

    now = datetime.datetime.now(datetime.timezone.utc)
    if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
        raise RuntimeError(
            f"cert validity period invalid: not_before={cert.not_valid_before_utc}, "
            f"not_after={cert.not_valid_after_utc}"
        )

    if private_key is not None:
        cert_pub = cert.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        local_pub = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if cert_pub != local_pub:
            raise RuntimeError(
                "cert public key does not match local private key — possible MITM"
            )

    return cert


def run(config: "AgentConfig", bootstrap_secret: str) -> None:
    # D52/RN-114: bootstrap carries shared_secret_hex/master_secret_hex in the
    # response body — refuse a plaintext backend_url before any network call.
    scheme = urlsplit(config.backend_url).scheme
    if scheme != "https":
        log.error(
            "agent.bootstrap.insecure_backend_url",
            backend_url=config.backend_url,
            scheme=scheme,
        )
        print(
            f"backend_url must use https (RN-114) — got '{config.backend_url}'",
            file=sys.stderr,
        )
        sys.exit(1)

    # D16: CA cert must be pre-provisioned by the operator before first bootstrap
    ca_cert_path = Path(config.ca_cert_path)
    if not ca_cert_path.exists():
        log.error(
            "agent.bootstrap.missing_ca_cert",
            ca_cert_path=str(ca_cert_path),
        )
        print(
            f"CA cert not found at {ca_cert_path} — pre-provision ca_cert_path before bootstrap",
            file=sys.stderr,
        )
        sys.exit(1)

    certs_dir = Path(config.storage.certs_dir)
    secrets_dir = Path(config.storage.secrets_dir)

    key_path = certs_dir / _AGENT_KEY
    private_key = generate_keypair(key_path)
    csr_pem = build_csr(private_key, config.agent_id)

    url = config.backend_url.rstrip("/") + "/agents/bootstrap"
    log.info("agent.bootstrap.start", agent_id=config.agent_id, url=url)

    try:
        resp = httpx.post(
            url,
            json={
                "agent_id": config.agent_id,
                "csr_pem": csr_pem,
                "bootstrap_secret": bootstrap_secret,
            },
            timeout=30.0,
            verify=str(ca_cert_path),
        )
    except httpx.ConnectError as exc:
        log.error("agent.bootstrap.connection_error", error=str(exc))
        sys.exit(1)
    except httpx.TimeoutException as exc:
        log.error("agent.bootstrap.timeout", error=str(exc))
        sys.exit(1)

    if resp.status_code != 200:
        log.error("agent.bootstrap.failed", status=resp.status_code, body=resp.text)
        sys.exit(1)

    data = resp.json()

    verify_cert(
        data["cert_pem"],
        data["ca_cert_pem"],
        config.agent_id,
        private_key=private_key,
    )

    # Solo persistir si las 3 verificaciones pasan
    _write_file(certs_dir / _AGENT_CERT, data["cert_pem"].encode(), mode=0o600)
    _write_file(certs_dir / _CA_CERT, data["ca_cert_pem"].encode(), mode=0o600)
    _write_file(secrets_dir / _SHARED_SECRET, bytes.fromhex(data["shared_secret_hex"]), mode=0o400)
    _write_file(secrets_dir / _MASTER_SECRET, bytes.fromhex(data["master_secret_hex"]), mode=0o400)

    log.info("agent.bootstrap.complete", agent_id=config.agent_id)
