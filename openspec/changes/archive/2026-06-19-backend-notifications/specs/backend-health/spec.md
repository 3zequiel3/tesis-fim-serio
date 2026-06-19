# Spec: backend-health

Capability: Endpoint `GET /health/components` que verifica en tiempo real el estado de postgres, valkey, n8n y agentes registrados; cachea el último estado en memoria y dispara un webhook n8n cuando hay un cambio de estado (`ok → down` o `down → ok`).

---

## ADDED Requirements

### Requirement: GET /health/components — verificación real de dependencias

El sistema SHALL exponer `GET /health/components` que realiza comprobaciones reales (no cached) de:
- **postgres**: `SELECT 1` con timeout 2s. Resultado: `ok` o `down`.
- **valkey**: `PING` con timeout 2s. Resultado: `ok` o `down`.
- **n8n**: `GET/HEAD {N8N_WEBHOOK_URL}` con timeout 3s; si `N8N_WEBHOOK_URL` no está configurado → `degraded`.
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

#### Scenario: N8N_WEBHOOK_URL no configurado
- **WHEN** `N8N_WEBHOOK_URL` es cadena vacía o no está seteada
- **THEN** la respuesta tiene `{"n8n": "degraded"}`

#### Scenario: Sin agentes registrados
- **WHEN** la tabla `agents` está vacía
- **THEN** `agents.status = "degraded"` (ningún agente online)

#### Scenario: Agentes con estado mixto — alguno online
- **WHEN** hay 3 agentes registrados y 1 está `online`
- **THEN** `agents.status = "ok"`

---

### Requirement: Detección de cambio de estado y webhook n8n

El sistema SHALL mantener en memoria (variable de módulo) el último estado conocido de cada componente. Cuando se llama `GET /health/components`, si el estado de algún componente cambió respecto al anterior (ej. `ok → down` o `down → ok`), el sistema SHALL disparar un POST asincrónico a `N8N_WEBHOOK_URL` informando el cambio. Este disparo es `asyncio.create_task` — no bloqueante. Si `N8N_WEBHOOK_URL` no está configurado, no se dispara.

El body del webhook SHALL incluir:
```json
{
  "event": "health_change",
  "component": "<nombre>",
  "old_status": "<estado_anterior>",
  "new_status": "<nuevo_estado>",
  "checked_at": "<ISO timestamp>"
}
```

#### Scenario: Primer check — no dispara webhook
- **WHEN** es la primera llamada a `/health/components` (no hay estado previo)
- **THEN** no se dispara webhook (no hay cambio que comparar)

#### Scenario: Cambio ok → down dispara webhook
- **WHEN** valkey estaba `ok` en el último check y ahora responde `down`
- **THEN** se dispara async `POST N8N_WEBHOOK_URL` con `{"component": "valkey", "old_status": "ok", "new_status": "down"}`

#### Scenario: Estado sin cambio — no dispara webhook
- **WHEN** el estado de todos los componentes es igual al check anterior
- **THEN** no se dispara ningún webhook
