#!/usr/bin/env python3
"""Genera el `.env` de un servidor FIM Platform (D54/RN-148, D59/RN-153).

POR QUÉ EXISTE
    La guía de despliegue remoto (change 52) exige preparar un servidor sin
    editar YAML ni ejecutar nada dentro de contenedores. Este script genera
    un `.env` completo — hosts públicos, modo TLS de la consola, todos los
    secretos — a partir de flags o prompts, usando sólo la biblioteca
    estándar de Python 3 (`secrets`, `ipaddress`, `argparse`, `getpass`) más
    Docker para el hash bcrypt del owner de n8n (ver `hash_n8n_owner_password`).

QUÉ VALIDA
    Cada entrada de `--fim-public-hosts` con la MISMA regla IP/DNS que
    `backend/app/core/pki.py::parse_public_hosts` (RFC 1123, sin comodines) —
    `scripts/tests/test_prepare_server_env.py` corre una tabla de casos común
    contra ambas implementaciones para probar la paridad.

QUÉ ESCRIBE
    `DB_PASSWORD`, `JWT_SECRET_CURRENT` (32 bytes hex), `JWT_SECRET_PREVIOUS`
    (vacío), `ADMIN_USERNAME`, `ADMIN_PASSWORD`, las rutas canónicas de
    certificados (`CA_CERT_PATH`, `CA_KEY_PATH`, `BACKEND_CERT_PATH`,
    `BACKEND_KEY_PATH`), `CORS_ALLOWED_ORIGINS` (derivado de
    `FIM_PUBLIC_HOSTS` ∪ `localhost` con AMBOS esquemas, `http` y `https` —
    D59/RN-153, revisado 2026-09-15 para que cambiar el modo de consola no
    exija editar `CORS_ALLOWED_ORIGINS` a mano), `FIM_PUBLIC_HOSTS`, las seis `CONSOLE_*`,
    `N8N_WEBHOOK_URL`/`N8N_HEALTH_URL` (URLs productivas), `N8N_ENCRYPTION_KEY`
    y las cuatro `N8N_INSTANCE_OWNER_*` (con el hash bcrypt de una contraseña
    generada, nunca la contraseña en claro).

EXCLUSIVIDAD
    Crea el archivo con `os.O_CREAT | os.O_EXCL` y modo `0600`: la
    exclusividad no depende de un chequeo previo con carrera. Si `.env` (o
    `--output`) ya existe, termina con exit distinto de 0 sin tocarlo.

USO
    python3 scripts/prepare_server_env.py --fim-public-hosts 203.0.113.10 \\
        --console-tls-mode off --n8n-owner-email ops@example.org
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import secrets
import string
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

N8N_IMAGE = "n8nio/n8n:2.17.8"
_BCRYPTJS_PATH = "/usr/local/lib/node_modules/n8n/node_modules/bcryptjs"

_DNS_LABEL_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")

_SAFE_ALPHABET = string.ascii_letters + string.digits


class ServerEnvError(Exception):
    """Raised for any condition that must abort before writing `.env`."""


# ── Validación de hosts — MISMA regla que backend/app/core/pki.py ────────────
# (RFC 1123, sin comodines). Duplicada deliberadamente: este script debe
# correr con sólo la stdlib, sin depender de `cryptography` ni del backend.
# La paridad se prueba en scripts/tests/test_prepare_server_env.py contra una
# tabla de casos común.


def _is_valid_dns_name(host: str) -> bool:
    if not host or len(host) > 253:
        return False
    return all(_DNS_LABEL_RE.match(label) for label in host.split("."))


def parse_public_hosts(raw: str) -> tuple[set[str], set[object]]:
    """Parse `FIM_PUBLIC_HOSTS` into `(dns_names, ip_addresses)`. Raises
    `ServerEnvError` naming the first invalid entry. Mirrors
    `app.core.pki.parse_public_hosts` exactly (same acceptance rule)."""
    dns_names: set[str] = set()
    ip_addresses: set[object] = set()
    for entry in raw.split(","):
        host = entry.strip()
        if not host:
            continue
        try:
            ip_addresses.add(ipaddress.ip_address(host))
            continue
        except ValueError:
            pass
        if not _is_valid_dns_name(host):
            raise ServerEnvError(
                f"FIM_PUBLIC_HOSTS: invalid entry {host!r}: not a valid IP "
                "address nor an RFC 1123 DNS name (wildcards not allowed)"
            )
        dns_names.add(host.lower())
    return dns_names, ip_addresses


# ── Secretos ───────────────────────────────────────────────────────────────


def generate_hex_secret(nbytes: int = 32) -> str:
    return secrets.token_hex(nbytes)


def generate_password(length: int = 24) -> str:
    """URL-safe alphanumeric password — no characters that break a Postgres
    connection URL or a shell command unescaped (@, /, #, :, spaces)."""
    return "".join(secrets.choice(_SAFE_ALPHABET) for _ in range(length))


def hash_n8n_owner_password(password: str, image: str = N8N_IMAGE) -> str:
    """Compute the bcrypt hash n8n expects for `N8N_INSTANCE_OWNER_PASSWORD_HASH`
    using an ephemeral container of the pinned n8n image (D-4): the stdlib has
    no bcrypt, and n8n itself ships `bcryptjs` for its own password hashing.
    The password travels over stdin, never as a CLI argument. Raises
    `ServerEnvError` (never writes `.env`) if the container run fails."""
    node_script = (
        "let d='';"
        "process.stdin.on('data',c=>d+=c);"
        "process.stdin.on('end',()=>{"
        f"const b=require({_BCRYPTJS_PATH!r});"
        "process.stdout.write(b.hashSync(d,10));"
        "});"
    )
    try:
        result = subprocess.run(
            # --entrypoint node is required: the image's default entrypoint
            # is n8n's own CLI (oclif-based), which treats a bare "node"
            # argument as an unrecognized n8n subcommand ("Command \"node\"
            # not found") instead of executing the Node.js binary. Verified
            # empirically against n8nio/n8n:2.17.8, 2026-09-13.
            ["docker", "run", "--rm", "-i", "--entrypoint", "node", image, "-e", node_script],
            input=password.encode(),
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServerEnvError(f"failed to run docker for n8n bcrypt hashing: {exc}") from exc
    if result.returncode != 0:
        raise ServerEnvError(
            "n8n bcrypt hashing container failed "
            f"(exit {result.returncode}): {result.stderr.decode(errors='replace')[:500]}"
        )
    hashed = result.stdout.decode().strip()
    if not hashed or not hashed.startswith(("$2a$", "$2b$", "$2y$")):
        raise ServerEnvError(f"unexpected bcrypt hash output: {hashed!r}")
    return hashed


# ── CORS_ALLOWED_ORIGINS (D59/RN-153) ─────────────────────────────────────────


def derive_cors_origins(
    dns_names: set[str],
    ip_addresses: set[object],
    console_tls_mode: str,
    http_port: int = 80,
    https_port: int = 443,
) -> str:
    """Union of FIM_PUBLIC_HOSTS ∪ {localhost}, with BOTH schemes (`http` and
    `https`) for each host and the port only when it is not that scheme's
    default (D59/RN-153, revised 2026-09-15 after the VPS acceptance run:
    with a single scheme, switching CONSOLE_TLS_MODE from `off` to
    `self_signed` made the HTTPS login fail with 403 until
    CORS_ALLOWED_ORIGINS was edited by hand — the whole point of deriving it
    was to make that edit unnecessary). `console_tls_mode` no longer affects
    which scheme is emitted, only which ports each scheme uses."""
    hosts = sorted(dns_names | {"localhost"}) + sorted(str(ip) for ip in ip_addresses)
    origins = []
    for host in hosts:
        display_host = f"[{host}]" if ":" in host else host
        for scheme, port, default_port in (("http", http_port, 80), ("https", https_port, 443)):
            if port == default_port:
                origins.append(f"{scheme}://{display_host}")
            else:
                origins.append(f"{scheme}://{display_host}:{port}")
    return ",".join(origins)


# ── Rendering y escritura ──────────────────────────────────────────────────


def _escape_dollar(value: str) -> str:
    """Escape literal `$` as `$$` (docker compose interpolates `--env-file`
    contents against themselves: an unescaped `$` in a value — e.g. inside a
    bcrypt hash like `$2a$10$...` — is parsed as a variable reference and
    silently replaced with an empty string, corrupting the value with no
    error. Verified empirically against Docker Compose v5.5.0, 2026-09-13.)"""
    return value.replace("$", "$$")


def render_env(values: dict[str, str]) -> str:
    values = {key: _escape_dollar(value) for key, value in values.items()}
    lines = [
        "# Generado por scripts/prepare_server_env.py — NO commitear.",
        "",
        "# --- PostgreSQL / JWT / admin -----------------------------------------------",
        f"DB_PASSWORD={values['DB_PASSWORD']}",
        f"JWT_SECRET_CURRENT={values['JWT_SECRET_CURRENT']}",
        f"JWT_SECRET_PREVIOUS={values['JWT_SECRET_PREVIOUS']}",
        f"ADMIN_USERNAME={values['ADMIN_USERNAME']}",
        f"ADMIN_PASSWORD={values['ADMIN_PASSWORD']}",
        "",
        "# --- PKI (rutas canónicas dentro del contenedor backend) --------------------",
        f"CA_CERT_PATH={values['CA_CERT_PATH']}",
        f"CA_KEY_PATH={values['CA_KEY_PATH']}",
        f"BACKEND_CERT_PATH={values['BACKEND_CERT_PATH']}",
        f"BACKEND_KEY_PATH={values['BACKEND_KEY_PATH']}",
        "",
        "# --- CORS (RN-95, D59/RN-153) ------------------------------------------------",
        f"CORS_ALLOWED_ORIGINS={values['CORS_ALLOWED_ORIGINS']}",
        "",
        "# --- Despliegue remoto (D53/RN-147, D55/RN-149) ------------------------------",
        f"FIM_PUBLIC_HOSTS={values['FIM_PUBLIC_HOSTS']}",
        f"CONSOLE_TLS_MODE={values['CONSOLE_TLS_MODE']}",
        f"CONSOLE_HTTP_PORT={values['CONSOLE_HTTP_PORT']}",
        f"CONSOLE_HTTPS_PORT={values['CONSOLE_HTTPS_PORT']}",
        f"CONSOLE_TLS_DIR={values['CONSOLE_TLS_DIR']}",
        f"CONSOLE_TLS_CERT_FILE={values['CONSOLE_TLS_CERT_FILE']}",
        f"CONSOLE_TLS_KEY_FILE={values['CONSOLE_TLS_KEY_FILE']}",
        "",
        "# --- n8n (D45/RN-139) --------------------------------------------------------",
        f"N8N_WEBHOOK_URL={values['N8N_WEBHOOK_URL']}",
        f"N8N_HEALTH_URL={values['N8N_HEALTH_URL']}",
        f"N8N_ENCRYPTION_KEY={values['N8N_ENCRYPTION_KEY']}",
        f"N8N_INSTANCE_OWNER_EMAIL={values['N8N_INSTANCE_OWNER_EMAIL']}",
        f"N8N_INSTANCE_OWNER_FIRST_NAME={values['N8N_INSTANCE_OWNER_FIRST_NAME']}",
        f"N8N_INSTANCE_OWNER_LAST_NAME={values['N8N_INSTANCE_OWNER_LAST_NAME']}",
        f"N8N_INSTANCE_OWNER_PASSWORD_HASH={values['N8N_INSTANCE_OWNER_PASSWORD_HASH']}",
        "",
        "# --- Notificaciones adicionales (D43/RN-137) — sin default en el compose;",
        "# se escriben vacías/con el default de .env.example para que",
        "# `docker compose config` no reporte variables faltantes. Completar a mano",
        "# para habilitar el canal SMTP o el fallback de webhook.",
        f"SMTP_HOST={values['SMTP_HOST']}",
        f"SMTP_PORT={values['SMTP_PORT']}",
        f"SMTP_USER={values['SMTP_USER']}",
        f"SMTP_PASSWORD={values['SMTP_PASSWORD']}",
        f"SMTP_FROM={values['SMTP_FROM']}",
        f"SMTP_TO={values['SMTP_TO']}",
        f"SMTP_STARTTLS={values['SMTP_STARTTLS']}",
        f"SMTP_SSL={values['SMTP_SSL']}",
        f"WEBHOOK_FALLBACK_URL={values['WEBHOOK_FALLBACK_URL']}",
        "",
    ]
    return "\n".join(lines)


def write_env_exclusive(path: Path, content: str) -> None:
    """Create `path` with mode 0600, atomically refusing to overwrite an
    existing file (O_EXCL — no separate existence check, no TOCTOU race)."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ServerEnvError(f"{path} already exists — refusing to overwrite it") from exc
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except Exception:
        raise
    os.chmod(path, 0o600)


# ── Prompts (no-op fuera de una TTY, para no colgar corridas automatizadas) ──


def _prompt_or_default(value: str | None, prompt_text: str, default: str = "") -> str:
    if value is not None:
        return value
    if sys.stdin.isatty():
        answer = input(f"{prompt_text} [{default}]: ").strip()
        return answer or default
    return default


# ── CLI ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fim-public-hosts", default=None, help="FIM_PUBLIC_HOSTS (comma-separated)")
    parser.add_argument(
        "--console-tls-mode", choices=["off", "self_signed", "provided"], default="off"
    )
    parser.add_argument("--console-http-port", type=int, default=80)
    parser.add_argument("--console-https-port", type=int, default=443)
    parser.add_argument("--console-tls-dir", default="./deploy/console-tls")
    parser.add_argument("--console-tls-cert-file", default="fullchain.pem")
    parser.add_argument("--console-tls-key-file", default="privkey.pem")
    parser.add_argument("--admin-username", default=None)
    parser.add_argument("--n8n-owner-email", default=None)
    parser.add_argument("--n8n-owner-first-name", default=None)
    parser.add_argument("--n8n-owner-last-name", default=None)
    parser.add_argument(
        "--n8n-image", default=N8N_IMAGE, help="Pinned n8n image used for bcrypt hashing"
    )
    parser.add_argument(
        "--output", default=str(REPO_ROOT / ".env"), help="Path to write (default: .env)"
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    if output_path.exists():
        print(f"error: {output_path} already exists — refusing to overwrite it", file=sys.stderr)
        return 1

    try:
        fim_public_hosts_raw = _prompt_or_default(
            args.fim_public_hosts, "FIM_PUBLIC_HOSTS (comma-separated IPs/DNS names)", ""
        )
        dns_names, ip_addresses = parse_public_hosts(fim_public_hosts_raw)

        admin_username = _prompt_or_default(args.admin_username, "Admin username", "admin")
        n8n_owner_email = _prompt_or_default(args.n8n_owner_email, "n8n owner email", "")
        n8n_owner_first_name = _prompt_or_default(args.n8n_owner_first_name, "n8n owner first name", "FIM")
        n8n_owner_last_name = _prompt_or_default(args.n8n_owner_last_name, "n8n owner last name", "Admin")

        admin_password = generate_password()
        n8n_owner_password = generate_password()

        # Bcrypt hashing runs BEFORE any file is written — a failure here
        # must never leave a plaintext password anywhere.
        n8n_owner_password_hash = hash_n8n_owner_password(n8n_owner_password, image=args.n8n_image)

        cors_origins = derive_cors_origins(
            dns_names,
            ip_addresses,
            args.console_tls_mode,
            http_port=args.console_http_port,
            https_port=args.console_https_port,
        )

        values = {
            "DB_PASSWORD": generate_password(),
            "JWT_SECRET_CURRENT": generate_hex_secret(32),
            "JWT_SECRET_PREVIOUS": "",
            "ADMIN_USERNAME": admin_username,
            "ADMIN_PASSWORD": admin_password,
            "CA_CERT_PATH": "/certs/ca.pem",
            "CA_KEY_PATH": "/certs/ca-key.pem",
            "BACKEND_CERT_PATH": "/certs/backend.pem",
            "BACKEND_KEY_PATH": "/certs/backend-key.pem",
            "CORS_ALLOWED_ORIGINS": cors_origins,
            "FIM_PUBLIC_HOSTS": fim_public_hosts_raw,
            "CONSOLE_TLS_MODE": args.console_tls_mode,
            "CONSOLE_HTTP_PORT": str(args.console_http_port),
            "CONSOLE_HTTPS_PORT": str(args.console_https_port),
            "CONSOLE_TLS_DIR": args.console_tls_dir,
            "CONSOLE_TLS_CERT_FILE": args.console_tls_cert_file,
            "CONSOLE_TLS_KEY_FILE": args.console_tls_key_file,
            "N8N_WEBHOOK_URL": "http://n8n:5678/webhook/fim-alert",
            "N8N_HEALTH_URL": "http://n8n:5678/healthz",
            "N8N_ENCRYPTION_KEY": generate_hex_secret(32),
            "N8N_INSTANCE_OWNER_EMAIL": n8n_owner_email,
            "N8N_INSTANCE_OWNER_FIRST_NAME": n8n_owner_first_name,
            "N8N_INSTANCE_OWNER_LAST_NAME": n8n_owner_last_name,
            "N8N_INSTANCE_OWNER_PASSWORD_HASH": n8n_owner_password_hash,
            # Sin default en docker-compose.yml (D43/RN-137: un canal sin
            # configurar debe reportarse NO CONFIGURADO, nunca falsamente
            # sano) — se escriben vacíos/con el default de .env.example
            # únicamente para que `docker compose config` no las reporte
            # como variables faltantes.
            "SMTP_HOST": "",
            "SMTP_PORT": "587",
            "SMTP_USER": "",
            "SMTP_PASSWORD": "",
            "SMTP_FROM": "",
            "SMTP_TO": "",
            "SMTP_STARTTLS": "true",
            "SMTP_SSL": "false",
            "WEBHOOK_FALLBACK_URL": "",
        }

        content = render_env(values)
        write_env_exclusive(output_path, content)
    except ServerEnvError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {output_path} (mode 0600).")
    print("")
    print("Initial admin password (shown once, never logged):")
    print(f"  {admin_password}")
    print("")
    print("Initial n8n owner password (shown once, never logged):")
    print(f"  {n8n_owner_password}")
    print("")
    if args.console_tls_mode == "off":
        print(
            "WARNING: CONSOLE_TLS_MODE=off — credentials and tokens travel "
            "unencrypted until you set a TLS mode.",
            file=sys.stderr,
        )
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
