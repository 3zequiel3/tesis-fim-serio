"""
D54/RN-148 — topología de servidor en `docker-compose.yml` +
`docker-compose.tls.yml` + perfil `app` (change 52, grupo 3).

Renderiza la composición real con `docker compose ... config --format json`
contra un `.env` de prueba (no arranca nada, no publica puertos reales).

`test_certs_init_presente` verifica el servicio one-shot `certs-init`
(D53/RN-147).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker no está disponible en este entorno"
)

_TEST_ENV = textwrap.dedent(
    """\
    DB_PASSWORD=testpassword1234
    JWT_SECRET_CURRENT=0123456789abcdef0123456789abcdef
    JWT_SECRET_PREVIOUS=
    ADMIN_USERNAME=admin
    ADMIN_PASSWORD=AdminPassword123!
    CA_CERT_PATH=/certs/ca.pem
    CA_KEY_PATH=/certs/ca-key.pem
    BACKEND_CERT_PATH=/certs/backend.pem
    BACKEND_KEY_PATH=/certs/backend-key.pem
    CORS_ALLOWED_ORIGINS=http://localhost
    FIM_PUBLIC_HOSTS=203.0.113.10
    CONSOLE_TLS_MODE=self_signed
    N8N_WEBHOOK_URL=
    N8N_HEALTH_URL=
    SMTP_HOST=
    SMTP_PORT=587
    SMTP_USER=
    SMTP_PASSWORD=
    SMTP_FROM=
    SMTP_TO=
    SMTP_STARTTLS=true
    SMTP_SSL=false
    WEBHOOK_FALLBACK_URL=
    N8N_ENCRYPTION_KEY=test-n8n-encryption-key-0123456789
    N8N_INSTANCE_OWNER_EMAIL=owner@example.org
    N8N_INSTANCE_OWNER_FIRST_NAME=Owner
    N8N_INSTANCE_OWNER_LAST_NAME=Test
    N8N_INSTANCE_OWNER_PASSWORD_HASH=$$2a$$10$$abcdefghijklmnopqrstuv
    N8N_FIM_CHANNELS=
    """
)


def _render(tmp_path: Path, *, profiles: list[str]) -> dict:
    env_file = tmp_path / "test.env"
    env_file.write_text(_TEST_ENV)
    cmd = ["docker", "compose", "--env-file", str(env_file),
           "-f", "docker-compose.yml", "-f", "docker-compose.tls.yml"]
    for profile in profiles:
        cmd += ["--profile", profile]
    cmd += ["config", "--format", "json"]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def rendered_app(tmp_path_factory) -> dict:
    return _render(tmp_path_factory.mktemp("compose-app"), profiles=["app"])


@pytest.fixture(scope="module")
def rendered_app_lab(tmp_path_factory) -> dict:
    return _render(tmp_path_factory.mktemp("compose-app-lab"), profiles=["app", "lab"])


def _published_ports(service: dict) -> set[str]:
    return {str(p["published"]) for p in service.get("ports", [])}


def test_puertos_publicados_exactos(rendered_app) -> None:
    """8000 se publica (sólo en 127.0.0.1, verificado aparte) — la spec lo
    excluye del conjunto de puertos "publicados" en el sentido de alcanzables
    desde otro host, no de la lista cruda de mappings."""
    services = rendered_app["services"]
    all_published: set[str] = set()
    for name in ("backend", "frontend", "valkey"):
        all_published |= _published_ports(services[name])
    assert all_published == {"80", "443", "8443", "8444", "6380", "8000"}


def test_puerto_8000_solo_en_loopback(rendered_app) -> None:
    backend_ports = rendered_app["services"]["backend"]["ports"]
    port_8000 = [p for p in backend_ports if str(p["published"]) == "8000"]
    assert len(port_8000) == 1
    assert port_8000[0].get("host_ip") == "127.0.0.1"


def test_sin_puertos_internos_publicados(rendered_app) -> None:
    services = rendered_app["services"]
    all_published: set[str] = set()
    for svc in services.values():
        all_published |= _published_ports(svc)
    assert "5432" not in all_published
    assert "6379" not in all_published
    assert "5678" not in all_published


def test_agent_ausente_con_perfil_app(rendered_app) -> None:
    assert "agent" not in rendered_app["services"]


def test_agent_presente_con_perfil_app_y_lab(rendered_app_lab) -> None:
    assert "agent" in rendered_app_lab["services"]


def test_certs_init_presente(rendered_app) -> None:
    assert "certs-init" in rendered_app["services"]


def test_parametros_tls_del_valkey_url(rendered_app) -> None:
    valkey_url = rendered_app["services"]["backend"]["environment"]["VALKEY_URL"]
    assert valkey_url.startswith("valkeys://valkey:6380")
    assert "ssl_certfile=/certs/backend-valkey.pem" in valkey_url
    assert "ssl_keyfile=/certs/backend-valkey-key.pem" in valkey_url
    assert "ssl_ca_certs=/certs/ca.pem" in valkey_url
    assert "ssl_check_hostname=true" in valkey_url


def test_mismo_console_tls_mode_en_frontend_y_backend(rendered_app) -> None:
    services = rendered_app["services"]
    assert services["frontend"]["environment"]["CONSOLE_TLS_MODE"] == "self_signed"
    assert services["backend"]["environment"]["CONSOLE_TLS_MODE"] == "self_signed"


def test_backend_single_instance(rendered_app) -> None:
    assert rendered_app["services"]["backend"]["deploy"]["replicas"] == 1
