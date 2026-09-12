"""
Integration lab — L8: mTLS real del backend hacia Valkey (D17/RN-115).

A diferencia de test_valkey_tls.py (unit, from_url mockeado), este módulo
levanta un valkey/valkey:9.0.3 REAL en un contenedor propio, con una CA y
certs de servidor/cliente self-signed generados en un directorio temporal
(nunca se escriben en el repo ni se archivan como evidencia), y prueba:

  (a) el helper del backend (app.core.valkey) conecta con mTLS y hace
      XADD/XREADGROUP sobre un stream real.
  (b) una conexión SIN certificado de cliente es rechazada por el servidor
      (--tls-auth-clients yes).
  (c) un certificado de cliente firmado por una CA que Valkey NO conoce es
      rechazado.
  (d) un mismatch de hostname (cert sin SAN para la IP usada) es rechazado
      por ssl_check_hostname=True, aun con CA y cert de cliente válidos.

Gateado por TEST_VALKEY_TLS=1 — requiere Docker. Se salta (no falla) si la
variable no está seteada o si Docker no está disponible.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import time
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fim:test@localhost:5432/fim_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379")
os.environ.setdefault("JWT_SECRET_CURRENT", "test-secret-current-32-chars-xxxxx")
os.environ.setdefault("JWT_SECRET_PREVIOUS", "")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")

pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_VALKEY_TLS") != "1",
    reason="Lab real de Valkey+mTLS — opt-in con TEST_VALKEY_TLS=1 (requiere Docker)",
)

_LAB_PORT = 56380
_LAB_HOST_DNS = "localhost"  # coincide con el SAN del cert de servidor
_LAB_HOST_MISMATCH = "127.0.0.1"  # NO está en el SAN del cert de servidor


def _make_ca():
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.x509.oid import NameOID

    key = Ed25519PrivateKey.generate()
    now = datetime.datetime.now(datetime.timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fim-l8-lab-ca")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False, content_commitment=False, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False,
        )
        .sign(key, None)
    )
    return key, cert


def _make_leaf(ca_key, ca_cert, *, cn: str, san_dns: list[str], client_auth: bool, server_auth: bool):
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = Ed25519PrivateKey.generate()
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False,
        )
    )
    if san_dns:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(name) for name in san_dns]), critical=False
        )
    eku = []
    if server_auth:
        eku.append(ExtendedKeyUsageOID.SERVER_AUTH)
    if client_auth:
        eku.append(ExtendedKeyUsageOID.CLIENT_AUTH)
    if eku:
        builder = builder.add_extension(x509.ExtendedKeyUsage(eku), critical=False)
    cert = builder.sign(ca_key, None)
    return key, cert


def _write_pem(path, key, cert=None):
    from cryptography.hazmat.primitives import serialization

    if cert is not None:
        path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    else:
        path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )


@pytest.fixture(scope="module")
def lab_certs(tmp_path_factory):
    """Trusted CA + server cert (SAN=localhost) + good client cert, plus an
    UNTRUSTED CA + client cert signed by it (for the wrong-CA rejection case).
    Everything lives under a pytest tmp_path — never committed, never copied
    into the evidence directory.
    """
    certs_dir = tmp_path_factory.mktemp("fim_l8_valkey_tls_certs")
    # pytest crea tmp_path con 0700 (sólo el owner) — el contenedor valkey
    # corre con un UID no-root y necesita poder atravesar/leer el directorio
    # montado en /certs, no sólo los archivos individuales.
    os.chmod(certs_dir, 0o755)

    ca_key, ca_cert = _make_ca()
    _write_pem(certs_dir / "ca.pem", ca_key, ca_cert)
    _write_pem(certs_dir / "ca-key.pem", ca_key)

    server_key, server_cert = _make_leaf(
        ca_key, ca_cert, cn="fim-l8-valkey-lab", san_dns=[_LAB_HOST_DNS],
        client_auth=False, server_auth=True,
    )
    _write_pem(certs_dir / "server.pem", server_key, server_cert)
    _write_pem(certs_dir / "server-key.pem", server_key)
    os.chmod(certs_dir / "server-key.pem", 0o644)  # el uid del contenedor valkey debe poder leerla

    client_key, client_cert = _make_leaf(
        ca_key, ca_cert, cn="fim-backend-lab-client", san_dns=[], client_auth=True, server_auth=False,
    )
    _write_pem(certs_dir / "client.pem", client_key, client_cert)
    _write_pem(certs_dir / "client-key.pem", client_key)

    # CA no confiable — para el caso (c).
    bad_ca_key, bad_ca_cert = _make_ca()
    bad_client_key, bad_client_cert = _make_leaf(
        bad_ca_key, bad_ca_cert, cn="fim-backend-lab-client-untrusted-ca", san_dns=[],
        client_auth=True, server_auth=False,
    )
    _write_pem(certs_dir / "client-untrusted-ca.pem", bad_client_key, bad_client_cert)
    _write_pem(certs_dir / "client-untrusted-ca-key.pem", bad_client_key)

    return certs_dir


@pytest.fixture(scope="module")
def valkey_tls_lab(lab_certs):
    """Start valkey/valkey:9.0.3 in a throwaway container bound to
    127.0.0.1:56380 with --tls-auth-clients yes, tear it down afterwards.
    """
    container_name = f"fim-l8-valkey-tls-lab-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)

    run_cmd = [
        "docker", "run", "-d", "--name", container_name,
        "-p", f"127.0.0.1:{_LAB_PORT}:6380",
        "-v", f"{lab_certs}:/certs:ro",
        "valkey/valkey:9.0.3",
        "valkey-server",
        "--port", "0",
        "--tls-port", "6380",
        "--tls-cert-file", "/certs/server.pem",
        "--tls-key-file", "/certs/server-key.pem",
        "--tls-ca-cert-file", "/certs/ca.pem",
        "--tls-auth-clients", "yes",
    ]
    result = subprocess.run(run_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"No se pudo levantar el contenedor Valkey TLS de laboratorio: {result.stderr.strip()}")

    try:
        _wait_for_port(_LAB_HOST_DNS, _LAB_PORT, container_name)
        yield container_name
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _wait_for_port(host: str, port: int, container_name: str, timeout: float = 20.0) -> None:
    import socket

    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError as exc:  # pragma: no cover - depende del timing del contenedor
            last_exc = exc
            time.sleep(0.5)
    logs = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True)
    pytest.fail(
        f"Valkey TLS lab no abrió el puerto {port} en {timeout}s: {last_exc}\n--- docker logs ---\n{logs.stdout}\n{logs.stderr}"
    )


# ── (a) happy path: helper del backend conecta y XADD/XREADGROUP funcionan ──


def test_a_backend_helper_connects_and_streams_work(valkey_tls_lab, lab_certs, monkeypatch):
    import app.core.valkey as valkey_mod

    # Mutamos app.core.valkey.settings (la instancia que _tls_kwargs() lee de
    # verdad), no un `from app.core.config import settings` fresco: otro test
    # module (test_notification_settings.py) hace `importlib.reload(app.core.config)`
    # y deja app.core.config.settings apuntando a OTRA instancia por el resto de
    # la sesión — un import fresco acá quedaría desincronizado de lo que
    # app.core.valkey realmente usa.
    settings = valkey_mod.settings

    monkeypatch.setattr(settings, "ca_cert_path", str(lab_certs / "ca.pem"))
    monkeypatch.setattr(settings, "backend_cert_path", str(lab_certs / "client.pem"))
    monkeypatch.setattr(settings, "backend_key_path", str(lab_certs / "client-key.pem"))

    url = f"valkeys://{_LAB_HOST_DNS}:{_LAB_PORT}"
    valkey_mod.init_valkey(url)
    try:
        client = valkey_mod.get_valkey_client()
        stream = "fim:l8:lab:stream"
        group = "fim:l8:lab:group"

        msg_id = client.xadd(stream, {"event": "l8-mtls-lab"})
        assert msg_id

        client.xgroup_create(stream, group, id="0")
        entries = client.xreadgroup(group, "consumer-1", {stream: ">"}, count=10)
        assert entries, "XREADGROUP no devolvió el mensaje publicado por XADD"
        _, messages = entries[0]
        assert messages[0][0] == msg_id
        assert messages[0][1]["event"] == "l8-mtls-lab"
    finally:
        valkey_mod.close_valkey()


# ── (b) sin certificado de cliente → rechazado ───────────────────────────────


def test_b_connection_without_client_cert_is_rejected(valkey_tls_lab, lab_certs):
    import valkey as valkey_pkg
    from valkey.exceptions import ConnectionError as ValkeyConnectionError

    client = valkey_pkg.Valkey.from_url(
        f"valkeys://{_LAB_HOST_DNS}:{_LAB_PORT}",
        ssl_ca_certs=str(lab_certs / "ca.pem"),
        ssl_check_hostname=True,
        decode_responses=True,
        socket_timeout=5,
    )
    with pytest.raises(ValkeyConnectionError):
        client.ping()


# ── (c) cert firmado por CA no confiable → rechazado ─────────────────────────


def test_c_client_cert_from_untrusted_ca_is_rejected(valkey_tls_lab, lab_certs):
    import valkey as valkey_pkg
    from valkey.exceptions import ConnectionError as ValkeyConnectionError

    client = valkey_pkg.Valkey.from_url(
        f"valkeys://{_LAB_HOST_DNS}:{_LAB_PORT}",
        ssl_certfile=str(lab_certs / "client-untrusted-ca.pem"),
        ssl_keyfile=str(lab_certs / "client-untrusted-ca-key.pem"),
        ssl_ca_certs=str(lab_certs / "ca.pem"),
        ssl_check_hostname=True,
        decode_responses=True,
        socket_timeout=5,
    )
    with pytest.raises(ValkeyConnectionError):
        client.ping()


# ── (d) hostname mismatch → rechazado por ssl_check_hostname=True ───────────


def test_d_hostname_mismatch_is_rejected(valkey_tls_lab, lab_certs):
    import valkey as valkey_pkg
    from valkey.exceptions import ConnectionError as ValkeyConnectionError

    client = valkey_pkg.Valkey.from_url(
        f"valkeys://{_LAB_HOST_MISMATCH}:{_LAB_PORT}",  # server cert SAN solo tiene "localhost"
        ssl_certfile=str(lab_certs / "client.pem"),
        ssl_keyfile=str(lab_certs / "client-key.pem"),
        ssl_ca_certs=str(lab_certs / "ca.pem"),
        ssl_check_hostname=True,
        decode_responses=True,
        socket_timeout=5,
    )
    with pytest.raises(ValkeyConnectionError):
        client.ping()
