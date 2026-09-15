"""FIM Agent installer — pure-Python logic behind `agent/install.sh` (D56/RN-150,
design D-7 of `vps-deployment-readiness`).

`install.sh` keeps everything that requires root and systemd (user/directory
creation, the venv, the unit file, `daemon-reload`, `enable`/`start`/`restart`,
and the ownership rules owned by change 41). Argument parsing, prompts, the CA
fingerprint check, `config.yaml` rendering, the bootstrap secret write, and the
network scope check live here instead, as pure functions testable with pytest
and no root privileges — the same split `agent/deployment.py` already uses for
the systemd drop-in.

`install.sh` invokes this module three times, forwarding its own arguments
unmodified (`"$@"`), never interpreting them itself, so no secret value ever
sits in a shell variable or shows up in `ps`:

    installer.py plan  "$@"   # resolve + validate everything, write nothing
    installer.py apply "$@"   # write config.yaml, ca.pem and env
    installer.py check "$@"   # verify network reachability of 8444 and 6380

Each subcommand re-resolves its inputs independently — there is no on-disk
cache between invocations, because the bootstrap secret must never be written
anywhere except the final `/etc/fim-agent/env` (D56/RN-150).
"""

from __future__ import annotations

import argparse
import getpass
import grp
import hashlib
import ipaddress
import os
import pwd
import re
import shutil
import socket
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding

from agent import deployment as agent_deployment

DEFAULT_CONFIG_DEST = "/etc/fim-agent/config.yaml"
DEFAULT_ENV_DEST = "/etc/fim-agent/env"
DEFAULT_CA_CERT_DEST = "/etc/fim-agent/certs/ca.pem"
DEFAULT_CONFIG_EXAMPLE = str(Path(__file__).parent / "deploy" / "config.yaml.example")
# Same path install.sh's AGENT_CERT_PATH points to — where agent/bootstrap.py
# writes the agent's own certificate after a successful bootstrap.
DEFAULT_AGENT_CERT_PATH = "/var/lib/fim-agent/certs/agent-cert.pem"

MIN_SECRET_LENGTH = 16
SCOPE_CHECK_TIMEOUT_S = 5.0
SCOPE_CHECK_PORTS: tuple[tuple[int, bool], ...] = (
    (8444, False),  # bootstrap listener: a client-cert rejection is a real failure
    (6380, True),  # Valkey: rejected for lacking a client cert is expected pre-enrollment
)

# Errors that mean "the TLS server demanded a client certificate we don't have
# yet" rather than "the server is unreachable or untrusted" — only relevant
# with tolerate_post_handshake_close=True (port 6380, D-7 step 9).
_CLIENT_CERT_REQUIRED_MARKERS = (
    "certificate required",
    "handshake failure",
    "peer did not return a certificate",
    "sslv3 alert handshake failure",
)


class InstallerError(Exception):
    """Raised for any condition that must abort the installer before writing
    anything under /etc/fim-agent, with a message naming the offending input."""


# ── Argument / environment resolution ─────────────────────────────────────────


def _get_value(
    flag_value: str | None,
    env_var: str,
    label: str,
    non_interactive: bool,
    *,
    allow_empty: bool = False,
) -> str:
    """flag > environment variable > interactive prompt, in that order."""
    if flag_value:
        return flag_value
    env_value = os.environ.get(env_var)
    if env_value:
        return env_value
    if non_interactive:
        if allow_empty:
            return ""
        raise InstallerError(f"missing required input: {label} (flag or ${env_var})")
    return input(f"{label}: ").strip()


def _split_watch_paths(entries: list[str]) -> list[str]:
    result: list[str] = []
    for entry in entries:
        result.extend(p.strip() for p in entry.split(",") if p.strip())
    return result


def validate_watch_paths(raw_paths: list[str]) -> list[str]:
    """Each watch path must be absolute, must exist, and must pass the same
    format-safety check `agent.deployment` applies before writing the systemd
    drop-in (D-7 step 3 / agent-core spec)."""
    validated: list[str] = []
    seen: set[str] = set()
    for raw in raw_paths:
        path = raw.strip()
        if not path:
            continue
        if not os.path.isabs(path):
            raise InstallerError(f"watch path must be absolute: {path!r}")
        if not os.path.exists(path):
            raise InstallerError(f"watch path does not exist: {path!r}")
        try:
            normalized = agent_deployment._validate_path(path)
        except ValueError as exc:
            raise InstallerError(str(exc)) from exc
        if normalized in seen:
            continue
        seen.add(normalized)
        validated.append(normalized)
    if not validated:
        raise InstallerError("at least one watch path is required")
    return validated


def bracket_host(host: str) -> str:
    """Wraps an IPv6 literal in brackets for use inside a URL; leaves IPv4
    literals and DNS names unchanged."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(addr, ipaddress.IPv6Address):
        return f"[{host}]"
    return host


def derive_urls(host: str) -> tuple[str, str, str]:
    """Derives `(backend_url, mtls_backend_url, valkey_url)` from the server
    host (agent-core spec, D53/RN-147 port assignments)."""
    bracketed = bracket_host(host)
    return (
        f"https://{bracketed}:8444",
        f"https://{bracketed}:8443",
        f"valkeys://{bracketed}:6380",
    )


def resolve_bootstrap_secret(
    bootstrap_secret_file: str | None, non_interactive: bool
) -> str:
    """Reads the bootstrap secret from a hidden prompt or a file — never from
    a flag or environment variable that could carry the value itself
    (agent-core spec: "El secreto de bootstrap nunca se acepta como
    argumento")."""
    if bootstrap_secret_file:
        try:
            secret = Path(bootstrap_secret_file).read_text().strip()
        except OSError as exc:
            raise InstallerError(
                f"cannot read bootstrap secret file {bootstrap_secret_file!r}: {exc}"
            ) from exc
    elif non_interactive:
        raise InstallerError(
            "missing required input: bootstrap secret "
            "(--bootstrap-secret-file; the hidden prompt requires a TTY)"
        )
    else:
        secret = getpass.getpass("Bootstrap secret (hidden): ").strip()

    if len(secret) < MIN_SECRET_LENGTH:
        raise InstallerError(
            f"bootstrap secret must be at least {MIN_SECRET_LENGTH} characters"
        )
    return secret


def is_already_enrolled(agent_cert_path: str) -> bool:
    """True when a valid (unexpired) agent certificate already exists at
    `agent_cert_path` — i.e. this host already completed a bootstrap.

    Delegates to `agent.bootstrap.is_bootstrapped`, the same check the agent
    process itself uses to decide whether to skip bootstrapping (D56/RN-150
    finding 14.3): reinstalling an already-enrolled agent SHALL NOT demand
    the bootstrap secret again, because after the first successful bootstrap
    the authoritative configuration lives in the backend, not in a locally
    supplied secret. The secret stays mandatory for a first install and for
    any `--reconfigure` run — see `secret_required` below."""
    from agent.bootstrap import is_bootstrapped

    try:
        return is_bootstrapped(Path(agent_cert_path).parent)
    except OSError:
        # Cannot even stat the certs directory (e.g. permission denied
        # walking a parent that install.sh has not created/chowned yet) —
        # treat as "not enrolled" so the installer falls back to the safe
        # default of requiring the bootstrap secret, rather than crashing.
        return False


def secret_required(args: argparse.Namespace) -> bool:
    """Whether `plan`/`apply` must resolve a bootstrap secret at all.

    Required on a first install (no valid agent certificate yet) and on any
    `--reconfigure` run; NOT required to reinstall an already-enrolled agent
    without `--reconfigure` (D56/RN-150 finding 14.3)."""
    if args.reconfigure:
        return True
    return not is_already_enrolled(args.agent_cert_path)


def reject_secret_argument(argv: list[str]) -> None:
    """SHALL NOT exist a flag that transports the secret itself (e.g.
    `--bootstrap-secret`). Checked against raw argv, before argparse even
    runs, so this always fires before anything is written."""
    for arg in argv:
        if arg == "--bootstrap-secret" or arg.startswith("--bootstrap-secret="):
            raise InstallerError(
                "the bootstrap secret is never accepted as a command-line "
                "argument — use the hidden prompt or --bootstrap-secret-file"
            )


# ── CA fingerprint verification ───────────────────────────────────────────────


def normalize_fingerprint(raw: str) -> str:
    """Case-insensitive, ignoring ':' and whitespace — the same format the
    server-side registration script prints and OpenSSL's `-fingerprint`
    output uses."""
    return re.sub(r"[:\s]", "", raw).strip().lower()


def compute_fingerprint(cert: x509.Certificate) -> str:
    der = cert.public_bytes(Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def load_and_verify_ca(cert_path: str, expected_fingerprint: str) -> bytes:
    """Loads `cert_path`, verifies it is a CA certificate whose SHA-256(DER)
    fingerprint matches `expected_fingerprint`, and returns its raw PEM bytes.

    Raises `InstallerError` — naming both fingerprints — on any mismatch, on
    an invalid PEM, or on a certificate that is not a CA. Never writes
    anything; callers write only after this returns successfully."""
    try:
        pem_bytes = Path(cert_path).read_bytes()
        cert = x509.load_pem_x509_certificate(pem_bytes)
    except (OSError, ValueError) as exc:
        raise InstallerError(f"invalid CA certificate at {cert_path!r}: {exc}") from exc

    try:
        basic_constraints = cert.extensions.get_extension_for_class(x509.BasicConstraints)
    except x509.ExtensionNotFound:
        raise InstallerError(f"{cert_path!r} is not a CA certificate (no BasicConstraints)")
    if not basic_constraints.value.ca:
        raise InstallerError(f"{cert_path!r} is not a CA certificate (BasicConstraints ca=False)")

    actual = compute_fingerprint(cert)
    expected = normalize_fingerprint(expected_fingerprint)
    if actual != expected:
        raise InstallerError(
            f"CA fingerprint mismatch: expected {expected}, got {actual}"
        )
    return pem_bytes


# ── config.yaml rendering ─────────────────────────────────────────────────────

_CONFIG_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "agent_id": re.compile(r"^agent_id:\s*.*$", re.MULTILINE),
    "backend_url": re.compile(r"^backend_url:\s*.*$", re.MULTILINE),
    "mtls_backend_url": re.compile(r"^mtls_backend_url:\s*.*$", re.MULTILINE),
    "valkey_url": re.compile(r"^valkey_url:\s*.*$", re.MULTILINE),
    "ca_cert_path": re.compile(r"^ca_cert_path:\s*.*$", re.MULTILINE),
}
_WATCH_PATHS_PATTERN = re.compile(r"^watch_paths:\n(?:^ {2}- .*\n?)+", re.MULTILINE)


def render_config_yaml(
    example_text: str,
    *,
    agent_id: str,
    backend_url: str,
    mtls_backend_url: str,
    valkey_url: str,
    ca_cert_path: str,
    watch_paths: list[str],
) -> str:
    """Replaces only the fields derived from installer inputs in
    `config.yaml.example`, leaving every comment and every other default
    (storage, publisher, allow_plaintext_valkey) untouched — text
    substitution rather than a YAML round-trip, so comments survive."""
    rendered = example_text
    replacements = {
        "agent_id": f"agent_id: {agent_id}",
        "backend_url": f"backend_url: {backend_url}",
        "mtls_backend_url": f"mtls_backend_url: {mtls_backend_url}",
        "valkey_url": f"valkey_url: {valkey_url}",
        "ca_cert_path": f"ca_cert_path: {ca_cert_path}",
    }
    for key, pattern in _CONFIG_FIELD_PATTERNS.items():
        rendered, count = pattern.subn(replacements[key], rendered, count=1)
        if count != 1:
            raise InstallerError(f"config.yaml.example is missing the '{key}:' field")

    watch_block = "watch_paths:\n" + "".join(f"  - {p}\n" for p in watch_paths)
    rendered, count = _WATCH_PATHS_PATTERN.subn(watch_block, rendered, count=1)
    if count != 1:
        raise InstallerError("config.yaml.example is missing the 'watch_paths:' block")
    return rendered


# ── File writes (config.yaml / env / ca.pem) — non-overwrite by default ──────


def _chown_best_effort(path: Path, user: str, group: str) -> None:
    """Best-effort chown, exactly like `certs_init._chown`: a no-op outside
    root (unit tests, local dev) — the file still gets the right mode, just
    not the final owner until a real install.sh run as root applies it."""
    try:
        uid = pwd.getpwnam(user).pw_uid
        gid = grp.getgrnam(group).gr_gid
    except KeyError:
        return
    try:
        os.chown(path, uid, gid)
    except (PermissionError, OSError):
        return


def _backup_existing(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(f"{path.name}.bak-{timestamp}")
    shutil.copy2(path, backup_path)
    return backup_path


def _write_managed_file(
    dest: Path,
    content: str | bytes,
    mode: int,
    *,
    reconfigure: bool,
    owner: tuple[str, str],
) -> str:
    """Writes `dest` atomically unless it already exists and `reconfigure` is
    False, in which case nothing changes. Returns "written" or
    "skipped_exists"."""
    if dest.exists():
        if not reconfigure:
            return "skipped_exists"
        _backup_existing(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    text_mode = isinstance(content, str)
    fd = os.open(str(tmp), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
    with os.fdopen(fd, "w" if text_mode else "wb") as f:
        f.write(content)  # type: ignore[arg-type]
    os.chmod(tmp, mode)
    os.replace(tmp, dest)
    _chown_best_effort(dest, *owner)
    return "written"


@dataclass
class ResolvedInputs:
    server_host: str
    agent_id: str
    watch_paths: list[str]
    backend_url: str
    mtls_backend_url: str
    valkey_url: str
    bootstrap_secret: str | None
    ca_pem_bytes: bytes


def resolve_inputs(args: argparse.Namespace, *, need_secret: bool, need_watch_paths: bool) -> ResolvedInputs:
    non_interactive = args.non_interactive

    server_host = _get_value(args.server_host, "FIM_SERVER_HOST", "Server host", non_interactive)
    agent_id = (
        _get_value(args.agent_id, "FIM_AGENT_ID", "Agent ID", non_interactive, allow_empty=True)
        or socket.gethostname()
    )
    ca_cert_path = _get_value(args.ca_cert, "FIM_CA_CERT", "Path to the server's ca.pem", non_interactive)
    ca_fingerprint = _get_value(
        args.ca_fingerprint, "FIM_CA_FINGERPRINT", "Expected CA SHA-256 fingerprint", non_interactive
    )

    watch_paths: list[str] = []
    if need_watch_paths:
        raw_watch_paths = _split_watch_paths(list(args.watch_path or []))
        if not raw_watch_paths:
            env_value = os.environ.get("FIM_WATCH_PATHS")
            if env_value:
                raw_watch_paths = _split_watch_paths([env_value])
        if not raw_watch_paths:
            if non_interactive:
                raise InstallerError(
                    "missing required input: watch paths (--watch-path or $FIM_WATCH_PATHS)"
                )
            raw_watch_paths = _split_watch_paths([input("Watch paths (comma-separated): ")])
        watch_paths = validate_watch_paths(raw_watch_paths)

    backend_url, mtls_backend_url, valkey_url = derive_urls(server_host)

    # The fingerprint check runs unconditionally, before any write, whether
    # this is `plan` or `apply` (agent-core spec: "aborta antes de cualquier
    # escritura en /etc/fim-agent mostrando ambas huellas").
    ca_pem_bytes = load_and_verify_ca(ca_cert_path, ca_fingerprint)

    bootstrap_secret = None
    if need_secret:
        bootstrap_secret = resolve_bootstrap_secret(args.bootstrap_secret_file, non_interactive)

    return ResolvedInputs(
        server_host=server_host,
        agent_id=agent_id,
        watch_paths=watch_paths,
        backend_url=backend_url,
        mtls_backend_url=mtls_backend_url,
        valkey_url=valkey_url,
        bootstrap_secret=bootstrap_secret,
        ca_pem_bytes=ca_pem_bytes,
    )


def apply_config(args: argparse.Namespace, inputs: ResolvedInputs) -> None:
    config_dest = Path(args.config_dest)
    example_text = Path(args.config_example).read_text()
    rendered = render_config_yaml(
        example_text,
        agent_id=inputs.agent_id,
        backend_url=inputs.backend_url,
        mtls_backend_url=inputs.mtls_backend_url,
        valkey_url=inputs.valkey_url,
        ca_cert_path=args.ca_cert_dest,
        watch_paths=inputs.watch_paths,
    )
    config_status = _write_managed_file(
        config_dest, rendered, 0o640, reconfigure=args.reconfigure, owner=("root", "fim-agent")
    )
    if config_status == "skipped_exists":
        print(f"installer.py: {config_dest} already exists, keeping it (use --reconfigure to replace)")

    env_dest = Path(args.env_dest)
    if env_dest.exists() and not args.reconfigure:
        # Reinstalling an enrolled agent (secret_required() returned False)
        # never has a bootstrap secret to write, and never needs one: `env`
        # already exists and stays untouched, same as any other managed file.
        print(f"installer.py: {env_dest} already exists, keeping it (use --reconfigure to replace)")
    else:
        if inputs.bootstrap_secret is None:
            raise InstallerError(
                f"internal error: {env_dest} needs to be (re)written but no bootstrap "
                "secret was resolved — this should be unreachable"
            )
        env_content = f"FIM_BOOTSTRAP_SECRET={inputs.bootstrap_secret}\n"
        _write_managed_file(
            env_dest, env_content, 0o600, reconfigure=args.reconfigure, owner=("root", "root")
        )

    ca_dest = Path(args.ca_cert_dest)
    ca_dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_ca = ca_dest.with_name(ca_dest.name + ".tmp")
    tmp_ca.write_bytes(inputs.ca_pem_bytes)
    os.chmod(tmp_ca, 0o644)
    os.replace(tmp_ca, ca_dest)
    _chown_best_effort(ca_dest, "root", "root")


# ── Network scope check (D-7 step 9) ──────────────────────────────────────────


@dataclass
class PortCheckResult:
    port: int
    ok: bool
    stage: str  # "ok" | "dns" | "tcp_refused" | "tcp_timeout" | "tls_verify" | "hostname_mismatch"
    detail: str


def _is_client_cert_required_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _CLIENT_CERT_REQUIRED_MARKERS)


def check_port(
    host: str,
    port: int,
    ca_cert_path: str,
    *,
    timeout: float = SCOPE_CHECK_TIMEOUT_S,
    tolerate_post_handshake_close: bool = False,
) -> PortCheckResult:
    """Resolves `host`, opens a TCP connection to `port`, and completes a TLS
    handshake verifying the server certificate against `ca_cert_path` and its
    SAN against `host` (agent-core spec: "resolución del nombre, la conexión
    TCP y un handshake TLS"). On port 6380 a rejection caused by the missing
    client certificate — which only happens *after* an otherwise-successful
    verification — does not count as a failure when
    `tolerate_post_handshake_close` is set."""
    try:
        socket.getaddrinfo(host, port)
    except socket.gaierror as exc:
        return PortCheckResult(port, False, "dns", f"DNS resolution for {host!r} failed: {exc}")

    try:
        raw_sock = socket.create_connection((host, port), timeout=timeout)
    except ConnectionRefusedError as exc:
        return PortCheckResult(port, False, "tcp_refused", f"connection to {host}:{port} refused: {exc}")
    except TimeoutError as exc:
        return PortCheckResult(port, False, "tcp_timeout", f"connection to {host}:{port} timed out: {exc}")
    except OSError as exc:
        return PortCheckResult(port, False, "tcp_refused", f"connection to {host}:{port} failed: {exc}")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=ca_cert_path)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED

    try:
        raw_sock.settimeout(timeout)
        with context.wrap_socket(raw_sock, server_hostname=host) as tls_sock:
            # A server enforcing "client certificate required" over TLS 1.3
            # (Valkey with --tls-auth-clients yes) completes the handshake
            # and only rejects us on the first application-data exchange —
            # that is the "posterior" rejection the spec calls out.
            try:
                tls_sock.settimeout(timeout)
                tls_sock.recv(0)
            except ssl.SSLError as exc:
                if tolerate_post_handshake_close and _is_client_cert_required_error(exc):
                    return PortCheckResult(
                        port, True, "ok", f"{host}:{port} reachable and trusted (client cert required, as expected)"
                    )
                return PortCheckResult(port, False, "tls_verify", f"{host}:{port} TLS verification failed: {exc}")
            except OSError:
                pass  # a clean post-handshake close with no TLS alert is also fine
    except ssl.CertificateError as exc:
        return PortCheckResult(port, False, "hostname_mismatch", f"{host}:{port} certificate does not cover {host}: {exc}")
    except ssl.SSLCertVerificationError as exc:
        reason = getattr(exc, "verify_message", "") or ""
        if "hostname mismatch" in reason.lower() or "hostname mismatch" in str(exc).lower():
            return PortCheckResult(port, False, "hostname_mismatch", f"{host}:{port} certificate does not cover {host}: {exc}")
        return PortCheckResult(port, False, "tls_verify", f"{host}:{port} TLS verification failed: {exc}")
    except ssl.SSLError as exc:
        if tolerate_post_handshake_close and _is_client_cert_required_error(exc):
            return PortCheckResult(
                port, True, "ok", f"{host}:{port} reachable and trusted (client cert required, as expected)"
            )
        return PortCheckResult(port, False, "tls_verify", f"{host}:{port} TLS handshake failed: {exc}")
    except TimeoutError as exc:
        return PortCheckResult(port, False, "tcp_timeout", f"TLS handshake with {host}:{port} timed out: {exc}")
    finally:
        try:
            raw_sock.close()
        except OSError:
            pass

    return PortCheckResult(port, True, "ok", f"{host}:{port} reachable and trusted")


def run_scope_check(host: str, ca_cert_path: str) -> bool:
    all_ok = True
    for port, tolerate in SCOPE_CHECK_PORTS:
        result = check_port(host, port, ca_cert_path, tolerate_post_handshake_close=tolerate)
        status_word = "OK" if result.ok else "FAILED"
        print(f"installer.py: scope check {host}:{port} -> {status_word} ({result.stage}): {result.detail}")
        if not result.ok:
            all_ok = False
    return all_ok


# ── CLI ────────────────────────────────────────────────────────────────────────

_AUTHORITY_NOTICE = (
    "installer.py: after the first successful bootstrap, the authoritative "
    "configuration lives in the backend and is edited from the console — "
    "re-running with --reconfigure only affects the connection data of an "
    "agent that has not enrolled yet."
)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="installer.py", description="FIM Agent installer (D56/RN-150)")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("plan", "apply", "check"):
        p = sub.add_parser(name)
        p.add_argument("--server-host")
        p.add_argument("--agent-id")
        p.add_argument("--watch-path", action="append", default=[])
        p.add_argument("--ca-cert")
        p.add_argument("--ca-fingerprint")
        p.add_argument("--bootstrap-secret-file")
        p.add_argument("--non-interactive", action="store_true")
        p.add_argument("--reconfigure", action="store_true")
        p.add_argument("--config-dest", default=DEFAULT_CONFIG_DEST)
        p.add_argument("--env-dest", default=DEFAULT_ENV_DEST)
        p.add_argument("--ca-cert-dest", default=DEFAULT_CA_CERT_DEST)
        p.add_argument("--config-example", default=DEFAULT_CONFIG_EXAMPLE)
        p.add_argument("--agent-cert-path", default=DEFAULT_AGENT_CERT_PATH)
        # Accepted (and otherwise ignored here) so install.sh can forward its
        # own arguments unchanged: `--python` only selects the interpreter
        # install.sh uses to create the venv (D56/RN-150 finding 14.1),
        # resolved and consumed entirely in bash before installer.py ever
        # runs. Declaring it here keeps argparse from rejecting it as
        # unrecognized when install.sh passes "$@" through unmodified.
        p.add_argument("--python")

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_secret_argument(raw_argv)
        args = _build_arg_parser().parse_args(raw_argv)

        if args.command == "plan":
            need_secret = secret_required(args)
            inputs = resolve_inputs(args, need_secret=need_secret, need_watch_paths=True)
            print("installer.py: plan")
            print(f"  agent_id={inputs.agent_id}")
            print(f"  backend_url={inputs.backend_url}")
            print(f"  mtls_backend_url={inputs.mtls_backend_url}")
            print(f"  valkey_url={inputs.valkey_url}")
            print(f"  watch_paths={inputs.watch_paths}")
            if need_secret:
                print("  bootstrap secret: provided (not shown)")
            else:
                print("  bootstrap secret: not required (agent already enrolled)")
        elif args.command == "apply":
            need_secret = secret_required(args)
            inputs = resolve_inputs(args, need_secret=need_secret, need_watch_paths=True)
            apply_config(args, inputs)
        elif args.command == "check":
            server_host = _get_value(args.server_host, "FIM_SERVER_HOST", "Server host", args.non_interactive)
            if not run_scope_check(server_host, args.ca_cert_dest):
                print(_AUTHORITY_NOTICE)
                return 1
        else:  # pragma: no cover — argparse enforces the choice set above
            raise InstallerError(f"unknown command: {args.command!r}")

    except InstallerError as exc:
        print(f"installer.py: {exc}", file=sys.stderr)
        return 1

    print(_AUTHORITY_NOTICE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
