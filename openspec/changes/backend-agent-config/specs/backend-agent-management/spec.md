# Spec: backend-agent-management

Capability: Endpoints REST de gestión operacional de agentes FIM — consulta de lista y detalle, actualización de watch_paths con publicación de update_config HMAC-signed, forzado de re-scan con gestión de pending, y transición automática al estado `dead`.

---

## ADDED Requirements

### Requirement: watch_paths almacenado en el modelo Agent

El sistema SHALL agregar el campo `watch_paths: list[str]` al modelo `Agent` en DB (columna JSON, default `[]`). Este campo es la fuente autoritativa de paths que el agente debe monitorear (RN-68). El backend persiste los paths y los envía al agente; el agente actualiza su configuración local al recibirlos.

#### Scenario: Agent registrado tiene watch_paths vacío por defecto
- **WHEN** se registra un agente nuevo con `POST /agents/register`
- **THEN** `agents.watch_paths` es `[]` en DB

#### Scenario: watch_paths persiste tras POST /agents/{id}/config
- **WHEN** un admin hace `POST /agents/{id}/config` con `watch_paths=["/etc", "/usr/bin"]`
- **THEN** `agents.watch_paths` es `["/etc", "/usr/bin"]` en DB
- **AND** el valor anterior queda completamente reemplazado

---

### Requirement: GET /agents — lista todos los agentes con estado operacional

El sistema SHALL exponer `GET /agents` (requiere JWT admin) que retorna la lista de todos los agentes. Cada ítem SHALL incluir: `agent_id`, `status` (online/offline/draining/dead), `last_heartbeat`, `queue_pressure`, `ruleset_version_applied`, `watch_paths`. La respuesta SHALL ser `{"items": [...], "total": int}`.

#### Scenario: Lista de agentes retorna todos los registrados
- **WHEN** existen 3 agentes registrados y se hace `GET /agents`
- **THEN** la respuesta contiene `total=3` y `items` con los 3 agentes

#### Scenario: Sin autenticación retorna 401
- **WHEN** `GET /agents` sin header `Authorization`
- **THEN** la respuesta es `401 Unauthorized`

#### Scenario: Agente dead aparece en la lista con status=dead
- **WHEN** un agente no envió heartbeat por más de 5 minutos
- **THEN** aparece en `GET /agents` con `status="dead"`

---

### Requirement: GET /agents/{id} — detalle de agente con estado operacional

El sistema SHALL exponer `GET /agents/{id}` (requiere JWT admin) que retorna el detalle completo de un agente. La respuesta SHALL incluir todos los campos de `GET /agents` más `watch_paths`. Si el agente no existe SHALL retornar `404 Not Found`.

#### Scenario: Agente encontrado retorna detalle completo
- **WHEN** existe un agente con `agent_id="agent-01"` y se hace `GET /agents/agent-01`
- **THEN** la respuesta es `200 OK` con todos los campos incluyendo `watch_paths`, `last_heartbeat`, `queue_pressure`, `ruleset_version_applied`, `status`

#### Scenario: Agente no encontrado retorna 404
- **WHEN** se hace `GET /agents/nonexistent`
- **THEN** la respuesta es `404 Not Found`

---

### Requirement: POST /agents/{id}/config — actualizar watch_paths y publicar update_config

El sistema SHALL exponer `POST /agents/{id}/config` (requiere JWT admin) que acepta `{watch_paths: list[str]}`. MUST persistir los nuevos `watch_paths` en DB (replace-all), incrementar `ruleset_version` (D5), publicar el comando `update_config` HMAC-signed al stream `commands` de Valkey con `target_agent_id` y la lista de paths, y registrar en `audit_log`. Si el agente no existe SHALL retornar `404`.

#### Scenario: Config actualizado y comando publicado
- **WHEN** un admin hace `POST /agents/agent-01/config` con `watch_paths=["/etc"]`
- **THEN** la respuesta es `200 OK`
- **AND** `agents.watch_paths` es `["/etc"]` en DB
- **AND** se publicó el mensaje `update_config` en el stream `commands` con `target_agent_id="agent-01"` y `watch_paths=["/etc"]`
- **AND** el mensaje tiene `signature` verificable con HMAC-SHA256 y el `shared_secret` del agente

#### Scenario: watch_paths vacío es válido
- **WHEN** el admin envía `watch_paths=[]`
- **THEN** la respuesta es `200 OK` y el agente deja de monitorear paths

#### Scenario: Agente inexistente retorna 404
- **WHEN** se hace `POST /agents/unknown-agent/config`
- **THEN** la respuesta es `404 Not Found`

#### Scenario: Config registrado en audit_log
- **WHEN** se actualiza la config
- **THEN** existe una fila en `audit_log` con `action="agent_config"` y el `agent_id`

---

### Requirement: POST /agents/{id}/rescan — forzar re-scan con gestión de pending

El sistema SHALL exponer `POST /agents/{id}/rescan` (requiere JWT admin) que acepta `{force: bool = false}`. Si `force=false` y existen eventos `pending` del agente, MUST retornar `409` con `{"code": "pending_events_exist", "count": N}`. Si `force=true` o no hay pending, MUST marcar todos los eventos `pending` del agente como `superseded` (con `parent_event_id=null`), publicar `rescan_baseline` HMAC-signed al stream `commands`, y registrar en `audit_log`.

#### Scenario: Rescan sin pending — comando publicado
- **WHEN** no hay eventos pending del agente y se hace `POST /agents/agent-01/rescan` con `force=false`
- **THEN** la respuesta es `200 OK`
- **AND** se publicó `rescan_baseline` en el stream `commands` con `target_agent_id="agent-01"`

#### Scenario: Rescan con pending y sin force — 409
- **WHEN** existen 3 eventos pending del agente y se hace `POST /agents/agent-01/rescan` con `force=false`
- **THEN** la respuesta es `409` con `{"code": "pending_events_exist", "count": 3}`
- **AND** ningún evento cambia de estado

#### Scenario: Rescan con force=true y pending existentes
- **WHEN** existen 3 eventos pending y se hace `POST /agents/agent-01/rescan` con `force=true`
- **THEN** la respuesta es `200 OK`
- **AND** los 3 eventos pending quedan con `status="superseded"`
- **AND** se publicó `rescan_baseline`

#### Scenario: Rescan registrado en audit_log
- **WHEN** se ejecuta un rescan
- **THEN** existe una fila en `audit_log` con `action="agent_rescan"` y el `agent_id`

---

### Requirement: Transición automática al estado dead (5 min sin heartbeat)

El sistema SHALL extender el sweep periódico del heartbeat consumer para marcar como `dead` a los agentes con `status=offline` cuyo `last_heartbeat` sea anterior a `now - 5 minutos` (RN-92). Los agentes en estado `draining` no deben transicionar a `dead` directamente — primero van a `offline` a los 30s, luego a `dead` a los 5 min.

#### Scenario: Agente offline por más de 5 min transiciona a dead
- **WHEN** un agente tiene `status=offline` y `last_heartbeat < now - 5min`
- **THEN** en el siguiente sweep, `status` transiciona a `dead`

#### Scenario: Agente offline por menos de 5 min permanece offline
- **WHEN** un agente tiene `status=offline` y `last_heartbeat = now - 2min`
- **THEN** `status` permanece `offline`

#### Scenario: Agente dead que envía heartbeat vuelve a online
- **WHEN** un agente en estado `dead` envía un heartbeat al backend
- **THEN** su `status` transiciona a `online` y `last_heartbeat` se actualiza
