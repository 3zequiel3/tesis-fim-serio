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

La referencia actual es
`docs/cierre/evidencia/drenaje-20260910-run3/`: 3.000/3.000 eventos,
0 rechazos, 0 duplicados, 3.000 `XADD`, cola final 0 y 51,773 s
(57,945 eventos/s). Mejora los 153 s históricos, pero el umbral original
`<30 s` permanece **NO CUMPLE**: excede en 21,773 s. Para 3.000 eventos se
requieren más de 100 eventos/s, porque 100 eventos/s produce exactamente 30 s.

Repetir la evaluación con contenedores locales y credenciales exclusivas del
laboratorio:

```bash
docker run -d --rm --name fim-drain-postgres \
  -e POSTGRES_DB=fim_drain -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=controlled \
  -p 127.0.0.1:55441:5432 postgres:18.3
docker run -d --rm --name fim-drain-valkey \
  -p 127.0.0.1:56380:6379 valkey/valkey:9.0.3

until docker exec fim-drain-postgres pg_isready -U fim -d fim_drain; do sleep 1; done
until docker exec fim-drain-valkey valkey-cli ping | grep -q PONG; do sleep 1; done

env PYTHONPATH=backend:. \
  DATABASE_URL=postgresql+psycopg://fim:controlled@127.0.0.1:55441/fim_drain \
  VALKEY_URL=valkey://127.0.0.1:56380/0 \
  JWT_SECRET_CURRENT=controlled-not-a-production-secret \
  RATE_LIMIT_INGEST_EVENTS=100000 \
  RATE_LIMIT_INGEST_WINDOW_SECONDS=60 \
  backend/.venv/bin/python \
    docs/cierre/evidencia/drenaje-20260910-run3/run_profile.py \
  | tee docs/cierre/evidencia/drenaje-20260910-run3/stdout.log

docker stop fim-drain-postgres fim-drain-valkey
```

El rate limit `100000/60 s` pertenece sólo al ensayo; el valor predeterminado de
producción es `100/60 s`. Registrar volumen planificado/real, tasa de generación,
corte/reconexión y timestamps por etapa: cola local, `XADD`, lectura, validación,
commit, `XACK` y ACK del agente. La construcción de la cola se excluye; el tiempo
principal comienza antes del flush de comandos y termina con 3.000 filas
persistidas y cola local vacía.

Conservar HMAC, persistencia PostgreSQL, auditoría, confirmaciones, `XACK` y
borrado durable activos. El candidato de Run 3 elimina la tormenta de reintentos
y el costo O(n²) de la cola; su cuello remanente es la ingesta serial del backend.
La optimización está fijada en `7c5afa5`; identificar además cada corrida mediante
`environment.json` y `source-manifest.sha256`, porque la evidencia todavía no
está incluida en ese commit.

Contraste histórico, sin reemplazar los datos originales:

- B5: 2.988 eventos en 153 s, 19,529 eventos/s;
- Run 3: 3.000 eventos en 51,773 s, 57,945 eventos/s;
- criterio original para Run 3: `<30 s`, es decir, más de 100 eventos/s.

Una repetición crea una evaluación nueva: no sobrescribir `stdout.log`,
`metrics.jsonl`, `summary.json` ni sus manifiestos de la corrida de referencia.

## 13. Ensayo reducido de dos anfitriones

En dos hosts Linux distintos, registrar versiones y relojes; ubicar agente y backend/Valkey en hosts diferentes; habilitar TLS/mTLS; capturar únicamente metadatos sanitizados. Verificar conectividad válida y rechazos negativos. No denominar multianfitrión a dos contenedores del mismo host.

## 14. Cerrar y verificar evidencia

```bash
find "$EVIDENCE_DIR" -type f -print0 | sort -z | xargs -0 sha256sum \
  > "$EVIDENCE_DIR/SHA256SUMS"
git rev-parse HEAD >> "$EVIDENCE_DIR/identidad.txt"
git status --short >> "$EVIDENCE_DIR/identidad.txt"

(cd docs/cierre/evidencia/absence-20260910T052521Z-r2 && sha256sum -c SHA256SUMS)
(cd docs/cierre/evidencia/drenaje-20260910-run3 && sha256sum -c SHA256SUMS)
```

Antes de publicar, sanitizar hostnames, rutas absolutas, payloads, destinatarios, certificados y secretos. Una copia sanitizada recibe nombre y hash nuevos; nunca se reemplaza silenciosamente el original.
