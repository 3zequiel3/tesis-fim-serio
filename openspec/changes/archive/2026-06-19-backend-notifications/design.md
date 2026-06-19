## Context

C15 agrega la capa de notificación del M3. La tabla `alerts` ya existe (C03, D6) con todos los campos necesarios. El event consumer (C11) ya ingiere eventos pero no llama ninguna notificación. Los módulos de reglas (C12) y eventos (C11) están estables — C15 se monta sobre ellos sin modificar su lógica central.

Estado actual relevante:
- `backend/app/modules/alerts/models.py` — `Alert` con `severity`, `channel`, `delivered_at`, `failed_at`, `last_error`, `retry_count`. Ya existe, sin service ni router.
- `backend/app/modules/events/consumer.py` — `_ingest()` retorna el `Event` persistido; el caller hace XACK después. El punto de inyección es justo tras `_ingest()`.
- `backend/app/modules/rules/models.py` — `Rule` con `pattern` (glob) y `severity` (critical/high/medium/low). Ya implementado (C12).
- `backend/app/core/config.py` — configuración Pydantic Settings; hay que agregar las vars de notificación.
- `backend/app/main.py` — ya expone `/health` básico (C02); hay que agregar `/health/components`.

## Goals / Non-Goals

**Goals:**
- Notificación post-ingesta asincrónica y no bloqueante (asyncio task).
- Severidad determinada por lookup de reglas en DB (max severity de reglas cuyo glob matchee el path del evento).
- Retry 3x exponencial con actualización de `alerts` en cada intento.
- Cascada n8n → SMTP → webhook directo → log crítico (RN-107).
- Endpoints DLQ: GET /alerts/failed, POST /alerts/{id}/retry, DELETE /alerts/{id}.
- GET /health/components con detección real y trigger webhook en cambios.

**Non-Goals:**
- Notificaciones para eventos superseded — no notifican (RN-22).
- Modificar el loop de XACK del consumer — la notificación va después del XACK.
- Retry automático en background (loop infinito) — C15 solo implementa retry manual desde la DLQ. El retry automático exponencial ocurre dentro del mismo ciclo de `notify_event()`.

## Decisions

### D-C15-01 — Severidad por max-severity de reglas matching

El campo `severity` de la alerta se determina con: `SELECT MAX(severity_rank) FROM rules WHERE glob_match(pattern, event.path)`. La función de glob matching usa `fnmatch.fnmatch` (Python stdlib). Si ninguna regla matchea → default `low`; si el resultado es `low` o `medium` → no se notifica (RN-52). Solo `critical` y `high` disparan notificación.

**Alternativa descartada**: agregar `rule_severity` al Event model — requiere cambio de schema en C11 y actualización del agente, complejidad innecesaria para este caso de uso.

### D-C15-02 — Notificación como asyncio.create_task() en el consumer

Después del XACK en `consumer.py`, si el evento fue persistido: `asyncio.create_task(notify_if_applicable(event))`. La tarea es fire-and-forget desde la perspectiva del consumer — el retry y logging están dentro de `notify_if_applicable`. No bloquea el loop principal.

### D-C15-03 — Retry 3x exponencial dentro de notify_event()

`notify_event()` intenta los canales en orden con waits `[5, 30, 120]` segundos entre intentos. Cada intento actualiza la fila en `alerts`. Si los 3 intentos fallan, la fila queda con `failed_at NOT NULL` y entra en la DLQ.

```python
RETRY_DELAYS = [5, 30, 120]  # segundos entre reintentos
```

Un "intento" usa el primer canal disponible de la cascada: n8n → SMTP → webhook_direct → log_only.

### D-C15-04 — Cascada de canales

Orden de intento por envío:
1. `n8n` — `POST {N8N_WEBHOOK_URL}` con timeout 10s.
2. `smtp_fallback` — solo si `SMTP_HOST` está configurado; `aiosmtplib` async.
3. `webhook_fallback` — solo si `WEBHOOK_FALLBACK_URL` está configurado; `httpx` async.
4. `log_only` — siempre disponible; emite log crítico y marca `delivered_at` (es un "canal" exitoso de último recurso, RN-54).

La fila en `alerts` refleja el canal que finalmente entregó (o el último que falló con `failed_at`).

### D-C15-05 — GET /health/components con cache de último estado

El endpoint realiza checks reales:
- **postgres**: `SELECT 1` con timeout 2s.
- **valkey**: `PING` con timeout 2s.
- **n8n**: `GET {N8N_WEBHOOK_URL}/health` o HEAD con timeout 3s; si `N8N_WEBHOOK_URL` no configurado → `degraded`.
- **agents**: lista de agentes con su `status` actual de DB.

El estado anterior se cachea en memoria (variable de módulo). Si hay un cambio (`ok→down`, `down→ok`), se dispara un webhook n8n de salud. Cache TTL implícito: el endpoint se llama cada 10s desde el frontend (RN-101), la caché es solo para comparar cambios.

**Alternativa descartada**: polling background task — añade complejidad; el endpoint ya se llama frecuentemente desde el frontend.

### D-C15-06 — Nuevas dependencias httpx y aiosmtplib

`httpx[asyncio]` para llamadas async HTTP (n8n webhook, webhook_fallback, health checks).
`aiosmtplib` para SMTP async.

Ambas se agregan a `backend/requirements.txt` con versiones fijadas.

### D-C15-07 — Módulo alerts: service.py + notifier.py + router.py

- `notifier.py`: lógica de envío (HTTP, SMTP) — fácil de mockear en tests.
- `service.py`: orquestación (crear Alert, llamar notifier, retrys, DLQ queries).
- `router.py`: endpoints FastAPI.

## Risks / Trade-offs

- **n8n caído en el momento de notificación** → la cascada intenta SMTP y fallback; si todos fallan → DLQ con `failed_at NOT NULL`; admin puede reintentar. `[Mitigado]`
- **Muchos eventos críticos simultáneos** → muchos `create_task` concurrentes. Para volumen de tesis es aceptable; en producción se usaría una cola de trabajo. `[Accepted risk]`
- **Lookup de reglas en cada notificación** → query simple sin joins, índice por pattern no existe pero con <1000 reglas la full-scan es negligible. `[Low risk]`

## Migration Plan

1. Agregar `httpx` y `aiosmtplib` a `requirements.txt`.
2. Agregar vars opcionales a `config.py` — sin valor → features opcionales degradan gracefully.
3. El módulo `alerts/service.py` + `router.py` son nuevos — sin breaking changes.
4. La modificación de `consumer.py` agrega un `create_task` al final del happy path — no cambia el flujo de XACK.

## Open Questions

Ninguna — todas las decisiones de canal y retry cerradas en RN-52/53/54/86/87/107 y D6.
