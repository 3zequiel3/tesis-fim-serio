# LANE L8 — backend mTLS hacia Valkey — evidencia

Rama: `lane/l8-valkey-tls` (worktree `l8-valkey-tls`, base `v10-base`).

## Qué se implementó

- `backend/app/core/valkey.py`: nuevo helper `_tls_kwargs(url)` — para
  `valkeys://`/`rediss://` arma `ssl_certfile`/`ssl_keyfile`/`ssl_ca_certs`/
  `ssl_check_hostname=True` reutilizando `settings.backend_cert_path` /
  `settings.backend_key_path` / `settings.ca_cert_path` (el mismo cert/key que
  el backend ya usa como servidor mTLS de agentes en `app/core/pki.py`); falla
  rápido con `RuntimeError` si el esquema es TLS y falta algún path. Esquemas
  en texto plano no cambian. Se agregó `build_async_valkey_client(url)`,
  factory compartida por `init_async_valkey()` y por el cliente async dedicado
  de los consumers en `app/main.py`.
- `backend/app/main.py`: el cliente async dedicado del lifespan (línea ~74)
  pasó de `avalkey.Valkey.from_url(...)` directo a
  `build_async_valkey_client(settings.valkey_url)` — mismo camino de TLS que
  el resto del backend.
- `docker-compose.tls.yml`: sin variables nuevas — comentario documentando que
  CA_CERT_PATH/BACKEND_CERT_PATH/BACKEND_KEY_PATH (ya definidas en
  `docker-compose.yml`, líneas 128-131) son las que el helper reutiliza.
- Tests nuevos: `backend/tests/test_valkey_tls.py` (unit, from_url mockeado) y
  `backend/tests/test_valkey_tls_integration.py` (lab real, gateado por
  `TEST_VALKEY_TLS=1`).

## Settings usadas (ya existentes, sin variables nuevas)

`ca_cert_path`, `backend_cert_path`, `backend_key_path` (`backend/app/core/config.py`).

## Contenedores propios de esta lane

- `fim-l8-db` — postgres:18.3, 127.0.0.1:55468, password aleatorio (no
  archivado — recuperable con `docker inspect fim-l8-db` mientras el
  contenedor viva).
- `fim-l8-valkey` — valkey/valkey:9.0.3, 127.0.0.1:56368 (texto plano, para la
  suite completa del backend).
- `fim-l8-valkey-tls-lab-<hex>` — valkey/valkey:9.0.3 efímero, creado y
  destruido por el fixture `valkey_tls_lab` de
  `test_valkey_tls_integration.py`, 127.0.0.1:56380, `--tls-auth-clients yes`.
  No queda ninguno corriendo al terminar la suite (`docker rm -f` en el
  `finally` del fixture).

## RED → GREEN (unit, TDD)

- `red/test_valkey_tls.red.log`: `test_valkey_tls.py` corrido contra el código
  PRE-cambio (`git stash` de `valkey.py`/`main.py`) → **15 failed, 1 passed**
  (ImportError de `_tls_kwargs`, kwargs TLS ausentes, `build_async_valkey_client`
  inexistente, no se lanza `RuntimeError` con certs faltantes).
- `green/test_valkey_tls.green.log`: mismo archivo, código restaurado
  (`git stash pop`) → **16 passed**.

## Bug encontrado y corregido durante el lab de integración

1. **Extensiones X.509 faltantes**: los primeros certs de laboratorio (CA +
   servidor) generados por el script del lab no incluían
   `SubjectKeyIdentifier` (CA) / `AuthorityKeyIdentifier` (leaf) — OpenSSL 3.x
   rechaza la cadena con `CERTIFICATE_VERIFY_FAILED: Missing Authority Key
   Identifier`. Corregido replicando el patrón ya usado en
   `backend/app/core/pki.py`.
2. **Permisos del directorio `tmp_path`**: pytest crea `tmp_path` con `0700`
   (sólo el owner) — el UID no-root del contenedor `valkey` no podía ni
   *atravesar* el directorio montado en `/certs` (`Permission denied` al
   cargar `server.pem`, aunque el archivo en sí era legible). Corregido con
   `os.chmod(certs_dir, 0o755)` en el fixture `lab_certs`.
3. **Bug de identidad de `settings` entre módulos de test** (no es un bug de
   producción): `backend/tests/core/test_notification_settings.py` hace
   `importlib.reload(app.core.config)`, que reasigna
   `app.core.config.settings` a una instancia NUEVA para el resto de la
   sesión de pytest. `app.core.valkey` importó `settings` en su propio
   namespace al cargar el módulo (antes de ese reload) y nunca se entera del
   cambio — así que un test que hiciera `from app.core.config import
   settings` DESPUÉS de ese reload mutaba un objeto distinto del que
   `_tls_kwargs()` lee. Sólo se manifestaba corriendo la suite COMPLETA (5
   tests fallaban únicamente ahí, nunca corriendo el archivo aislado).
   Corregido en los dos archivos de test nuevos: en vez de
   `from app.core.config import settings`, usan `app.core.valkey.settings` —
   la referencia que el código bajo prueba realmente usa. No se tocó
   `test_notification_settings.py` ni el patrón de import de `app/main.py` /
   `app/core/valkey.py` (está fuera del alcance de esta lane y el reload ahí
   es intencional para probar defaults sensibles a variables de entorno).

## Lab TLS real — resultados (a)-(d)

`tls_lab.log` (pytest) y `tls_lab_reasons.log` (motivo textual de cada
rechazo, capturado con un script standalone que reutiliza los mismos
fixtures):

| Caso | Resultado | Motivo TLS exacto |
|---|---|---|
| (a) helper del backend, cert válido, host correcto | **ACEPTADO** — XADD + XREADGROUP devuelven el mensaje publicado | — |
| (b) sin certificado de cliente | **RECHAZADO** | `SSL: TLSV13_ALERT_CERTIFICATE_REQUIRED` |
| (c) cert de cliente firmado por CA no confiable | **RECHAZADO** | `SSL: TLSV1_ALERT_UNKNOWN_CA` |
| (d) hostname mismatch (CA y cert válidos, host fuera del SAN) | **RECHAZADO** | `CERTIFICATE_VERIFY_FAILED: IP address mismatch` |

`backend/tests/test_valkey_tls_integration.py` — **4 passed** (gateado por
`TEST_VALKEY_TLS=1`, requiere Docker). Certs y CAs son self-signed Ed25519
generados en `tmp_path` (nunca escritos en el repo, nunca copiados a esta
carpeta de evidencia — sólo quedan los logs de texto).

## Comandos exactos (reproducibles desde la raíz del worktree)

```bash
PW=$(docker inspect fim-l8-db --format '{{range .Config.Env}}{{println .}}{{end}}' | grep POSTGRES_PASSWORD | sed 's/.*=//')

# Backend completo (con TLS lab incluido)
PYTHONPATH=$PWD/backend \
TEST_DATABASE_URL="postgresql+psycopg://fim:${PW}@127.0.0.1:55468/fim_test" \
TEST_VALKEY_URL="valkey://127.0.0.1:56368" \
TEST_VALKEY_TLS=1 \
[HOME]/Facultad/tesis/tesis-fim-serio/backend/.venv/bin/pytest -p no:cacheprovider backend/tests -q

# Agente completo
PYTHONPATH=$PWD \
[HOME]/Facultad/tesis/tesis-fim-serio/backend/.venv/bin/pytest -p no:cacheprovider agent/tests -q

# Integridad de specs (D47/RN-141)
python3 scripts/check_spec_integrity.py
```

## Totales finales

- Backend (texto plano, `TEST_VALKEY_TLS` sin setear): **618 passed, 4 skipped**
  (`backend-full.log` / `.junit.xml`) — baseline v10-base era 602 passed; el
  delta es exactamente las 16 unit tests nuevas + 4 tests de integración
  (skipped sin el flag).
- Backend con `TEST_VALKEY_TLS=1`: **622 passed, 0 skipped**
  (`backend-full-with-tls.log` / `.junit.xml`).
- Agente: **513 passed, 1 skipped** (`agent-full.log` / `.junit.xml`) —
  idéntico al baseline v10-base, sin cambios en `agent/`.
- `scripts/check_spec_integrity.py`: **OK** — 44 main specs, 249 requisitos,
  sin problemas (`spec-integrity.log`).

## Qué falta para una corrida real de dos hosts

- Esta lane deja al **backend** capaz de hablar `valkeys://` con su propio
  cert/key CA-issued. El **agente** ya lo hacía (`agent/transport.py`,
  D17/RN-115, preexistente).
- Falta emitir el cert de SERVIDOR de Valkey en el entorno real de dos hosts
  (`scripts/emitir_cert_valkey.py`, SAN debe incluir el hostname/IP real que
  use `VALKEY_URL` en ese despliegue — hoy sólo cubre `valkey`/`localhost`
  para docker-compose).
- No se tocó la política D20 (warning de texto plano) para el backend — el
  guard hoy sólo existe en `agent/transport.py`/`AgentConfig`. Si se quiere
  visibilidad simétrica del lado backend, es una decisión de producto
  separada (no estaba en el alcance de esta lane: "plaintext schemes
  unchanged").
- El `backend_cert_path`/`backend_key_path` reutilizado tiene
  `ExtendedKeyUsage=[SERVER_AUTH]` únicamente (emitido en
  `_ensure_backend_cert`, `app/core/pki.py`) — funciona como cert de cliente
  Valkey porque ni OpenSSL ni Valkey validan EKU del lado servidor por
  default (confirmado por el lab: (a) fue ACEPTADO), pero si en el futuro se
  quisiera imponer verificación estricta de EKU en Valkey, haría falta
  agregar `CLIENT_AUTH` a ese cert (mismo patrón que
  `scripts/emitir_cert_valkey.py` ya usa para el cert de servidor de Valkey,
  que lleva ambos).
