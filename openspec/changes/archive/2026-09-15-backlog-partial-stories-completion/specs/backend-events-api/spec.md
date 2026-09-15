## MODIFIED Requirements

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
