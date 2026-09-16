# Spec: backend-events-api

## Purpose
Exponer un endpoint REST `GET /events` con paginación y filtros multi-select (status, path, fechas), y un endpoint `GET /events/{id}` para consulta de eventos individuales con contexto de proceso. Permitir consultas desde el frontend con autenticación JWT.
## Requirements
### Requirement: GET /events con paginación y filtros multi-select

El sistema SHALL exponer `GET /events` en `backend/app/modules/events/router.py` que retorna eventos paginados. Los parámetros de query SHALL ser: `status` (multi-value, acepta múltiples valores, e.g. `?status=pending&status=approved`), `path_prefix` (string, match case-sensitive de prefijo), `date_from` (ISO8601 datetime), `date_to` (ISO8601 datetime), `include_superseded` (bool, default `false`), `page` (int, default `1`, min `1`), `page_size` (int, default `50`, min `1`, max `200`). La respuesta SHALL ser `{"total": int, "page": int, "page_size": int, "items": [...]}`. Cuando `include_superseded=false` (default), los eventos con `status=superseded` SHALL ser excluidos del resultado y del conteo `total` (RN-22, RN-98). El endpoint SHALL requerir `require_full_access` (no solo `get_current_user`): un usuario con `must_change_password=True` (token con `scope=password_change_only`) MUST recibir 403 `password_change_required` y no puede leer eventos hasta cambiar su password (C7).

La paginación MUST implementarse a nivel SQL con `LIMIT/OFFSET/ORDER BY created_at DESC` — está prohibido cargar todos los registros en memoria y paginar en Python. El `total` MUST obtenerse mediante una query `SELECT COUNT(*) FROM (subquery con filtros)`, no mediante `len(result)` (FIX-04).

#### Scenario: Listado default excluye superseded
- **WHEN** `GET /events` sin parámetros, con un access token de acceso completo
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

#### Scenario: Paginación SQL retorna subconjunto correcto sin full table scan
- **WHEN** existen 120 eventos y se hace `GET /events?page=2&page_size=50`
- **THEN** `items` contiene los eventos 51–100 (ordenados por `created_at DESC`)
- **AND** `total` es `120`
- **AND** `page` es `2`
- **AND** `page_size` es `50`
- **AND** la query NO carga los 120 eventos en memoria (usa LIMIT/OFFSET en SQL)

#### Scenario: Sin autenticación retorna 401
- **WHEN** `GET /events` sin header `Authorization`
- **THEN** la respuesta es `401 Unauthorized`

#### Scenario: Usuario con must_change_password retorna 403
- **WHEN** `GET /events` con un access token cuyo `scope=password_change_only`
- **THEN** la respuesta es `403 Forbidden` con detalle `password_change_required`

### Requirement: GET /events/{id} con timestamps dobles y contexto proceso

El sistema SHALL exponer `GET /events/{id}` que retorna el detalle de un evento. La respuesta SHALL incluir todos los campos del modelo `Event`: `id`, `path`, `hash_detected`, `status`, `parent_event_id`, `version`, `process_pid`, `process_uid`, `process_exe`, `detected_at`, `received_at`, `created_at`, `resolved_at`, `resolved_by`. La respuesta MUST incluir además `baseline_status: "present" | "absent" | null` (US-12, C10), resuelto con una consulta a `baseline_entries` por `(event.path, event.agent_id)`: `null` cuando `event.path` es `null` (p. ej. `detection_gap`, D50/RN-144) o no existe una fila de `baseline_entries` para ese path y agente. El endpoint SHALL requerir `require_full_access` (no solo `get_current_user`): un usuario con `must_change_password=True` MUST recibir 403 `password_change_required` (C7). Si el evento no existe SHALL retornar `404 Not Found`.

#### Scenario: Evento encontrado retorna detalle completo
- **WHEN** `GET /events/42` con un access token de acceso completo y existe el evento con `id=42`
- **THEN** la respuesta es `200 OK`
- **AND** el body incluye `detected_at` y `received_at` como timestamps dobles (RN-90)
- **AND** el body incluye `process_pid`, `process_uid`, `process_exe` (contexto proceso)

#### Scenario: Evento no encontrado retorna 404
- **WHEN** `GET /events/99999` y no existe el evento con `id=99999`
- **THEN** la respuesta es `404 Not Found`

#### Scenario: Evento superseded es accesible directamente
- **WHEN** `GET /events/{id}` donde el evento tiene `status=superseded`
- **THEN** la respuesta es `200 OK` con el evento completo (acceso directo por ID no aplica filtro de superseded)

#### Scenario: Usuario con must_change_password retorna 403
- **WHEN** `GET /events/42` con un access token cuyo `scope=password_change_only`
- **THEN** la respuesta es `403 Forbidden` con detalle `password_change_required`

#### Scenario: Baseline absent
- **WHEN** `GET /events/{id}` donde `baseline_entries` tiene una fila para `(event.path, event.agent_id)` con `status="absent"`
- **THEN** el body incluye `baseline_status: "absent"`

#### Scenario: Baseline present
- **WHEN** `GET /events/{id}` donde `baseline_entries` tiene una fila para `(event.path, event.agent_id)` con `status="present"`
- **THEN** el body incluye `baseline_status: "present"`

#### Scenario: Sin fila de baseline_entries
- **WHEN** `GET /events/{id}` donde no existe fila de `baseline_entries` para `(event.path, event.agent_id)`, o `event.path` es `null`
- **THEN** el body incluye `baseline_status: null`

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

### Requirement: FK parent_event_id con ON DELETE SET NULL

El modelo `Event` en `backend/app/modules/events/models.py` SHALL definir la foreign key auto-referencial `parent_event_id` con `ondelete="SET NULL"`. Al eliminar un evento que es `parent_event_id` de otro (durante la compactación de cadena), PostgreSQL MUST poner en `NULL` la referencia del hijo en lugar de lanzar `IntegrityError`, dejando un encabezado de cadena válido en vez de una referencia colgante. Las bases de datos nuevas obtienen esta definición vía `SQLModel.metadata.create_all()` en el lifespan (D3, sin Alembic). Las bases ya existentes SHALL aplicar una vez el script SQL idempotente `db/migrations/001_fix_parent_event_id_ondelete.sql`, que recrea la constraint con `ON DELETE SET NULL` de forma segura ante re-ejecución (C9).

#### Scenario: Borrar un evento padre pone en NULL la referencia del hijo
- **WHEN** existe `event_B` con `parent_event_id = event_A.id` y se elimina `event_A`
- **THEN** el borrado completa sin `IntegrityError`
- **AND** `event_B.parent_event_id` queda en `NULL`

#### Scenario: Base nueva obtiene la FK correcta vía create_all
- **WHEN** se inicializa una base de datos nueva con `SQLModel.metadata.create_all()`
- **THEN** la FK `events.parent_event_id` tiene `ON DELETE SET NULL`

#### Scenario: Script de migración idempotente para base existente
- **WHEN** se ejecuta `db/migrations/001_fix_parent_event_id_ondelete.sql` sobre una base con la constraint antigua (`NO ACTION`)
- **THEN** la constraint se recrea con `ON DELETE SET NULL`
- **AND** re-ejecutar el script no produce error

### Requirement: Every instant the API emits carries an explicit UTC offset

Every timestamp field in every API response SHALL be serialized as ISO-8601 with an explicit offset — `2026-08-20T19:55:59.641248+00:00`. No response MAY contain a date-time string without a time zone designator.

This is not a formatting preference. ECMAScript requires a date-time string with no designator to be interpreted as **local time**, so `new Date(iso)` in a browser shifts the instant by the viewer's offset. Emitting the offset is what makes the value mean the same thing to every consumer.

The requirement covers every endpoint that returns an instant, including the event listing and detail, the alert feed, the agent listing and the health report — not only the events routes.

#### Scenario: A listed event carries the offset
- **WHEN** `GET /events` returns any event
- **THEN** `detected_at`, `received_at` and `created_at` each end in an explicit offset, and `resolved_at` does too when it is not null

#### Scenario: The serialized form is rejected when the offset is absent
- **WHEN** a serialized timestamp is examined
- **THEN** parsing it yields a time-zone-aware value, and the check MUST interrogate that the parsed value carries a zone — not merely that the string parses, since a naive string parses just as well

#### Scenario: A null instant stays null
- **WHEN** an event has no `resolved_at`
- **THEN** the field is `null`, not an empty string and not a fabricated instant

#### Scenario: A round trip through the API preserves the instant
- **WHEN** an event is stored with a known, literal UTC instant and then read back through the API
- **THEN** the value returned denotes that same instant, compared against the known constant rather than against another value produced by the same path

### Requirement: Date range filters are interpreted as instants

`GET /events` SHALL accept `date_from` and `date_to` as ISO-8601 values carrying an explicit offset, and SHALL interpret them as instants when comparing against `created_at`.

A value that arrives without an offset SHALL be interpreted as UTC, so that the endpoint keeps a defined meaning for existing links rather than depending on server-side configuration. The endpoint MUST NOT interpret an incoming value in the server's local zone.

The filtered range MUST be the range the caller asked for. Today the frontend sends the browser's raw local wall-clock string and the backend compares it against UTC columns, so in a UTC−3 zone the window queried is displaced three hours from the window requested.

#### Scenario: An offset-bearing range selects by instant
- **WHEN** `GET /events` is called with `date_from` and `date_to` carrying explicit offsets
- **THEN** exactly the events whose `created_at` falls within that interval of instants are returned, independently of the server's session zone

#### Scenario: Two equivalent ranges expressed in different zones select the same events
- **WHEN** the same interval is expressed once with a `+00:00` offset and once with a `-03:00` offset denoting the same instants
- **THEN** both calls return the same events

#### Scenario: A range without an offset is read as UTC
- **WHEN** `GET /events` is called with `date_from` written without an offset
- **THEN** it is interpreted as UTC, and the response is identical to the same call with an explicit `+00:00`

#### Scenario: Boundary events are included
- **WHEN** an event's `created_at` equals `date_from` exactly, and another equals `date_to` exactly
- **THEN** both are returned, preserving the inclusive bounds the endpoint already had

### Requirement: Event model persists symlink metadata columns

The `Event` model (`backend/app/modules/events/models.py`) SHALL gain two columns: `is_symlink: bool = False` and `symlink_target: str | None = None`. Both MUST be nullable/defaulted so that existing rows and events lacking the metadata remain valid. The columns SHALL be added via an idempotent SQL migration in `backend/db/migrations/` following the D3 convention (raw SQL, no Alembic), using the next sequence number after `004_add_command_ack_tracking.sql`, and MUST use `ADD COLUMN IF NOT EXISTS` so re-running the migration is safe. (D33 / RN-127)

#### Scenario: Migration adds the columns idempotently
- **WHEN** the symlink-metadata migration runs against a database that already has the columns
- **THEN** it completes without error because it uses `ADD COLUMN IF NOT EXISTS`

#### Scenario: Existing events without symlink metadata remain valid
- **WHEN** an event row created before this change is read
- **THEN** `is_symlink` defaults to `false` and `symlink_target` is `null`, and the row loads without error

### Requirement: EventOut exposes symlink metadata

The event output schema `EventOut` SHALL expose `is_symlink` and `symlink_target` alongside the other event fields, following the same pattern used to expose `ack_status` (D30/C36). Both `GET /events` and `GET /events/{id}` responses SHALL include these fields for every event. (D33 / RN-127)

#### Scenario: Symlink event is serialized with its metadata
- **WHEN** a client fetches an event that represents a symlink
- **THEN** the response includes `is_symlink: true` and `symlink_target` set to the reported target string

#### Scenario: Regular-file event serializes symlink metadata as defaults
- **WHEN** a client fetches an event that represents a regular file
- **THEN** the response includes `is_symlink: false` and `symlink_target: null`

