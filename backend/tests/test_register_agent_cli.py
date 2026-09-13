"""D56/RN-150 — `python -m app.modules.agents.cli register` (design D-8 of
`vps-deployment-readiness`), the server-side single-step agent registration
CLI wrapped by `scripts/register-agent.sh`.
"""

from __future__ import annotations

import hashlib

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from sqlmodel import Session

from app.core.config import settings
from app.core.database import engine
from app.core.pki import ensure_ca
from app.modules.agents.cli import compute_ca_fingerprint, main, register
from app.modules.agents.models import Agent, AgentStatus


@pytest.fixture()
def ca_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    ca_cert = tmp_path / "ca.pem"
    ca_key = tmp_path / "ca-key.pem"
    ensure_ca(str(ca_cert), str(ca_key))
    monkeypatch.setattr(settings, "ca_cert_path", str(ca_cert))
    monkeypatch.setattr(settings, "fim_public_hosts", "203.0.113.10,fim.example.org")
    return str(ca_cert)


def _get_agent(agent_id: str) -> Agent | None:
    with Session(engine) as session:
        return session.get(Agent, agent_id)


def test_register_success_argon2id_hash_and_offline_status(ca_file: str, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["register", "--agent-id", "web-01"])
    assert exit_code == 0

    agent = _get_agent("web-01")
    assert agent is not None
    assert agent.status == AgentStatus.offline
    assert agent.bootstrap_secret_hash is not None
    assert agent.bootstrap_secret_hash.startswith("$argon2id$")


def test_register_output_contains_all_four_fields_and_secretless_command(
    ca_file: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["register", "--agent-id", "web-02"])
    assert exit_code == 0
    out = capsys.readouterr().out

    assert "hosts: 203.0.113.10, fim.example.org" in out
    assert "ca_fingerprint_sha256:" in out
    assert "bootstrap_secret:" in out
    assert "install.sh" in out

    secret_line = next(line for line in out.splitlines() if line.startswith("bootstrap_secret:"))
    secret = secret_line.split(":", 1)[1].strip()
    assert len(secret) >= 32

    install_command_line = next(line for line in out.splitlines() if "install.sh" in line)
    assert secret not in install_command_line
    assert "--bootstrap-secret-file" in install_command_line


def test_register_duplicate_agent_id_conflict(ca_file: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["register", "--agent-id", "web-03"]) == 0
    capsys.readouterr()  # discard first registration's output

    exit_code = main(["register", "--agent-id", "web-03"])
    assert exit_code != 0

    captured = capsys.readouterr()
    assert "bootstrap_secret:" not in captured.out
    assert "already registered" in captured.err


def test_fingerprint_matches_sha256_of_der(ca_file: str) -> None:
    cert = x509.load_pem_x509_certificate(open(ca_file, "rb").read())
    expected = hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()
    assert compute_ca_fingerprint(ca_file) == expected


@pytest.mark.integration
def test_fingerprint_matches_openssl(ca_file: str) -> None:
    import shutil
    import subprocess

    if shutil.which("openssl") is None:
        pytest.skip("openssl not available")

    result = subprocess.run(
        ["openssl", "x509", "-in", ca_file, "-outform", "DER"],
        capture_output=True,
        check=True,
    )
    expected = hashlib.sha256(result.stdout).hexdigest()
    assert compute_ca_fingerprint(ca_file) == expected


def test_secret_absent_from_captured_logs(
    ca_file: str, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    exit_code = register("web-04")
    assert exit_code == 0

    out = capsys.readouterr().out
    secret_line = next(line for line in out.splitlines() if line.startswith("bootstrap_secret:"))
    secret = secret_line.split(":", 1)[1].strip()

    assert secret not in caplog.text
