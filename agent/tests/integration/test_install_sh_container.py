"""Container integration test for agent/install.sh (D56/RN-150, design D-7 of
`vps-deployment-readiness`, task 9.8).

Runs the real `install.sh` as root inside a throwaway Docker container, with
`systemctl` replaced by a shim (`agent/tests/integration/docker/systemctl`)
that logs its invocations and tracks a trivial per-unit "active" state — no
real systemd, and nothing here ever touches this host's own /opt, /etc or
systemd. A pair of local `openssl s_server` processes bound to 127.0.0.1
inside the container stand in for the backend's 8444 and 6380 listeners, so
the network scope check (D-7 step 9) exercises a real TLS handshake.

Every test gets its own fresh container (function-scoped fixture): install.sh
is genuinely re-run against the SAME container across the mutating steps of
each scenario (idempotency, reconfigure, code replacement), but state never
leaks between scenarios.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_SRC = REPO_ROOT / "agent"
DOCKER_DIR = Path(__file__).parent / "docker"
IMAGE_TAG = "fim-c52-installer-test:latest"
SHIM_LOG = "/var/log/fim-systemctl-shim.log"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available"),
    # Each test provisions a fresh container (venv creation, two pip installs,
    # a from-scratch CA) and some run install.sh more than once — well above
    # the suite-wide 60s default (agent/pyproject.toml).
    pytest.mark.timeout(240),
]


def _docker(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def _exec(name: str, script: str, *, workdir: str = "/workspace", timeout: float = 60.0) -> subprocess.CompletedProcess:
    return _docker("exec", "-w", workdir, name, "bash", "-c", script, timeout=timeout)


@pytest.fixture(scope="module")
def installer_image() -> str:
    result = _docker("build", "-t", IMAGE_TAG, str(DOCKER_DIR), timeout=180.0)
    assert result.returncode == 0, result.stdout + result.stderr
    yield IMAGE_TAG
    _docker("rmi", IMAGE_TAG)


@pytest.fixture()
def container(installer_image: str):
    name = f"fim-c52-inst-{int(time.time() * 1000)}"
    result = _docker(
        "run", "-d", "--name", name, "-v", f"{AGENT_SRC}:/repo-agent:ro", installer_image
    )
    assert result.returncode == 0, result.stdout + result.stderr
    try:
        yield name
    finally:
        _docker("rm", "-f", name)


# Fixed compute of the fingerprint from inside the container avoids requiring
# `cryptography` on the host running pytest for this one integration test.
_FINGERPRINT_SNIPPET = (
    "python3 -c \""
    "import hashlib; from cryptography import x509; "
    "from cryptography.hazmat.primitives.serialization import Encoding; "
    "cert = x509.load_pem_x509_certificate(open('/workspace/certs/ca.pem','rb').read()); "
    "print(hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest())\""
)


def _provision(name: str, *, start_servers: bool = True) -> None:
    """Copies a writable agent source tree, generates a CA + server
    certificate for 127.0.0.1, a bootstrap secret file and a watch directory,
    and — unless `start_servers` is False — starts the two local TLS servers
    the scope check (8444, 6380) is expected to reach."""
    setup = f"""
set -e
pip install --quiet cryptography
mkdir -p /workspace/agent-src /workspace/certs /workspace/watched
cp -r /repo-agent/. /workspace/agent-src/
cd /workspace/certs
openssl ecparam -name prime256v1 -genkey -noout -out ca-key.pem
openssl req -x509 -new -key ca-key.pem -days 365 -out ca.pem -subj "/CN=test-ca" \
    -addext "basicConstraints=critical,CA:true"
openssl ecparam -name prime256v1 -genkey -noout -out server-key.pem
openssl req -new -key server-key.pem -out server.csr -subj "/CN=fim-server"
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -days 365 \
    -out server.pem -extfile <(echo "subjectAltName=IP:127.0.0.1")
echo "0123456789abcdef0123" > /workspace/secret
chmod 600 /workspace/secret
"""
    result = _exec(name, setup, timeout=120.0)
    assert result.returncode == 0, result.stdout + result.stderr

    if start_servers:
        start = """
set -e
cd /workspace/certs
nohup openssl s_server -accept 8444 -cert server.pem -key server-key.pem \
    -naccept 100 -quiet >/tmp/s8444.log 2>&1 &
nohup openssl s_server -accept 6380 -cert server.pem -key server-key.pem \
    -CAfile ca.pem -Verify 1 -naccept 100 -quiet >/tmp/s6380.log 2>&1 &
sleep 0.5
"""
        result = _exec(name, start)
        assert result.returncode == 0, result.stdout + result.stderr


def _fingerprint(name: str) -> str:
    result = _exec(name, _FINGERPRINT_SNIPPET)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _install_argv(fingerprint: str, *, agent_id: str = "test-agent-01", reconfigure: bool = False) -> str:
    extra = " --reconfigure" if reconfigure else ""
    return (
        "bash /workspace/agent-src/install.sh --non-interactive "
        "--server-host 127.0.0.1 "
        f"--agent-id {agent_id} "
        "--watch-path /workspace/watched "
        "--ca-cert /workspace/certs/ca.pem "
        f"--ca-fingerprint {fingerprint} "
        "--bootstrap-secret-file /workspace/secret"
        f"{extra}"
    )


def _run_install(name: str, fingerprint: str, **kwargs: object) -> subprocess.CompletedProcess:
    return _exec(name, _install_argv(fingerprint, **kwargs), timeout=120.0)  # type: ignore[arg-type]


# ── Scenarios ──────────────────────────────────────────────────────────────────


def test_clean_install(container: str) -> None:
    _provision(container)
    fingerprint = _fingerprint(container)

    result = _run_install(container, fingerprint)
    assert result.returncode == 0, result.stdout + result.stderr

    config = _exec(container, "cat /etc/fim-agent/config.yaml")
    assert "agent_id: test-agent-01" in config.stdout
    assert "backend_url: https://127.0.0.1:8444" in config.stdout
    assert "valkey_url: valkeys://127.0.0.1:6380" in config.stdout
    assert "watch_paths:\n  - /workspace/watched" in config.stdout

    env = _exec(container, "cat /etc/fim-agent/env")
    assert "FIM_BOOTSTRAP_SECRET=0123456789abcdef0123" in env.stdout

    nested = _exec(container, "test -e /opt/fim-agent/agent/agent && echo present || echo absent")
    assert nested.stdout.strip() == "absent"

    shim_log = _exec(container, f"cat {SHIM_LOG}")
    assert "systemctl enable fim-agent" in shim_log.stdout
    assert "systemctl start fim-agent" in shim_log.stdout


def test_secret_never_leaks_to_logs_or_output(container: str) -> None:
    _provision(container)
    fingerprint = _fingerprint(container)
    secret = "0123456789abcdef0123"

    result = _run_install(container, fingerprint)
    assert result.returncode == 0
    assert secret not in result.stdout
    assert secret not in result.stderr

    leaked = _exec(
        container,
        f"grep -rl {secret} /var/log /etc/fim-agent 2>/dev/null | grep -v '^/etc/fim-agent/env$' || true",
    )
    assert leaked.stdout.strip() == ""


def test_rerun_without_reconfigure_is_byte_identical_and_restarts(container: str) -> None:
    _provision(container)
    fingerprint = _fingerprint(container)

    assert _run_install(container, fingerprint).returncode == 0
    before = _exec(container, "md5sum /etc/fim-agent/config.yaml /etc/fim-agent/env")

    result = _run_install(container, fingerprint)
    assert result.returncode == 0
    after = _exec(container, "md5sum /etc/fim-agent/config.yaml /etc/fim-agent/env")
    assert before.stdout == after.stdout

    shim_log = _exec(container, f"cat {SHIM_LOG}")
    assert "systemctl restart fim-agent" in shim_log.stdout


def test_reconfigure_replaces_config_and_backs_up(container: str) -> None:
    _provision(container)
    fingerprint = _fingerprint(container)

    assert _run_install(container, fingerprint).returncode == 0
    result = _run_install(container, fingerprint, agent_id="web-02", reconfigure=True)
    assert result.returncode == 0, result.stdout + result.stderr

    config = _exec(container, "cat /etc/fim-agent/config.yaml")
    assert "agent_id: web-02" in config.stdout

    backups = _exec(container, "ls /etc/fim-agent/config.yaml.bak-* 2>/dev/null | wc -l")
    assert backups.stdout.strip() == "1"


def test_code_update_replaces_and_removes_stale_files(container: str) -> None:
    _provision(container)
    fingerprint = _fingerprint(container)
    assert _run_install(container, fingerprint).returncode == 0

    _exec(container, "echo '# marker' >> /workspace/agent-src/config.py")
    _exec(container, "echo 'stale' > /workspace/agent-src/stale_module.py")
    assert _run_install(container, fingerprint).returncode == 0

    present = _exec(container, "test -e /opt/fim-agent/agent/stale_module.py && echo yes || echo no")
    assert present.stdout.strip() == "yes"

    _exec(container, "rm /workspace/agent-src/stale_module.py")
    assert _run_install(container, fingerprint).returncode == 0

    removed = _exec(container, "test -e /opt/fim-agent/agent/stale_module.py && echo yes || echo no")
    assert removed.stdout.strip() == "no"

    diff = _exec(container, "diff /workspace/agent-src/config.py /opt/fim-agent/agent/config.py")
    assert diff.returncode == 0

    leftovers = _exec(
        container,
        "test -e /opt/fim-agent/agent.previous -o -e /opt/fim-agent/agent.staging && echo yes || echo no",
    )
    assert leftovers.stdout.strip() == "no"


def test_bootstrap_secret_flag_rejected(container: str) -> None:
    _provision(container, start_servers=False)
    result = _exec(
        container,
        "bash /workspace/agent-src/install.sh --non-interactive "
        "--server-host 127.0.0.1 --agent-id reject-test --watch-path /workspace/watched "
        "--ca-cert /workspace/certs/ca.pem --ca-fingerprint deadbeef "
        "--bootstrap-secret 0123456789abcdef",
    )
    assert result.returncode != 0
    assert "0123456789abcdef" not in result.stdout
    assert "0123456789abcdef" not in result.stderr
    assert "never accepted as a command-line argument" in (result.stdout + result.stderr)

    config_exists = _exec(container, "test -f /etc/fim-agent/config.yaml && echo yes || echo no")
    assert config_exists.stdout.strip() == "no"


def test_relative_ca_cert_and_secret_paths_resolved_from_invocation_dir(container: str) -> None:
    """14.2: --ca-cert and --bootstrap-secret-file given as RELATIVE paths
    must resolve against the directory install.sh was invoked from
    (/workspace here), not against /opt/fim-agent — install.sh `cd`s there
    for the apply/check phases (D-7 steps 6/9) before this fix."""
    _provision(container)
    fingerprint = _fingerprint(container)

    result = _exec(
        container,
        "bash /workspace/agent-src/install.sh --non-interactive "
        "--server-host 127.0.0.1 --agent-id rel-path-test --watch-path /workspace/watched "
        "--ca-cert certs/ca.pem "
        f"--ca-fingerprint {fingerprint} "
        "--bootstrap-secret-file secret",
        timeout=120.0,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    env = _exec(container, "cat /etc/fim-agent/env")
    assert "FIM_BOOTSTRAP_SECRET=0123456789abcdef0123" in env.stdout


def test_wrong_python_version_aborts_before_venv_created(container: str) -> None:
    """14.1: a Python interpreter that is not exactly 3.13 aborts install.sh
    BEFORE creating the venv, naming both the found and required versions."""
    _provision(container, start_servers=False)
    fake = """
cat > /usr/local/bin/fake-python-314 <<'PYEOF'
#!/bin/sh
if [ "$1" = "-c" ]; then
  echo "3.14"
  exit 0
fi
exit 1
PYEOF
chmod +x /usr/local/bin/fake-python-314
"""
    setup = _exec(container, fake)
    assert setup.returncode == 0, setup.stdout + setup.stderr

    result = _exec(
        container,
        "bash /workspace/agent-src/install.sh --non-interactive "
        "--python /usr/local/bin/fake-python-314 "
        "--server-host 127.0.0.1 --agent-id ver-test --watch-path /workspace/watched "
        "--ca-cert /workspace/certs/ca.pem --ca-fingerprint deadbeef "
        "--bootstrap-secret-file /workspace/secret",
    )
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "3.14" in output
    assert "3.13" in output

    venv_exists = _exec(container, "test -d /opt/fim-agent/venv && echo yes || echo no")
    assert venv_exists.stdout.strip() == "no"


def test_python_flag_selects_venv_interpreter(container: str) -> None:
    """14.1: `--python <path>` overrides the default `python3` used to
    create the venv — verified via pyvenv.cfg's `home` entry."""
    _provision(container)
    fingerprint = _fingerprint(container)
    python_path = _exec(container, "command -v python3").stdout.strip()
    assert python_path

    result = _exec(
        container,
        "bash /workspace/agent-src/install.sh --non-interactive "
        f"--python {python_path} "
        "--server-host 127.0.0.1 --agent-id py-flag-test --watch-path /workspace/watched "
        "--ca-cert /workspace/certs/ca.pem "
        f"--ca-fingerprint {fingerprint} "
        "--bootstrap-secret-file /workspace/secret",
        timeout=120.0,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    cfg = _exec(container, "cat /opt/fim-agent/venv/pyvenv.cfg")
    python_dir = python_path.rsplit("/", 1)[0]
    assert python_dir in cfg.stdout


def test_reinstall_enrolled_agent_does_not_require_secret(container: str) -> None:
    """14.3: reinstalling a host whose own agent certificate is already
    present (a completed enrollment) does not require
    --bootstrap-secret-file in --non-interactive mode, as long as
    --reconfigure is not passed."""
    _provision(container)
    fingerprint = _fingerprint(container)
    assert _run_install(container, fingerprint).returncode == 0

    # Simulate a completed enrollment: write a valid, unexpired self-signed
    # certificate at the path the agent writes its own cert to after a real
    # bootstrap (agent/bootstrap.py's is_bootstrapped()).
    fake_cert = """
set -e
mkdir -p /var/lib/fim-agent/certs
openssl ecparam -name prime256v1 -genkey -noout -out /tmp/agent-key.pem
openssl req -x509 -new -key /tmp/agent-key.pem -days 365 \
    -out /var/lib/fim-agent/certs/agent-cert.pem -subj "/CN=test-agent-01"
"""
    setup = _exec(container, fake_cert)
    assert setup.returncode == 0, setup.stdout + setup.stderr

    result = _exec(
        container,
        "bash /workspace/agent-src/install.sh --non-interactive "
        "--server-host 127.0.0.1 --agent-id test-agent-01 --watch-path /workspace/watched "
        "--ca-cert /workspace/certs/ca.pem "
        f"--ca-fingerprint {fingerprint}",
        timeout=120.0,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_scope_check_failure_blocks_enable_and_exits_3(container: str) -> None:
    _provision(container, start_servers=False)  # nothing listens on 8444/6380
    fingerprint = _fingerprint(container)

    result = _run_install(container, fingerprint)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "Scope check failed" in (result.stdout + result.stderr)

    shim_log = _exec(container, f"cat {SHIM_LOG}")
    assert "systemctl enable fim-agent" not in shim_log.stdout
    assert "systemctl start fim-agent" not in shim_log.stdout
