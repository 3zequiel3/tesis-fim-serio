"""Tests for agent/transport.py — Valkey client factory (C24)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.config import AgentConfig, StorageConfig
from agent.transport import create_valkey_client


def _make_config(valkey_url: str, certs_dir: str = "/tmp/certs") -> AgentConfig:
    return AgentConfig(
        agent_id="test-agent",
        backend_url="http://localhost:8000",
        valkey_url=valkey_url,
        ca_cert_path="/etc/fim-agent/certs/ca.pem",
        watch_paths=["/etc"],
        storage=StorageConfig(
            baseline_dir="/tmp/baseline",
            queue_dir="/tmp/queue",
            journal_dir="/tmp/journal",
            secrets_dir="/tmp/secrets",
            certs_dir=certs_dir,
        ),
    )


def _create_dummy_certs(certs_dir: Path) -> None:
    """Create placeholder cert files so the factory's existence check passes."""
    certs_dir.mkdir(parents=True, exist_ok=True)
    for name in ("agent-cert.pem", "agent-key.pem", "ca.pem"):
        (certs_dir / name).write_text("placeholder")


class TestPlaintextSchemes:
    """valkey:// and redis:// must produce a client with no SSL parameters."""

    @pytest.mark.parametrize("url", ["valkey://localhost:6379", "redis://localhost:6379"])
    def test_no_ssl_kwargs_passed(self, url: str) -> None:
        config = _make_config(url)

        with patch("agent.transport.avalkey.Valkey.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            create_valkey_client(config)

        call_kwargs = mock_from_url.call_args.kwargs
        ssl_keys = [k for k in call_kwargs if k.startswith("ssl")]
        assert ssl_keys == [], f"Expected no ssl_* kwargs for {url!r}, got {ssl_keys}"

    def test_valkey_scheme_decode_responses_preserved(self) -> None:
        config = _make_config("valkey://localhost:6379")

        with patch("agent.transport.avalkey.Valkey.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            create_valkey_client(config)

        assert mock_from_url.call_args.kwargs.get("decode_responses") is True


class TestTLSSchemes:
    """valkeys:// and rediss:// must produce a client with full mTLS parameters."""

    @pytest.mark.parametrize("url_template", ["valkeys://localhost:6380", "rediss://localhost:6380"])
    def test_ssl_params_set(self, url_template: str, tmp_path: Path) -> None:
        certs_dir = tmp_path / "certs"
        _create_dummy_certs(certs_dir)
        config = _make_config(url_template, certs_dir=str(certs_dir))

        with patch("agent.transport.avalkey.Valkey.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            create_valkey_client(config)

        kw = mock_from_url.call_args.kwargs
        assert kw.get("ssl_certfile") == str(certs_dir / "agent-cert.pem")
        assert kw.get("ssl_keyfile") == str(certs_dir / "agent-key.pem")
        assert kw.get("ssl_ca_certs") == str(certs_dir / "ca.pem")
        assert kw.get("ssl_cert_reqs") == "required"
        assert kw.get("decode_responses") is True

    def test_valkeys_cert_paths_match_certs_dir(self, tmp_path: Path) -> None:
        certs_dir = tmp_path / "fim-certs"
        _create_dummy_certs(certs_dir)
        config = _make_config("valkeys://localhost:6380", certs_dir=str(certs_dir))

        with patch("agent.transport.avalkey.Valkey.from_url") as mock_from_url:
            mock_from_url.return_value = MagicMock()
            create_valkey_client(config)

        kw = mock_from_url.call_args.kwargs
        assert kw["ssl_certfile"] == str(certs_dir / "agent-cert.pem")
        assert kw["ssl_keyfile"] == str(certs_dir / "agent-key.pem")
        assert kw["ssl_ca_certs"] == str(certs_dir / "ca.pem")

    def test_rediss_identical_to_valkeys(self, tmp_path: Path) -> None:
        certs_dir = tmp_path / "certs"
        _create_dummy_certs(certs_dir)

        captured: dict = {}

        def capture_call(url: str, **kwargs: object) -> MagicMock:
            captured[url] = kwargs
            return MagicMock()

        with patch("agent.transport.avalkey.Valkey.from_url", side_effect=capture_call):
            create_valkey_client(_make_config("valkeys://localhost:6380", str(certs_dir)))
            create_valkey_client(_make_config("rediss://localhost:6380", str(certs_dir)))

        valkeys_kw = {k: v for k, v in captured["valkeys://localhost:6380"].items() if k.startswith("ssl")}
        rediss_kw = {k: v for k, v in captured["rediss://localhost:6380"].items() if k.startswith("ssl")}
        assert valkeys_kw == rediss_kw

    def test_missing_cert_raises_runtime_error(self, tmp_path: Path) -> None:
        certs_dir = tmp_path / "certs"
        # Intentionally do NOT create any cert files
        config = _make_config("valkeys://localhost:6380", certs_dir=str(certs_dir))

        with pytest.raises(RuntimeError, match="mTLS cert files missing"):
            create_valkey_client(config)

    def test_missing_single_cert_raises(self, tmp_path: Path) -> None:
        certs_dir = tmp_path / "certs"
        _create_dummy_certs(certs_dir)
        # Remove one file to simulate partial bootstrap
        (certs_dir / "agent-key.pem").unlink()
        config = _make_config("valkeys://localhost:6380", certs_dir=str(certs_dir))

        with pytest.raises(RuntimeError, match="agent-key.pem"):
            create_valkey_client(config)


class TestUnknownScheme:
    """Unrecognized schemes must raise ValueError."""

    @pytest.mark.parametrize("url", ["http://localhost:6379", "tcp://localhost:6379", "ftp://x"])
    def test_unknown_scheme_raises_value_error(self, url: str) -> None:
        config = _make_config(url)
        with pytest.raises(ValueError, match="Unrecognized Valkey URL scheme"):
            create_valkey_client(config)
