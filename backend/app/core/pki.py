"""
PKI propia del backend FIM — CA Ed25519, emisión de certs de agentes,
revocación y servidor mTLS en puerto 8443 (RN-78, C6).
"""

from __future__ import annotations

import datetime
import hashlib
import ipaddress
import os
import re
import ssl
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.core.logging import log

if TYPE_CHECKING:
    from sqlmodel import Session

_CA_VALIDITY_DAYS = 365 * 10
_CERT_VALIDITY_DAYS = 90
_CERT_RENEWAL_THRESHOLD_DAYS = 15
PEER_CERT_SCOPE_KEY = "mtls_peer_certificate_der"

IPAddressT = "ipaddress.IPv4Address | ipaddress.IPv6Address"

# RFC 1123 label: alnum, may contain hyphens but not lead/trail with one.
_DNS_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def _is_valid_dns_name(host: str) -> bool:
    """RFC 1123 hostname validation. Rejects wildcards implicitly ('*' is not
    in the label alphabet)."""
    if not host or len(host) > 253:
        return False
    return all(_DNS_LABEL_RE.match(label) for label in host.split("."))


def parse_public_hosts(raw: str) -> tuple[set[str], set["ipaddress.IPv4Address | ipaddress.IPv6Address"]]:
    """Parse `FIM_PUBLIC_HOSTS` (D53/RN-147) into `(dns_names, ip_addresses)`.

    Comma-separated entries, trimmed, empty entries ignored. Each entry that
    parses as an IPv4/IPv6 address is returned as an `ipaddress` object (SAN
    `IPAddress`, never `DNSName`); anything else must be an RFC 1123 DNS name
    without wildcards (SAN `DNSName`). An entry that is neither raises
    `ValueError` naming it, so the caller can abort startup with a clear
    message.
    """
    dns_names: set[str] = set()
    ip_addresses: set["ipaddress.IPv4Address | ipaddress.IPv6Address"] = set()
    for entry in raw.split(","):
        host = entry.strip()
        if not host:
            continue
        try:
            ip_addresses.add(ipaddress.ip_address(host))
            continue
        except ValueError:
            pass
        if not _is_valid_dns_name(host):
            raise ValueError(
                f"FIM_PUBLIC_HOSTS: invalid entry {host!r}: not a valid IP "
                "address nor an RFC 1123 DNS name (wildcards not allowed)"
            )
        dns_names.add(host.lower())
    return dns_names, ip_addresses


def required_san(
    internal_names: set[str], public_hosts: str
) -> tuple[set[str], set["ipaddress.IPv4Address | ipaddress.IPv6Address"]]:
    """Union of the always-present internal DNS names with the hosts parsed
    from `public_hosts` (D53/RN-147). Returns `(dns_names, ip_addresses)`."""
    extra_dns, ip_addresses = parse_public_hosts(public_hosts)
    dns_names = {name.lower() for name in internal_names} | extra_dns
    return dns_names, ip_addresses


def san_covers(
    cert: x509.Certificate,
    dns_names: set[str],
    ip_addresses: set["ipaddress.IPv4Address | ipaddress.IPv6Address"],
) -> bool:
    """Whether `cert`'s SAN extension covers every required DNS name and IP.

    DNS names compare case-insensitively; IPs compare as normalized
    `ipaddress` objects. When `cert` has no SAN extension at all, it "covers"
    only the empty requirement (used by certs that intentionally carry no
    SAN, e.g. the backend-to-Valkey client certificate).
    """
    required_dns = {name.lower() for name in dns_names}
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except x509.ExtensionNotFound:
        return not required_dns and not ip_addresses
    existing_dns = {name.lower() for name in san.value.get_values_for_type(x509.DNSName)}
    existing_ips = set(san.value.get_values_for_type(x509.IPAddress))
    return required_dns <= existing_dns and ip_addresses <= existing_ips


def _san_general_names(
    dns_names: set[str], ip_addresses: set["ipaddress.IPv4Address | ipaddress.IPv6Address"]
) -> list["x509.GeneralName"]:
    names: list["x509.GeneralName"] = [x509.DNSName(name) for name in sorted(dns_names)]
    names.extend(x509.IPAddress(ip) for ip in sorted(ip_addresses, key=str))
    return names


def _cert_expiring_soon(
    cert: x509.Certificate, threshold_days: int = _CERT_RENEWAL_THRESHOLD_DAYS
) -> bool:
    """D61/RN-155: true when fewer than `threshold_days` remain before
    `not_valid_after`. Reissuance keeps the same CA; the CA is never rotated
    by this check."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return cert.not_valid_after_utc - now < datetime.timedelta(days=threshold_days)


def _needs_reissue(
    cert: x509.Certificate,
    dns_names: set[str],
    ip_addresses: set["ipaddress.IPv4Address | ipaddress.IPv6Address"],
    require_aki: bool = True,
) -> bool:
    """A certs-init-managed certificate is reissued (same key; same CA when
    `require_aki` is true) when it lacks AuthorityKeyIdentifier (skipped for
    a standalone self-signed leaf, which never carries one — D62/RN-156),
    its SAN does not cover the required set, or it is within
    `_CERT_RENEWAL_THRESHOLD_DAYS` of expiry (D53/D61, RN-147/RN-155)."""
    if require_aki:
        try:
            cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
        except x509.ExtensionNotFound:
            return True
    if not san_covers(cert, dns_names, ip_addresses):
        return True
    return _cert_expiring_soon(cert)


def fingerprint_sha256(cert: x509.Certificate) -> str:
    """SHA-256 fingerprint over the certificate's DER encoding, formatted as
    uppercase hex pairs separated by `:` (the operator-facing format compared
    against a browser's certificate details, D56/RN-150, D62/RN-156)."""
    digest = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


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
    fim_public_hosts: str = "",
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
        _ensure_backend_cert(cert_path, key_path, backend_cert_path, backend_key_path, fim_public_hosts)


def _ensure_backend_cert(
    ca_cert_path: str,
    ca_key_path: str,
    cert_path: str,
    key_path: str,
    fim_public_hosts: str = "",
) -> None:
    p_key = Path(key_path)
    p_cert = Path(cert_path)

    ca_key = serialization.load_pem_private_key(Path(ca_key_path).read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())
    dns_names, ip_addresses = required_san({"backend", "fim-backend", "localhost"}, fim_public_hosts)

    if p_key.exists():
        backend_key = serialization.load_pem_private_key(p_key.read_bytes(), password=None)
        if p_cert.exists():
            existing = x509.load_pem_x509_certificate(p_cert.read_bytes())
            if not _needs_reissue(existing, dns_names, ip_addresses):
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
            x509.SubjectAlternativeName(_san_general_names(dns_names, ip_addresses)),
            critical=False,
        )
        .sign(ca_key, None)  # type: ignore[arg-type]
    )
    _write_pem(p_cert, cert.public_bytes(serialization.Encoding.PEM), mode=0o644)
    log.info("pki.backend_cert.generated", cert_path=cert_path)


def _ensure_leaf_cert(
    ca_cert_path: str,
    ca_key_path: str,
    cert_path: str,
    key_path: str,
    common_name: str,
    dns_names: set[str],
    ip_addresses: set["ipaddress.IPv4Address | ipaddress.IPv6Address"],
    extended_key_usage: list["x509.ObjectIdentifier"],
    key_mode: int = 0o400,
) -> None:
    """Shared idempotent issuance for a leaf certificate signed by the
    platform CA, with critical `BasicConstraints(ca=False)` and
    `AuthorityKeyIdentifier`, reissued on SAN gap or approaching expiry
    (D53/RN-147, D61/RN-155). Used for the Valkey server certificate, the
    backend-to-Valkey client certificate (empty `dns_names`/`ip_addresses` →
    no SAN extension at all) and the console self-signed certificate.
    """
    p_key = Path(key_path)
    p_cert = Path(cert_path)

    ca_key = serialization.load_pem_private_key(Path(ca_key_path).read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())

    if p_key.exists():
        leaf_key = serialization.load_pem_private_key(p_key.read_bytes(), password=None)
        if p_cert.exists():
            existing = x509.load_pem_x509_certificate(p_cert.read_bytes())
            if not _needs_reissue(existing, dns_names, ip_addresses):
                return
    else:
        leaf_key = Ed25519PrivateKey.generate()
        _write_pem(p_key, leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ), mode=key_mode)

    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage(extended_key_usage), critical=False)
    )
    if dns_names or ip_addresses:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(_san_general_names(dns_names, ip_addresses)),
            critical=False,
        )
    cert = builder.sign(ca_key, None)  # type: ignore[arg-type]
    _write_pem(p_cert, cert.public_bytes(serialization.Encoding.PEM), mode=0o644)
    log.info("pki.leaf_cert.generated", cert_path=cert_path, common_name=common_name)


def ensure_valkey_server_cert(
    ca_cert_path: str,
    ca_key_path: str,
    cert_path: str,
    key_path: str,
    fim_public_hosts: str = "",
) -> None:
    """Emite (idempotente) el certificado de servidor de Valkey: `CN=valkey`,
    SAN `{valkey, localhost} ∪ FIM_PUBLIC_HOSTS`, `BasicConstraints` crítica,
    AKI, EKU `serverAuth` + `clientAuth` (el segundo lo usa el healthcheck de
    Valkey para autenticarse ante sí mismo) — D53/RN-147.
    """
    dns_names, ip_addresses = required_san({"valkey", "localhost"}, fim_public_hosts)
    _ensure_leaf_cert(
        ca_cert_path,
        ca_key_path,
        cert_path,
        key_path,
        common_name="valkey",
        dns_names=dns_names,
        ip_addresses=ip_addresses,
        extended_key_usage=[ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH],
    )


def ensure_backend_valkey_client_cert(
    ca_cert_path: str,
    ca_key_path: str,
    cert_path: str,
    key_path: str,
) -> None:
    """Emite (idempotente) el certificado de cliente propio del backend ante
    Valkey: `CN=fim-backend-valkey`, EKU únicamente `clientAuth`, sin SAN,
    AKI (D53/RN-147). El backend NO se autentica ante Valkey con
    `backend.pem` (sólo `serverAuth`) ni con el certificado de servidor de
    Valkey.
    """
    _ensure_leaf_cert(
        ca_cert_path,
        ca_key_path,
        cert_path,
        key_path,
        common_name="fim-backend-valkey",
        dns_names=set(),
        ip_addresses=set(),
        extended_key_usage=[ExtendedKeyUsageOID.CLIENT_AUTH],
    )


def ensure_console_cert(
    cert_path: str,
    key_path: str,
    fim_public_hosts: str = "",
) -> str:
    """Emite (idempotente) el certificado autofirmado STANDALONE de la
    consola —sólo usado con `CONSOLE_TLS_MODE=self_signed`—: clave ECDSA
    P-256, firma ECDSA-SHA256, `issuer == subject` (NO firmado por la CA
    propia — D62/RN-156, reabre D55/RN-149), SAN `{localhost} ∪
    FIM_PUBLIC_HOSTS`, `BasicConstraints(ca=False)` crítica, EKU únicamente
    `serverAuth` (D61/RN-155 para el criterio de reemisión por vencimiento).

    Chrome y Firefox rechazan certificados TLS Ed25519 (verificado: un
    `page.goto()` real de Playwright Chromium fallaba con
    `ERR_SSL_VERSION_OR_CIPHER_MISMATCH` contra la hoja Ed25519 anterior,
    firmada por la CA propia); ECDSA P-256 es aceptado por ambos. No firmar
    con la CA propia evita exponer `ca-key.pem` (Ed25519) al contenedor de
    nginx y es lo que exige D62/RN-156.

    El caller decide si corresponde invocar esta función según el modo
    configurado; esta función siempre emite/reemite cuando se la llama.
    Retorna la huella SHA-256 (`fingerprint_sha256`) del certificado vigente
    tras la llamada, para que el caller la loguee.
    """
    dns_names, ip_addresses = required_san({"localhost"}, fim_public_hosts)
    p_key = Path(key_path)
    p_cert = Path(cert_path)

    if p_key.exists():
        console_key = serialization.load_pem_private_key(p_key.read_bytes(), password=None)
        if p_cert.exists():
            existing = x509.load_pem_x509_certificate(p_cert.read_bytes())
            if not _needs_reissue(existing, dns_names, ip_addresses, require_aki=False):
                return fingerprint_sha256(existing)
    else:
        console_key = ec.generate_private_key(ec.SECP256R1())
        _write_pem(p_key, console_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ), mode=0o400)

    now = datetime.datetime.now(datetime.timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fim-console")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(console_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectAlternativeName(_san_general_names(dns_names, ip_addresses)),
            critical=False,
        )
        .sign(console_key, hashes.SHA256())
    )
    _write_pem(p_cert, cert.public_bytes(serialization.Encoding.PEM), mode=0o644)
    fingerprint = fingerprint_sha256(cert)
    log.info("pki.console_cert.generated", cert_path=cert_path, sha256_fingerprint=fingerprint)
    return fingerprint


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
