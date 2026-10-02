# LANE L9 — tooling para ensayo multianfitrión — evidencia

Rama: `lane/l9-multihost` (worktree `l9-multihost`, base `lane/l8-valkey-tls`).

Esta lane NO corre el ensayo real de dos hosts (eso son las Fases 3-7 del
runbook, pendientes de ejecución manual en hardware real). Prepara y
verifica el TOOLING: SANs configurables en los certs, el override de
compose multihost, los scripts de `scripts/multihost/`, y un dry-run
completo de un solo host que ejercita ese tooling de punta a punta.

## Qué se implementó

- `backend/app/core/pki.py`: `parse_extra_sans()` (formato `IP:`/`DNS:`) y
  `ensure_ca(..., extra_sans=...)` — el cert de servidor del backend ahora
  puede llevar SANs adicionales (IP/hostname LAN real) sin perder los fijos
  (`backend`, `fim-backend`, `localhost`). El mismo cert pasa a llevar EKU
  `SERVER_AUTH + CLIENT_AUTH` (antes sólo `SERVER_AUTH`) — se reutiliza como
  identidad de cliente TLS hacia Valkey (L8, `app.core.valkey._tls_kwargs`);
  ningún test lo impedía y ni OpenSSL ni Valkey exigen EKU estricto por
  default, pero es más correcto declararlo.
- `backend/app/core/config.py`: nuevo `fim_extra_sans: str = ""`, vacío por
  default (no cambia el laboratorio de un solo host).
- `backend/app/main.py`: pasa `settings.fim_extra_sans` a `ensure_ca()`.
- `scripts/emitir_cert_valkey.py`: mismo parseo de `FIM_EXTRA_SANS` para el
  cert de servidor de Valkey. **Bug encontrado y corregido durante el
  dry-run**: el cert nunca llevaba `AuthorityKeyIdentifier` — OpenSSL 3.x
  rechaza la cadena con `Missing Authority Key Identifier` en cuanto se usa
  contra un peer TLS real (nunca se manifestaba en tests, sólo al conectar
  el backend real a un Valkey real con este cert).
- `docker-compose.multihost.yml`: override que publica SOLO el listener
  mTLS del backend (8443) y Valkey TLS (6380) en una IP LAN configurable
  (`FIM_HOST_IP`, default `192.168.1.43`); ni PostgreSQL ni Valkey en texto
  plano se publican; API HTTP y frontend quedan en `127.0.0.1`. Usa la
  etiqueta `!override` de la Compose Specification para REEMPLAZAR — no
  concatenar — los bindings `0.0.0.0` del compose base (confirmado con
  Docker Compose v5.5.0). Puertos publicados también parametrizables
  (`FIM_MTLS_PORT`/`FIM_API_PORT`/`FIM_FRONTEND_PORT`/`FIM_VALKEY_TLS_PORT`)
  para poder correr un dry-run sin chocar con otro stack en el mismo host.
- `scripts/multihost/`: `server-prepare.sh`, `agent-config.yaml.example`,
  `collect-server-evidence.sh`, `collect-agent-evidence.sh`,
  `latency-run.sh`, `latency-server-export.sh`, `latency_query.sql`.
- `.v10-evidence/l9/RUNBOOK_PHASES_3_7.md`: Fases 3-7 del ensayo A-3, en
  español, con comandos exactos y salidas esperadas.

## Tests nuevos

- `backend/tests/test_pki_extra_sans.py` (10 tests): `parse_extra_sans`,
  SANs fijos + adicionales, EKU completo, idempotencia (no regenera con los
  mismos SANs, sí regenera si cambian).
- `scripts/tests/test_emitir_cert_valkey.py` (9 tests): mismo parseo,
  emisión con SAN adicional, y la regresión del `AuthorityKeyIdentifier`.

## RED → GREEN

- `san-eku.red.log`: los 19 tests nuevos corridos contra el código
  PRE-cambio (`git stash` de `pki.py`/`config.py`/`main.py`/
  `emitir_cert_valkey.py`) → **17 failed, 2 passed** (los 2 que pasan son
  los que confirman que SIN `extra_sans` el comportamiento no cambia).
- `san-eku.green.log`: mismos archivos, código restaurado (`git stash pop`)
  → **19 passed**.

## Dry-run de un solo host (`dry-run/`) — NO es una corrida de dos hosts

Todo bajo `dry-run/` es un smoke test funcional en UN SOLO host (esta
sandbox), NO el ensayo real de dos equipos físicos:

- Se levantó el stack completo (`db`+`valkey`+`backend`) con
  `docker-compose.yml` + `docker-compose.tls.yml` +
  `docker-compose.multihost.yml`, `FIM_HOST_IP=127.0.0.1`, puertos
  alternativos (18443/18000/18080/16380) para no chocar con el stack de
  desarrollo del propio repo que ya estaba corriendo en este host
  (`tesis-fim-serio-backend-1` en 8000/8443 — NUNCA se tocó).
- Se emitió el cert de Valkey con `FIM_EXTRA_SANS=IP:127.0.0.1` y se
  confirmó (`openssl x509 -text`) que el cert del backend lleva el mismo
  SAN y el EKU dual.
- Se registró un agente (`dryrun-remote-agent`) y se corrió un contenedor
  separado con `fim-agent:dev` y `--network host`, apuntando a
  `https://127.0.0.1:18443` / `valkeys://127.0.0.1:16380` — es decir,
  ejerciendo el mismo camino que usaría un host remoto real (puertos
  publicados, no el nombre del contenedor Docker interno). Bootstrap mTLS
  exitoso, heartbeat publicado por Valkey TLS.
- `server-evidence/`: salida completa de `collect-server-evidence.sh`
  (positivos + 4 negativos backend, positivo + 4 negativos Valkey,
  hostname mismatch). `agent-evidence/`: lo mismo corrido dentro del
  contenedor del agente dry-run.
- `latency/`: corrida completa de `latency-run.sh` (100 modificaciones a
  10 ops/s) + `latency-server-export.sh` — **99 de 100 filas** en el CSV
  (coalescencia de escrituras muy rápidas sobre el mismo archivo, no un
  error — ver nota en el propio runbook).
- **Hallazgo de metodología, ya corregido en los scripts**: con TLS 1.3 hay
  una carrera real entre "el cliente cierra por EOF de stdin" y "el
  servidor manda su alerta de rechazo" — `openssl s_client </dev/null`
  puede terminar con "DONE" limpio aunque la conexión haya sido
  rechazada. `collect-server-evidence.sh`/`collect-agent-evidence.sh`
  usan `timeout N openssl s_client ... -ign_eof <<< "$PROBE"`, que da un
  resultado estable y verificado repetidas veces: una respuesta de
  aplicación real (aceptado) vs. `unexpected eof while reading` o una
  línea `SSL alert number ...` (rechazado).
- Teardown: `docker compose ... down -v` + `docker rm -f` del contenedor
  del agente dry-run. Confirmado con `docker ps -a`/`volume ls`/
  `network ls` filtrando por `l9-multihost`/`dryrun`: cero recursos
  residuales. El stack de desarrollo pre-existente del repo
  (`tesis-fim-serio-*`) siguió corriendo sin interrupciones.

## Verificación

- Contenedores propios: `fim-l9-db` (postgres:18.3, 127.0.0.1:55469),
  `fim-l9-valkey` (valkey/valkey:9.0.3, 127.0.0.1:56369).
- Backend (texto plano): **628 passed, 4 skipped** (`verification/backend-full.log`)
  — baseline L8 618+4, delta = las 10 tests nuevas de
  `test_pki_extra_sans.py`.
- Backend con `TEST_VALKEY_TLS=1`: **632 passed** (`verification/backend-full-with-tls.log`)
  — baseline L8 622, mismo delta de +10.
- Agente: **513 passed, 1 skipped** (`verification/agent-full.log`) —
  idéntico al baseline, sin cambios en `agent/`.
- `scripts/check_spec_integrity.py`: **OK** — 44 main specs, 249
  requisitos (`verification/spec-integrity.log`).

## Qué falta para la corrida real de dos hosts

Ejecutar `RUNBOOK_PHASES_3_7.md` en hardware real: laptop Linux
(192.168.1.43) como servidor central, PC Windows con Ubuntu 24.04 en WSL2
como agente nativo (`agent/install.sh` + systemd). Todo lo demás (SANs,
override de compose, scripts de recolección de evidencia, latencia) ya
está construido y probado funcionalmente en este dry-run.
