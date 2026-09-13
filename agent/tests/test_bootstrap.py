"""Tests de verificación de bootstrap (C23-H3): cadena Ed25519, CN y clave pública."""
from __future__ import annotations

import datetime
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.x509.oid import NameOID

from agent.bootstrap import run
from agent.config import AgentConfig, StorageConfig


# ── helpers ────────────────────────────────────────────────────────────────────

def _generate_ca() -> tuple[Ed25519PrivateKey, x509.Certificate]:
    """Genera una CA Ed25519 auto-firmada."""
    ca_key = Ed25519PrivateKey.generate()
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, None)  # type: ignore[arg-type]  # Ed25519 sin hash
    )
    return ca_key, ca_cert


def _issue_cert(
    ca_key: Ed25519PrivateKey,
    ca_cert: x509.Certificate,
    subject_key: Ed25519PrivateKey,
    cn: str,
) -> x509.Certificate:
    """Emite un cert firmado por la CA con el CN y la clave dadas."""
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_cert.subject)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=90))
        .sign(ca_key, None)  # type: ignore[arg-type]
    )


def _cert_pem(cert: x509.Certificate) -> str:
    return cert.public_bytes(Encoding.PEM).decode()


def _key_pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()


def _bootstrap_response(cert: x509.Certificate, ca_cert: x509.Certificate) -> dict:
    return {
        "cert_pem": _cert_pem(cert),
        "ca_cert_pem": _cert_pem(ca_cert),
        "shared_secret_hex": os.urandom(32).hex(),
        "master_secret_hex": os.urandom(32).hex(),
    }


def _make_config(
    tmp_path: Path, agent_id: str = "test-agent-001", backend_url: str = "https://localhost:8444"
) -> AgentConfig:
    certs_dir = tmp_path / "certs"
    secrets_dir = tmp_path / "secrets"
    certs_dir.mkdir(parents=True)
    secrets_dir.mkdir(parents=True)
    # D16: ca_cert_path must exist before bootstrap.run() (BUG-07 fix)
    (certs_dir / "ca.pem").write_bytes(b"dummy-ca-for-tests")
    return AgentConfig(
        agent_id=agent_id,
        backend_url=backend_url,
        valkey_url="redis://localhost:6379",
        ca_cert_path=str(certs_dir / "ca.pem"),
        watch_paths=["/tmp"],
        storage=StorageConfig(
            baseline_dir=str(tmp_path / "baseline"),
            queue_dir=str(tmp_path / "queue"),
            journal_dir=str(tmp_path / "journal"),
            secrets_dir=str(secrets_dir),
            certs_dir=str(certs_dir),
        ),
    )


# ── tests ──────────────────────────────────────────────────────────────────────

def test_bootstrap_valid_material_persists(tmp_path: Path) -> None:
    """Material válido (cadena+CN+clave OK) se persiste correctamente."""
    config = _make_config(tmp_path)
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    cert = _issue_cert(ca_key, ca_cert, agent_key, config.agent_id)
    response_data = _bootstrap_response(cert, ca_cert)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_data

    with (
        patch("httpx.post", return_value=mock_resp),
        patch("agent.bootstrap.generate_keypair", return_value=agent_key),
    ):
        run(config, "bootstrap-secret")

    assert (Path(config.storage.certs_dir) / "agent-cert.pem").exists()
    assert (Path(config.storage.certs_dir) / "ca.pem").exists()
    assert (Path(config.storage.secrets_dir) / "shared_secret").exists()
    assert (Path(config.storage.secrets_dir) / "master_secret").exists()


def test_bootstrap_wrong_cn_raises_runtime_error(tmp_path: Path) -> None:
    """Cert con CN incorrecto → RuntimeError, nada se persiste."""
    config = _make_config(tmp_path, agent_id="correct-agent")
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    # Emitir cert con CN diferente al agent_id
    cert = _issue_cert(ca_key, ca_cert, agent_key, "wrong-agent")
    response_data = _bootstrap_response(cert, ca_cert)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_data

    with (
        patch("httpx.post", return_value=mock_resp),
        patch("agent.bootstrap.generate_keypair", return_value=agent_key),
    ):
        with pytest.raises(RuntimeError, match="CN mismatch"):
            run(config, "bootstrap-secret")

    # Nada debe haberse persistido
    assert not (Path(config.storage.certs_dir) / "agent-cert.pem").exists()


def test_bootstrap_cert_not_signed_by_ca_raises_runtime_error(tmp_path: Path) -> None:
    """Cert no firmado por la CA recibida → RuntimeError."""
    config = _make_config(tmp_path)
    ca_key, ca_cert = _generate_ca()
    # CA diferente para firmar el cert
    rogue_ca_key, _ = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    # El cert está firmado por rogue_ca pero la respuesta incluye la ca_cert legítima
    rogue_cert = _issue_cert(rogue_ca_key, ca_cert, agent_key, config.agent_id)
    response_data = _bootstrap_response(rogue_cert, ca_cert)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_data

    with (
        patch("httpx.post", return_value=mock_resp),
        patch("agent.bootstrap.generate_keypair", return_value=agent_key),
    ):
        with pytest.raises(RuntimeError, match="not signed by CA"):
            run(config, "bootstrap-secret")

    assert not (Path(config.storage.certs_dir) / "agent-cert.pem").exists()


def test_bootstrap_pubkey_mismatch_raises_runtime_error(tmp_path: Path) -> None:
    """Cert cuya clave pública no coincide con la clave local → RuntimeError."""
    config = _make_config(tmp_path)
    ca_key, ca_cert = _generate_ca()
    # La clave en el cert es diferente a la clave local del agente
    cert_key = Ed25519PrivateKey.generate()
    local_key = Ed25519PrivateKey.generate()
    cert = _issue_cert(ca_key, ca_cert, cert_key, config.agent_id)
    response_data = _bootstrap_response(cert, ca_cert)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_data

    with (
        patch("httpx.post", return_value=mock_resp),
        # generate_keypair devuelve la clave LOCAL (diferente a la del cert)
        patch("agent.bootstrap.generate_keypair", return_value=local_key),
    ):
        with pytest.raises(RuntimeError, match="public key does not match"):
            run(config, "bootstrap-secret")

    assert not (Path(config.storage.certs_dir) / "agent-cert.pem").exists()


def test_bootstrap_rejects_non_https_backend_url(tmp_path: Path) -> None:
    """RN-114/D52: a plaintext backend_url must abort before any HTTP call —
    bootstrap responses carry shared_secret_hex/master_secret_hex in the clear."""
    config = _make_config(tmp_path, backend_url="http://localhost:8444")

    with patch("httpx.post") as mock_post:
        with pytest.raises(SystemExit) as exc_info:
            run(config, "bootstrap-secret")

    assert exc_info.value.code == 1
    mock_post.assert_not_called()
    assert not (Path(config.storage.certs_dir) / "agent-cert.pem").exists()
