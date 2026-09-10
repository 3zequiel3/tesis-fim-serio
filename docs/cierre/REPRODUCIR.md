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

## 10. Reproducir n8n unidad A controlada

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

Crear una salida nueva e incluir por operación:

`operation_id → path sanitizado → hash anterior → baseline vigente → hash posterior → evento kernel → decisión agente → queue ID → stream ID → event ID backend`.

Ejecutar cambios sucesivos, retorno a baseline, creación, eliminación y modificación efímera. No sobrescribir B3/B5 históricos. Una nueva corrida caracteriza el sistema actual y no prueba retroactivamente la causa de las 19 ausencias.

## 12. Repetir drenaje y deduplicación

Registrar volumen planificado/real, tasa de generación, corte/reconexión y timestamps por etapa: cola local, XADD, lectura, validación, commit, XACK y ACK del agente. Para 2.988 eventos:

- umbral original: menos de 30 s;
- caudal mínimo derivado: 99,6 eventos/s;
- línea base histórica: 153 s y 19,529 eventos/s.

No desactivar firma, auditoría, persistencia ni confirmaciones.

## 13. Ensayo reducido de dos anfitriones

En dos hosts Linux distintos, registrar versiones y relojes; ubicar agente y backend/Valkey en hosts diferentes; habilitar TLS/mTLS; capturar únicamente metadatos sanitizados. Verificar conectividad válida y rechazos negativos. No denominar multianfitrión a dos contenedores del mismo host.

## 14. Cerrar y verificar evidencia

```bash
find "$EVIDENCE_DIR" -type f -print0 | sort -z | xargs -0 sha256sum \
  > "$EVIDENCE_DIR/SHA256SUMS"
git rev-parse HEAD >> "$EVIDENCE_DIR/identidad.txt"
git status --short >> "$EVIDENCE_DIR/identidad.txt"
```

Antes de publicar, sanitizar hostnames, rutas absolutas, payloads, destinatarios, certificados y secretos. Una copia sanitizada recibe nombre y hash nuevos; nunca se reemplaza silenciosamente el original.
