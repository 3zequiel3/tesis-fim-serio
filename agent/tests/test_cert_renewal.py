"""Tests de G3 — renovación proactiva de certificado mTLS (C26 task 5.x)."""
from __future__ import annotations

import asyncio
import datetime
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

from agent.bootstrap import verify_cert


# ── helpers compartidos ───────────────────────────────────────────────────────

def _generate_ca() -> tuple[Ed25519PrivateKey, x509.Certificate]:
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
        .sign(ca_key, None)  # type: ignore[arg-type]
    )
    return ca_key, ca_cert


def _issue_cert(
    ca_key: Ed25519PrivateKey,
    ca_cert: x509.Certificate,
    subject_key: Ed25519PrivateKey,
    cn: str,
    days: int = 90,
) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    not_valid_before = now - datetime.timedelta(days=90) if days < 0 else now
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_cert.subject)
        .public_key(subject_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(now + datetime.timedelta(days=days))
        .sign(ca_key, None)  # type: ignore[arg-type]
    )


def _cert_pem(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _ca_pem(ca_cert: x509.Certificate) -> str:
    return ca_cert.public_bytes(serialization.Encoding.PEM).decode()


def _make_cfg(tmp_path: Path, interval_h: float = 24.0) -> MagicMock:
    cfg = MagicMock()
    cfg.agent_id = "agent-renewal-test"
    cfg.backend_url = "https://fim-backend:8000"
    cfg.mtls_backend_url = "https://fim-backend:8443"
    cfg.storage.certs_dir = str(tmp_path / "certs")
    cfg.cert_renewal_check_interval_h = interval_h
    return cfg


def _write_certs(
    certs_dir: Path,
    cert: x509.Certificate,
    key: Ed25519PrivateKey,
    ca_cert: x509.Certificate,
) -> None:
    certs_dir.mkdir(parents=True, exist_ok=True)
    (certs_dir / "agent-cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (certs_dir / "agent-key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (certs_dir / "ca.pem").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))


# ── verify_cert (función extraída de bootstrap) ───────────────────────────────

def test_verify_cert_valid() -> None:
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    cert = _issue_cert(ca_key, ca_cert, agent_key, "agent-test")

    result = verify_cert(_cert_pem(cert), _ca_pem(ca_cert), "agent-test", agent_key)
    assert result is cert or result.serial_number == cert.serial_number


def test_verify_cert_cn_mismatch() -> None:
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    cert = _issue_cert(ca_key, ca_cert, agent_key, "wrong-cn")

    with pytest.raises(RuntimeError, match="CN mismatch"):
        verify_cert(_cert_pem(cert), _ca_pem(ca_cert), "expected-agent", agent_key)


def test_verify_cert_key_mismatch() -> None:
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    other_key = Ed25519PrivateKey.generate()
    cert = _issue_cert(ca_key, ca_cert, agent_key, "agent-test")

    with pytest.raises(RuntimeError, match="MITM"):
        verify_cert(_cert_pem(cert), _ca_pem(ca_cert), "agent-test", other_key)


# ── config: cert_renewal_check_interval_h ────────────────────────────────────

def test_config_cert_renewal_interval_default() -> None:
    from agent.config import AgentConfig, StorageConfig

    cfg = AgentConfig(
        agent_id="test",
        backend_url="https://test",
        valkey_url="valkey://localhost",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir="/tmp/baseline",
            queue_dir="/tmp/queue",
            journal_dir="/tmp/journal",
        ),
    )
    assert cfg.cert_renewal_check_interval_h == 24.0


def test_config_cert_renewal_interval_custom() -> None:
    from agent.config import AgentConfig, StorageConfig

    cfg = AgentConfig(
        agent_id="test",
        backend_url="https://test",
        valkey_url="valkey://localhost",
        ca_cert_path="/tmp/ca.pem",
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir="/tmp/baseline",
            queue_dir="/tmp/queue",
            journal_dir="/tmp/journal",
        ),
        cert_renewal_check_interval_h=48.0,
    )
    assert cfg.cert_renewal_check_interval_h == 48.0


# ── _cert_renewal_loop ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cert_renewal_skipped_when_valid(tmp_path: Path) -> None:
    """Cert vigente (> 15 días): no llama al backend."""
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    cert = _issue_cert(ca_key, ca_cert, agent_key, "agent-renewal-test", days=90)

    certs_dir = tmp_path / "certs"
    _write_certs(certs_dir, cert, agent_key, ca_cert)

    cfg = _make_cfg(tmp_path, interval_h=0.0001)  # intervalo muy corto
    stop_event = asyncio.Event()

    http_calls: list = []

    async def _fake_post(*args, **kwargs) -> MagicMock:
        http_calls.append(args)
        return MagicMock(status_code=200, json=lambda: {})

    from agent.__main__ import _cert_renewal_loop

    async def _stop_after_one_iteration() -> None:
        await asyncio.sleep(0.5)
        stop_event.set()

    with patch("agent.__main__.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_client_cls.return_value = mock_client

        await asyncio.gather(
            _cert_renewal_loop(cfg, stop_event),
            _stop_after_one_iteration(),
        )

    mock_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_cert_renewal_triggered_when_expiring(tmp_path: Path) -> None:
    """Cert que vence en ≤ 15 días: llama al backend y persiste el nuevo cert."""
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    expiring_cert = _issue_cert(ca_key, ca_cert, agent_key, "agent-renewal-test", days=10)
    new_cert = _issue_cert(ca_key, ca_cert, agent_key, "agent-renewal-test", days=90)

    certs_dir = tmp_path / "certs"
    _write_certs(certs_dir, expiring_cert, agent_key, ca_cert)

    cfg = _make_cfg(tmp_path, interval_h=0.0001)
    stop_event = asyncio.Event()

    new_cert_pem = _cert_pem(new_cert)
    ca_pem = _ca_pem(ca_cert)

    from agent.__main__ import _cert_renewal_loop

    async def _stop_after_renewal() -> None:
        await asyncio.sleep(0.5)
        stop_event.set()

    with patch("agent.__main__.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"cert_pem": new_cert_pem, "ca_cert_pem": ca_pem}
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        await asyncio.gather(
            _cert_renewal_loop(cfg, stop_event),
            _stop_after_renewal(),
        )

    mock_client.post.assert_called_once()
    assert mock_client.post.call_args.args[0] == "https://fim-backend:8443/agents/renew"
    saved_cert_pem = (certs_dir / "agent-cert.pem").read_text()
    assert saved_cert_pem == new_cert_pem


@pytest.mark.asyncio
async def test_cert_renewal_failure_no_interrupt(tmp_path: Path) -> None:
    """Error de red / 404: log warning, cert actual intacto, loop no se detiene."""
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    expiring_cert = _issue_cert(ca_key, ca_cert, agent_key, "agent-renewal-test", days=5)

    certs_dir = tmp_path / "certs"
    _write_certs(certs_dir, expiring_cert, agent_key, ca_cert)
    original_cert_pem = _cert_pem(expiring_cert)

    cfg = _make_cfg(tmp_path, interval_h=0.0001)
    stop_event = asyncio.Event()

    from agent.__main__ import _cert_renewal_loop

    async def _stop_after() -> None:
        await asyncio.sleep(0.5)
        stop_event.set()

    with patch("agent.__main__.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("network_error"))
        mock_client_cls.return_value = mock_client

        # Debe terminar normalmente (sin excepción propagada)
        await asyncio.gather(
            _cert_renewal_loop(cfg, stop_event),
            _stop_after(),
        )

    # Cert original intacto
    assert (certs_dir / "agent-cert.pem").read_text() == original_cert_pem


@pytest.mark.asyncio
async def test_expired_certificate_requires_administrative_recovery(tmp_path: Path) -> None:
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    expired_cert = _issue_cert(ca_key, ca_cert, agent_key, "agent-renewal-test", days=-1)
    _write_certs(tmp_path / "certs", expired_cert, agent_key, ca_cert)
    cfg = _make_cfg(tmp_path, interval_h=0.0001)
    stop_event = asyncio.Event()

    from agent.__main__ import _cert_renewal_loop

    async def _stop_after() -> None:
        await asyncio.sleep(0.5)
        stop_event.set()

    with patch("agent.__main__.httpx.AsyncClient") as mock_client_cls:
        await asyncio.gather(_cert_renewal_loop(cfg, stop_event), _stop_after())

    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_cert_renewal_invalid_new_cert_no_persist(tmp_path: Path) -> None:
    """Nuevo cert con CN incorrecto: verify_cert lanza, el cert original queda intacto."""
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    expiring_cert = _issue_cert(ca_key, ca_cert, agent_key, "agent-renewal-test", days=5)
    bad_cert = _issue_cert(ca_key, ca_cert, agent_key, "wrong-agent", days=90)

    certs_dir = tmp_path / "certs"
    _write_certs(certs_dir, expiring_cert, agent_key, ca_cert)
    original_cert_pem = _cert_pem(expiring_cert)

    cfg = _make_cfg(tmp_path, interval_h=0.0001)
    stop_event = asyncio.Event()

    from agent.__main__ import _cert_renewal_loop

    async def _stop_after() -> None:
        await asyncio.sleep(0.5)
        stop_event.set()

    with patch("agent.__main__.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "cert_pem": _cert_pem(bad_cert),
            "ca_cert_pem": _ca_pem(ca_cert),
        }
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        await asyncio.gather(
            _cert_renewal_loop(cfg, stop_event),
            _stop_after(),
        )

    assert (certs_dir / "agent-cert.pem").read_text() == original_cert_pem


@pytest.mark.asyncio
async def test_cert_renewal_loop_terminates_on_stop_event(tmp_path: Path) -> None:
    """stop_event termina el loop limpiamente."""
    ca_key, ca_cert = _generate_ca()
    agent_key = Ed25519PrivateKey.generate()
    cert = _issue_cert(ca_key, ca_cert, agent_key, "agent-renewal-test", days=90)

    certs_dir = tmp_path / "certs"
    _write_certs(certs_dir, cert, agent_key, ca_cert)

    cfg = _make_cfg(tmp_path, interval_h=24.0)  # intervalo largo
    stop_event = asyncio.Event()

    from agent.__main__ import _cert_renewal_loop

    async def _trigger_stop() -> None:
        await asyncio.sleep(0.1)
        stop_event.set()

    import time
    t0 = time.monotonic()
    await asyncio.gather(_cert_renewal_loop(cfg, stop_event), _trigger_stop())
    elapsed = time.monotonic() - t0

    # Debe haberse detenido en < 1 segundo (no esperar las 24h del intervalo)
    assert elapsed < 1.0
