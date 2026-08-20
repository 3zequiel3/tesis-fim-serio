#!/usr/bin/env python3
"""Emite el certificado de servidor de Valkey firmado por la CA del backend.

POR QUÉ EXISTE
    El laboratorio corre `valkey://` (texto plano), pero RN-115 y D17 exigen
    `valkeys://` con verificación de hostname. Sin un certificado de servidor
    para Valkey, el canal no se puede cifrar y el ítem 55 del Cap. 5 (captura
    .pcap) sólo puede evidenciar tráfico legible — lo contrario de lo que el
    capítulo afirma.

    Este script cierra ese hueco emitiendo el cert que falta, firmado por la
    misma CA que ya usa el bootstrap de agentes (`/certs/ca.pem`).

QUÉ EMITE
    /certs/valkey.pem      — certificado de servidor, SAN: valkey, localhost
    /certs/valkey-key.pem  — clave privada Ed25519, sin passphrase

    El SAN es obligatorio: el agente conecta con `ssl_check_hostname=True`
    (agent/transport.py, D17), así que un cert sin SAN=valkey es rechazado.
    Se incluye `localhost` para poder probar desde el host.

USO
    docker compose exec -T backend python /app/scripts/emitir_cert_valkey.py

    (o montar el script; corre dentro del contenedor del backend porque ahí
    viven la CA y la librería `cryptography`.)

IDEMPOTENCIA
    Reemplaza los archivos si ya existen. Emitir de nuevo invalida las
    conexiones TLS en curso hasta que Valkey recargue.
"""
from __future__ import annotations

import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CERTS = pathlib.Path("/certs")
VALIDEZ_DIAS = 90


def main() -> int:
    ca_cert_path = CERTS / "ca.pem"
    ca_key_path = CERTS / "ca-key.pem"
    if not ca_cert_path.exists() or not ca_key_path.exists():
        print(f"ERROR: falta la CA en {CERTS}", file=sys.stderr)
        return 1

    ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
    print(f"CA   : {ca_cert.subject.rfc4514_string()}  (clave {type(ca_key).__name__})")

    key = ed25519.Ed25519PrivateKey.generate()
    ahora = datetime.now(timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "valkey")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(minutes=5))
        .not_valid_after(ahora + timedelta(days=VALIDEZ_DIAS))
        # SAN obligatorio: el agente valida hostname (D17).
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("valkey"), x509.DNSName("localhost")]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
        .sign(ca_key, None)  # Ed25519 no lleva algoritmo de hash explícito
    )

    (CERTS / "valkey.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (CERTS / "valkey-key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    # Valkey corre con otro uid dentro de su contenedor y necesita leer la clave.
    os.chmod(CERTS / "valkey-key.pem", 0o644)

    print(f"cert : CN=valkey  SAN=valkey,localhost  vence {cert.not_valid_after_utc.date()}")
    print(f"salida: {CERTS/'valkey.pem'} + {CERTS/'valkey-key.pem'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
