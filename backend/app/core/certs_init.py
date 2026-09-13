"""
Servicio one-shot `certs-init` (D53/RN-147, D-1 del design de
`vps-deployment-readiness`).

Ejecuta, en este orden: asegura la CA (crearla si falta, validar su perfil si
existe) y el certificado de servidor del backend, el certificado de servidor
de Valkey, el certificado de cliente del backend ante Valkey y —sólo con
`CONSOLE_TLS_MODE=self_signed`— el certificado autofirmado STANDALONE de la
consola (ECDSA P-256, NO firmado por la CA propia — D62/RN-156; ver
`pki.ensure_console_cert`). Se loguea su huella SHA-256 al terminar ese paso.

Corre como root (`user: "0:0"` en el compose) para poder fijar dueño y modo
por archivo en los tres volúmenes de material TLS (`backend_certs`,
`valkey_tls`, `console_tls_generated`): cada volumen queda con el propietario
final que su consumidor necesita. `valkey_tls` y `console_tls_generated`
SHALL NOT contener la clave privada de la CA.

Uso: `python -m app.core.certs_init`. Un fallo termina con exit distinto de 0
y el log nombra la causa (RuntimeError/ValueError propagado desde `pki.py`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.core.logging import configure_logging, log
from app.core.pki import (
    ensure_backend_valkey_client_cert,
    ensure_ca,
    ensure_console_cert,
    ensure_valkey_server_cert,
)

# Ownership targets per volume. Determined empirically against the pinned
# images (2026-09-13, see design.md §Risks):
#   - backend_certs → uid 10001 ("app"), the backend's own runtime user
#     (backend/Dockerfile `useradd --uid 10001 app`); the backend's own
#     idempotent `ensure_ca()` call at lifespan needs read (and, without
#     certs-init, write) access to every file here, including ca-key.pem.
#   - valkey_tls → uid 999 ("valkey"), the user valkey/valkey:9.0.3's
#     entrypoint drops privileges to via `setpriv --reuid=valkey`.
#   - console_tls_generated → root. nginx:alpine's master process (the one
#     that reads `ssl_certificate_key` while parsing config) runs as root
#     inside the container; only worker processes drop to uid 101 ("nginx").
_BACKEND_UID = 10001
_BACKEND_GID = 10001
_VALKEY_UID = 999
_VALKEY_GID = 999
_CONSOLE_UID = 0
_CONSOLE_GID = 0

_VALID_CONSOLE_TLS_MODES = {"off", "self_signed", "provided"}


def _chown(path: Path, uid: int, gid: int) -> None:
    """Best-effort chown: only meaningful (and permitted) when running as
    root, which is how `certs-init` runs in the compose topology. Skipped
    silently outside root (local dev, unit tests) — the file still gets the
    correct mode from `pki.py`, just not the final owner."""
    if not path.exists():
        return
    if os.geteuid() != 0:
        return
    os.chown(path, uid, gid)


def main() -> int:
    configure_logging()

    ca_cert_path = os.environ.get("CA_CERT_PATH", "/certs/ca.pem")
    ca_key_path = os.environ.get("CA_KEY_PATH", "/certs/ca-key.pem")
    backend_cert_path = os.environ.get("BACKEND_CERT_PATH", "/certs/backend.pem")
    backend_key_path = os.environ.get("BACKEND_KEY_PATH", "/certs/backend-key.pem")
    backend_valkey_cert_path = os.environ.get(
        "BACKEND_VALKEY_CERT_PATH", "/certs/backend-valkey.pem"
    )
    backend_valkey_key_path = os.environ.get(
        "BACKEND_VALKEY_KEY_PATH", "/certs/backend-valkey-key.pem"
    )
    valkey_tls_dir = Path(os.environ.get("VALKEY_TLS_DIR", "/valkey-certs"))
    console_tls_dir = Path(os.environ.get("CONSOLE_TLS_GENERATED_DIR", "/console-certs"))
    fim_public_hosts = os.environ.get("FIM_PUBLIC_HOSTS", "")
    console_tls_mode = os.environ.get("CONSOLE_TLS_MODE", "off")

    if console_tls_mode not in _VALID_CONSOLE_TLS_MODES:
        log.error("certs_init.invalid_console_tls_mode", value=console_tls_mode)
        return 1

    try:
        log.info("certs_init.step.start", step="ca_and_backend")
        ensure_ca(
            ca_cert_path,
            ca_key_path,
            backend_cert_path,
            backend_key_path,
            fim_public_hosts=fim_public_hosts,
        )
        _chown(Path(ca_cert_path), _BACKEND_UID, _BACKEND_GID)
        _chown(Path(ca_key_path), _BACKEND_UID, _BACKEND_GID)
        _chown(Path(backend_cert_path), _BACKEND_UID, _BACKEND_GID)
        _chown(Path(backend_key_path), _BACKEND_UID, _BACKEND_GID)
        log.info("certs_init.step.done", step="ca_and_backend")

        log.info("certs_init.step.start", step="valkey_server")
        valkey_tls_dir.mkdir(parents=True, exist_ok=True)
        valkey_cert_path = valkey_tls_dir / "valkey.pem"
        valkey_key_path = valkey_tls_dir / "valkey-key.pem"
        ensure_valkey_server_cert(
            ca_cert_path,
            ca_key_path,
            str(valkey_cert_path),
            str(valkey_key_path),
            fim_public_hosts=fim_public_hosts,
        )
        _chown(valkey_cert_path, _VALKEY_UID, _VALKEY_GID)
        _chown(valkey_key_path, _VALKEY_UID, _VALKEY_GID)
        # Isolated CA copy inside valkey_tls — never the CA private key.
        valkey_ca_copy = valkey_tls_dir / "ca.pem"
        valkey_ca_copy.write_bytes(Path(ca_cert_path).read_bytes())
        os.chmod(valkey_ca_copy, 0o644)
        _chown(valkey_ca_copy, _VALKEY_UID, _VALKEY_GID)
        log.info("certs_init.step.done", step="valkey_server")

        log.info("certs_init.step.start", step="backend_valkey_client")
        ensure_backend_valkey_client_cert(
            ca_cert_path,
            ca_key_path,
            backend_valkey_cert_path,
            backend_valkey_key_path,
        )
        _chown(Path(backend_valkey_cert_path), _BACKEND_UID, _BACKEND_GID)
        _chown(Path(backend_valkey_key_path), _BACKEND_UID, _BACKEND_GID)
        log.info("certs_init.step.done", step="backend_valkey_client")

        if console_tls_mode == "self_signed":
            log.info("certs_init.step.start", step="console")
            console_tls_dir.mkdir(parents=True, exist_ok=True)
            console_cert_path = console_tls_dir / "console.pem"
            console_key_path = console_tls_dir / "console-key.pem"
            fingerprint = ensure_console_cert(
                str(console_cert_path),
                str(console_key_path),
                fim_public_hosts=fim_public_hosts,
            )
            _chown(console_cert_path, _CONSOLE_UID, _CONSOLE_GID)
            _chown(console_key_path, _CONSOLE_UID, _CONSOLE_GID)
            log.info(
                "certs_init.step.done", step="console", sha256_fingerprint=fingerprint
            )
        else:
            log.info(
                "certs_init.step.skipped", step="console", console_tls_mode=console_tls_mode
            )
    except Exception as exc:  # noqa: BLE001 — this is the process boundary; log and exit non-zero.
        log.error("certs_init.failed", reason=str(exc))
        return 1

    log.info("certs_init.done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
