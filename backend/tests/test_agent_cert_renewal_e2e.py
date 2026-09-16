"""End-to-end verification (task 6.1) over a real local mTLS listener.

Proves that an agent whose certificate is within the 15-day renewal
threshold (RN-78, `_CERT_RENEWAL_THRESHOLD_DAYS`) can renew it through
`POST /agents/renew` with no manual step, and that the renewed certificate,
combined with the agent's unchanged private key, keeps authenticating over
the same mTLS transport the agent uses to publish events to Valkey
(`agent/transport.py`: `ssl_certfile`/`ssl_keyfile` are the same
`agent-cert.pem`/`agent-key.pem` files the renewal loop overwrites). A real
TLS handshake here, not a mocked one, is what actually demonstrates
continuity: the renewed cert must be independently accepted by a *second*,
fresh mTLS connection signed by the same platform CA.
"""
from __future__ import annotations

import asyncio
import datetime
import os
import socket
import ssl
import sys
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import FastAPI
from sqlmodel import Session, SQLModel, create_engine

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")

from app.core.database import get_session
from app.core.pki import _CERT_RENEWAL_THRESHOLD_DAYS, ensure_ca, start_mtls_server
from app.modules.agents.models import Agent, AgentStatus
from app.modules.agents.router import renew_router

# El agente vive en <repo_root>/agent, fuera del árbol de paquetes del backend
# (mismo patrón que test_event_status_derivation.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from agent import bootstrap as agent_bootstrap  # noqa: E402


def _issue_client_cert(ca_cert_path, ca_key_path, key: Ed25519PrivateKey, cn: str, days: int):
    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(ca_key, None)
    )


def _free_port() -> int:
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
    except PermissionError:
        pytest.skip("sandbox does not permit local TCP sockets")


def _client_ssl_context(ca_path, cert_path, key_path) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(ca_path))
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(str(cert_path), str(key_path))
    return context


async def test_agent_near_expiry_renews_unattended_and_keeps_authenticating(
    tmp_path, monkeypatch
) -> None:
    ca_cert_path = tmp_path / "ca.pem"
    ca_key_path = tmp_path / "ca-key.pem"
    server_cert_path = tmp_path / "backend-cert.pem"
    server_key_path = tmp_path / "backend-key.pem"
    # Same production helper that generates the CA and the backend's own
    # mTLS server leaf at startup (app.core.pki.ensure_ca).
    ensure_ca(str(ca_cert_path), str(ca_key_path), str(server_cert_path), str(server_key_path))

    agent_key = Ed25519PrivateKey.generate()
    agent_key_path = tmp_path / "agent-key.pem"
    agent_key_path.write_bytes(
        agent_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    # 10 days left: inside the 15-day renewal threshold (RN-78) and still
    # valid, matching exactly the condition _cert_renewal_loop checks before
    # calling POST /agents/renew (agent/__main__.py).
    old_cert = _issue_client_cert(
        ca_cert_path, ca_key_path, agent_key, "agent-e2e", days=10
    )
    old_cert_path = tmp_path / "agent-cert.pem"
    old_cert_path.write_bytes(old_cert.public_bytes(serialization.Encoding.PEM))

    days_left = (old_cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)).days
    assert days_left <= _CERT_RENEWAL_THRESHOLD_DAYS

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Agent(agent_id="agent-e2e", status=AgentStatus.online))
        session.commit()

    def _session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(renew_router)
    app.dependency_overrides[get_session] = _session

    @app.get("/publish-check")
    async def publish_check() -> dict[str, bool]:
        # Stand-in for the agent publishing an event to Valkey: both are
        # plain authenticated requests over the same mTLS transport primitive
        # (agent/transport.py builds its Valkey client from the identical
        # agent-cert.pem/agent-key.pem pair this test renews).
        return {"ok": True}

    from app.modules.agents import router as agent_router

    monkeypatch.setattr(agent_router.settings, "ca_cert_path", str(ca_cert_path))
    monkeypatch.setattr(agent_router.settings, "ca_key_path", str(ca_key_path))

    port = _free_port()
    server = start_mtls_server(
        app,
        str(ca_cert_path),
        str(server_cert_path),
        str(server_key_path),
        host="127.0.0.1",
        port=port,
    )
    assert server is not None
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)

        # Step 1: the agent's unattended renewal call, byte-for-byte the same
        # body _cert_renewal_loop sends: {"agent_id": cfg.agent_id}, mTLS
        # client auth with its current (soon-to-expire) cert/key.
        async with httpx.AsyncClient(
            verify=_client_ssl_context(ca_cert_path, old_cert_path, agent_key_path),
            trust_env=False,
        ) as client:
            resp = await client.post(
                f"https://localhost:{port}/agents/renew", json={"agent_id": "agent-e2e"}
            )
        assert resp.status_code == 200
        data = resp.json()
        new_cert_pem = data["cert_pem"]
        ca_cert_pem = data.get("ca_cert_pem", ca_cert_path.read_text())

        # Step 2: exactly what the agent does before trusting the response
        # (agent/bootstrap.py:verify_cert, called from _cert_renewal_loop) —
        # binds the new certificate to the *existing* private key. No CSR,
        # no key rotation (D-2 / task 7.2).
        renewed = agent_bootstrap.verify_cert(
            new_cert_pem, ca_cert_pem, "agent-e2e", private_key=agent_key
        )
        assert renewed.serial_number != old_cert.serial_number

        # Step 3: atomic replace, mirroring the agent's write path.
        new_cert_path = tmp_path / "agent-cert.pem.new"
        new_cert_path.write_bytes(new_cert_pem.encode())
        os.replace(new_cert_path, old_cert_path)

        # Step 4: a brand-new mTLS connection using the renewed certificate
        # and the *unchanged* private key succeeds against the platform CA —
        # the agent keeps publishing without downtime or manual recovery.
        async with httpx.AsyncClient(
            verify=_client_ssl_context(ca_cert_path, old_cert_path, agent_key_path),
            trust_env=False,
        ) as client:
            publish_resp = await client.get(f"https://localhost:{port}/publish-check")
        assert publish_resp.status_code == 200
        assert publish_resp.json() == {"ok": True}
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
