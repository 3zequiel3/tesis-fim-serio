## ADDED Requirements

### Requirement: The heartbeat consumer persists the agent's local discard count

The heartbeat consumer SHALL read the cumulative count of locally discarded events from the heartbeat payload and persist it on the `Agent` model in a nullable integer column, added by an idempotent migration under the D3 convention (plain SQL in `backend/db/migrations/`, no Alembic, applied by hand).

The value SHALL be treated with forward tolerance: an absent key SHALL leave the stored value unchanged rather than reset it to zero, and a non-numeric value SHALL be ignored with a log rather than reject the heartbeat. This is the same criterion already applied to `queue_pressure` and to the per-path write status.

`GET /agents` and `GET /agents/{id}` SHALL expose the value.

An event of integrity that gets discarded is a serious fact, and today it would be invisible: the agent would delete it silently and no one on the operator's side would ever know. (D37 / RN-131, RN-92)

#### Scenario: The discard count is persisted from the heartbeat

- **WHEN** a heartbeat arrives carrying a discard count of 3 for `agent-01`
- **THEN** the stored value for `agent-01` is 3 and both agent endpoints expose it

#### Scenario: An absent key does not reset the stored value

- **WHEN** a heartbeat from an agent that does not send the key arrives after a heartbeat that reported 3
- **THEN** the stored value remains 3

#### Scenario: A non-numeric value is ignored

- **WHEN** a heartbeat carries a non-numeric discard count
- **THEN** the heartbeat is otherwise processed normally and the stored value is unchanged

#### Scenario: An agent that never reported a count reads as null

- **WHEN** an agent has never sent the key
- **THEN** the endpoints expose a null value rather than zero, distinguishing "never reported" from "reported zero"

## MODIFIED Requirements

### Requirement: POST /agents/{id}/config — actualizar watch_paths y publicar update_config

El sistema SHALL exponer `POST /agents/{id}/config` (requiere JWT admin) que acepta `{watch_paths: list[str]}`. MUST persistir los nuevos `watch_paths` en DB (replace-all), incrementar `ruleset_version` (D5), **encolar el comando `update_config` HMAC-signed en el outbox transaccional** con `target_agent_id` y la lista de paths, y registrar en `audit_log`. Si el agente no existe SHALL retornar `404`.

**Emisión por outbox (D37 / RN-131).** La fila `PublishedCommand` con el payload ya firmado SHALL insertarse con `status="pending"` y `published_at=None` **dentro de la misma transacción** que la persistencia de `watch_paths`, el incremento de `ruleset_version` y el `audit_log`; el `XADD` lo ejecuta el despachador del outbox después del commit, con un intento inmediato best-effort para no agregar latencia al camino feliz. Deja de existir el estado en que la configuración quedó persistida y el comando no se emitió. `ruleset_version_applied` conserva su semántica de D5/RN-106 y C36: solo avanza cuando el consumer de `command_ack` confirma la ejecución, nunca al publicar.

D37/RN-131 enumera `baseline_update`, `restore_file` y `quarantine_file`; `update_config` se incluye por tener el hueco idéntico y compartir el mismo publicador síncrono, sin introducir mecanismo, tabla ni semántica nueva.

#### Scenario: Config actualizado y comando encolado
- **WHEN** un admin hace `POST /agents/agent-01/config` con `watch_paths=["/etc"]`
- **THEN** la respuesta es `200 OK`
- **AND** `agents.watch_paths` es `["/etc"]` en DB
- **AND** existe una fila `PublishedCommand` con `command_type="update_config"` y `status="pending"` comiteada junto con esa mutación
- **AND** el payload persistido tiene `target_agent_id="agent-01"`, `watch_paths=["/etc"]` y `signature` verificable con HMAC-SHA256 y el `shared_secret` del agente

#### Scenario: Valkey caído deja la config persistida y el comando pendiente
- **WHEN** se actualiza la config y el `XADD` falla porque Valkey no responde
- **THEN** la respuesta es `200 OK`, `agents.watch_paths` refleja el cambio y la fila del comando queda `pending`
- **AND** el despachador del outbox la publica en una corrida posterior y la marca `published`

#### Scenario: watch_paths vacío es válido
- **WHEN** el admin envía `watch_paths=[]`
- **THEN** la respuesta es `200 OK` y el agente deja de monitorear paths

#### Scenario: Agente inexistente retorna 404
- **WHEN** se hace `POST /agents/unknown-agent/config`
- **THEN** la respuesta es `404 Not Found`

#### Scenario: Config registrado en audit_log
- **WHEN** se actualiza la config
- **THEN** existe una fila en `audit_log` con `action="agent_config"` y el `agent_id`

#### Scenario: Un agente sin shared_secret hace fallar la actualización
- **WHEN** se actualiza la config de un agente sin `shared_secret_hex`
- **THEN** la transacción se revierte, `watch_paths` conserva su valor anterior y la respuesta es un error

### Requirement: POST /agents/{id}/rescan — forzar re-scan con gestión de pending

El sistema SHALL exponer `POST /agents/{id}/rescan` (requiere JWT admin) que acepta `{force: bool = false}`. Si `force=false` y existen eventos `pending` del agente, MUST retornar `409` con `{"code": "pending_events_exist", "count": N}`. Si `force=true` o no hay pending, MUST marcar todos los eventos `pending` del agente como `superseded` (con `parent_event_id=null`), **encolar `rescan_baseline` HMAC-signed en el outbox transaccional**, y registrar en `audit_log`.

**Emisión por outbox (D37 / RN-131).** La fila `PublishedCommand` SHALL insertarse con `status="pending"` dentro de la misma transacción que la supersesión de los eventos pendientes y el `audit_log`. Un fallo de publicación se vuelve un reintento del despachador, no una supersesión sin comando: sin esto, los eventos quedan `superseded` y el agente nunca recibe la orden de re-escanear, dejando al operador con una vista vacía y un baseline sin refrescar.

#### Scenario: Rescan sin pending — comando encolado
- **WHEN** no hay eventos pending del agente y se hace `POST /agents/agent-01/rescan` con `force=false`
- **THEN** la respuesta es `200 OK`
- **AND** existe una fila `PublishedCommand` con `command_type="rescan_baseline"`, `status="pending"` y `target_agent_id="agent-01"`

#### Scenario: Rescan con pending y sin force — 409
- **WHEN** existen 3 eventos pending del agente y se hace `POST /agents/agent-01/rescan` con `force=false`
- **THEN** la respuesta es `409` con `{"code": "pending_events_exist", "count": 3}`
- **AND** ningún evento cambia de estado
- **AND** no se inserta ninguna fila `PublishedCommand`

#### Scenario: Rescan con force=true y pending existentes
- **WHEN** existen 3 eventos pending y se hace `POST /agents/agent-01/rescan` con `force=true`
- **THEN** la respuesta es `200 OK`
- **AND** los 3 eventos pending quedan con `status="superseded"`
- **AND** la fila `rescan_baseline` quedó encolada en la misma transacción

#### Scenario: Valkey caído deja la supersesión hecha y el comando pendiente
- **WHEN** se ejecuta un rescan con `force=true` y el `XADD` falla porque Valkey no responde
- **THEN** la respuesta es `200 OK`, los eventos quedan `superseded` y la fila del comando queda `pending`
- **AND** el despachador del outbox la publica en una corrida posterior

#### Scenario: Rescan registrado en audit_log
- **WHEN** se ejecuta un rescan
- **THEN** existe una fila en `audit_log` con `action="agent_rescan"` y el `agent_id`
