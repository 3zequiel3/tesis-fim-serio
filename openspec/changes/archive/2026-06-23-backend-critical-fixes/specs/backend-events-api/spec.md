## MODIFIED Requirements

### Requirement: GET /events con paginación y filtros multi-select

El sistema SHALL exponer `GET /events` en `backend/app/modules/events/router.py` que retorna eventos paginados. Los parámetros de query SHALL ser: `status` (multi-value, acepta múltiples valores, e.g. `?status=pending&status=approved`), `path_prefix` (string, match case-sensitive de prefijo), `date_from` (ISO8601 datetime), `date_to` (ISO8601 datetime), `include_superseded` (bool, default `false`), `page` (int, default `1`, min `1`), `page_size` (int, default `50`, min `1`, max `200`). La respuesta SHALL ser `{"total": int, "page": int, "page_size": int, "items": [...]}`. Cuando `include_superseded=false` (default), los eventos con `status=superseded` SHALL ser excluidos del resultado y del conteo `total` (RN-22, RN-98). El endpoint SHALL requerir `require_full_access` (no solo `get_current_user`): un usuario con `must_change_password=True` (token con `scope=password_change_only`) MUST recibir 403 `password_change_required` y no puede leer eventos hasta cambiar su password (C7).

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

#### Scenario: Paginación retorna subconjunto correcto
- **WHEN** existen 120 eventos y se hace `GET /events?page=2&page_size=50`
- **THEN** `items` contiene los eventos 51–100
- **AND** `total` es `120`
- **AND** `page` es `2`
- **AND** `page_size` es `50`

#### Scenario: Sin autenticación retorna 401
- **WHEN** `GET /events` sin header `Authorization`
- **THEN** la respuesta es `401 Unauthorized`

#### Scenario: Usuario con must_change_password retorna 403
- **WHEN** `GET /events` con un access token cuyo `scope=password_change_only`
- **THEN** la respuesta es `403 Forbidden` con detalle `password_change_required`

### Requirement: GET /events/{id} con timestamps dobles y contexto proceso

El sistema SHALL exponer `GET /events/{id}` que retorna el detalle de un evento. La respuesta SHALL incluir todos los campos del modelo `Event`: `id`, `path`, `hash_detected`, `status`, `parent_event_id`, `version`, `process_pid`, `process_uid`, `process_exe`, `detected_at`, `received_at`, `created_at`, `resolved_at`, `resolved_by`. El endpoint SHALL requerir `require_full_access` (no solo `get_current_user`): un usuario con `must_change_password=True` MUST recibir 403 `password_change_required` (C7). Si el evento no existe SHALL retornar `404 Not Found`.

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

## ADDED Requirements

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
