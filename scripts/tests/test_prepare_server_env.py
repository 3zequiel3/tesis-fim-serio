"""
D54/RN-148, D59/RN-153 — `scripts/prepare_server_env.py`.

Los tests no marcados `integration` no invocan Docker: `hash_n8n_owner_password`
se monkeypatchea con un valor bcrypt sintético. Los marcados `integration`
corren el hashing real contra la imagen pinneada de n8n y/o `docker compose
config` sobre el `.env` generado.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location(
    "prepare_server_env", REPO_ROOT / "scripts" / "prepare_server_env.py"
)
assert _SPEC and _SPEC.loader
prepare_server_env = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(prepare_server_env)

_FAKE_BCRYPT_HASH = "$2a$10$" + "x" * 53


@pytest.fixture(autouse=True)
def _no_docker_hashing(request, monkeypatch):
    """Every non-integration test avoids invoking Docker. Tests marked
    `integration` opt out, so they exercise the real bcrypt hashing path."""
    if request.node.get_closest_marker("integration"):
        return
    monkeypatch.setattr(
        prepare_server_env, "hash_n8n_owner_password", lambda password, image=None: _FAKE_BCRYPT_HASH
    )


# ── parse_public_hosts — paridad con el backend ───────────────────────────────

_COMMON_HOST_CASES: list[tuple[str, bool]] = [
    ("", True),
    ("203.0.113.10", True),
    ("fim.example.org", True),
    ("FIM.Example.ORG", True),
    ("2001:DB8::1", True),
    ("203.0.113.10, fim.example.org", True),
    (" , fim.example.org , , ", True),
    ("bad_host!", False),
    ("*.example.org", False),
    ("-leading-hyphen.example.org", False),
    ("trailing-hyphen-.example.org", False),
    ("localhost", True),
]


def test_parse_public_hosts_paridad_con_backend_pki() -> None:
    """Corre la tabla de casos común contra prepare_server_env y contra
    app.core.pki (backend) y afirma resultados equivalentes."""
    backend_path = REPO_ROOT / "backend"
    sys.path.insert(0, str(backend_path))
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
    os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
    os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
    os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
    os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    try:
        from app.core.pki import parse_public_hosts as backend_parse_public_hosts
    finally:
        sys.path.remove(str(backend_path))

    for raw, expect_valid in _COMMON_HOST_CASES:
        script_error = None
        backend_error = None
        script_result = None
        backend_result = None
        try:
            script_result = prepare_server_env.parse_public_hosts(raw)
        except prepare_server_env.ServerEnvError as exc:
            script_error = exc
        try:
            backend_result = backend_parse_public_hosts(raw)
        except ValueError as exc:
            backend_error = exc

        assert (script_error is None) == expect_valid, f"script disagreed on {raw!r}"
        assert (backend_error is None) == expect_valid, f"backend disagreed on {raw!r}"
        if expect_valid:
            script_dns, script_ips = script_result
            backend_dns, backend_ips = backend_result
            assert script_dns == backend_dns, raw
            assert {ipaddress.ip_address(str(ip)) for ip in script_ips} == set(backend_ips), raw


# ── derive_cors_origins (D59/RN-153) ──────────────────────────────────────────


def test_derive_cors_origins_off_default_ports() -> None:
    origins = prepare_server_env.derive_cors_origins({"fim.example.org"}, set(), "off")
    assert origins == "http://fim.example.org,http://localhost"


def test_derive_cors_origins_self_signed_https_default_port() -> None:
    origins = prepare_server_env.derive_cors_origins(set(), set(), "self_signed")
    assert origins == "https://localhost"


def test_derive_cors_origins_non_default_port_included() -> None:
    origins = prepare_server_env.derive_cors_origins(
        set(), set(), "self_signed", https_port=8443
    )
    assert origins == "https://localhost:8443"


def test_derive_cors_origins_ipv6_bracketed() -> None:
    ip = ipaddress.ip_address("2001:db8::1")
    origins = prepare_server_env.derive_cors_origins(set(), {ip}, "off")
    assert "http://[2001:db8::1]" in origins.split(",")


# ── run() — generación de .env ────────────────────────────────────────────────


def test_run_crea_env_0600_con_todas_las_claves(tmp_path) -> None:
    output = tmp_path / ".env"
    rc = prepare_server_env.run(
        [
            "--fim-public-hosts", "203.0.113.10",
            "--console-tls-mode", "off",
            "--admin-username", "admin",
            "--n8n-owner-email", "ops@example.org",
            "--output", str(output),
        ]
    )
    assert rc == 0
    assert output.exists()
    mode = stat.S_IMODE(output.stat().st_mode)
    assert mode == 0o600

    content = output.read_text()
    values = dict(
        line.split("=", 1) for line in content.splitlines() if line and not line.startswith("#")
    )
    required_keys = [
        "DB_PASSWORD", "JWT_SECRET_CURRENT", "ADMIN_USERNAME", "ADMIN_PASSWORD",
        "CA_CERT_PATH", "CA_KEY_PATH", "BACKEND_CERT_PATH", "BACKEND_KEY_PATH",
        "CORS_ALLOWED_ORIGINS", "FIM_PUBLIC_HOSTS", "CONSOLE_TLS_MODE",
        "CONSOLE_HTTP_PORT", "CONSOLE_HTTPS_PORT", "CONSOLE_TLS_DIR",
        "CONSOLE_TLS_CERT_FILE", "CONSOLE_TLS_KEY_FILE", "N8N_WEBHOOK_URL",
        "N8N_HEALTH_URL", "N8N_ENCRYPTION_KEY", "N8N_INSTANCE_OWNER_EMAIL",
        "N8N_INSTANCE_OWNER_FIRST_NAME", "N8N_INSTANCE_OWNER_LAST_NAME",
        "N8N_INSTANCE_OWNER_PASSWORD_HASH",
    ]
    non_empty_secrets = [
        "DB_PASSWORD", "JWT_SECRET_CURRENT", "ADMIN_PASSWORD", "N8N_ENCRYPTION_KEY",
        "N8N_INSTANCE_OWNER_PASSWORD_HASH",
    ]
    for key in required_keys:
        assert key in values, key
    for key in non_empty_secrets:
        assert values[key] != "", key
    # JWT_SECRET_PREVIOUS is intentionally empty on first generation.
    assert values["JWT_SECRET_PREVIOUS"] == ""


def test_run_env_existente_exit_distinto_de_cero_e_identico(tmp_path) -> None:
    output = tmp_path / ".env"
    original = "PRE_EXISTING=1\n"
    output.write_text(original)

    rc = prepare_server_env.run(
        ["--fim-public-hosts", "", "--console-tls-mode", "off", "--output", str(output)]
    )
    assert rc != 0
    assert output.read_text() == original


def test_run_host_invalido_no_crea_archivo(tmp_path) -> None:
    output = tmp_path / ".env"
    rc = prepare_server_env.run(
        ["--fim-public-hosts", "bad_host!", "--console-tls-mode", "off", "--output", str(output)]
    )
    assert rc != 0
    assert not output.exists()


def test_run_dos_corridas_secretos_distintos(tmp_path) -> None:
    out1, out2 = tmp_path / "a" / ".env", tmp_path / "b" / ".env"
    out1.parent.mkdir()
    out2.parent.mkdir()

    for out in (out1, out2):
        rc = prepare_server_env.run(
            ["--fim-public-hosts", "", "--console-tls-mode", "off", "--output", str(out)]
        )
        assert rc == 0

    values1 = dict(
        line.split("=", 1) for line in out1.read_text().splitlines()
        if line and not line.startswith("#")
    )
    values2 = dict(
        line.split("=", 1) for line in out2.read_text().splitlines()
        if line and not line.startswith("#")
    )
    for key in ("DB_PASSWORD", "JWT_SECRET_CURRENT", "ADMIN_PASSWORD", "N8N_ENCRYPTION_KEY"):
        assert values1[key] != values2[key], key


def test_run_bcrypt_hashing_falla_no_escribe_env(tmp_path, monkeypatch) -> None:
    def _boom(password, image=None):
        raise prepare_server_env.ServerEnvError("simulated docker failure")

    monkeypatch.setattr(prepare_server_env, "hash_n8n_owner_password", _boom)
    output = tmp_path / ".env"
    rc = prepare_server_env.run(
        ["--fim-public-hosts", "", "--console-tls-mode", "off", "--output", str(output)]
    )
    assert rc != 0
    assert not output.exists()


# ── Integración: hashing real y docker compose config ────────────────────────


@pytest.mark.integration
def test_hash_n8n_owner_password_formato_bcrypt_real() -> None:
    import shutil

    if shutil.which("docker") is None:
        pytest.skip("docker no disponible")
    hashed = prepare_server_env.hash_n8n_owner_password("a-test-password")
    assert hashed.startswith(("$2a$", "$2b$", "$2y$"))


@pytest.mark.integration
def test_docker_compose_config_sin_warnings_sobre_env_generado(tmp_path) -> None:
    import shutil
    import subprocess

    if shutil.which("docker") is None:
        pytest.skip("docker no disponible")

    output = tmp_path / "test.env"
    rc = prepare_server_env.run(
        [
            "--fim-public-hosts", "203.0.113.10",
            "--console-tls-mode", "off",
            "--output", str(output),
        ]
    )
    assert rc == 0

    result = subprocess.run(
        [
            "docker", "compose", "--env-file", str(output),
            "-f", "docker-compose.yml", "-f", "docker-compose.tls.yml",
            "--profile", "app", "config", "--quiet",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "is not set" not in result.stderr
