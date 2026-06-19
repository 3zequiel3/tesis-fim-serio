# Spec: backend-events-api

Capability: API REST del backend para consultar eventos — lista paginada con filtros y detalle por ID.

---

## Purpose

Exponer un endpoint REST `GET /events` con paginación y filtros multi-select (status, path, fechas), y un endpoint `GET /events/{id}` para consulta de eventos individuales con contexto de proceso. Permitir consultas desde el frontend con autenticación JWT.
## Requirements
### Requirement: GET /events con paginación y filtros multi-select

El sistema SHALL exponer `GET /events` en `backend/app/modules/events/router.py` que retorna eventos paginados. Los parámetros de query SHALL ser: `status` (multi-value, acepta múltiples valores, e.g. `?status=pending&status=approved`), `path_prefix` (string, match case-sensitive de prefijo), `date_from` (ISO8601 datetime), `date_to` (ISO8601 datetime), `include_superseded` (bool, default `false`), `page` (int, default `1`, min `1`), `page_size` (int, default `50`, min `1`, max `200`). La respuesta SHALL ser `{"total": int, "page": int, "page_size": int, "items": [...]}`. Cuando `include_superseded=false` (default), los eventos con `status=superseded` SHALL ser excluidos del resultado y del conteo `total` (RN-22, RN-98). El endpoint SHALL requerir autenticación JWT (mismo middleware que C04).

#### Scenario: Listado default excluye superseded
- **WHEN** `GET /events` sin parámetros
- **THEN** la respuesta retorna `200 OK`
- **AND** `items` contiene solo eventos cuyo `status != superseded`
- **AND** `total` refleja el conteo sin superseded

#### Scenario: Filtro por estado único
- **WHEN** `GET /events?status=pending`
- **THEN** `items` contiene solo eventos con `status=pending`
- **AND** `total` es el conteo de eventos pending (excluyendo superseded del conteo si `include_superseded=false`)

#### Scenario: Filtro por múltiples estados
- **WHEN** `GET /events?status=pending&status=approved`
- **THEN** `items` contiene eventos con `status` en `{pending, approved}`

#### Scenario: include_superseded habilita superseded en resultados
- **WHEN** `GET /events?include_superseded=true`
- **THEN** `items` puede contener eventos con `status=superseded`
- **AND** `total` incluye superseded en el conteo

#### Scenario: Filtro por path_prefix
- **WHEN** `GET /events?path_prefix=/etc/`
- **THEN** `items` contiene solo eventos cuyo `path` empieza con `/etc/`

#### Scenario: Paginación retorna subconjunto correcto
- **WHEN** existen 120 eventos y se hace `GET /events?page=2&page_size=50`
- **THEN** `items` contiene los eventos 51–100
- **AND** `total` es `120`
- **AND** `page` es `2`
- **AND** `page_size` es `50`

#### Scenario: Sin autenticación retorna 401
- **WHEN** `GET /events` sin header `Authorization`
- **THEN** la respuesta es `401 Unauthorized`

### Requirement: GET /events/{id} con timestamps dobles y contexto proceso

El sistema SHALL exponer `GET /events/{id}` que retorna el detalle de un evento. La respuesta SHALL incluir todos los campos del modelo `Event`: `id`, `path`, `hash_detected`, `status`, `parent_event_id`, `version`, `process_pid`, `process_uid`, `process_exe`, `detected_at`, `received_at`, `created_at`, `resolved_at`, `resolved_by`. El endpoint SHALL requerir autenticación JWT. Si el evento no existe SHALL retornar `404 Not Found`.

#### Scenario: Evento encontrado retorna detalle completo
- **WHEN** `GET /events/42` y existe el evento con `id=42`
- **THEN** la respuesta es `200 OK`
- **AND** el body incluye `detected_at` y `received_at` como timestamps dobles (RN-90)
- **AND** el body incluye `process_pid`, `process_uid`, `process_exe` (contexto proceso)

#### Scenario: Evento no encontrado retorna 404
- **WHEN** `GET /events/99999` y no existe el evento con `id=99999`
- **THEN** la respuesta es `404 Not Found`

#### Scenario: Evento superseded es accesible directamente
- **WHEN** `GET /events/{id}` donde el evento tiene `status=superseded`
- **THEN** la respuesta es `200 OK` con el evento completo (acceso directo por ID no aplica filtro de superseded)

### Requirement: Router de eventos registrado en main.py

El sistema SHALL registrar el router de eventos en `backend/app/main.py` con prefix `/events` y tag `events`. El router SHALL importarse desde `backend/app/modules/events/router.py`.

#### Scenario: Endpoints accesibles tras arrancar el backend
- **WHEN** el backend arranca
- **THEN** `GET /events` y `GET /events/{id}` están disponibles en la aplicación FastAPI

### Requirement: resolved_at y resolved_by se populan al aprobar o rechazar un evento

Cuando un evento transiciona de `pending` a `approved` o `rejected` via `POST /actions/approve` o `POST /actions/reject`, el sistema SHALL poblar los campos `resolved_at` (timestamp UTC de la acción) y `resolved_by` (user_id del admin que ejecutó la acción). Estos campos SHALL ser retornados en la respuesta de `GET /events/{id}` y en los ítems de `GET /events`.

#### Scenario: GET /events/{id} tras approve muestra resolved_at y resolved_by
- **WHEN** un evento fue aprobado y se hace `GET /events/{id}` para ese evento
- **THEN** la respuesta incluye `resolved_at` con el timestamp de la aprobación
- **AND** la respuesta incluye `resolved_by` con el `user_id` del admin que aprobó
- **AND** `status` es `approved`

#### Scenario: GET /events/{id} de evento pending tiene resolved_at null
- **WHEN** un evento tiene `status=pending`
- **THEN** `resolved_at` y `resolved_by` son `null` en la respuesta

#### Scenario: GET /events filtra por status=approved correctamente
- **WHEN** se hace `GET /events?status=approved`
- **THEN** todos los ítems retornados tienen `status=approved` y `resolved_at` no nulo

### Requirement: Hook de notificación post-ingesta en el event consumer

El consumer SHALL disparar una tarea asincrónica de notificación (`asyncio.create_task(notify_if_applicable(event))`) tras persistir exitosamente un evento en DB y realizar XACK, sin bloquear el flujo del consumer ni depender el XACK del resultado de la notificación.

**Contexto existente**: El consumer `consumer.py` ingiere eventos de Valkey Streams, persiste en DB y hace XACK. Este delta agrega la llamada de notificación después del XACK, sin modificar la lógica de ingesta ni el flujo de XACK.

**Cambio**: Después de que un evento se persiste exitosamente en DB y se realiza XACK, el consumer SHALL disparar `asyncio.create_task(notify_if_applicable(event))` donde `notify_if_applicable` está definido en `backend/app/modules/alerts/service.py`. La función retorna inmediatamente sin await — es fire-and-forget desde la perspectiva del consumer.

**Invariante preservado**: El XACK NO depende del resultado de la notificación. Si la notificación falla internamente, no impacta el procesamiento del stream.

#### Scenario: Evento persistido dispara tarea de notificación
- **WHEN** el consumer persiste exitosamente un evento en DB y hace XACK
- **THEN** se crea un `asyncio.Task` con `notify_if_applicable(event)` sin bloquear el loop del consumer

#### Scenario: Evento que falla la persistencia no dispara notificación
- **WHEN** `_ingest()` lanza una excepción o retorna None
- **THEN** NO se llama `notify_if_applicable`

#### Scenario: Error en la notificación no afecta el consumer
- **WHEN** `notify_if_applicable` levanta una excepción internamente
- **THEN** el consumer continúa procesando el siguiente mensaje normalmente (la excepción queda en el Task)

