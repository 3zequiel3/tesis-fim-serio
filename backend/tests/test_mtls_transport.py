"""Real local TLS harness for the dedicated agent listener."""
from __future__ import annotations

import asyncio
import datetime
import os
import socket
import ssl

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import FastAPI, Request

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")

from app.core.pki import PEER_CERT_SCOPE_KEY, start_mtls_server


def _write_pki(root, *, expired_client: bool = False):
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = Ed25519PrivateKey.generate()
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "harness-ca")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
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
        .sign(ca_key, None)
    )
    ca_path = root / "ca.pem"
    ca_key_path = root / "ca-key.pem"
    ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    ca_key_path.write_bytes(
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    def issue(name: str, eku, *, expired: bool = False, signer_key=ca_key, signer=ca_cert):
        key = Ed25519PrivateKey.generate()
        cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(signer.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=30 if expired else 1))
            .not_valid_after(now - datetime.timedelta(days=1) if expired else now + datetime.timedelta(days=10))
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(signer_key.public_key()),
                critical=False,
            )
            .add_extension(x509.ExtendedKeyUsage([eku]), critical=False)
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
            )
            .sign(signer_key, None)
        )
        cert_path = root / f"{name}-cert.pem"
        key_path = root / f"{name}-key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        return cert_path, key_path

    server_cert, server_key = issue("localhost", ExtendedKeyUsageOID.SERVER_AUTH)
    client_cert, client_key = issue(
        "agent-harness", ExtendedKeyUsageOID.CLIENT_AUTH, expired=expired_client
    )
    return ca_path, server_cert, server_key, client_cert, client_key


def _free_port() -> int:
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
    except PermissionError:
        pytest.skip("sandbox does not permit local TCP sockets")


def _client_context(ca_path, cert_pair=None) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(ca_path))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    if cert_pair is not None:
        context.load_cert_chain(str(cert_pair[0]), str(cert_pair[1]))
    return context


async def test_real_mtls_handshake_and_peer_certificate_scope(tmp_path) -> None:
    ca, server_cert, server_key, client_cert, client_key = _write_pki(tmp_path)
    foreign = tmp_path / "foreign-client"
    foreign.mkdir()
    _, _, _, foreign_cert, foreign_key = _write_pki(foreign)
    expired = tmp_path / "expired-client"
    expired.mkdir()
    _, _, _, expired_cert, expired_key = _write_pki(expired, expired_client=True)

    app = FastAPI()

    @app.get("/peer")
    async def peer(request: Request):
        return {"peer_present": isinstance(request.scope["state"].get(PEER_CERT_SCOPE_KEY), bytes)}

    port = _free_port()
    server = start_mtls_server(
        app,
        str(ca),
        str(server_cert),
        str(server_key),
        host="127.0.0.1",
        port=port,
    )
    assert server is not None
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)

        async with httpx.AsyncClient(
            verify=_client_context(ca, (client_cert, client_key)), trust_env=False
        ) as client:
            response = await client.get(f"https://localhost:{port}/peer")
        assert response.status_code == 200
        assert response.json() == {"peer_present": True}

        for cert_pair in (
            None,
            (str(foreign_cert), str(foreign_key)),
            (str(expired_cert), str(expired_key)),
        ):
            with pytest.raises(httpx.TransportError):
                async with httpx.AsyncClient(
                    verify=_client_context(ca, cert_pair), trust_env=False, timeout=2
                ) as client:
                    await client.get(f"https://localhost:{port}/peer")
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
