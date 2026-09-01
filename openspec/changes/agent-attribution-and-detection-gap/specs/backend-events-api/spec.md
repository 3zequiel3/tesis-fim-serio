## MODIFIED Requirements

### Requirement: GET /events/{id} con timestamps dobles y contexto proceso

El sistema SHALL exponer `GET /events/{id}` que retorna el detalle de un evento. La respuesta SHALL
incluir todos los campos del modelo `Event`: `id`, `event_type`, `path`, `hash_detected`, `status`,
`severity`, `parent_event_id`, `version`, `process_pid`, `process_uid`, `process_exe`, `detected_at`,
`received_at`, `created_at`, `resolved_at`, `resolved_by`. El campo `event_type` SHALL ser `str` no
nulo con el vocabulario en minúsculas snake_case que el agente emite (RN-71, D51/RN-145). El campo
`path` SHALL ser `str | None`: es nulo en los eventos que no hablan de un archivo concreto, como
`detection_gap`. Los campos `process_pid`, `process_uid` y `process_exe` SHALL ser `int | None` /
`str | None` y un nulo SHALL significar **atribución no resuelta**, nunca root (D49/RN-143). El
endpoint SHALL requerir `require_full_access` (no solo `get_current_user`): un usuario con
`must_change_password=True` MUST recibir 403 `password_change_required` (C7). Si el evento no existe
SHALL retornar `404 Not Found`.

#### Scenario: Evento encontrado retorna detalle completo
- **WHEN** `GET /events/42` con un access token de acceso completo y existe el evento con `id=42`
- **THEN** la respuesta es `200 OK`
- **AND** el body incluye `detected_at` y `received_at` como timestamps dobles (RN-90)
- **AND** el body incluye `process_pid`, `process_uid`, `process_exe` (contexto proceso)
- **AND** el body incluye `event_type`

#### Scenario: Evento no encontrado retorna 404
- **WHEN** `GET /events/99999` y no existe el evento con `id=99999`
- **THEN** la respuesta es `404 Not Found`

#### Scenario: Evento superseded es accesible directamente
- **WHEN** `GET /events/{id}` donde el evento tiene `status=superseded`
- **THEN** la respuesta es `200 OK` con el evento completo (acceso directo por ID no aplica filtro de superseded)

#### Scenario: Usuario con must_change_password retorna 403
- **WHEN** `GET /events/42` con un access token cuyo `scope=password_change_only`
- **THEN** la respuesta es `403 Forbidden` con detalle `password_change_required`

#### Scenario: Evento sin ruta retorna path nulo y event_type discriminante
- **WHEN** `GET /events/{id}` sobre un evento `detection_gap`
- **THEN** la respuesta es `200 OK` con `path: null` y `event_type: "detection_gap"`
- **AND** la serialización no falla por el nulo

#### Scenario: Atribución no resuelta se serializa como nulo
- **WHEN** `GET /events/{id}` sobre un evento cuyo `process_uid` es `NULL` en la base
- **THEN** la respuesta lleva `process_uid: null`
- **AND** no lleva `process_uid: 0`

## ADDED Requirements

### Requirement: EventOut expone event_type y admite path nulo en el listado

El schema de respuesta `EventOut` SHALL declarar `event_type: str` y SHALL relajar `path` a
`str | None`, de modo que el listado paginado de `GET /events` y el detalle compartan el mismo
contrato (D51/RN-145). El campo es aditivo: ningún filtro, orden ni paginación cambia.

El filtro `path_prefix` SHALL seguir operando sobre la columna `path` con semántica de prefijo. Un
evento con `path` nulo MUST NOT matchear ningún `path_prefix`, de modo que quede fuera de una
búsqueda por ruta — el comportamiento correcto, porque no tiene ruta que buscar. Un evento con
`path` nulo SHALL aparecer en el listado cuando no se aplica `path_prefix`, y SHALL responder a los
filtros de `status`, `severity` y rango de fechas como cualquier otro.

#### Scenario: El listado incluye event_type en cada ítem
- **WHEN** `GET /events` con un access token de acceso completo
- **THEN** cada elemento de `items` incluye el campo `event_type`

#### Scenario: Un evento sin ruta aparece en el listado sin filtro de ruta
- **WHEN** existe un evento `detection_gap` y se consulta `GET /events` sin `path_prefix`
- **THEN** el evento aparece en `items` con `path: null`

#### Scenario: Un evento sin ruta queda fuera de un filtro por prefijo
- **WHEN** existe un evento `detection_gap` y se consulta `GET /events?path_prefix=/etc`
- **THEN** el evento no aparece en `items`

#### Scenario: Un evento sin ruta responde al filtro de severidad
- **WHEN** existe un evento `detection_gap` con `severity=high` y se consulta `GET /events?severity=high`
- **THEN** el evento aparece en `items`
