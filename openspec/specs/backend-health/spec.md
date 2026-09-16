# backend-health Specification

## Purpose
TBD - created by archiving change backend-notifications. Update Purpose after archive.
## Requirements
### Requirement: GET /health/components — verificación real de dependencias

El sistema SHALL exponer `GET /health/components` que realiza comprobaciones reales (no cached) de:
- **postgres**: `SELECT 1` con timeout 2s. Resultado: `ok` o `down`.
- **valkey**: `PING` con timeout 2s. Resultado: `ok` o `down`.
- **n8n**: `HEAD {N8N_WEBHOOK_URL}` con timeout 3s; el check MUST inspeccionar el status code HTTP (o invocar `raise_for_status()`) y reportar `down` ante cualquier status de error (4xx/5xx). Si el `HEAD` falla o el endpoint no soporta `HEAD`, el check MUST reintentar con `GET` (fallback documentado) antes de decidir el resultado. Si `N8N_WEBHOOK_URL` no está configurado → `degraded`. Un `HEAD`/`GET` que devuelva 5xx MUST reportarse como `down`, nunca como `ok`.
- **agents**: lista todos los agentes de la DB con su `status` actual (`online`, `offline`, `dead`, `inactive`). Resultado agregado: `ok` si alguno está `online`, `degraded` si ninguno está `online`.

La respuesta SHALL ser `200 OK` independientemente del estado de los componentes (para que el frontend pueda procesarlo). El cuerpo SHALL tener la forma:

```json
{
  "postgres": "ok",
  "valkey": "ok",
  "n8n": "degraded",
  "agents": {
    "status": "ok",
    "items": [
      {"agent_id": "...", "hostname": "...", "status": "online"}
    ]
  },
  "checked_at": "2026-06-19T12:00:00Z"
}
```

No requiere autenticación JWT (RN-101 — monitoreo sin login).

#### Scenario: Todos los componentes up
- **WHEN** postgres, valkey y n8n responden correctamente
- **THEN** la respuesta tiene `{"postgres": "ok", "valkey": "ok", "n8n": "ok"}`

#### Scenario: Valkey down
- **WHEN** valkey no responde dentro de 2s
- **THEN** la respuesta tiene `{"valkey": "down"}` y status HTTP sigue siendo 200

#### Scenario: n8n responde 500 se reporta down
- **WHEN** el endpoint n8n responde con status 500
- **THEN** la respuesta tiene `{"n8n": "down"}` (nunca `ok`)

#### Scenario: n8n no soporta HEAD — fallback a GET
- **WHEN** el `HEAD` al endpoint n8n falla o devuelve un status que indica método no soportado
- **THEN** el check reintenta con `GET` y decide el resultado según el status de esa respuesta

#### Scenario: N8N_WEBHOOK_URL no configurado
- **WHEN** `N8N_WEBHOOK_URL` es cadena vacía o no está seteada
- **THEN** la respuesta tiene `{"n8n": "degraded"}`

#### Scenario: Sin agentes registrados
- **WHEN** la tabla `agents` está vacía
- **THEN** `agents.status = "degraded"` (ningún agente online)

#### Scenario: Agentes con estado mixto — alguno online
- **WHEN** hay 3 agentes registrados y 1 está `online`
- **THEN** `agents.status = "ok"`

### Requirement: Detección de cambio de estado y webhook n8n

El sistema SHALL mantener en memoria (variable de módulo) el último estado conocido de cada componente. Cuando se llama `GET /health/components`, si el estado de algún componente cambió respecto al anterior (ej. `ok → down` o `down → ok`), el sistema SHALL disparar un POST asincrónico a `N8N_WEBHOOK_URL` informando el cambio. Este disparo es `asyncio.create_task` — no bloqueante. Si `N8N_WEBHOOK_URL` no está configurado, no se dispara.

El body del webhook SHALL adoptar el sobre plano de `notification-payload-contract` (D40/RN-134), con `type = "health_change"`:

```json
{
  "schema_version": 1,
  "notification_id": "<uuid v4>",
  "type": "health_change",
  "event": "health_change",
  "component": "<nombre>",
  "old_status": "<estado_anterior>",
  "new_status": "<nuevo_estado>",
  "checked_at": "<ISO timestamp>"
}
```

El campo `event` se conserva por compatibilidad con consumidores previos; `type` es el discriminador canónico.

#### Scenario: Primer check — no dispara webhook
- **WHEN** es la primera llamada a `/health/components` (no hay estado previo)
- **THEN** no se dispara webhook (no hay cambio que comparar)

#### Scenario: Cambio ok → down dispara webhook
- **WHEN** valkey estaba `ok` en el último check y ahora responde `down`
- **THEN** se dispara async `POST N8N_WEBHOOK_URL` con `{"component": "valkey", "old_status": "ok", "new_status": "down"}`

#### Scenario: Estado sin cambio — no dispara webhook
- **WHEN** el estado de todos los componentes es igual al check anterior
- **THEN** no se dispara ningún webhook

#### Scenario: El payload de health_change lleva el discriminador
- **WHEN** se dispara un webhook por cambio de estado
- **THEN** el cuerpo incluye `"type": "health_change"`, `schema_version` y `notification_id`

### Requirement: Notificación de cambio de estado de componente con referencia fuerte a la task asyncio

El health checker MUST guardar una referencia fuerte a cualquier `asyncio.Task` creada para notificar cambios de estado de componentes (e.g., `send_n8n`). La referencia SHALL mantenerse en un `set` module-level hasta que la task complete, previniendo cancelación silenciosa por el GC antes de que la notificación se envíe.

#### Scenario: Task de notificación de health no es cancelada por GC

- **WHEN** el health checker detecta un cambio de estado y crea una task para notificar vía n8n
- **THEN** la task mantiene una referencia fuerte hasta completar
- **AND** el GC no puede cancelar la task durante el I/O HTTP de la notificación

