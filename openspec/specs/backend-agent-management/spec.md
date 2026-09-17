# Spec: backend-agent-management

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: watch_paths almacenado en el modelo Agent

El sistema SHALL agregar el campo `watch_paths: list[str]` al modelo `Agent` en DB (columna JSON, default `[]`). Este campo es la fuente autoritativa de paths que el agente debe monitorear (RN-68). El backend persiste los paths y los envía al agente; el agente actualiza su configuración local al recibirlos.

#### Scenario: Agent registrado tiene watch_paths vacío por defecto
- **WHEN** se registra un agente nuevo con `POST /agents/register`
- **THEN** `agents.watch_paths` es `[]` en DB

#### Scenario: watch_paths persiste tras POST /agents/{id}/config
- **WHEN** un admin hace `POST /agents/{id}/config` con `watch_paths=["/etc", "/usr/bin"]`
- **THEN** `agents.watch_paths` es `["/etc", "/usr/bin"]` en DB
- **AND** el valor anterior queda completamente reemplazado

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

### Requirement: GET /agents/{id} — detalle de agente con estado operacional

El sistema SHALL exponer `GET /agents/{id}` (requiere JWT admin) que retorna el detalle completo de un agente. La respuesta SHALL incluir todos los campos de `GET /agents` más `watch_paths`. Si el agente no existe SHALL retornar `404 Not Found`.

#### Scenario: Agente encontrado retorna detalle completo
- **WHEN** existe un agente con `agent_id="agent-01"` y se hace `GET /agents/agent-01`
- **THEN** la respuesta es `200 OK` con todos los campos incluyendo `watch_paths`, `last_heartbeat`, `queue_pressure`, `ruleset_version_applied`, `status`

#### Scenario: Agente no encontrado retorna 404
- **WHEN** se hace `GET /agents/nonexistent`
- **THEN** la respuesta es `404 Not Found`

### Requirement: POST /agents/{id}/config — actualizar watch_paths y publicar update_config

El sistema SHALL exponer `POST /agents/{id}/config` (requiere JWT admin) que acepta `{watch_paths: list[str]}`. MUST persistir los nuevos `watch_paths` en DB (replace-all), incrementar `ruleset_version` (D5), publicar el comando `update_config` HMAC-signed al stream `commands` de Valkey con `target_agent_id` y la lista de paths, y registrar en `audit_log`. Si el agente no existe SHALL retornar `404`.

El campo `detail` del registro `audit_log` de esta operación MUST ser JSON válido, serializado con `json.dumps(...)` (comillas dobles, escape correcto), y no una interpolación f-string sobre `str(list)`. El `detail` MUST permanecer JSON válido aunque algún path contenga caracteres especiales como comillas dobles (`"`) o barras invertidas (`\`).

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

#### Scenario: detail del audit_log es JSON válido con paths que contienen comillas
- **WHEN** se actualiza la config con un path que contiene comillas dobles o barras invertidas
- **THEN** el `detail` del `audit_log` es JSON parseable (comillas dobles, escape correcto) y no rompe el parseo posterior

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

### Requirement: The heartbeat consumer persists the per-path write status on the Agent model

The `Agent` model SHALL gain a nullable JSON column holding the map of watch path to write classification reported by the agent's heartbeat, added by an idempotent raw SQL migration following the project's convention. The model already stores `watch_paths` as a JSON column, so this follows an established precedent in the same table rather than introducing a new persistence pattern.

The heartbeat consumer SHALL read the status map from the heartbeat payload and persist it. The consumer applies no schema and no allowlist to heartbeat payloads today — it reads the fields it needs and ignores the rest — so reading one more key requires no change to signature verification.

Tolerance SHALL work in both directions:

- when the key is **absent**, the stored column SHALL be left untouched, so a heartbeat from an older agent does not erase the last known status;
- when the value is **not a mapping of strings**, it SHALL be ignored with a warning and the heartbeat SHALL still be processed normally. A malformed extra field must never make an agent appear offline.

The agent responses returned by the list and detail endpoints SHALL expose the stored map. Both endpoints serialize through a single conversion function, so the change has one point of application. (D36 / RN-130, RN-92, RN-93)

#### Scenario: A reported status map is persisted

- **WHEN** a signed heartbeat carrying a watch path status map is consumed
- **THEN** the map is persisted on the agent row and the usual heartbeat side effects still occur

#### Scenario: An older agent does not erase the stored status

- **WHEN** a heartbeat arrives with no status map key
- **THEN** the previously stored map is retained unchanged

#### Scenario: A malformed status value does not break the heartbeat

- **WHEN** a heartbeat carries a status value that is not a mapping of strings
- **THEN** the value is ignored with a warning, the stored map is retained, and the agent's liveness and queue pressure are still updated

#### Scenario: The list endpoint exposes the status map

- **WHEN** the agent list is requested
- **THEN** each agent carries its watch path status map

#### Scenario: The detail endpoint exposes the status map

- **WHEN** a single agent is requested by identifier
- **THEN** the response carries its watch path status map

#### Scenario: An agent that never reported has a null map

- **WHEN** an agent registered before this change is returned
- **THEN** its status map is null rather than an empty object misread as "all paths writable"

### Requirement: El consumer de heartbeat persiste el contador de descartes fuera de scope

El consumer de heartbeat SHALL leer del payload el contador acumulativo de eventos descartados por
caer fuera de los `watch_paths` y SHALL persistirlo en el modelo `Agent` en una columna entera
**nullable**, agregada por una migración aditiva e idempotente bajo la convención D3 (SQL plano en
`backend/db/migrations/`, sin Alembic, aplicada a mano). La migración MUST ser estrictamente aditiva:
no hay backfill posible —no existe forma de reconstruir cuántos descartes acumuló un agente antes de
la columna— y `NULL` es la respuesta correcta para las filas existentes (D69/RN-163).

El valor SHALL tratarse con tolerancia hacia adelante, con el mismo criterio ya aplicado a
`queue_pressure`, `watch_path_status` y `discarded_events`: una clave ausente SHALL dejar el valor
guardado sin tocar en vez de resetearlo a cero, y un valor no numérico SHALL ignorarse con un log en
vez de rechazar el heartbeat. Un booleano SHALL rechazarse explícitamente como no numérico. Un
contador malformado MUST NOT impedir que el resto del heartbeat se procese.

`GET /agents` y `GET /agents/{id}` SHALL exponer el valor. `None` SHALL significar "el agente nunca
reportó la clave" y SHALL ser distinguible de `0`, que significa "reportó y no descartó nada": el
agente ya publica la clave en cada heartbeat, así que un nulo es información sobre el agente, no
sobre el filtro de scope (D69/RN-163, RN-04, RN-92).

#### Scenario: El contador se persiste desde el heartbeat

- **WHEN** llega un heartbeat de `agent-01` con un contador de descartes fuera de scope de 2748492
- **THEN** el valor guardado para `agent-01` es 2748492 y los dos endpoints de agentes lo exponen

#### Scenario: Una clave ausente no resetea el valor guardado

- **WHEN** llega un heartbeat sin la clave, de un agente que antes había reportado 2748492
- **THEN** el valor guardado sigue siendo 2748492

#### Scenario: Un valor no numérico se ignora sin romper el heartbeat

- **WHEN** llega un heartbeat cuyo contador de descartes fuera de scope no es numérico
- **THEN** el valor guardado queda sin cambios
- **AND** el resto del heartbeat se procesa normalmente y el agente queda `online`

#### Scenario: Un booleano se rechaza como no numérico

- **WHEN** llega un heartbeat cuyo contador de descartes fuera de scope es un booleano
- **THEN** el valor guardado queda sin cambios y se registra un log de valor inválido

#### Scenario: Un agente que nunca reportó se lee como nulo

- **WHEN** un agente nunca envió la clave
- **THEN** los endpoints exponen un valor nulo en vez de cero, distinguiendo "nunca reportó" de
  "reportó cero"

