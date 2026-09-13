"""Focused boundary tests for the dedicated bootstrap TLS listener (D52/RN-146).

Covers:
- The plain-HTTP app (port 8000) no longer mounts POST /agents/bootstrap.
- The bootstrap-only app serves it end to end via the existing bootstrap_agent
  service.
- start_bootstrap_server builds a TLS 1.3 server that does NOT require a
  client certificate, and returns None when certs are missing — same
  contract as start_mtls_server.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

import ssl

import pytest
from argon2 import PasswordHasher
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import Session, SQLModel, create_engine

from app.core.database import get_session
from app.core.pki import ensure_ca, start_bootstrap_server
from app.main import app as http_app
from app.main import bootstrap_app
from app.modules.agents.models import Agent, AgentStatus
from app.modules.agents.router import bootstrap_router


def _build_csr(agent_id: str) -> str:
    key = Ed25519PrivateKey.generate()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, agent_id)]))
        .sign(key, None)  # type: ignore[arg-type]  # Ed25519 has no hash
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


# ── the plain HTTP app no longer serves bootstrap ────────────────────────────


def test_http_app_does_not_mount_bootstrap_route() -> None:
    paths = {route.path for route in http_app.routes}
    assert "/agents/bootstrap" not in paths


def test_bootstrap_app_only_mounts_bootstrap_route() -> None:
    paths = {route.path for route in bootstrap_app.routes}
    assert paths == {"/agents/bootstrap"}


# ── the bootstrap-only app serves it end to end ──────────────────────────────


@pytest.fixture()
def bootstrap_env(tmp_path):
    ca_cert = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    ensure_ca(str(ca_cert), str(ca_key))

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    bootstrap_secret = "a" * 32
    with Session(engine) as session:
        session.add(
            Agent(
                agent_id="bootstrap-agent",
                status=AgentStatus.offline,
                bootstrap_secret_hash=PasswordHasher().hash(bootstrap_secret),
            )
        )
        session.commit()

    app = FastAPI()
    app.include_router(bootstrap_router)

    async def _session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session

    from app.modules.agents import router as agent_router

    return app, bootstrap_secret, ca_cert, ca_key, agent_router


async def test_bootstrap_route_issues_cert_and_secrets(bootstrap_env, monkeypatch) -> None:
    app, bootstrap_secret, ca_cert, ca_key, agent_router = bootstrap_env
    monkeypatch.setattr(agent_router.settings, "ca_cert_path", str(ca_cert))
    monkeypatch.setattr(agent_router.settings, "ca_key_path", str(ca_key))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://bootstrap") as client:
        response = await client.post(
            "/agents/bootstrap",
            json={
                "agent_id": "bootstrap-agent",
                "csr_pem": _build_csr("bootstrap-agent"),
                "bootstrap_secret": bootstrap_secret,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert {"cert_pem", "ca_cert_pem", "shared_secret_hex", "master_secret_hex"} <= body.keys()


async def test_bootstrap_route_rejects_wrong_secret(bootstrap_env, monkeypatch) -> None:
    app, _bootstrap_secret, ca_cert, ca_key, agent_router = bootstrap_env
    monkeypatch.setattr(agent_router.settings, "ca_cert_path", str(ca_cert))
    monkeypatch.setattr(agent_router.settings, "ca_key_path", str(ca_key))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://bootstrap") as client:
        response = await client.post(
            "/agents/bootstrap",
            json={
                "agent_id": "bootstrap-agent",
                "csr_pem": _build_csr("bootstrap-agent"),
                "bootstrap_secret": "wrong-secret-wrong-secret-wrong",
            },
        )

    assert response.status_code == 401


# ── start_bootstrap_server: TLS 1.3, no client cert required ─────────────────


def _real_cert_paths(tmp_path):
    ca_file = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    cert_file = tmp_path / "cert.pem"
    key_file = tmp_path / "key.pem"
    ensure_ca(str(ca_file), str(ca_key), str(cert_file), str(key_file))
    return cert_file, key_file


def test_start_bootstrap_server_does_not_require_client_cert(tmp_path) -> None:
    import uvicorn

    cert_file, key_file = _real_cert_paths(tmp_path)

    app = FastAPI()
    server = start_bootstrap_server(app, cert_path=str(cert_file), key_path=str(key_file))

    assert server is not None
    assert isinstance(server, uvicorn.Server)
    assert server.config.ssl.verify_mode == ssl.CERT_NONE
    assert server.config.ssl.minimum_version.name == "TLSv1_3"
    assert server.config.install_signal_handlers is False


def test_start_bootstrap_server_returns_none_when_cert_missing(tmp_path) -> None:
    app = FastAPI()
    result = start_bootstrap_server(
        app,
        cert_path=str(tmp_path / "noexiste_cert.pem"),
        key_path=str(tmp_path / "noexiste_key.pem"),
    )
    assert result is None


def test_start_bootstrap_server_returns_none_when_paths_empty() -> None:
    app = FastAPI()
    result = start_bootstrap_server(app, cert_path="", key_path="")
    assert result is None
