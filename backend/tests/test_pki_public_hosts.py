"""
D53/RN-147 — SAN configurable del certificado de servidor del backend desde
`FIM_PUBLIC_HOSTS`, y reemisión por vencimiento (D61/RN-155).

Cubre `parse_public_hosts`, `required_san`, `san_covers` y el refactor de
`_ensure_backend_cert` para usarlas.
"""

from __future__ import annotations

import datetime
import ipaddress
import os
import socket
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")


# ── parse_public_hosts ────────────────────────────────────────────────────────


def test_parse_public_hosts_empty() -> None:
    from app.core.pki import parse_public_hosts

    dns_names, ip_addresses = parse_public_hosts("")
    assert dns_names == set()
    assert ip_addresses == set()


def test_parse_public_hosts_ip_and_dns_name() -> None:
    from app.core.pki import parse_public_hosts

    dns_names, ip_addresses = parse_public_hosts("203.0.113.10, fim.example.org")
    assert ip_addresses == {ipaddress.ip_address("203.0.113.10")}
    assert dns_names == {"fim.example.org"}
    # 203.0.113.10 must never be classified as a DNS name.
    assert "203.0.113.10" not in dns_names


def test_parse_public_hosts_ipv6_normalized() -> None:
    from app.core.pki import parse_public_hosts

    dns_names, ip_addresses = parse_public_hosts("2001:DB8::1")
    assert dns_names == set()
    assert ip_addresses == {ipaddress.ip_address("2001:db8::1")}


def test_parse_public_hosts_uppercase_dns_name_lowercased() -> None:
    from app.core.pki import parse_public_hosts

    dns_names, _ = parse_public_hosts("FIM.Example.ORG")
    assert dns_names == {"fim.example.org"}


def test_parse_public_hosts_ignores_blank_entries() -> None:
    from app.core.pki import parse_public_hosts

    dns_names, ip_addresses = parse_public_hosts(" , fim.example.org , , ")
    assert dns_names == {"fim.example.org"}
    assert ip_addresses == set()


def test_parse_public_hosts_invalid_entry_named() -> None:
    from app.core.pki import parse_public_hosts

    with pytest.raises(ValueError, match=r"bad_host!"):
        parse_public_hosts("fim.example.org, bad_host!")


def test_parse_public_hosts_rejects_wildcards() -> None:
    from app.core.pki import parse_public_hosts

    with pytest.raises(ValueError, match=r"\*\.example\.org"):
        parse_public_hosts("*.example.org")


# ── required_san ──────────────────────────────────────────────────────────────


def test_required_san_union_of_internal_and_public() -> None:
    from app.core.pki import required_san

    dns_names, ip_addresses = required_san({"backend", "fim-backend", "localhost"}, "203.0.113.10")
    assert dns_names == {"backend", "fim-backend", "localhost"}
    assert ip_addresses == {ipaddress.ip_address("203.0.113.10")}


# ── san_covers ─────────────────────────────────────────────────────────────────


def _leaf_cert(dns_names: set[str], ip_addresses: set, *, with_aki: bool = True) -> x509.Certificate:
    from app.core.pki import _san_general_names

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = Ed25519PrivateKey.generate()
    key = Ed25519PrivateKey.generate()
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "leaf")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ca")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=90))
    )
    if with_aki:
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
    if dns_names or ip_addresses:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(_san_general_names(dns_names, ip_addresses)), critical=False
        )
    return builder.sign(ca_key, None)  # type: ignore[arg-type]


def test_san_covers_true_when_superset() -> None:
    from app.core.pki import san_covers

    cert = _leaf_cert({"backend", "fim-backend"}, set())
    assert san_covers(cert, {"backend"}, set()) is True


def test_san_covers_false_when_missing_entry() -> None:
    from app.core.pki import san_covers

    cert = _leaf_cert({"backend"}, set())
    assert san_covers(cert, {"backend", "fim-backend"}, set()) is False


def test_san_covers_case_insensitive_dns() -> None:
    from app.core.pki import san_covers

    cert = _leaf_cert({"fim.example.org"}, set())
    assert san_covers(cert, {"FIM.EXAMPLE.ORG"}, set()) is True


def test_san_covers_no_san_extension_covers_only_empty() -> None:
    from app.core.pki import san_covers

    cert = _leaf_cert(set(), set())
    assert san_covers(cert, set(), set()) is True
    assert san_covers(cert, {"backend"}, set()) is False


# ── _ensure_backend_cert (vía ensure_ca) ──────────────────────────────────────


def test_ensure_ca_backend_cert_sin_hosts_publicos_solo_nombres_internos(tmp_path) -> None:
    from app.core.pki import ensure_ca

    ca_file, ca_key = tmp_path / "ca.pem", tmp_path / "ca-key.pem"
    cert_file, key_file = tmp_path / "backend.pem", tmp_path / "backend-key.pem"
    ensure_ca(str(ca_file), str(ca_key), str(cert_file), str(key_file), fim_public_hosts="")

    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    dns_names = set(san.value.get_values_for_type(x509.DNSName))
    assert dns_names == {"backend", "fim-backend", "localhost"}
    assert san.value.get_values_for_type(x509.IPAddress) == []


def test_ensure_ca_backend_cert_certificado_que_ya_cubre_no_se_reescribe(tmp_path) -> None:
    from app.core.pki import ensure_ca

    ca_file, ca_key = tmp_path / "ca.pem", tmp_path / "ca-key.pem"
    cert_file, key_file = tmp_path / "backend.pem", tmp_path / "backend-key.pem"
    ensure_ca(str(ca_file), str(ca_key), str(cert_file), str(key_file), fim_public_hosts="203.0.113.10")

    first = x509.load_pem_x509_certificate(cert_file.read_bytes())
    mtime_before = cert_file.stat().st_mtime_ns

    ensure_ca(str(ca_file), str(ca_key), str(cert_file), str(key_file), fim_public_hosts="203.0.113.10")

    second = x509.load_pem_x509_certificate(cert_file.read_bytes())
    assert first.serial_number == second.serial_number
    assert cert_file.stat().st_mtime_ns == mtime_before


def test_ensure_ca_backend_cert_host_nuevo_reemite_misma_ca_misma_clave(tmp_path) -> None:
    from app.core.pki import ensure_ca

    ca_file, ca_key = tmp_path / "ca.pem", tmp_path / "ca-key.pem"
    cert_file, key_file = tmp_path / "backend.pem", tmp_path / "backend-key.pem"
    ensure_ca(str(ca_file), str(ca_key), str(cert_file), str(key_file), fim_public_hosts="")

    first = x509.load_pem_x509_certificate(cert_file.read_bytes())
    first_key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)

    ensure_ca(str(ca_file), str(ca_key), str(cert_file), str(key_file), fim_public_hosts="fim.example.org")

    second = x509.load_pem_x509_certificate(cert_file.read_bytes())
    second_key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    assert first.serial_number != second.serial_number
    assert second.issuer == first.issuer
    assert (
        second_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        == first_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    )
    san = second.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert "fim.example.org" in set(san.value.get_values_for_type(x509.DNSName))


def test_ensure_ca_backend_cert_sin_aki_se_reemite(tmp_path) -> None:
    from app.core.pki import ensure_ca

    ca_file, ca_key_file = tmp_path / "ca.pem", tmp_path / "ca-key.pem"
    ensure_ca(str(ca_file), str(ca_key_file))
    ca_key = serialization.load_pem_private_key(ca_key_file.read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(ca_file.read_bytes())

    backend_key = Ed25519PrivateKey.generate()
    key_file = tmp_path / "backend-key.pem"
    key_file.write_bytes(
        backend_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    no_aki_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fim-backend")]))
        .issuer_name(ca_cert.subject)
        .public_key(backend_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=90))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(n) for n in ["backend", "fim-backend", "localhost"]]
            ),
            critical=False,
        )
        .sign(ca_key, None)  # type: ignore[arg-type]
    )
    cert_file = tmp_path / "backend.pem"
    cert_file.write_bytes(no_aki_cert.public_bytes(serialization.Encoding.PEM))
    original_serial = no_aki_cert.serial_number

    from app.core.pki import ensure_ca as ensure_ca_again

    ensure_ca_again(str(ca_file), str(ca_key_file), str(cert_file), str(key_file), fim_public_hosts="")

    reissued = x509.load_pem_x509_certificate(cert_file.read_bytes())
    assert reissued.serial_number != original_serial
    reissued.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)


# ── Handshake TLS real contra IP del SAN ──────────────────────────────────────


def test_ensure_ca_backend_cert_handshake_tls_contra_ip_del_san(tmp_path) -> None:
    from app.core.pki import ensure_ca

    ca_file, ca_key = tmp_path / "ca.pem", tmp_path / "ca-key.pem"
    cert_file, key_file = tmp_path / "backend.pem", tmp_path / "backend-key.pem"
    ensure_ca(str(ca_file), str(ca_key), str(cert_file), str(key_file), fim_public_hosts="127.0.0.1")

    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(str(cert_file), str(key_file))

    raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    raw_sock.bind(("127.0.0.1", 0))
    raw_sock.listen(1)
    port = raw_sock.getsockname()[1]

    accepted: dict = {}

    def _serve() -> None:
        conn, _ = raw_sock.accept()
        try:
            tls_conn = server_ctx.wrap_socket(conn, server_side=True)
            tls_conn.close()
        except Exception as exc:  # pragma: no cover - diagnostics only
            accepted["error"] = exc

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_ctx.load_verify_locations(str(ca_file))
    client_ctx.check_hostname = True
    client_ctx.verify_mode = ssl.CERT_REQUIRED

    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        with client_ctx.wrap_socket(sock, server_hostname="127.0.0.1") as tls_sock:
            assert tls_sock.getpeercert() is not None

    thread.join(timeout=5)
    raw_sock.close()
    assert "error" not in accepted


# ── D61/RN-155 — reemisión por vencimiento ────────────────────────────────────


def _write_backend_cert_with_expiry(
    tmp_path, ca_file, ca_key_file, days_until_expiry: int
) -> tuple:
    from app.core.pki import _san_general_names

    ca_key = serialization.load_pem_private_key(ca_key_file.read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate(ca_file.read_bytes())
    backend_key = Ed25519PrivateKey.generate()
    key_file = tmp_path / "backend-key.pem"
    key_file.write_bytes(
        backend_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fim-backend")]))
        .issuer_name(ca_cert.subject)
        .public_key(backend_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days_until_expiry))
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(ExtendedKeyUsageExt(), critical=False)
        .add_extension(
            x509.SubjectAlternativeName(
                _san_general_names({"backend", "fim-backend", "localhost"}, set())
            ),
            critical=False,
        )
        .sign(ca_key, None)  # type: ignore[arg-type]
    )
    cert_file = tmp_path / "backend.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_file, key_file, cert.serial_number


def ExtendedKeyUsageExt():
    return x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH])


def test_ensure_ca_backend_cert_proximo_a_vencer_se_reemite(tmp_path) -> None:
    from app.core.pki import ensure_ca

    ca_file, ca_key_file = tmp_path / "ca.pem", tmp_path / "ca-key.pem"
    ensure_ca(str(ca_file), str(ca_key_file))
    cert_file, key_file, original_serial = _write_backend_cert_with_expiry(
        tmp_path, ca_file, ca_key_file, days_until_expiry=10
    )

    ensure_ca(str(ca_file), str(ca_key_file), str(cert_file), str(key_file), fim_public_hosts="")

    reissued = x509.load_pem_x509_certificate(cert_file.read_bytes())
    ca_cert = x509.load_pem_x509_certificate(ca_file.read_bytes())
    assert reissued.serial_number != original_serial
    assert reissued.issuer == ca_cert.subject


def test_ensure_ca_backend_cert_vence_en_60_dias_no_se_reemite(tmp_path) -> None:
    from app.core.pki import ensure_ca

    ca_file, ca_key_file = tmp_path / "ca.pem", tmp_path / "ca-key.pem"
    ensure_ca(str(ca_file), str(ca_key_file))
    cert_file, key_file, original_serial = _write_backend_cert_with_expiry(
        tmp_path, ca_file, ca_key_file, days_until_expiry=60
    )

    ensure_ca(str(ca_file), str(ca_key_file), str(cert_file), str(key_file), fim_public_hosts="")

    untouched = x509.load_pem_x509_certificate(cert_file.read_bytes())
    assert untouched.serial_number == original_serial
