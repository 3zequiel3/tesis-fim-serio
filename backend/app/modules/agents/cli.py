"""Server-side agent registration CLI (D56/RN-150, design D-8 of
`vps-deployment-readiness`).

Usage: `python -m app.modules.agents.cli register --agent-id <id>`

Wraps `scripts/register-agent.sh`, which runs this inside the backend
container via `docker compose exec`. In one step it: generates a single-use
bootstrap secret with a cryptographic generator; registers the agent using
the exact same service-layer logic as `POST /agents/register` (Argon2id
hash, 409 on an existing `agent_id`); and prints what the operator needs to
run `agent/install.sh` on the remote host — the `FIM_PUBLIC_HOSTS` entries,
the CA's SHA-256 fingerprint in the format the installer accepts, the secret
itself, and a suggested install command with the secret deliberately
omitted. The secret exists only in this one terminal output: it is never
written to disk here and never logged (D56/RN-150 — "el paso SHALL NOT
exigir la contraseña del admin" and "el secreto SHALL NOT escribirse en
disco, en logs ni en argumentos de procesos").
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from fastapi import HTTPException
from sqlmodel import Session

from app.core.config import settings
from app.core.database import engine
from app.modules.agents.models import AgentRegisterRequest
from app.modules.agents.service import register_agent

# secrets.token_hex(16) -> 32 hex characters, the floor the agent-core spec
# sets for the registration script's generated secret.
_SECRET_BYTES = 16


def compute_ca_fingerprint(ca_cert_path: str) -> str:
    """SHA-256 over the DER encoding of `ca_cert_path` — the same value and
    format `agent/installer.py`'s `--ca-fingerprint` accepts."""
    cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())
    return hashlib.sha256(cert.public_bytes(Encoding.DER)).hexdigest()


def _public_hosts(raw: str) -> list[str]:
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def register(agent_id: str) -> int:
    """Registers `agent_id` with a freshly generated secret and prints the
    registration output. Returns a process exit code (0 on success, non-zero
    on conflict) — never prints a secret unless the registration actually
    succeeded."""
    secret = secrets.token_hex(_SECRET_BYTES)

    with Session(engine) as session:
        try:
            register_agent(
                AgentRegisterRequest(agent_id=agent_id, bootstrap_secret=secret),
                session,
            )
        except HTTPException as exc:
            print(f"cli.register: {exc.detail}", file=sys.stderr)
            return 1

    fingerprint = compute_ca_fingerprint(settings.ca_cert_path)
    hosts = _public_hosts(settings.fim_public_hosts)
    host_for_command = hosts[0] if hosts else "<FIM_PUBLIC_HOSTS host>"

    print(f"agent_id: {agent_id}")
    print(f"hosts: {', '.join(hosts) if hosts else '(FIM_PUBLIC_HOSTS is empty)'}")
    print(f"ca_fingerprint_sha256: {fingerprint}")
    print(f"bootstrap_secret: {secret}")
    print()
    print("Suggested install command (run on the monitored host; the secret is")
    print("deliberately omitted — read it from the line above):")
    print(
        f"  sudo bash agent/install.sh --non-interactive --server-host {host_for_command} "
        f"--agent-id {agent_id} --watch-path <path> --ca-cert ./fim-ca.pem "
        f"--ca-fingerprint {fingerprint} --bootstrap-secret-file <path-to-secret-file>"
    )
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.modules.agents.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    register_parser = sub.add_parser("register")
    register_parser.add_argument("--agent-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "register":
        return register(args.agent_id)
    return 1  # pragma: no cover — argparse enforces the choice set above


if __name__ == "__main__":
    sys.exit(main())
