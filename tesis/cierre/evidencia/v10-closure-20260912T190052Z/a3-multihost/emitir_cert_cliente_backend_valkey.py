#!/usr/bin/env python3
"""Emite el certificado de CLIENTE del backend hacia Valkey (ensayo A-3, carril L8).

POR QUÉ EXISTE
    Con `docker-compose.tls.yml`, Valkey exige certificado de cliente
    (`--tls-auth-clients yes`). El agente ya presenta el suyo, pero el backend
    no tiene identidad de cliente:
      - `backend.pem` sólo lleva EKU serverAuth (backend/app/core/pki.py), así
        que Valkey lo rechazaría como cliente.
      - Reusar `valkey.pem` funcionaría, pero el backend se presentaría con la
        identidad del propio servidor Valkey.
    Este script emite una identidad propia, firmada por la misma CA.

QUÉ EMITE
    /certs/backend-valkey.pem      — CN=fim-backend-valkey, EKU sólo clientAuth
    /certs/backend-valkey-key.pem  — clave privada Ed25519, modo 0400

    No lleva SAN: la verificación de hostname aplica al certificado del
    servidor, no al del cliente.

USO (desde la raíz del repositorio, con el backend corriendo)
    docker compose exec -T backend python - < <este archivo>

    Corre dentro del contenedor del backend porque ahí viven la CA y la
    librería `cryptography`. El proceso corre como uid 10001 (app), el mismo
    que usa el backend, así que la clave queda legible sólo para él.

IDEMPOTENCIA
    Reemplaza los archivos si ya existen.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CERTS = pathlib.Path("/certs")
CERT_PATH = CERTS / "backend-valkey.pem"
KEY_PATH = CERTS / "backend-valkey-key.pem"
VALIDEZ_DIAS = 30


def _write_private_key(path: pathlib.Path, data: bytes) -> None:
    # A previous 0400 file cannot be reopened for writing by its owner.
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(path, 0o400)


def main() -> int:
    ca_cert_path = CERTS / "ca.pem"
    ca_key_path = CERTS / "ca-key.pem"
    if not ca_cert_path.exists() or not ca_key_path.exists():
        print(f"ERROR: falta la CA en {CERTS}", file=sys.stderr)
        return 1

    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)

    key = ed25519.Ed25519PrivateKey.generate()
    ahora = datetime.now(timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fim-backend-valkey")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(minutes=5))
        .not_valid_after(ahora + timedelta(days=VALIDEZ_DIAS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),  # type: ignore[arg-type]
            critical=False,
        )
        .sign(ca_key, None)  # type: ignore[arg-type]  # Ed25519: sin hash explícito
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    CERT_PATH.write_bytes(cert_pem)
    os.chmod(CERT_PATH, 0o644)
    _write_private_key(
        KEY_PATH,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )

    fingerprint = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    print(f"CA     : {ca_cert.subject.rfc4514_string()}")
    print("cert   : CN=fim-backend-valkey  EKU=clientAuth")
    print(f"serial : {cert.serial_number:x}")
    print(f"vence  : {cert.not_valid_after_utc.isoformat()}")
    print(f"sha256 : {fingerprint}")
    print(f"salida : {CERT_PATH} (0644) + {KEY_PATH} (0400)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
