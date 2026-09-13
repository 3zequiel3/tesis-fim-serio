"""
D53/RN-147 — emisión automática del certificado de servidor de Valkey y del
certificado de cliente del backend ante Valkey; D55/RN-149 — certificado
autofirmado de la consola. D61/RN-155 — reemisión por vencimiento comparte
criterio con `backend-pki`.
"""

from __future__ import annotations

import datetime
import os
import ssl

import pytest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, SignatureAlgorithmOID

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")


@pytest.fixture()
def ca_paths(tmp_path):
    from app.core.pki import ensure_ca

    ca_file, ca_key_file = tmp_path / "ca.pem", tmp_path / "ca-key.pem"
    ensure_ca(str(ca_file), str(ca_key_file))
    return ca_file, ca_key_file


# ── Certificado de servidor de Valkey ─────────────────────────────────────────


def test_ensure_valkey_server_cert_perfil(tmp_path, ca_paths) -> None:
    from app.core.pki import ensure_valkey_server_cert

    ca_file, ca_key_file = ca_paths
    cert_file, key_file = tmp_path / "valkey.pem", tmp_path / "valkey-key.pem"
    ensure_valkey_server_cert(
        str(ca_file), str(ca_key_file), str(cert_file), str(key_file), fim_public_hosts="203.0.113.10"
    )

    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
    assert bc.critical is True
    assert bc.value.ca is False
    cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    assert ExtendedKeyUsageOID.CLIENT_AUTH in eku
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert set(san.value.get_values_for_type(x509.DNSName)) == {"valkey", "localhost"}
    assert san.value.get_values_for_type(x509.IPAddress) == [
        __import__("ipaddress").ip_address("203.0.113.10")
    ]


def test_ensure_valkey_server_cert_idempotente(tmp_path, ca_paths) -> None:
    from app.core.pki import ensure_valkey_server_cert

    ca_file, ca_key_file = ca_paths
    cert_file, key_file = tmp_path / "valkey.pem", tmp_path / "valkey-key.pem"
    ensure_valkey_server_cert(str(ca_file), str(ca_key_file), str(cert_file), str(key_file))
    first = x509.load_pem_x509_certificate(cert_file.read_bytes())

    ensure_valkey_server_cert(str(ca_file), str(ca_key_file), str(cert_file), str(key_file))
    second = x509.load_pem_x509_certificate(cert_file.read_bytes())
    assert first.serial_number == second.serial_number


def test_ensure_valkey_server_cert_verificacion_estricta_python313(tmp_path, ca_paths) -> None:
    from app.core.pki import ensure_valkey_server_cert

    ca_file, ca_key_file = ca_paths
    cert_file, key_file = tmp_path / "valkey.pem", tmp_path / "valkey-key.pem"
    ensure_valkey_server_cert(str(ca_file), str(ca_key_file), str(cert_file), str(key_file))

    ctx = ssl.create_default_context(cafile=str(ca_file))
    # Loading the leaf cert chain and verifying against the CA store must not
    # raise for a missing AuthorityKeyIdentifier.
    ctx.load_cert_chain(str(cert_file), str(key_file))


# ── Certificado de cliente del backend ante Valkey ────────────────────────────


def test_ensure_backend_valkey_client_cert_perfil(tmp_path, ca_paths) -> None:
    from app.core.pki import ensure_backend_valkey_client_cert

    ca_file, ca_key_file = ca_paths
    cert_file, key_file = tmp_path / "backend-valkey.pem", tmp_path / "backend-valkey-key.pem"
    ensure_backend_valkey_client_cert(str(ca_file), str(ca_key_file), str(cert_file), str(key_file))

    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert list(eku) == [ExtendedKeyUsageOID.CLIENT_AUTH]
    cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
    with pytest.raises(x509.ExtensionNotFound):
        cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)


def test_ensure_backend_valkey_client_cert_idempotente(tmp_path, ca_paths) -> None:
    from app.core.pki import ensure_backend_valkey_client_cert

    ca_file, ca_key_file = ca_paths
    cert_file, key_file = tmp_path / "backend-valkey.pem", tmp_path / "backend-valkey-key.pem"
    ensure_backend_valkey_client_cert(str(ca_file), str(ca_key_file), str(cert_file), str(key_file))
    first = x509.load_pem_x509_certificate(cert_file.read_bytes())

    ensure_backend_valkey_client_cert(str(ca_file), str(ca_key_file), str(cert_file), str(key_file))
    second = x509.load_pem_x509_certificate(cert_file.read_bytes())
    assert first.serial_number == second.serial_number


# ── Certificado autofirmado STANDALONE de la consola (D62/RN-156) ────────────
#
# A diferencia de los certificados de arriba, este NO recibe `ca_paths`: es
# un certificado autofirmado independiente de la CA propia (issuer==subject),
# con clave ECDSA P-256 y firma ECDSA-SHA256 — Chrome y Firefox rechazan TLS
# con Ed25519.


def test_ensure_console_cert_perfil(tmp_path) -> None:
    from app.core.pki import ensure_console_cert, fingerprint_sha256

    cert_file, key_file = tmp_path / "console.pem", tmp_path / "console-key.pem"
    returned_fingerprint = ensure_console_cert(
        str(cert_file), str(key_file), fim_public_hosts="203.0.113.10"
    )

    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
    assert bc.critical is True
    assert bc.value.ca is False
    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert list(eku) == [ExtendedKeyUsageOID.SERVER_AUTH]
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    assert "localhost" in set(san.value.get_values_for_type(x509.DNSName))
    assert __import__("ipaddress").ip_address("203.0.113.10") in san.value.get_values_for_type(
        x509.IPAddress
    )

    # D62/RN-156: standalone self-signed — issuer == subject, no AKI, key is
    # ECDSA P-256, signature algorithm is ecdsa-with-SHA256 (never Ed25519).
    assert cert.issuer == cert.subject
    with pytest.raises(x509.ExtensionNotFound):
        cert.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
    public_key = cert.public_key()
    assert isinstance(public_key, ec.EllipticCurvePublicKey)
    assert isinstance(public_key.curve, ec.SECP256R1)
    assert cert.signature_algorithm_oid == SignatureAlgorithmOID.ECDSA_WITH_SHA256

    # Self-signed: the certificate verifies against its OWN public key, never
    # against a CA (there is no CA involved in issuing this certificate).
    public_key.verify(
        cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm)
    )

    assert returned_fingerprint == fingerprint_sha256(cert)

    # Verifiable by Python 3.13's ssl with the leaf loaded as its own trust
    # anchor (self-signed — there is no separate CA to hand ssl here).
    ctx = ssl.create_default_context(cafile=str(cert_file))
    ctx.load_cert_chain(str(cert_file), str(key_file))


def test_ensure_console_cert_idempotencia_y_vencimiento(tmp_path) -> None:
    from app.core.pki import ensure_console_cert

    cert_file, key_file = tmp_path / "console.pem", tmp_path / "console-key.pem"
    ensure_console_cert(str(cert_file), str(key_file))
    first = x509.load_pem_x509_certificate(cert_file.read_bytes())

    ensure_console_cert(str(cert_file), str(key_file))
    second = x509.load_pem_x509_certificate(cert_file.read_bytes())
    assert first.serial_number == second.serial_number
    # Same key preserved across the idempotent no-op call.
    assert first.public_key().public_numbers() == second.public_key().public_numbers()

    # Force the on-disk cert into a near-expiry state (60 days is untouched,
    # 10 days triggers reissue) using the same private key.
    key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    now = datetime.datetime.now(datetime.timezone.utc)
    from app.core.pki import _san_general_names

    subject = second.subject
    near_expiry = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=10))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.SubjectAlternativeName(_san_general_names({"localhost"}, set())), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_file.write_bytes(near_expiry.public_bytes(serialization.Encoding.PEM))

    ensure_console_cert(str(cert_file), str(key_file))
    reissued = x509.load_pem_x509_certificate(cert_file.read_bytes())
    assert reissued.serial_number != near_expiry.serial_number
    assert reissued.issuer == reissued.subject


def test_ensure_console_cert_no_ca_signature(tmp_path, ca_paths) -> None:
    """D62/RN-156: the console cert must NOT verify against the project CA —
    it is not signed by it. `ca_paths` here only supplies an unrelated CA to
    assert against, proving the console leaf's signature is independent."""
    from app.core.pki import ensure_console_cert

    ca_file, _ca_key_file = ca_paths
    cert_file, key_file = tmp_path / "console.pem", tmp_path / "console-key.pem"
    ensure_console_cert(str(cert_file), str(key_file))

    cert = x509.load_pem_x509_certificate(cert_file.read_bytes())
    ca_cert = x509.load_pem_x509_certificate(ca_file.read_bytes())
    assert cert.issuer != ca_cert.subject
    with pytest.raises((InvalidSignature, ValueError)):
        ca_cert.public_key().verify(  # type: ignore[union-attr]
            cert.signature, cert.tbs_certificate_bytes
        )
