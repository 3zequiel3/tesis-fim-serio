"""
D55/RN-149, D60/RN-154 — modos TLS de la consola (`frontend/docker-entrypoint.d/
40-fim-console-tls.sh`), change 52, grupo 5.

Todos los tests están marcados `integration`: construyen la imagen real del
frontend y corren contenedores reales de Docker.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_TAG = "fim-frontend:c52-console-tls-test"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker no disponible"),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def frontend_image():
    subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "-f", "frontend/Dockerfile", "frontend"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    yield IMAGE_TAG
    subprocess.run(["docker", "rmi", IMAGE_TAG], capture_output=True)


@pytest.fixture()
def container_name():
    name = f"fim-c52-consoletls-{int(time.time() * 1000)}"
    yield name
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def _run(image: str, name: str, *, env: dict[str, str], volumes: list[tuple[str, str]],
          ports: list[tuple[int, int]], detach: bool) -> subprocess.CompletedProcess:
    cmd = ["docker", "run", "--rm"]
    if detach:
        cmd.append("-d")
    cmd += ["--name", name, "--add-host", "backend:127.0.0.1"]
    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]
    for host_path, container_path in volumes:
        cmd += ["-v", f"{host_path}:{container_path}:ro"]
    for host_port, container_port in ports:
        cmd += ["-p", f"{host_port}:{container_port}"]
    cmd.append(image)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _wait_http(port: int, *, scheme: str = "http", timeout: float = 10.0) -> None:
    import urllib.request
    import ssl

    ctx = ssl._create_unverified_context() if scheme == "https" else None
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{scheme}://127.0.0.1:{port}/", timeout=1, context=ctx)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(0.3)
    raise TimeoutError(f"server on port {port} never became ready: {last_exc}")


@pytest.fixture(scope="module")
def self_signed_certs(tmp_path_factory):
    d = tmp_path_factory.mktemp("self-signed")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ed25519", "-keyout", str(d / "console-key.pem"),
         "-out", str(d / "console.pem"), "-days", "1", "-nodes", "-subj", "/CN=test"],
        check=True, capture_output=True,
    )
    return d


@pytest.fixture(scope="module")
def provided_letsencrypt_style(tmp_path_factory):
    d = tmp_path_factory.mktemp("provided")
    archive = d / "archive" / "example.org"
    live = d / "live" / "example.org"
    archive.mkdir(parents=True)
    live.mkdir(parents=True)
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ed25519",
         "-keyout", str(archive / "privkey1.pem"), "-out", str(archive / "fullchain1.pem"),
         "-days", "1", "-nodes", "-subj", "/CN=example.org"],
        check=True, capture_output=True,
    )
    (live / "fullchain.pem").symlink_to("../../archive/example.org/fullchain1.pem")
    (live / "privkey.pem").symlink_to("../../archive/example.org/privkey1.pem")
    return d


# ── nginx -t por modo ──────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["off", "self_signed", "provided"])
def test_nginx_dash_t_por_modo(frontend_image, container_name, self_signed_certs,
                                 provided_letsencrypt_style, mode) -> None:
    volumes = []
    env = {"CONSOLE_TLS_MODE": mode}
    if mode == "self_signed":
        volumes = [(str(self_signed_certs), "/run/fim-console-tls/self-signed")]
    elif mode == "provided":
        volumes = [(str(provided_letsencrypt_style), "/run/fim-console-tls/provided")]
        env["CONSOLE_TLS_CERT_FILE"] = "live/example.org/fullchain.pem"
        env["CONSOLE_TLS_KEY_FILE"] = "live/example.org/privkey.pem"

    cmd = ["docker", "run", "--rm", "--add-host", "backend:127.0.0.1",
           "--entrypoint", "sh"]
    for key, value in env.items():
        cmd += ["-e", f"{key}={value}"]
    for host_path, container_path in volumes:
        cmd += ["-v", f"{host_path}:{container_path}:ro"]
    cmd += [frontend_image, "-c",
            "/docker-entrypoint.d/40-fim-console-tls.sh && nginx -t"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "syntax is ok" in result.stderr
    assert "test is successful" in result.stderr


# ── off ──────────────────────────────────────────────────────────────────


def test_modo_off_200_sin_hsts_con_headers(frontend_image, container_name) -> None:
    port = _free_port()
    result = _run(frontend_image, container_name, env={"CONSOLE_TLS_MODE": "off"},
                  volumes=[], ports=[(port, 80)], detach=True)
    assert result.returncode == 0, result.stderr
    _wait_http(port)

    import urllib.request

    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)
    assert resp.status == 200
    headers = resp.headers
    assert "Strict-Transport-Security" not in headers
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" in headers


# ── self_signed ────────────────────────────────────────────────────────────


def test_modo_self_signed_redirect_301_preserva_path_y_query(
    frontend_image, container_name, self_signed_certs
) -> None:
    http_port, https_port = _free_port(), _free_port()
    result = _run(
        frontend_image, container_name,
        env={"CONSOLE_TLS_MODE": "self_signed"},
        volumes=[(str(self_signed_certs), "/run/fim-console-tls/self-signed")],
        ports=[(http_port, 80), (https_port, 443)],
        detach=True,
    )
    assert result.returncode == 0, result.stderr
    _wait_http(https_port, scheme="https")

    import urllib.error
    import urllib.request

    # Do NOT let urllib auto-follow the redirect: nginx's Location header is
    # `https://$host$request_uri` (no port — correct for a real deployment,
    # where the console listens on the standard 443), but this test remaps
    # the container's 443 to an ephemeral host port, so following it would
    # try to connect to the real port 443 on the test host and fail. We only
    # need to assert the redirect response itself.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(f"http://127.0.0.1:{http_port}/events?x=1")
    try:
        opener.open(req, timeout=5)
        pytest.fail("expected an HTTPError(301)")
    except urllib.error.HTTPError as exc:
        assert exc.code == 301
        location = exc.headers["Location"]
        assert location.endswith("/events?x=1")
        assert location.startswith("https://")


def test_modo_self_signed_hsts_max_age_300_sin_include_subdomains(
    frontend_image, container_name, self_signed_certs
) -> None:
    https_port = _free_port()
    result = _run(
        frontend_image, container_name,
        env={"CONSOLE_TLS_MODE": "self_signed"},
        volumes=[(str(self_signed_certs), "/run/fim-console-tls/self-signed")],
        ports=[(https_port, 443)],
        detach=True,
    )
    assert result.returncode == 0, result.stderr
    _wait_http(https_port, scheme="https")

    import ssl
    import urllib.request

    ctx = ssl._create_unverified_context()
    resp = urllib.request.urlopen(f"https://127.0.0.1:{https_port}/", timeout=5, context=ctx)
    hsts = resp.headers["Strict-Transport-Security"]
    assert hsts == "max-age=300"
    assert "includeSubDomains" not in hsts


# ── provided ───────────────────────────────────────────────────────────────


def test_modo_provided_hsts_largo_con_include_subdomains_y_symlinks(
    frontend_image, container_name, provided_letsencrypt_style
) -> None:
    https_port = _free_port()
    result = _run(
        frontend_image, container_name,
        env={
            "CONSOLE_TLS_MODE": "provided",
            "CONSOLE_TLS_CERT_FILE": "live/example.org/fullchain.pem",
            "CONSOLE_TLS_KEY_FILE": "live/example.org/privkey.pem",
        },
        volumes=[(str(provided_letsencrypt_style), "/run/fim-console-tls/provided")],
        ports=[(https_port, 443)],
        detach=True,
    )
    assert result.returncode == 0, result.stderr
    _wait_http(https_port, scheme="https")

    import ssl
    import urllib.request

    ctx = ssl._create_unverified_context()
    resp = urllib.request.urlopen(f"https://127.0.0.1:{https_port}/", timeout=5, context=ctx)
    hsts = resp.headers["Strict-Transport-Security"]
    assert hsts == "max-age=63072000; includeSubDomains"


# ── Fallos ─────────────────────────────────────────────────────────────────


def test_certificado_faltante_exit_distinto_de_cero_nombrando_archivo(
    frontend_image, container_name
) -> None:
    result = _run(frontend_image, container_name, env={"CONSOLE_TLS_MODE": "self_signed"},
                  volumes=[], ports=[], detach=False)
    assert result.returncode != 0
    assert "console.pem" in result.stderr


def test_modo_desconocido_exit_distinto_de_cero(frontend_image, container_name) -> None:
    result = _run(frontend_image, container_name, env={"CONSOLE_TLS_MODE": "bogus"},
                  volumes=[], ports=[], detach=False)
    assert result.returncode != 0
    assert "bogus" in result.stderr
