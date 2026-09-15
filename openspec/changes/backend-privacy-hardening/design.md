## Context

Change 54 de `CHANGES.md`, originado en el riesgo M-4 de la auditoría V10. Implementa dos decisiones ya cerradas: D64/RN-158 (ticket SSE de un solo uso) y D65/RN-159 (retención de `rejected_events_audit`, `audit_log` sin purga).

Estado actual verificado en el código:

- `backend/app/modules/alerts/router.py` define `_require_admin_from_token(token: str = Query(...))`, que decodifica el JWT de `?token=`, revisa blacklist, scope `password_change_only`, rate limit, usuario activo y rol admin. Un `token` ausente devuelve hoy 422 (validación de FastAPI), aunque la spec `sse-alerts` dice 401.
- `frontend/src/hooks/useAlertsSSE.ts` construye `${VITE_API_URL}/alerts/stream?token=<accessToken>` y delega la reconexión en `EventSource`, que reenvía `Last-Event-ID` (D-EV-6). El effect depende de `accessToken`, por lo que cada refresh reabre la conexión.
- La cookie de refresh tiene `Path=/auth/refresh`, así que no llega a `/alerts/stream`.
- nginx (`frontend/nginx/common-locations.conf`) hace proxy de `/api/` al backend. La imagen `nginx:alpine` usa el `log_format main` por defecto, que incluye `$request` con la query string completa. No hay `log_format` propio en `frontend/nginx/`.
- uvicorn corre con access log activo (`CMD` sin `--no-access-log`) y `uvicorn.access` pasa por `ProcessorFormatter` con `sanitize_secrets`, que redacta por nombre de key y no inspecciona el contenido del mensaje: la URL con `?token=` hoy se registra en claro.
- `RejectedEventAudit` (`backend/app/modules/events/models.py`, tabla `rejected_events_audit`) tiene `received_at` (aware, NOT NULL, reloj del backend) y `detected_at` (nullable, reloj del agente). No hay índice sobre `received_at` ni herramienta de migraciones: el esquema se crea con `create_all`.
- `retention_task()` (`backend/app/modules/events/service.py`) es el precedente: loop con `asyncio.sleep(3600)`, lanzado y cancelado en `backend/app/main.py`.

Restricción de coordinación: el Change 55 (`backlog-partial-stories-completion`) también modifica `backend/app/modules/alerts/` (auditoría de reintentos de la DLQ). **Los applies de los changes 54 y 55 deben ejecutarse en serie**, no en paralelo, para evitar conflictos en `router.py` y en los tests del módulo.

## Goals / Non-Goals

**Goals:**

- Ningún JWT viaja en una URL hacia `/alerts/stream`.
- Un ticket reutilizado, vencido, inexistente o ausente recibe 401.
- El frontend reconecta sin perder alertas, con un ticket nuevo por conexión.
- El valor del ticket no aparece en los logs de uvicorn/structlog ni en el access log de nginx.
- `rejected_events_audit` no conserva filas más antiguas que `REJECTED_EVENTS_RETENTION_DAYS`; `audit_log` conserva todo.

**Non-Goals:**

- Reemplazar `EventSource` por `fetch` + `ReadableStream` o WebSocket.
- Cambiar qué eventos emite el stream, su formato o la exigencia de rol admin (D64 lo excluye explícitamente).
- Retención o purga de `audit_log` (W18/RN-94).
- Cifrado de la cola offline del agente (D63, otro change) y TLS de Valkey.
- Configuraciones nginx de laboratorio (`frontend/nginx.us20-sse-proxy.conf`, `frontend/nginx.us02-us20-us31-lab.conf`), que no forman parte del despliegue.
- Cortar conexiones SSE ya abiertas cuando el usuario se desactiva o hace logout desde otra sesión (comportamiento actual sin cambios).

## Decisions

### 1. Ticket opaco en Valkey con clave hasheada y consumo por `GETDEL`

`POST /alerts/stream-ticket` reutiliza `require_admin` (JWT en header, scope completo, activo, admin, rate limit). Genera `secrets.token_urlsafe(32)` y hace `SET fim:sse_ticket:<sha256_hex(ticket)> <user_id> EX 30 NX` con el cliente Valkey async. Responde `{"ticket", "expires_in": 30}`.

La nueva dependencia del stream recibe `ticket: str | None = Query(default=None)` y responde 401 explícito si falta (corrige la divergencia 422 frente a la spec). Consume con `GETDEL` sobre la clave hasheada; `None` ⇒ 401. Con el `user_id` obtenido, re-verifica usuario existente y activo (401), rol admin (403) y aplica `check_api_rate_limit`. El parámetro `token` desaparece de la firma, por lo que `?token=<jwt>` sin ticket cae en "ticket ausente" ⇒ 401.

La lógica vive en un módulo nuevo `backend/app/modules/alerts/stream_ticket.py` (`issue_ticket`, `consume_ticket`) para testearla sin HTTP.

- *Por qué `GETDEL`*: es una operación atómica de un solo comando (Valkey ≥ 6.2), sin script Lua ni `WATCH/MULTI`; garantiza que dos consumos concurrentes no validen el mismo ticket.
- *Por qué hashear la clave*: un `KEYS`/`SCAN`/`MONITOR` sobre Valkey no expone tickets usables; el costo es un SHA-256 por request.
- *Alternativa descartada — JWT de corta vida firmado (sin estado)*: no es de un solo uso sin agregar igualmente una lista de `jti` consumidos en Valkey, y seguiría siendo un JWT en la URL, contra el texto de D64.
- *Alternativa descartada — cookie con `Path=/alerts/stream`*: requiere cambiar el modelo de sesión y CSRF de la consola; D64 eligió ticket.

### 2. Continuidad D-EV-6: `last_event_id` en query como equivalente del header

El generador SSE toma el último id del header `Last-Event-ID` y, si falta, del query param `last_event_id`; el header prevalece. Mismo tratamiento de valores no enteros (`0`). D64 prevé explícitamente "`Last-Event-ID` o su equivalente en la URL". El id no es secreto, por lo que no necesita redacción.

### 3. Estrategia de reconexión del frontend: cerrar ante error y reabrir manualmente

Problema: ante un corte de red, `EventSource` pasa a `CONNECTING` y reintenta **con la misma URL**, es decir, con un ticket ya consumido ⇒ 401 ⇒ `CLOSED`. Además, una nueva instancia de `EventSource` no permite fijar `Last-Event-ID`.

Decisión: el hook gestiona el ciclo completo.

1. `connect()`: `POST /alerts/stream-ticket` vía `apiClient` (nueva función `fetchStreamTicket()` en `frontend/src/api/alerts.ts`; el interceptor existente resuelve el 401 con refresh single-flight). Construye `…/alerts/stream?ticket=<t>` y agrega `&last_event_id=<id>` sólo si ya se recibió alguna alerta.
2. Cada evento `alert` guarda `e.lastEventId` en un `ref` que sobrevive a las reconexiones del mismo montaje.
3. `onerror` (en cualquier `readyState`): `es.close()` inmediato —impide el reintento nativo con ticket consumido— y programa `connect()` con backoff exponencial 1 s → 2 s → … → 30 s máx.
4. `onopen`: reinicia el backoff; si no es la primera apertura, invalida `['alerts']`, `['dashboard']` y `['alerts-failed-count']`.
5. Fallo de `fetchStreamTicket()`: 401 (refresh fallido; el interceptor ya limpia la sesión) o 403 ⇒ deja de reintentar; error de red o 5xx ⇒ backoff.
6. El effect depende de `isAuthenticated = Boolean(accessToken)`, no del token: la rotación del access token ya no reabre el stream (el ticket sólo se valida al abrir). Cleanup: flag `cancelled`, `clearTimeout`, `es.close()`.

- *Por qué no aprovechar la reconexión nativa*: reutiliza la URL; el primer reintento siempre fallaría con 401, generando ruido, un 401 en logs por cada corte y un retardo adicional.
- *Alternativa descartada — `fetch` con `ReadableStream` y header `Authorization`*: evitaría el ticket, pero reimplementa el parser SSE y el keepalive, y contradice D64 ("sin reemplazar `EventSource`").
- *Alternativa descartada — ticket multiuso durante 30 s*: permitiría la reconexión nativa dentro de la ventana, pero rompe "un solo uso" de D64.

La elección del backoff (1 s a 30 s) se alinea con el keepalive de 15 s: un proxy que corte por inactividad produce como mucho una reconexión rápida.

### 4. Redacción en logs: processor de contenido en backend y `log_format` en nginx

- **Backend**: nuevo processor `redact_query_credentials` en `backend/app/core/logging.py`, después de `sanitize_secrets` en ambas cadenas (structlog y `foreign_pre_chain`). Aplica la regex `(?i)([?&](?:ticket|token|access_token)=)[^&\s"']+` → `\1[REDACTED]` sobre todo valor string, incluido `event`, que para registros stdlib (`uvicorn.access`) contiene la línea ya renderizada con la URL. Se elige un processor y no un `logging.Filter` para cubrir con un solo mecanismo logs de structlog y stdlib, igual que D-CHANGE-01.
- **nginx**: nuevo `frontend/nginx/log-format.conf` incluido en contexto `http` al inicio de `console-http.conf` y `console-https.conf` (ambos se instalan como `conf.d/default.conf`, que nginx incluye dentro de `http`). Define `map $request $fim_redacted_request` con captura regex del parámetro `ticket`/`token` y `log_format fim_redacted` equivalente a `combined` con `$fim_redacted_request`. Cada `server` declara `access_log /var/log/nginx/access.log fim_redacted;`, que prevalece sobre el `access_log … main` heredado.
- *Alternativa descartada — `access_log off` en `location /api/alerts/stream`*: pierde la trazabilidad de conexiones y reconexiones, útil para diagnosticar el feed.

### 5. Retención de `rejected_events_audit`: tarea propia, en lotes, sobre `received_at`

- Setting `rejected_events_retention_days: int = Field(default=90, ge=1)` en `Settings`; la variable se documenta en `.env.example`.
- Nueva `rejected_events_retention_task()` en `backend/app/modules/events/service.py` (junto al modelo y a `retention_task`), con una función síncrona testeable `purge_rejected_events_audit(session_factory, now, days, batch_size=1000) -> int`.
- Cada lote: `DELETE FROM rejected_events_audit WHERE id IN (SELECT id … WHERE received_at < :cutoff ORDER BY id LIMIT :batch)` + commit; repite mientras el lote borre `batch_size` filas. Portable a SQLite (tests en memoria) y Postgres.
- `received_at` porque es NOT NULL y del reloj del backend; `detected_at` es nullable y viene del agente (puede estar desfasado, justamente una de las razones de rechazo).
- Cadencia horaria, igual que RN-98. Cada corrida envuelta en `try/except` con log de error, para que un fallo transitorio de la base no termine la task (`retention_task` actual no lo hace; no se modifica en este change).
- Tarea separada de `retention_task` para aislar fallos y no alterar la semántica ni los tests de RN-98.
- *Alternativa descartada — un único `DELETE … WHERE received_at < cutoff`*: tras meses de acumulación puede bloquear la tabla y generar una transacción larga mientras el consumer inserta rechazos.
- `audit_log` no se toca: la tarea sólo referencia `RejectedEventAudit`; un test verifica el conteo de `audit_log` antes y después.

## Risks / Trade-offs

- [El `error_log` de nginx incluye la línea de request (con el ticket) en errores de upstream y no admite `log_format`] → El ticket ya está consumido o vence en 30 s, por lo que el valor registrado es inservible; se documenta como residual.
- [Corte antes de recibir la primera alerta: sin `last_event_id` no hay replay y se pierden los toasts de alertas creadas durante el corte] → Comportamiento preexistente con `EventSource` nativo; se mitiga invalidando las queries al reabrir, de modo que listados, dashboard y banner reflejan las alertas. Ver Open Questions.
- [Clientes que todavía usen `?token=` (por ejemplo, un bundle de frontend cacheado) dejan de recibir alertas] → Cambio **BREAKING** coordinado: backend y frontend se despliegan juntos en el mismo compose; el bundle usa hashes de contenido e `index.html` no se cachea de forma inmutable.
- [Cada reconexión agrega un `POST` y consume rate limit de API (100/min por usuario)] → El backoff mínimo de 1 s con duplicación limita los intentos a unos pocos por minuto en un corte sostenido.
- [Valkey caído impide emitir o consumir tickets] → El stream ya depende de Valkey (rate limit, blacklist); el frontend reintenta con backoff y el resto de la consola sigue por polling.
- [Sin índice sobre `received_at`, cada lote hace un recorrido secuencial] → Con cadencia horaria y la tabla acotada a 90 días el costo es bajo; ver Open Questions.
- [Conflictos con el Change 55 en `backend/app/modules/alerts/`] → Applies en serie.

## Migration Plan

1. Desplegar backend y frontend juntos (`docker compose --profile app up -d --build backend frontend`). No hay migración de datos: `rejected_events_audit` y `audit_log` no cambian de esquema.
2. La primera corrida de la retención (una hora después del arranque) elimina en lotes el histórico de más de 90 días. Para conservar más historia, fijar `REJECTED_EVENTS_RETENTION_DAYS` antes de desplegar.
3. Rollback: revertir ambas imágenes a la versión anterior. Los tickets en Valkey vencen solos en 30 s; las filas ya purgadas de `rejected_events_audit` no se recuperan (sin obligación normativa de conservación, D65).

## Open Questions

- **Índice sobre `rejected_events_audit.received_at`**: el proyecto crea el esquema con `create_all`, que no agrega índices a tablas existentes. ¿Se acepta el recorrido secuencial por lote, o se agrega un `CREATE INDEX IF NOT EXISTS` idempotente en el lifespan? Ninguna decisión cerrada establece una convención para cambios de esquema sobre tablas existentes; el diseño asume sin índice hasta que se cierre.
- **Brecha de replay previa a la primera alerta**: cerrarla por completo requeriría que el backend informe un cursor inicial (por ejemplo, un `id` en un evento de apertura), lo que cambia los eventos emitidos y choca con D64 ("no cambia qué eventos se emiten"). ¿Se acepta la mitigación por invalidación de queries o se abre una decisión nueva?
