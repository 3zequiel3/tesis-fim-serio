"""Tests for agent/installer.py (D56/RN-150, design D-7).

Pure-Python and root-free: TLS servers used for the scope-check tests bind to
127.0.0.1 on ephemeral ports and use certificates generated on the fly with
`cryptography` — nothing here touches `/etc/fim-agent` or systemd (that is
covered by the container integration test,
agent/tests/integration/test_install_sh_container.py).
"""

from __future__ import annotations

import argparse
import datetime
import socket
import ssl
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from agent.installer import (
    InstallerError,
    _build_arg_parser,
    _get_value,
    apply_config,
    bracket_host,
    check_port,
    compute_fingerprint,
    derive_urls,
    is_already_enrolled,
    load_and_verify_ca,
    main,
    normalize_fingerprint,
    reject_secret_argument,
    render_config_yaml,
    resolve_bootstrap_secret,
    run_scope_check,
    secret_required,
    validate_watch_paths,
)

CONFIG_EXAMPLE = Path(__file__).parent.parent / "deploy" / "config.yaml.example"


# ── Certificate helpers ───────────────────────────────────────────────────────


def _make_ca(common_name: str = "test-ca") -> tuple[x509.Certificate, "ec.EllipticCurvePrivateKey"]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert, key


def _make_leaf(
    ca_cert: x509.Certificate,
    ca_key: "ec.EllipticCurvePrivateKey",
    *,
    common_name: str,
    san_dns: list[str] | None = None,
    san_ip: list[str] | None = None,
    is_ca: bool = False,
) -> tuple[x509.Certificate, "ec.EllipticCurvePrivateKey"]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    if san_dns or san_ip:
        import ipaddress as ip_mod

        names: list[x509.GeneralName] = [x509.DNSName(d) for d in (san_dns or [])]
        names.extend(x509.IPAddress(ip_mod.ip_address(i)) for i in (san_ip or []))
        builder = builder.add_extension(x509.SubjectAlternativeName(names), critical=False)
    cert = builder.sign(ca_key, hashes.SHA256())
    return cert, key


def _write_pem(path: Path, cert: x509.Certificate) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _key_pem(key: "ec.EllipticCurvePrivateKey") -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


# ── _get_value precedence ─────────────────────────────────────────────────────


def test_get_value_flag_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIM_SERVER_HOST", "from-env")
    assert _get_value("from-flag", "FIM_SERVER_HOST", "Server host", True) == "from-flag"


def test_get_value_env_wins_over_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIM_SERVER_HOST", "from-env")
    assert _get_value(None, "FIM_SERVER_HOST", "Server host", False) == "from-env"


def test_get_value_falls_back_to_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIM_SERVER_HOST", raising=False)
    monkeypatch.setattr("builtins.input", lambda _: "from-prompt")
    assert _get_value(None, "FIM_SERVER_HOST", "Server host", False) == "from-prompt"


def test_get_value_missing_non_interactive_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIM_SERVER_HOST", raising=False)
    with pytest.raises(InstallerError, match="Server host"):
        _get_value(None, "FIM_SERVER_HOST", "Server host", True)


# ── Derived URLs ───────────────────────────────────────────────────────────────


def test_derive_urls_ipv4() -> None:
    backend, mtls, valkey = derive_urls("203.0.113.10")
    assert backend == "https://203.0.113.10:8444"
    assert mtls == "https://203.0.113.10:8443"
    assert valkey == "valkeys://203.0.113.10:6380"


def test_derive_urls_dns_name() -> None:
    backend, mtls, valkey = derive_urls("fim.example.org")
    assert backend == "https://fim.example.org:8444"
    assert mtls == "https://fim.example.org:8443"
    assert valkey == "valkeys://fim.example.org:6380"


def test_derive_urls_ipv6_is_bracketed() -> None:
    backend, mtls, valkey = derive_urls("2001:db8::1")
    assert backend == "https://[2001:db8::1]:8444"
    assert mtls == "https://[2001:db8::1]:8443"
    assert valkey == "valkeys://[2001:db8::1]:6380"


def test_bracket_host_leaves_dns_and_ipv4_unbracketed() -> None:
    assert bracket_host("example.org") == "example.org"
    assert bracket_host("10.0.0.1") == "10.0.0.1"


# ── Watch path validation ─────────────────────────────────────────────────────


def test_watch_path_relative_rejected() -> None:
    with pytest.raises(InstallerError, match="absolute"):
        validate_watch_paths(["relative/path"])


def test_watch_path_nonexistent_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    with pytest.raises(InstallerError, match="does not exist"):
        validate_watch_paths([str(missing)])


def test_watch_path_valid_absolute_existing(tmp_path: Path) -> None:
    target = tmp_path / "watched"
    target.mkdir()
    assert validate_watch_paths([str(target)]) == [str(target)]


def test_watch_path_empty_list_rejected() -> None:
    with pytest.raises(InstallerError, match="at least one watch path"):
        validate_watch_paths([])


def test_watch_path_rejects_newline_via_deployment_check(tmp_path: Path) -> None:
    # agent.deployment._validate_path rejects a newline; os.path.exists()
    # would never see a path like this in practice, but the check must run
    # regardless of what a directly-called validate_watch_paths receives.
    bad = str(tmp_path) + "\nBadDirective"
    with pytest.raises(InstallerError):
        validate_watch_paths([bad])


# ── Secret handling ────────────────────────────────────────────────────────────


def test_reject_secret_argument_bare_flag() -> None:
    with pytest.raises(InstallerError, match="never accepted"):
        reject_secret_argument(["apply", "--bootstrap-secret", "0123456789abcdef"])


def test_reject_secret_argument_equals_form() -> None:
    with pytest.raises(InstallerError, match="never accepted"):
        reject_secret_argument(["apply", "--bootstrap-secret=0123456789abcdef"])


def test_reject_secret_argument_allows_file_flag() -> None:
    reject_secret_argument(["apply", "--bootstrap-secret-file", "/tmp/secret"])  # no raise


def test_resolve_bootstrap_secret_from_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("0123456789abcdef\n")
    assert resolve_bootstrap_secret(str(secret_file), non_interactive=True) == "0123456789abcdef"


def test_resolve_bootstrap_secret_too_short(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("short")
    with pytest.raises(InstallerError, match="16 characters"):
        resolve_bootstrap_secret(str(secret_file), non_interactive=True)


def test_resolve_bootstrap_secret_missing_non_interactive() -> None:
    with pytest.raises(InstallerError, match="bootstrap secret"):
        resolve_bootstrap_secret(None, non_interactive=True)


def test_resolve_bootstrap_secret_interactive_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda _: "0123456789abcdef")
    assert resolve_bootstrap_secret(None, non_interactive=False) == "0123456789abcdef"


# ── Reinstall of an enrolled agent skips the bootstrap secret (14.3) ─────────


def _write_fake_agent_cert(path: Path, *, expired: bool = False) -> None:
    """Writes a self-signed certificate at `path` — good enough for
    `is_bootstrapped`, which only checks existence and expiry, never CA-ness
    or a trust chain."""
    cert, key = _make_ca(common_name="test-agent-01")
    if expired:
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(cert.subject)
            .issuer_name(cert.issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=10))
            .not_valid_after(now - datetime.timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_pem(path, cert)


def test_is_already_enrolled_false_without_cert(tmp_path: Path) -> None:
    assert is_already_enrolled(str(tmp_path / "agent-cert.pem")) is False


def test_is_already_enrolled_true_with_valid_cert(tmp_path: Path) -> None:
    cert_path = tmp_path / "certs" / "agent-cert.pem"
    _write_fake_agent_cert(cert_path)
    assert is_already_enrolled(str(cert_path)) is True


def test_is_already_enrolled_false_with_expired_cert(tmp_path: Path) -> None:
    cert_path = tmp_path / "certs" / "agent-cert.pem"
    _write_fake_agent_cert(cert_path, expired=True)
    assert is_already_enrolled(str(cert_path)) is False


def _namespace(*, reconfigure: bool, agent_cert_path: str) -> argparse.Namespace:
    return _build_arg_parser().parse_args(
        ["plan", "--agent-cert-path", agent_cert_path]
        + (["--reconfigure"] if reconfigure else [])
    )


def test_secret_required_true_on_first_install(tmp_path: Path) -> None:
    args = _namespace(reconfigure=False, agent_cert_path=str(tmp_path / "agent-cert.pem"))
    assert secret_required(args) is True


def test_secret_required_false_on_reinstall_of_enrolled_agent(tmp_path: Path) -> None:
    cert_path = tmp_path / "agent-cert.pem"
    _write_fake_agent_cert(cert_path)
    args = _namespace(reconfigure=False, agent_cert_path=str(cert_path))
    assert secret_required(args) is False


def test_secret_required_true_with_reconfigure_even_if_enrolled(tmp_path: Path) -> None:
    cert_path = tmp_path / "agent-cert.pem"
    _write_fake_agent_cert(cert_path)
    args = _namespace(reconfigure=True, agent_cert_path=str(cert_path))
    assert secret_required(args) is True


def test_apply_reinstall_enrolled_agent_without_secret_succeeds(tmp_path: Path) -> None:
    """End-to-end: `apply` on a host with an existing valid agent certificate
    and no --reconfigure succeeds in --non-interactive mode without
    --bootstrap-secret-file, and does not touch the existing env file."""
    ca_cert, _ = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    fingerprint = compute_fingerprint(ca_cert)
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    agent_cert_path = tmp_path / "certs" / "agent-cert.pem"
    env_dest = tmp_path / "env"

    # First install: writes env with the secret, as usual.
    secret_file = tmp_path / "secret"
    secret_file.write_text("0123456789abcdef")
    first_argv = [
        "apply",
        "--non-interactive",
        "--server-host",
        "203.0.113.10",
        "--agent-id",
        "web-01",
        "--watch-path",
        str(watch_dir),
        "--ca-cert",
        str(ca_path),
        "--ca-fingerprint",
        fingerprint,
        "--bootstrap-secret-file",
        str(secret_file),
        "--config-dest",
        str(tmp_path / "config.yaml"),
        "--env-dest",
        str(env_dest),
        "--ca-cert-dest",
        str(tmp_path / "ca-installed.pem"),
        "--config-example",
        str(CONFIG_EXAMPLE),
        "--agent-cert-path",
        str(agent_cert_path),
    ]
    assert main(first_argv) == 0
    env_before = env_dest.read_bytes()

    # Simulate a completed bootstrap: the agent wrote its own certificate.
    _write_fake_agent_cert(agent_cert_path)

    # Reinstall WITHOUT --bootstrap-secret-file and WITHOUT --reconfigure.
    reinstall_argv = [
        "apply",
        "--non-interactive",
        "--server-host",
        "203.0.113.10",
        "--agent-id",
        "web-01",
        "--watch-path",
        str(watch_dir),
        "--ca-cert",
        str(ca_path),
        "--ca-fingerprint",
        fingerprint,
        "--config-dest",
        str(tmp_path / "config.yaml"),
        "--env-dest",
        str(env_dest),
        "--ca-cert-dest",
        str(tmp_path / "ca-installed.pem"),
        "--config-example",
        str(CONFIG_EXAMPLE),
        "--agent-cert-path",
        str(agent_cert_path),
    ]
    assert main(reinstall_argv) == 0
    assert env_dest.read_bytes() == env_before


def test_plan_first_install_without_secret_fails(tmp_path: Path) -> None:
    ca_cert, _ = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    fingerprint = compute_fingerprint(ca_cert)
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()

    argv = [
        "plan",
        "--non-interactive",
        "--server-host",
        "203.0.113.10",
        "--agent-id",
        "web-01",
        "--watch-path",
        str(watch_dir),
        "--ca-cert",
        str(ca_path),
        "--ca-fingerprint",
        fingerprint,
        "--agent-cert-path",
        str(tmp_path / "agent-cert.pem"),
    ]
    assert main(argv) != 0


# ── --python is accepted but unused by installer.py (14.1) ──────────────────


def test_python_flag_accepted_without_error() -> None:
    args = _build_arg_parser().parse_args(["plan", "--python", "/usr/bin/python3.13"])
    assert args.python == "/usr/bin/python3.13"


def test_secret_absent_from_apply_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ca_cert, ca_key = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    fingerprint = compute_fingerprint(ca_cert)
    secret_file = tmp_path / "secret"
    secret = "s3cr3t-value-not-in-output"
    secret_file.write_text(secret)
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()

    argv = [
        "apply",
        "--non-interactive",
        "--server-host",
        "203.0.113.10",
        "--agent-id",
        "web-01",
        "--watch-path",
        str(watch_dir),
        "--ca-cert",
        str(ca_path),
        "--ca-fingerprint",
        fingerprint,
        "--bootstrap-secret-file",
        str(secret_file),
        "--config-dest",
        str(tmp_path / "config.yaml"),
        "--env-dest",
        str(tmp_path / "env"),
        "--ca-cert-dest",
        str(tmp_path / "ca-installed.pem"),
        "--config-example",
        str(CONFIG_EXAMPLE),
    ]
    exit_code = main(argv)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert secret not in captured.out
    assert secret not in captured.err
    env_content = (tmp_path / "env").read_text()
    assert f"FIM_BOOTSTRAP_SECRET={secret}" in env_content


# ── CA fingerprint verification ────────────────────────────────────────────────


def test_load_and_verify_ca_matching_fingerprint(tmp_path: Path) -> None:
    ca_cert, _ = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    fingerprint = compute_fingerprint(ca_cert)
    pem_bytes = load_and_verify_ca(str(ca_path), fingerprint)
    assert pem_bytes == ca_path.read_bytes()


def test_load_and_verify_ca_mismatched_fingerprint(tmp_path: Path) -> None:
    ca_cert, _ = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    with pytest.raises(InstallerError, match="fingerprint mismatch"):
        load_and_verify_ca(str(ca_path), "0" * 64)


def test_load_and_verify_ca_equivalent_formats(tmp_path: Path) -> None:
    ca_cert, _ = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    fingerprint = compute_fingerprint(ca_cert)
    colon_form = ":".join(fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)).upper()
    load_and_verify_ca(str(ca_path), colon_form)  # no raise


def test_load_and_verify_ca_rejects_non_ca_cert(tmp_path: Path) -> None:
    ca_cert, ca_key = _make_ca()
    leaf_cert, _ = _make_leaf(ca_cert, ca_key, common_name="not-a-ca", is_ca=False)
    leaf_path = tmp_path / "leaf.pem"
    _write_pem(leaf_path, leaf_cert)
    fingerprint = compute_fingerprint(leaf_cert)
    with pytest.raises(InstallerError, match="not a CA certificate"):
        load_and_verify_ca(str(leaf_path), fingerprint)


def test_normalize_fingerprint_strips_colons_and_spaces() -> None:
    assert normalize_fingerprint("AB:CD: EF") == "abcdef"


# ── config.yaml rendering ──────────────────────────────────────────────────────


def test_render_config_yaml_replaces_derived_fields() -> None:
    example_text = CONFIG_EXAMPLE.read_text()
    rendered = render_config_yaml(
        example_text,
        agent_id="web-01",
        backend_url="https://203.0.113.10:8444",
        mtls_backend_url="https://203.0.113.10:8443",
        valkey_url="valkeys://203.0.113.10:6380",
        ca_cert_path="/etc/fim-agent/certs/ca.pem",
        watch_paths=["/srv/app"],
    )
    assert "agent_id: web-01" in rendered
    assert "backend_url: https://203.0.113.10:8444" in rendered
    assert "mtls_backend_url: https://203.0.113.10:8443" in rendered
    assert "valkey_url: valkeys://203.0.113.10:6380" in rendered
    assert "watch_paths:\n  - /srv/app\n" in rendered
    # Everything else (comments, storage/publisher defaults) is preserved.
    assert "storage:" in rendered
    assert "allow_plaintext_valkey: false" in rendered
    assert "- /etc\n" not in rendered  # old watch_paths entries are gone


# ── Full apply(): non-overwrite and --reconfigure ─────────────────────────────


def _apply_argv(tmp_path: Path, ca_path: Path, fingerprint: str, secret_file: Path, watch_dir: Path, **overrides: str) -> list[str]:
    argv = [
        "apply",
        "--non-interactive",
        "--server-host",
        overrides.get("server_host", "203.0.113.10"),
        "--agent-id",
        "web-01",
        "--watch-path",
        str(watch_dir),
        "--ca-cert",
        str(ca_path),
        "--ca-fingerprint",
        fingerprint,
        "--bootstrap-secret-file",
        str(secret_file),
        "--config-dest",
        str(tmp_path / "config.yaml"),
        "--env-dest",
        str(tmp_path / "env"),
        "--ca-cert-dest",
        str(tmp_path / "ca-installed.pem"),
        "--config-example",
        str(CONFIG_EXAMPLE),
    ]
    if overrides.get("reconfigure"):
        argv.append("--reconfigure")
    return argv


def test_apply_does_not_overwrite_without_reconfigure(tmp_path: Path) -> None:
    ca_cert, _ = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    fingerprint = compute_fingerprint(ca_cert)
    secret_file = tmp_path / "secret"
    secret_file.write_text("0123456789abcdef")
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()

    argv = _apply_argv(tmp_path, ca_path, fingerprint, secret_file, watch_dir)
    assert main(argv) == 0
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / "env"
    original_config = config_path.read_bytes()
    original_env = env_path.read_bytes()

    # Second run with a DIFFERENT host — must not change either file.
    argv2 = _apply_argv(tmp_path, ca_path, fingerprint, secret_file, watch_dir, server_host="198.51.100.5")
    assert main(argv2) == 0
    assert config_path.read_bytes() == original_config
    assert env_path.read_bytes() == original_env


def test_apply_reconfigure_replaces_and_backs_up(tmp_path: Path) -> None:
    ca_cert, _ = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    fingerprint = compute_fingerprint(ca_cert)
    secret_file = tmp_path / "secret"
    secret_file.write_text("0123456789abcdef")
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()

    argv = _apply_argv(tmp_path, ca_path, fingerprint, secret_file, watch_dir)
    assert main(argv) == 0

    argv2 = _apply_argv(
        tmp_path, ca_path, fingerprint, secret_file, watch_dir, server_host="198.51.100.5", reconfigure="1"
    )
    assert main(argv2) == 0

    config_path = tmp_path / "config.yaml"
    assert "198.51.100.5" in config_path.read_text()
    backups = list(tmp_path.glob("config.yaml.bak-*"))
    assert len(backups) == 1


def test_apply_ca_fingerprint_mismatch_writes_nothing(tmp_path: Path) -> None:
    ca_cert, _ = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    secret_file = tmp_path / "secret"
    secret_file.write_text("0123456789abcdef")
    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()

    argv = _apply_argv(tmp_path, ca_path, "0" * 64, secret_file, watch_dir)
    exit_code = main(argv)
    assert exit_code == 1
    assert not (tmp_path / "config.yaml").exists()
    assert not (tmp_path / "env").exists()
    assert not (tmp_path / "ca-installed.pem").exists()


# ── Network scope check ────────────────────────────────────────────────────────


class _TlsTestServer:
    """A minimal single-connection TLS test server bound to 127.0.0.1 for the
    scope-check tests. `require_client_cert=True` simulates Valkey's
    `--tls-auth-clients yes`."""

    def __init__(self, cert_path: Path, key_path: Path, *, require_client_cert: bool = False) -> None:
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.load_cert_chain(str(cert_path), str(key_path))
        if require_client_cert:
            self._context.verify_mode = ssl.CERT_REQUIRED
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve_once, daemon=True)
        self._thread.start()

    def _serve_once(self) -> None:
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        try:
            with self._context.wrap_socket(conn, server_side=True):
                pass
        except ssl.SSLError:
            pass
        except OSError:
            pass

    def close(self) -> None:
        self._sock.close()


@pytest.fixture()
def ca_and_server_cert(tmp_path: Path) -> tuple[Path, x509.Certificate, "ec.EllipticCurvePrivateKey"]:
    ca_cert, ca_key = _make_ca()
    ca_path = tmp_path / "ca.pem"
    _write_pem(ca_path, ca_cert)
    return ca_path, ca_cert, ca_key


def test_check_port_ok_against_valid_server(tmp_path: Path, ca_and_server_cert: tuple) -> None:
    ca_path, ca_cert, ca_key = ca_and_server_cert
    server_cert, server_key = _make_leaf(
        ca_cert, ca_key, common_name="fim-server", san_ip=["127.0.0.1"]
    )
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server-key.pem"
    _write_pem(cert_path, server_cert)
    key_path.write_bytes(_key_pem(server_key))

    server = _TlsTestServer(cert_path, key_path)
    try:
        result = check_port("127.0.0.1", server.port, str(ca_path))
        assert result.ok, result.detail
        assert result.stage == "ok"
    finally:
        server.close()


def test_check_port_hostname_mismatch(tmp_path: Path, ca_and_server_cert: tuple) -> None:
    ca_path, ca_cert, ca_key = ca_and_server_cert
    server_cert, server_key = _make_leaf(
        ca_cert, ca_key, common_name="fim-server", san_dns=["not-127-0-0-1.example.org"]
    )
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server-key.pem"
    _write_pem(cert_path, server_cert)
    key_path.write_bytes(_key_pem(server_key))

    server = _TlsTestServer(cert_path, key_path)
    try:
        result = check_port("127.0.0.1", server.port, str(ca_path))
        assert not result.ok
        assert result.stage == "hostname_mismatch"
    finally:
        server.close()


def test_check_port_tcp_refused(ca_and_server_cert: tuple) -> None:
    ca_path, _, _ = ca_and_server_cert
    # Bind and immediately close to obtain a very-likely-unused port.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    result = check_port("127.0.0.1", port, str(ca_path))
    assert not result.ok
    assert result.stage == "tcp_refused"


def test_check_port_client_cert_required_tolerated(tmp_path: Path, ca_and_server_cert: tuple) -> None:
    ca_path, ca_cert, ca_key = ca_and_server_cert
    server_cert, server_key = _make_leaf(
        ca_cert, ca_key, common_name="valkey", san_ip=["127.0.0.1"]
    )
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server-key.pem"
    _write_pem(cert_path, server_cert)
    key_path.write_bytes(_key_pem(server_key))

    server = _TlsTestServer(cert_path, key_path, require_client_cert=True)
    try:
        result = check_port("127.0.0.1", server.port, str(ca_path), tolerate_post_handshake_close=True)
        assert result.ok, result.detail
    finally:
        server.close()


def test_run_scope_check_all_ok(tmp_path: Path, ca_and_server_cert: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    ca_path, ca_cert, ca_key = ca_and_server_cert
    server_cert, server_key = _make_leaf(ca_cert, ca_key, common_name="fim-server", san_ip=["127.0.0.1"])
    cert_path = tmp_path / "server.pem"
    key_path = tmp_path / "server-key.pem"
    _write_pem(cert_path, server_cert)
    key_path.write_bytes(_key_pem(server_key))

    server_a = _TlsTestServer(cert_path, key_path)
    server_b = _TlsTestServer(cert_path, key_path)
    try:
        monkeypatch.setattr(
            "agent.installer.SCOPE_CHECK_PORTS",
            ((server_a.port, False), (server_b.port, False)),
        )
        assert run_scope_check("127.0.0.1", str(ca_path)) is True
    finally:
        server_a.close()
        server_b.close()
