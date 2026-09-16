## MODIFIED Requirements

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
