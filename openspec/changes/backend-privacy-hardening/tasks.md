> **Coordinación**: el Change 55 (`backlog-partial-stories-completion`) también modifica `backend/app/modules/alerts/`. No aplicar este change en paralelo con el 55: los applies se ejecutan en serie, orden recomendado 55 primero y luego este change (resuelto por aprobación del usuario, 2026-09-15; ver "Orden de apply con el Change 55" en `design.md`).
>
> **Entorno de tests del backend**: desde `backend/`, con Postgres y Valkey aislados del laboratorio. No hay binario `python` en el PATH: usar `uv run --no-sync python -m pytest`. Plantilla:
> `TEST_DATABASE_URL='postgresql+psycopg://fim:test@127.0.0.1:<pg_port>/fim_test' TEST_VALKEY_URL='valkey://127.0.0.1:<valkey_port>' uv run --no-sync python -m pytest <tests> -q`

## 1. Ticket SSE en el backend (D64/RN-158)

- [x] 1.1 Crear `backend/app/modules/alerts/stream_ticket.py` con `issue_ticket(user_id, valkey) -> str` (`secrets.token_urlsafe(32)`, `SET fim:sse_ticket:<sha256_hex> <user_id> EX 30 NX`) y `consume_ticket(ticket, valkey) -> int | None` (`GETDEL` sobre la clave hasheada); constantes `SSE_TICKET_PREFIX` y `SSE_TICKET_TTL_SECONDS = 30`
- [x] 1.2 Agregar `POST /alerts/stream-ticket` en `backend/app/modules/alerts/router.py` con `Depends(require_admin)` y cliente Valkey async; response model `{"ticket": str, "expires_in": int}`; sin loguear el valor del ticket
- [x] 1.3 Reemplazar `_require_admin_from_token` por una dependencia `_require_admin_from_ticket(ticket: str | None = Query(default=None))`: 401 si falta o si `consume_ticket` devuelve `None`; luego usuario existente y activo (401), rol admin (403) y `check_api_rate_limit`; eliminar el parámetro `token` y los imports que queden sin uso
- [x] 1.4 En `_alert_sse_generator`, leer el último id desde el header `Last-Event-ID` y, si falta, desde el query param `last_event_id` (header prevalece; no entero ⇒ `0`)
- [x] 1.5 Actualizar el docstring del módulo y del endpoint (contrato C16: autenticación por ticket)

## 2. Redacción de credenciales en logs

- [x] 2.1 Agregar el processor `redact_query_credentials` en `backend/app/core/logging.py` (regex case-insensitive sobre `ticket`, `token`, `access_token` en query strings; recursivo con `_MAX_DEPTH`) y registrarlo después de `sanitize_secrets` en la cadena de structlog y en el `foreign_pre_chain`
- [x] 2.2 Crear `frontend/nginx/log-format.conf` con `map $request $fim_redacted_request` y `log_format fim_redacted` (equivalente a `combined` con la variable redactada)
- [x] 2.3 Incluir `log-format.conf` en contexto `http` al inicio de `frontend/nginx/console-http.conf` y `frontend/nginx/console-https.conf`, y declarar `access_log /var/log/nginx/access.log fim_redacted;` en cada bloque `server` (incluido el redirect 80→443)

## 3. Retención de `rejected_events_audit` (D65/RN-159)

- [x] 3.1 Agregar `rejected_events_retention_days: int = Field(default=90, ge=1)` a `Settings` en `backend/app/core/config.py`, con comentario que cite D65/RN-159 y W18/RN-94
- [x] 3.2 Documentar `REJECTED_EVENTS_RETENTION_DAYS=90` en `.env.example` con una línea explicativa
- [x] 3.3 Crear `backend/db/migrations/017_add_rejected_events_audit_received_at_index.sql` con `CREATE INDEX IF NOT EXISTS ix_rejected_events_audit_received_at ON rejected_events_audit (received_at);`, siguiendo el formato de comentario de cabecera de las migraciones existentes (propósito, idempotencia, comando `psql -f` de aplicación)
- [x] 3.4 Implementar en `backend/app/modules/events/service.py` la función `purge_rejected_events_audit(session_factory, now, days, batch_size=1000) -> int` (lotes por `id IN (SELECT … ORDER BY id LIMIT :batch)` con `received_at < cutoff`, commit por lote, hasta un lote incompleto) sin referenciar `AuditLog`
- [x] 3.5 Implementar `rejected_events_retention_task()` (sleep de 3600 s, llamada a la purga, `try/except` con `log.error` por corrida, `log.info("service.rejected_retention_run", deleted=n)` sólo si `n > 0`)
- [x] 3.6 Registrar la task en el lifespan de `backend/app/main.py` junto a `retention_task()`, cancelarla en el shutdown e incluirla en el `gather` de cierre

## 4. Frontend: conexión y reconexión con ticket

- [x] 4.1 Agregar `fetchStreamTicket(): Promise<{ ticket: string; expires_in: number }>` en `frontend/src/api/alerts.ts` usando `apiClient.post('/alerts/stream-ticket')`
- [x] 4.2 Reescribir `frontend/src/hooks/useAlertsSSE.ts`: `connect()` pide ticket y abre `EventSource` con `ticket` y `last_event_id` (sólo si hay id previo); `lastEventIdRef` actualizado en cada `alert`; `onerror` cierra de inmediato y programa reconexión con backoff 1 s → 30 s; `onopen` reinicia el backoff e invalida `['alerts']`, `['dashboard']`, `['alerts-failed-count']` en reaperturas; 401/403 al pedir ticket detienen los reintentos; cleanup con flag `cancelled`, `clearTimeout` y `close()`
- [x] 4.3 Hacer que el effect dependa de `Boolean(accessToken)` en lugar del valor del token y actualizar el JSDoc (quitar la referencia a `?token=` y a la reconexión nativa)

## 5. Tests del backend

- [x] 5.1 Crear `backend/tests/test_sse_stream_ticket.py` con un Valkey async falso (dict + TTL con reloj inyectable, `set(nx, ex)`, `getdel`) o `TEST_VALKEY_URL`: emisión 200 con `expires_in=30` y clave hasheada con TTL ≤ 30; sin JWT ⇒ 401; no admin ⇒ 403; scope `password_change_only` ⇒ 403; dos tickets distintos
- [x] 5.2 Tests del stream: ticket válido ⇒ 200 `text/event-stream` y clave eliminada; ticket reutilizado ⇒ 401; ticket vencido ⇒ 401; ticket inexistente ⇒ 401; ticket ausente ⇒ 401 (no 422); `?token=<JWT admin válido>` sin ticket ⇒ 401; ticket de usuario desactivado ⇒ 401
- [x] 5.3 Test de atomicidad contra Valkey real (`TEST_VALKEY_URL`): dos `consume_ticket` concurrentes sobre el mismo ticket ⇒ exactamente uno devuelve el `user_id`
- [x] 5.4 Tests de replay: `?last_event_id=9` con alertas 10, 11, 12 ⇒ se reemiten en orden; header `Last-Event-ID: 11` prevalece sobre `?last_event_id=9`; sin ninguno ⇒ sin replay
- [x] 5.5 Actualizar `backend/tests/test_sse_alerts.py` y `backend/tests/test_c32_sse_security_fixes.py`: reemplazar el override de `_require_admin_from_token` y los tests `token inválido ⇒ 401` / `sin token ⇒ 422` por sus equivalentes con ticket
- [x] 5.6 Extender `backend/tests/test_logging_sanitize.py`: línea de `uvicorn.access` con `?ticket=abc123&last_event_id=9` ⇒ contiene `ticket=[REDACTED]&last_event_id=9` y no `abc123`; `?token=eyJ…` redactado; string anidado con `Ticket=` redactado; URL sin credenciales intacta
- [x] 5.7 Test end-to-end de redacción: `TestClient` con `configure_logging()` y captura de stdout haciendo `GET /alerts/stream?ticket=<valor>` ⇒ ninguna línea contiene `<valor>`
- [x] 5.8 Crear `backend/tests/test_rejected_events_retention.py`: fila de 91 días eliminada y de 89 conservada con default 90; período 7 elimina 8 días y conserva 6; 2500 filas vencidas ⇒ 3 lotes (1000, 1000, 500); conteo de `audit_log` (incluidas filas de 400 días) idéntico antes y después; `Settings` con `REJECTED_EVENTS_RETENTION_DAYS=0` ⇒ `ValidationError`; excepción de DB en una corrida no termina la task (sleep parcheado para dos iteraciones)
- [x] 5.8b Contra Postgres (`TEST_DATABASE_URL`), aplicar `backend/db/migrations/017_add_rejected_events_audit_received_at_index.sql` dos veces seguidas y confirmar que la segunda no produce error; verificar con una consulta a `pg_indexes` que el índice `ix_rejected_events_audit_received_at` existe una sola vez
- [x] 5.9 Test del lifespan: la task de retención de rechazos se crea en el startup y queda cancelada tras el shutdown

## 6. Tests del frontend

- [x] 6.1 Reescribir `frontend/src/hooks/useAlertsSSE.test.tsx` con `fetchStreamTicket` mockeado y timers falsos: la URL contiene `ticket=` y no contiene `token=` ni el access token; se pide el ticket antes de crear el `EventSource`
- [x] 6.2 Test de reconexión sin pérdida: tras recibir la alerta con `lastEventId` 9, `onerror` cierra el `EventSource`, y tras el backoff se pide un ticket nuevo y la nueva URL contiene `last_event_id=9`; sin alertas previas la URL no contiene `last_event_id`
- [x] 6.3 Tests de backoff (1 s, 2 s, 4 s … tope 30 s, reinicio tras `onopen`), de invalidación de queries en reapertura, de 401/403 al pedir ticket que detienen los reintentos, de rotación del access token que no reabre el stream y de desmontaje que cancela el reintento pendiente

## 7. Verificación

- [x] 7.1 Backend dirigido (desde `backend/`): `TEST_DATABASE_URL='postgresql+psycopg://fim:test@127.0.0.1:<pg_port>/fim_test' TEST_VALKEY_URL='valkey://127.0.0.1:<valkey_port>' uv run --no-sync python -m pytest tests/test_sse_stream_ticket.py tests/test_sse_alerts.py tests/test_c32_sse_security_fixes.py tests/test_logging_sanitize.py tests/test_rejected_events_retention.py tests/test_retention_task.py tests/modules/events/test_retention.py -q`
- [x] 7.2 Suite completa del backend con el mismo entorno: `uv run --no-sync python -m pytest -q` sin fallos nuevos respecto de la base
- [x] 7.3 Frontend (desde `frontend/`): `pnpm test` y `pnpm build`
- [x] 7.4 nginx: con el stack levantado, `docker compose exec frontend nginx -t` en `CONSOLE_TLS_MODE=off` y en `self_signed`; hacer `curl -k '<consola>/api/alerts/stream?ticket=probe-ticket-123'` y confirmar que `docker compose logs frontend backend` contiene `ticket=[REDACTED]` y no contiene `probe-ticket-123`
- [ ] 7.5 Verificar que ningún request a `/alerts/stream` lleva JWT: `rg -n "stream\?token|token=\\$\{" frontend/src` sin resultados y, en la consola desplegada, la pestaña de red muestra sólo `?ticket=` (y `last_event_id` tras un corte)
- [ ] 7.6 Prueba manual de reconexión: con la consola abierta, reiniciar el contenedor `backend`, crear una alerta durante el corte y confirmar que al reconectar llega el toast (si ya había alertas previas) y que listados y banner se actualizan
- [x] 7.7 Confirmar que ningún código del backend emite `DELETE` sobre `audit_log`: `rg -n "AuditLog" backend/app | rg -i "delete"` sin resultados
- [x] 7.8 Migración del índice: aplicar `backend/db/migrations/017_add_rejected_events_audit_received_at_index.sql` contra la base de destino, ejecutarla una segunda vez y confirmar que no falla; con `EXPLAIN` sobre la consulta del lote de purga (`WHERE received_at < :cutoff ORDER BY id LIMIT :batch`), confirmar que el plan usa `ix_rejected_events_audit_received_at`
- [x] 7.9 `openspec validate backend-privacy-hardening --strict`
