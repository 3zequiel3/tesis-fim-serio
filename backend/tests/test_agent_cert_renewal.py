"""Focused boundary tests for certificate renewal on the dedicated mTLS app."""
from __future__ import annotations

import datetime
import os

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, SQLModel, create_engine

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

from app.core.database import get_session
from app.core.pki import PEER_CERT_SCOPE_KEY, ensure_ca
from app.main import app as http_app
from app.modules.agents.models import Agent, AgentStatus, RevokedCertificate
from app.modules.agents.router import renew_router


def _issue_client(ca_cert_path, ca_key_path, key, cn: str, days: int = 10):
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


@pytest.fixture()
def renewal_env(tmp_path, monkeypatch):
    ca_cert = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    ensure_ca(str(ca_cert), str(ca_key))
    key = Ed25519PrivateKey.generate()
    cert = _issue_client(ca_cert, ca_key, key, "agent-renew", days=10)

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Agent(agent_id="agent-renew", status=AgentStatus.online))
        session.commit()

    app = FastAPI()
    app.include_router(renew_router)
    app.state.peer_cert_der = cert.public_bytes(serialization.Encoding.DER)

    async def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session

    @app.middleware("http")
    async def _test_tls_scope(request, call_next):
        request.scope.setdefault("state", {})[PEER_CERT_SCOPE_KEY] = request.app.state.peer_cert_der
        return await call_next(request)

    from app.modules.agents import router as agent_router

    monkeypatch.setattr(agent_router.settings, "ca_cert_path", str(ca_cert))
    monkeypatch.setattr(agent_router.settings, "ca_key_path", str(ca_key))
    return app, engine, key, cert, ca_cert, ca_key


async def test_valid_certificate_renews_with_new_serial_and_same_key(renewal_env) -> None:
    app, _engine, key, old_cert, _ca_cert, _ca_key = renewal_env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://mtls") as client:
        response = await client.post("/agents/renew", json={"agent_id": "agent-renew"})

    assert response.status_code == 200
    renewed = x509.load_pem_x509_certificate(response.json()["cert_pem"].encode())
    assert renewed.serial_number != old_cert.serial_number
    assert renewed.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ) == key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


@pytest.mark.parametrize("failure", ["mismatch", "agent_revoked", "serial_revoked"])
async def test_identity_and_revocation_fail_closed(renewal_env, failure: str) -> None:
    app, engine, _key, cert, _ca_cert, _ca_key = renewal_env
    body_agent = "other-agent" if failure == "mismatch" else "agent-renew"
    if failure != "mismatch":
        with Session(engine) as session:
            agent = session.get(Agent, "agent-renew")
            assert agent is not None
            if failure == "agent_revoked":
                agent.status = AgentStatus.revoked
                session.add(agent)
            else:
                session.add(
                    RevokedCertificate(
                        agent_id="agent-renew", serial_number=str(cert.serial_number)
                    )
                )
            session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://mtls") as client:
        response = await client.post("/agents/renew", json={"agent_id": body_agent})
    assert response.status_code == 403


async def test_certificate_outside_pre_expiry_threshold_is_not_renewed(renewal_env) -> None:
    app, _engine, key, _old_cert, ca_cert, ca_key = renewal_env
    too_early = _issue_client(ca_cert, ca_key, key, "agent-renew", days=30)
    app.state.peer_cert_der = too_early.public_bytes(serialization.Encoding.DER)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://mtls") as client:
        response = await client.post("/agents/renew", json={"agent_id": "agent-renew"})

    assert response.status_code == 409


def test_http_app_does_not_mount_credential_renewal_route() -> None:
    paths = {route.path for route in http_app.routes}
    assert "/agents/renew" not in paths


async def test_renewal_without_tls_scope_certificate_is_forbidden() -> None:
    app = FastAPI()
    app.include_router(renew_router)

    async def _unused_session():
        yield None

    app.dependency_overrides[get_session] = _unused_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://plain") as client:
        response = await client.post("/agents/renew", json={"agent_id": "agent-renew"})
    assert response.status_code == 403
