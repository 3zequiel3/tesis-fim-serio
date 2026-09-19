# Reproducir la validación de cierre

> Ejecutar sobre un clon de laboratorio y un commit congelado, en una misma sesión de Bash para conservar `RUN_ID` y `EVIDENCE_DIR`. No sobrescribir `resultados/`. Los comandos destructivos se limitan a contenedores/volúmenes de prueba identificados.

## 1. Congelar identidad y crear directorio de evidencia

```bash
cd /ruta/al/repositorio/tesis-fim-serio
git rev-parse HEAD
git status --short
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD)"
EVIDENCE_DIR="docs/cierre/evidencia/$RUN_ID"
mkdir -p "$EVIDENCE_DIR"
printf 'head=%s\nrun_id=%s\n' "$(git rev-parse HEAD)" "$RUN_ID" > "$EVIDENCE_DIR/identidad.txt"
```

Si `git status --short` no está vacío, conservar su salida y no atribuir los resultados sólo al commit.

## 2. Registrar host, kernel, filesystem y reloj

```bash
{
  date --utc --iso-8601=seconds
  timedatectl status
  uname -a
  cat /etc/os-release
  findmnt -T . -o TARGET,SOURCE,FSTYPE,OPTIONS
  lscpu
  free -h
  python3 --version
  docker version
  docker compose version
  node --version
  pnpm --version
} > "$EVIDENCE_DIR/entorno.txt"
```

Para latencia entre dos hosts, registrar sincronización y error máximo de reloj en ambos. Un único host no acredita despliegue multianfitrión.

## 3. Configuración segura de ejemplo

```bash
umask 077
cp .env.example .env
${EDITOR:-vi} .env
```

Definir valores nuevos para `DB_PASSWORD`, JWT, credenciales administrativas y `N8N_ENCRYPTION_KEY`. No imprimirlos ni versionarlos. Para el agente nativo:

```bash
sudo install -o root -g root -m 0600 agent/deploy/env.example /etc/fim-agent/env
sudoedit /etc/fim-agent/env
```

El secreto bootstrap es de un uso. La configuración funcional parte de `agent/deploy/config.yaml.example` y `docs/operations.md`.

## 4. Validar e iniciar el laboratorio

```bash
docker compose config > "$EVIDENCE_DIR/compose-config.txt"
docker compose pull
docker compose --profile app build
docker compose up -d db valkey n8n
docker compose --profile app up -d backend frontend
docker compose ps > "$EVIDENCE_DIR/compose-ps.txt"
curl -fsS http://127.0.0.1:8000/health
```

El Compose principal fija n8n 2.16.1 y no importa el router E2E. La evaluación controlada n8n usa un Compose separado con n8n 2.17.8; no mezclar ambos resultados.

## 5. Aplicar migraciones desde una instalación limpia

```bash
find backend/db/migrations -maxdepth 1 -type f -name '*.sql' -printf '%f\n' | sort
while IFS= read -r migration; do
  docker compose exec -T db psql -v ON_ERROR_STOP=1 -U fim -d fim \
    < "backend/db/migrations/$migration"
done < <(find backend/db/migrations -maxdepth 1 -type f -name '*.sql' -printf '%f\n' | sort)
```

Repetir el bucle para comprobar idempotencia. Registrar stdout/stderr; cualquier error bloquea la validación.

## 6. Instalar y verificar el agente nativo

```bash
sudo bash agent/install.sh
sudoedit /etc/fim-agent/config.yaml
sudo systemctl daemon-reload
sudo systemctl enable --now fim-agent.service
sudo systemctl status fim-agent.service --no-pager
sudo journalctl -u fim-agent.service -n 200 --no-pager
```

Verificar capabilities y rutas de escritura:

```bash
systemctl cat fim-agent.service
pid="$(systemctl show --property=MainPID --value fim-agent.service)"
grep '^Cap' "/proc/$pid/status"
```

Probar detección, restauración y cuarentena por separado. Se requieren `CAP_SYS_ADMIN` y `CAP_DAC_READ_SEARCH` para fanotify/FID; las operaciones de remediación también necesitan permisos reales de escritura sobre cada ruta.

## 7. Ejecutar suites consolidadas

> **Servicios que la suite del backend necesita, y por qué el procedimiento de abajo no alcanza
> tal cual.** `backend/tests/conftest.py` apunta por defecto a
> `postgresql+psycopg://fim:test@localhost:5432/fim_test` y a `valkey://localhost:6379`. Si en esos
> puertos está el laboratorio, la suite entera falla por autenticación —835 errores en la corrida del
> 2026-09-19— porque la contraseña del laboratorio no es `test`. El `conftest` admite
> `TEST_DATABASE_URL` y `TEST_VALKEY_URL` justamente para esto; hay que levantar contenedores propios
> y apuntarlos ahí.
>
> Además, la aplicación levanta el servidor mTLS en el **8443** durante su `lifespan`
> (`backend/app/main.py:92`, puerto fijo en `backend/app/core/pki.py`), de modo que el backend del
> laboratorio tiene que estar detenido mientras corre la suite, y el material TLS se escribe en
> `/certs` —ruta interna del contenedor, no escribible en el anfitrión—, así que las cuatro rutas de
> certificados se redirigen a un directorio propio.
>
> El procedimiento completo, con cada una de esas causas comentada donde se maneja, está en
> `scripts/correr_suites_candidato.sh`. Aun así quedan **8 fallas conocidas** por conflicto de puerto
> entre pruebas que ejecutan el `lifespan` real; el análisis está en
> `evidencia/oficial-cap5-20260917T223823Z/suites/RESULTADO.md`.

```bash
# Servicios aislados para la suite del backend.
docker run --rm -d --name fim-test-pg \
  -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fim_test \
  -p 127.0.0.1:55440:5432 postgres:18.3
docker run --rm -d --name fim-test-valkey \
  -p 127.0.0.1:55441:6379 valkey/valkey:9.0.3

# Liberar 8443/8444, que el lifespan de la aplicación necesita bindear.
docker compose -f docker-compose.yml -f docker-compose.tls.yml stop backend

export TEST_DATABASE_URL='postgresql+psycopg://fim:test@127.0.0.1:55440/fim_test'
export TEST_VALKEY_URL='valkey://127.0.0.1:55441'
export CA_CERT_PATH="$PWD/.suites-certs/ca.pem"
export CA_KEY_PATH="$PWD/.suites-certs/ca-key.pem"
export BACKEND_CERT_PATH="$PWD/.suites-certs/backend.pem"
export BACKEND_KEY_PATH="$PWD/.suites-certs/backend-key.pem"
mkdir -p "$PWD/.suites-certs"
```

```bash
uv venv backend/.venv --python 3.13
uv pip install --python backend/.venv/bin/python \
  -r backend/requirements-dev.txt -r agent/requirements.txt

backend/.venv/bin/pytest agent/tests -q \
  --junitxml="$EVIDENCE_DIR/agente.xml"

(
  cd backend
  .venv/bin/pytest -q --junitxml="../$EVIDENCE_DIR/backend.xml" \
    --cov=app --cov-report=term-missing \
    --cov-report="xml:../$EVIDENCE_DIR/backend-coverage.xml"
)

(
  cd frontend
  pnpm install --frozen-lockfile
  pnpm test -- --run
  pnpm typecheck
  pnpm build
)
```

El reporte debe indicar statements/branches, denominador, exclusiones, versión de coverage y commit. Las dos pruebas opt-in de rate limiting requieren un Valkey real accesible; cualquier omisión debe declararse.

### Verificaciones dirigidas incorporadas después del coverage

Los commits `b70934d` + `b8e9513` corrigen atribución y eventos sin ruta;
`8d37075` liga la baseline aprobada al evento; y `965dcac` reduce de 8 a 5
sentencias SQL por evento. La verificación registrada para la última unidad fue
de **32 pruebas dirigidas PASS**. Para una nueva evaluación, ejecutar los tests
desde un snapshot limpio del commit correspondiente y conservar su JUnit; no
sumar ese conteo a Run 3 ni atribuirlo a una suite consolidada de HEAD.

### Reproducir la verificación de cuarentena

U1 y U2 se verificaron por separado para distinguir cifrado/durabilidad de
retención/migración. Los siguientes comandos usan snapshots limpios y el entorno
virtual del repositorio anfitrión:

```bash
git worktree add --detach /tmp/fim-quarantine-u1-verify b060e5f
PYTHONPATH=/tmp/fim-quarantine-u1-verify \
  backend/.venv/bin/python -m py_compile \
  /tmp/fim-quarantine-u1-verify/agent/quarantine.py \
  /tmp/fim-quarantine-u1-verify/agent/decision.py \
  /tmp/fim-quarantine-u1-verify/agent/commands.py \
  /tmp/fim-quarantine-u1-verify/agent/publisher.py \
  /tmp/fim-quarantine-u1-verify/agent/__main__.py
PYTHONPATH=/tmp/fim-quarantine-u1-verify \
  backend/.venv/bin/pytest -q \
  /tmp/fim-quarantine-u1-verify/agent/tests/test_quarantine.py \
  /tmp/fim-quarantine-u1-verify/agent/tests/test_decision.py \
  /tmp/fim-quarantine-u1-verify/agent/tests/test_commands.py \
  /tmp/fim-quarantine-u1-verify/agent/tests/test_publisher_dispatch_integration.py
git worktree remove /tmp/fim-quarantine-u1-verify

git worktree add --detach /tmp/fim-quarantine-u2-verify 947edb6
PYTHONPATH=/tmp/fim-quarantine-u2-verify \
  backend/.venv/bin/python -m py_compile \
  /tmp/fim-quarantine-u2-verify/agent/quarantine.py \
  /tmp/fim-quarantine-u2-verify/agent/config.py \
  /tmp/fim-quarantine-u2-verify/agent/__main__.py \
  /tmp/fim-quarantine-u2-verify/agent/tests/test_quarantine_maintenance.py
PYTHONPATH=/tmp/fim-quarantine-u2-verify \
  backend/.venv/bin/pytest -q \
  /tmp/fim-quarantine-u2-verify/agent/tests/test_quarantine_maintenance.py \
  /tmp/fim-quarantine-u2-verify/agent/tests/test_quarantine.py \
  /tmp/fim-quarantine-u2-verify/agent/tests/test_agent_config.py
git worktree remove /tmp/fim-quarantine-u2-verify
```

Resultados de referencia: U1 py_compile PASS y 76/76 dirigidas; U2 py_compile
PASS y 50/50 dirigidas. Las suites completas registraron respectivamente
486 PASS/1 SKIP/2 FAIL y 505 PASS/1 SKIP/2 FAIL; los mismos dos fallos se
reprodujeron en la base, por lo que no deben ocultarse ni atribuirse a cuarentena.

Verificar además, sobre filesystem temporal real: artefacto 0400 y opaco,
readback autenticado antes de unlink, reintento idempotente, ruta recreada no
borrada, symlink capturado como objeto, hardlink fail-closed, retención en el
límite, corrupto preservado/degradado y migración legacy reanudable. El default
es 30 días y el rango válido 1..365; el mantenimiento corre al inicio y cada
24 h. Esta prueba no acredita protección frente a root ni borrado seguro del
soporte.

## 8. Reproducir US-09 sobre snapshot limpio

Los commits funcionales son `8039624` y `f08626a`. En un worktree temporal creado desde `f08626a`:

```bash
git worktree add --detach /tmp/fim-us09-verify f08626a
docker run --rm -d --name fim-us09-doc-verify \
  -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fim_test \
  -p 127.0.0.1:55440:5432 postgres:18.3
for _ in $(seq 1 30); do
  docker exec fim-us09-doc-verify pg_isready -U fim -d fim_test && break
  sleep 1
done
PYTHONPATH=/tmp/fim-us09-verify \
  backend/.venv/bin/pytest -q \
  /tmp/fim-us09-verify/agent/tests/test_detector_diff.py
TEST_DATABASE_URL='postgresql+psycopg://fim:test@127.0.0.1:55440/fim_test' \
PYTHONPATH=/tmp/fim-us09-verify/backend \
  backend/.venv/bin/pytest -q \
  /tmp/fim-us09-verify/backend/tests/test_event_listing_contract.py \
  /tmp/fim-us09-verify/backend/tests/test_event_service.py \
  -k 'textual_diff or real_agent_payload or bounds_diff or ignores_non_text_diff or rejects_unsafe_or_non_patch_diff or unknown_returns_404'
docker stop fim-us09-doc-verify
git worktree remove /tmp/fim-us09-verify
```

El contenedor usa credenciales exclusivas del laboratorio. Si una prueba falla, conservar su salida antes de limpiar. No usar solamente hashes como diff. Verificar un texto con varios hunks y un binario descartado legítimamente.

## 9. Reproducir el límite mTLS real

```bash
PYTHONPATH=backend backend/.venv/bin/pytest -q --timeout=20 --noconftest \
  backend/tests/test_mtls_transport.py
PYTHONPATH=backend backend/.venv/bin/pytest -q --noconftest \
  backend/tests/test_c22_pki.py backend/tests/test_agent_cert_renewal.py
PYTHONPATH=. backend/.venv/bin/pytest -q --noconftest \
  agent/tests/test_cert_renewal.py
```

La primera prueba abre un listener local TLS 1.3 y exige: handshake confiable; rechazo sin certificado; rechazo de CA no confiable; rechazo de certificado vencido; cierre del servidor. La revocación de agente/serial se comprueba en autorización de renovación, no como CRL/OCSP del handshake.

Para Valkey TLS, usar el override sólo después de emitir el certificado con SAN `valkey` según `docker-compose.tls.yml`:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml config \
  > "$EVIDENCE_DIR/compose-tls-config.txt"
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d
```

## 10. Reproducir n8n controlada y estado durable

Este Compose usa únicamente datos sintéticos y un receptor SQLite controlado:

```bash
export N8N_ENCRYPTION_KEY="$(openssl rand -hex 32)"
docker compose -f n8n/docker-compose.e2e.yml up -d --wait
PYTHONPATH=backend backend/.venv/bin/python n8n/e2e/send-test-alert.py
curl -fsS http://127.0.0.1:18081/receipts | python3 -m json.tool
docker compose -f n8n/docker-compose.e2e.yml down -v
unset N8N_ENCRYPTION_KEY
```

`down -v` elimina **sólo los volúmenes del laboratorio E2E**. Repetir los escenarios documentados en `n8n/e2e/README.md`: receptor caído debe producir 502, n8n caído debe fallar y ambos deben recuperar a 202. Conservar los cuatro timestamps independientes.

### Unidad B: estado durable y recuperación

Aplicar la migración (la segunda ejecución debe ser idempotente) y correr las nueve pruebas dirigidas: `PG_TEST_URL` usa formato libpq (`postgresql://...`) y `TEST_DATABASE_URL` formato SQLAlchemy (`postgresql+psycopg://...`) contra la misma base aislada:

```bash
psql "$PG_TEST_URL" -v ON_ERROR_STOP=1 \
  -f backend/db/migrations/014_add_alert_delivery_state.sql
psql "$PG_TEST_URL" -v ON_ERROR_STOP=1 \
  -f backend/db/migrations/014_add_alert_delivery_state.sql
PYTHONPATH=backend backend/.venv/bin/pytest -q \
  backend/tests/test_notifications.py::test_notify_event_delivers_on_first_attempt \
  backend/tests/test_notifications.py::test_notify_event_retry_3x_then_dlq \
  backend/tests/test_notifications.py::test_log_only_no_entrega_si_hay_primarios_configurados \
  backend/tests/test_notifications.py::test_n8n_retry_ladder_finishes_before_real_fallback \
  backend/tests/test_notifications.py::test_persisted_retry_recovers_after_interrupted_task \
  backend/tests/test_notifications.py::test_terminal_dlq_entry_is_not_retried_on_restart \
  backend/tests/test_notifications.py::test_retry_alert_resets_dlq_state_and_reschedules \
  backend/tests/test_notifications.py::test_retry_alert_delivers_and_leaves_the_dlq \
  backend/tests/test_c31_backend_event_correctness.py::test_fix01_primary_fails_dlq_activated
```

La evaluación runtime registrada en `n8n/e2e/evidence/20260910-durable-fallback.json` usó PostgreSQL 18.3 limpio y el receptor controlado: cuatro intentos n8n fallidos, fallback webhook exitoso; fallo total persistido; y recuperación desde un proceso nuevo con el mismo `notification_id`. Los delays se inyectaron como 0 sólo para el ensayo; producción mantiene 5/30/120 s.

El driver runtime ad hoc no quedó persistido como script. Por eso el JSON es evidencia del ensayo ejecutado, pero la reproducción exacta de los tres escenarios exige convertir ese driver en un script versionado. No sustituirlo por un mock ni afirmar que SMTP fue probado: el único fallback externo ejecutado fue el webhook controlado.

## 11. Repetir operaciones sin evento con instrumentación

La corrida válida de referencia está en
`docs/cierre/evidencia/absence-20260910T052521Z-r2/`: 60 operaciones,
50 eventos totalmente correlacionados y persistidos, 10 retornos a la baseline
aprobada descartados legítimamente y 0 ausencias nuevas inexplicadas. Es una
nueva evaluación del comportamiento actual; **no** reconstruye la causalidad
runtime de las 19 ausencias históricas de B3/B5.

Crear siempre un `RUN_ID` nuevo. Precrear C0 con el agente detenido; después
iniciar el agente, promover C0 mediante `rescan_baseline` y recién entonces
ejecutar las operaciones contadas. `ADMIN_TOKEN` y `AGENT_ID` deben pertenecer
al laboratorio aislado y no deben guardarse en la evidencia.

```bash
RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
EVIDENCE_DIR="docs/cierre/evidencia/$RUN_ID"
mkdir -p "$EVIDENCE_DIR"

# El agente debe estar detenido mientras se precrean las diez baseline C0.
docker compose --profile app stop agent
python3 - "$RUN_ID" <<'PY'
import sys
from pathlib import Path
from scripts.bateria_reversion import C0, safe_run_slug, scoped_run_path, write_bytes

root = Path("fim-watch")
slug = safe_run_slug(sys.argv[1])
for repetition in range(1, 11):
    write_bytes(scoped_run_path(root, "baseline", slug, repetition), C0)
PY

FIM_EXPERIMENT_RUN_ID="$RUN_ID" \
FIM_EXPERIMENT_TRACE_FILE="/evidence/$RUN_ID/agent_trace.jsonl" \
  docker compose --profile app up -d agent

curl -fsS -X POST "http://127.0.0.1:8000/agents/$AGENT_ID/rescan" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"force":false}' \
  > "$EVIDENCE_DIR/rescan-request.json"

# Esperar el command_ack satisfactorio y verificar en el log del agente que
# commands.rescan_baseline.done ocurrió antes de continuar.

python3 scripts/bateria_reversion.py \
  --dir fim-watch \
  --agent-prefix /watch \
  --run-id "$RUN_ID" \
  --salida "$EVIDENCE_DIR"

python3 scripts/analisis_ausencias.py \
  --operaciones "$EVIDENCE_DIR/bateria9_operaciones.jsonl" \
  --traza "$EVIDENCE_DIR/agent_trace.jsonl" \
  --salida "$EVIDENCE_DIR/bateria9_correlacion.csv" \
  --database-url "$DATABASE_URL"
```

`DATABASE_URL` debe apuntar a la base aislada de esa corrida y mantenerse fuera
de logs. Si no se proporciona, el analizador deja la persistencia backend como
`unknown`; no equivale a una validación completa. No contar operaciones hasta
comprobar en la traza que `baseline_read` informa `present` y el hash C0. La
salida debe incluir por operación:

`operation_id → path sanitizado → hash anterior → baseline vigente → hash posterior → evento kernel → decisión agente → queue ID → stream ID → event ID backend`.

El harness ejecuta diez repeticiones de cambios sucesivos, retorno a baseline,
creación, eliminación y modificación efímera. No sobrescribir B3/B5 históricos
ni sumar los intentos inválidos conservados en
`docs/cierre/evidencia/absence-20260910T051102Z/`.

## 12. Repetir drenaje y deduplicación

La referencia final es
`docs/cierre/evidencia/drenaje-20260910-run4-unit1/`: 3.000/3.000 eventos,
0 rechazos, 0 duplicados, 3.000 `XADD`/lecturas/HMAC/commits/`XACK`/`event_ack`,
cola final 0 y **29,146335596 s (102,928891 eventos/s)**. **CUMPLE** el umbral original
`<30 s` bajo estas condiciones. Run 3 (51,773 s) se conserva como resultado
intermedio y 32,358 s se identifica como proyección previa, nunca medición.

Repetir la evaluación con contenedores locales y credenciales exclusivas del
laboratorio:

```bash
docker run -d --rm --name fim-drain-run4-postgres \
  -e POSTGRES_DB=fim_drain -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=controlled \
  -p 127.0.0.1:55441:5432 postgres:18.3
docker run -d --rm --name fim-drain-run4-valkey \
  -p 127.0.0.1:56380:6379 valkey/valkey:9.0.3

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-drain-run4-repeat"
RUN4_DIR="docs/cierre/evidencia/$RUN_ID"
mkdir -p "$RUN4_DIR"
cp docs/cierre/evidencia/drenaje-20260910-run4-unit1/run_profile.py \
  "$RUN4_DIR/run_profile.py"

until docker exec fim-drain-run4-postgres pg_isready -U fim -d fim_drain; do sleep 1; done
until docker exec fim-drain-run4-valkey valkey-cli ping | grep -q PONG; do sleep 1; done

env PYTHONPATH=backend:. \
  DATABASE_URL=postgresql+psycopg://fim:controlled@127.0.0.1:55441/fim_drain \
  VALKEY_URL=valkey://127.0.0.1:56380/0 \
  JWT_SECRET_CURRENT=controlled-not-a-production-secret \
  RATE_LIMIT_INGEST_EVENTS=100000 \
  RATE_LIMIT_INGEST_WINDOW_SECONDS=60 \
  backend/.venv/bin/python "$RUN4_DIR/run_profile.py" \
  | tee "$RUN4_DIR/stdout.log"

docker stop fim-drain-run4-postgres fim-drain-run4-valkey
```

El rate limit `100000/60 s` pertenece sólo al ensayo; el valor predeterminado de
producción es `100/60 s`. Registrar volumen planificado/real, tasa de generación,
corte/reconexión y timestamps por etapa: cola local, `XADD`, lectura, validación,
commit, `XACK` y ACK del agente. La construcción de la cola se excluye; el tiempo
principal comienza antes del flush de comandos y termina con 3.000 filas
persistidas y cola local vacía.

Conservar HMAC, persistencia PostgreSQL, auditoría, confirmaciones, `XACK` y
borrado durable activos. La cola/ACK está fijada en `7c5afa5` y backend Unidad 1
en `965dcac`. Identificar cada corrida mediante `environment.json` y
`source-manifest.sha256`; conservar cualquier intento inválido por separado y
excluirlo explícitamente de resultados y denominadores.

Contraste histórico, sin reemplazar los datos originales:

- B5: 2.988 eventos en 153 s, 19,529 eventos/s;
- Run 3: 3.000 eventos en 51,773 s, 57,945 eventos/s (**NO CUMPLE**);
- Run 4: 3.000 eventos en 29,146335596 s, 102,928891 eventos/s (**CUMPLE**);
- criterio original: `<30 s`; para 3.000 exige más de 100 eventos/s.

Una repetición crea una evaluación nueva: no sobrescribir `stdout.log`,
`metrics.jsonl`, `summary.json` ni sus manifiestos de la corrida de referencia.

## 13. Ensayo reducido de dos anfitriones

En dos hosts Linux distintos, registrar versiones y relojes; ubicar agente y backend/Valkey en hosts diferentes; habilitar TLS/mTLS; capturar únicamente metadatos sanitizados. Verificar conectividad válida y rechazos negativos. No denominar multianfitrión a dos contenedores del mismo host.

Este ensayo ya se ejecutó una vez como A-3 (dos equipos físicos por LAN doméstica, `docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/`) y una segunda vez, sobre infraestructura real, como A-4 (VPS público + PC del operador, `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/`). Ninguna de las dos corrió sobre el candidato consolidado `7a7ee50`; una repetición sobre ese candidato exige recongelarlo y repetir ambos procedimientos íntegros, no sólo esta sección.

## 13a. Reproducir el despliegue multianfitrión / servidor remoto

La guía operativa completa es `docs/despliegue_servidor_remoto.md`. Resumen de su procedimiento, verificado por lectura completa de esa guía:

1. **Requisitos.** Servidor con Docker Engine + Compose v2, puertos publicables para la consola (80/443 según el modo TLS elegido), 8443 (mTLS agente-backend), 8444 (bootstrap) y 6380 (Valkey TLS); IP pública o nombre DNS. Host monitoreado con systemd, kernel ≥ 5.1 y Python 3.13 exacto (`agent/install.sh` valida la versión antes de crear el venv y admite `--python` para apuntar a un intérprete alternativo cuando el del sistema es otra versión).
2. **Preparar el `.env` del servidor** con `scripts/prepare_server_env.py --fim-public-hosts <ip-o-dominio> --console-tls-mode off|self_signed|provided`; nunca sobrescribe un `.env` existente; las contraseñas generadas se muestran una sola vez.
3. **Elegir el modo de consola** (`off`, `self_signed` o `provided`) según haya sólo IP, un dominio sin certificado, o un certificado real.
4. **Levantar el stack** con `docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d --build`, sin editar ningún YAML; verificar `certs-init` (`Exited (0)` es el resultado esperado) y `n8n` en `healthy`.
5. **Restringir los puertos publicados** insertando reglas en la cadena `DOCKER-USER` (no en `ufw` directamente, porque Docker las evalúa antes) para 8443/8444/6380.
6. **Registrar el agente** con `scripts/register-agent.sh <agent_id>` desde el servidor; exporta la CA, la huella y un secreto de bootstrap de un solo uso.
7. **Instalar el agente** en el host monitoreado con `agent/install.sh --non-interactive --server-host <host> --agent-id <agent_id> --watch-path ... --ca-cert ./fim-ca.pem --ca-fingerprint <huella> --bootstrap-secret-file <archivo>`.
8. **Verificar el despliegue**: `systemctl status fim-agent` activo; bootstrap visible en el log del backend; un cambio en un `watch_path` aparece como evento en la consola; `GET /health/components` reporta `n8n: ok` una vez sano; un `POST` real contra el webhook del enrutador de n8n entrega el canal habilitado.
9. **Reinstalar/actualizar** el agente es idempotente y reemplaza el código instalado sin anidarlo (verificar explícitamente este punto: A-3 documentó un hallazgo abierto de anidamiento con una versión anterior del instalador; A-4 lo corrigió con prueba, hallazgo 14.1/14.3 de su evidencia).
10. **Reset de contraseña de administrador** y **renovación del certificado de consola en modo `provided`** tienen procedimientos explícitos en las secciones 10 y 11 de la guía.

Esta guía es el procedimiento que efectivamente se siguió, con hallazgos y correcciones propios, en A-3 (`docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/README.md`) y A-4 (`docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/README.md`); ver también `docs/cierre/CAMBIOS_PARA_TESIS_V11.md` §4 para la redacción propuesta hacia el cuerpo de la tesis.

## 14. Cerrar y verificar evidencia

```bash
find "$EVIDENCE_DIR" -type f -print0 | sort -z | xargs -0 sha256sum \
  > "$EVIDENCE_DIR/SHA256SUMS"
git rev-parse HEAD >> "$EVIDENCE_DIR/identidad.txt"
git status --short >> "$EVIDENCE_DIR/identidad.txt"

(cd docs/cierre/evidencia/absence-20260910T052521Z-r2 && sha256sum -c SHA256SUMS)
(cd docs/cierre/evidencia/drenaje-20260910-run3 && sha256sum -c SHA256SUMS)
(cd docs/cierre/evidencia/drenaje-20260910-run4-unit1 && sha256sum -c SHA256SUMS)
```

Antes de publicar, sanitizar hostnames, rutas absolutas, payloads, destinatarios, certificados y secretos. Una copia sanitizada recibe nombre y hash nuevos; nunca se reemplaza silenciosamente el original.

## 12. Playwright real para US-03 y US-25

Instalar sólo Chromium y ejecutar cada historia antes del conjunto:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
FIM_E2E_RUN_DIR="../docs/cierre/evidencia/<run>/individual-us03" \
  pnpm exec playwright test e2e/us03-session-refresh.spec.ts
FIM_E2E_RUN_DIR="../docs/cierre/evidencia/<run>/individual-us25" \
  pnpm exec playwright test e2e/us25-bulk-actions.spec.ts
FIM_E2E_RUN_DIR="../docs/cierre/evidencia/<run>/combined" \
  pnpm exec playwright test e2e/us03-session-refresh.spec.ts e2e/us25-bulk-actions.spec.ts
cd ..
python3 scripts/sanitize-playwright-artifacts.py "docs/cierre/evidencia/<run>"
```

El harness usa Vite como frontend actual y proxy same-origin, pero no mockea red: backend, PostgreSQL y Valkey son reales. Cada caso crea un usuario administrador único, elimina exclusivamente su bucket `fim:rl:login:<usuario>:<IP observada>` después del login y borra usuario/auditoría al cerrar. US-25 crea y limpia fixtures DB por IDs/paths únicos. El resultado funcional vigente es exit `0`; los criterios BLOCKED se consultan en `RESULTADO.md` y no se cuentan como PASS.

## Laboratorio efímero aislado — US-03, US-16, US-17 y US-25

**PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA**

```bash
scripts/run-isolated-acceptance-lab.sh
```

El comando usa exclusivamente `docker-compose.acceptance-lab.yml` con un project name aleatorio. Genera secretos, configuración, PKI, estado, baseline y dos archivos vigilados dentro del lab; no lee `.env` para sus valores `FIM_LAB_*`, no publica DB/Valkey, no inicia n8n y deja vacíos todos los canales externos. Ejecuta, en orden: build, health real, cambio de clave CURRENT/PREVIOUS, bootstrap mTLS del agente, los dos casos Playwright individuales y el conjunto.

La trampa de salida siempre corre `docker compose down -v --remove-orphans`, elimina el directorio temporal y compara el inventario del stack principal antes/después. El aislamiento cubre estado, datos y recursos de Compose, no el kernel del host: fanotify puede observar eventos fuera de `/watch`, pero el filtro de alcance los descarta y no se contabilizan como eventos FIM aceptados. El resultado vigente y sus checksums están en `evidencia/us03-us16-us17-us25-isolated-20260910T235332Z/`.

## Playwright dirigido — US-02, US-20 y US-31

El paquete histórico de descubrimiento está en `docs/cierre/evidencia/us02-us20-us31-playwright-20260910T212203Z/`. No debe sobrescribirse ni sumarse a la reevaluación posterior.

```bash
cd frontend
FIM_E2E_RUN_DIR=../docs/cierre/evidencia/playwright-recheck-us02 pnpm exec playwright test e2e/us02-logout.spec.ts
FIM_E2E_RUN_DIR=../docs/cierre/evidencia/playwright-recheck-us20 pnpm exec playwright test e2e/us20-realtime-alerts.spec.ts
FIM_E2E_RUN_DIR=../docs/cierre/evidencia/playwright-recheck-us31 pnpm exec playwright test e2e/us31-superseded-toggle.spec.ts
```

La corrección posterior se reproduce en un laboratorio aislado con:

```bash
scripts/run-us02-us20-us31-acceptance-lab.sh
```

El script construye y levanta PostgreSQL, Valkey, backend, frontend y un proxy exclusivo de SSE, deja vacíos los canales externos, ejecuta las historias individualmente y luego dos veces como conjunto, sanitiza la evidencia y elimina todos los recursos. Para US-20 detiene únicamente el proxy de `/alerts/stream`, exige el cierre observable del stream, verifica API y refresh 200 durante el corte, restaura el proxy, espera una segunda respuesta SSE exitosa antes de publicar y exige el toast del evento real posterior. El resultado vigente está en `evidencia/us02-us20-us31-fixed-us20isolated20260911T0220Z/`.

## 14. Reproducir cierre canónico US-03 / US-25

**PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA**

```bash
scripts/run-isolated-acceptance-lab.sh
```

El runner ejecuta US-03, US-16/17 y US-25 individualmente, luego la suite combinada dos veces. Usa recursos Compose, PKI, estado, baseline y watch directory propios; el trap elimina todos los recursos incluso ante fallo. El resultado vigente está en `docs/cierre/evidencia/us03-us16-us17-us25-isolated-20260911T015529Z/`.
