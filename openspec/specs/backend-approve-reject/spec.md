# Spec: backend-approve-reject

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

### Requirement: POST /actions/approve — approve single pending event

El sistema SHALL exponer `POST /actions/approve` (requiere JWT de admin) que acepta `{event_id: int, version: int, confirm_absent: bool = false}`. El endpoint MUST ejecutar `UPDATE events SET status='approved', version=version+1, resolved_at=now(), resolved_by=<user_id> WHERE id=event_id AND version=<version> AND status='pending'` de forma atómica. Si el rowcount es 0 (versión incorrecta, estado no-pending o id inexistente) MUST retornar 409. Si `event.hash is None` y `confirm_absent=false` MUST retornar 422 con `{"code": "absent_confirmation_required"}`. En caso de éxito MUST hacer upsert en `baseline_entries` y publicar el comando `baseline_update` al stream `commands` de Valkey.

#### Scenario: Approve exitoso de evento present
- **WHEN** un admin hace `POST /actions/approve` con `event_id` válido en estado `pending`, `version` correcto y `event.hash` no nulo
- **THEN** la respuesta es `200 OK`
- **AND** `events.status` transiciona a `approved`
- **AND** `events.resolved_at` y `events.resolved_by` quedan poblados
- **AND** existe o se actualiza la fila en `baseline_entries` con `status='present'` y `hash=event.hash`
- **AND** se publicó el mensaje `baseline_update` en el stream `commands` de Valkey con `target_agent_id=event.agent_id`

#### Scenario: Optimistic lock — versión incorrecta
- **WHEN** el admin envía `version` distinto al actual en DB
- **THEN** la respuesta es `409 Conflict` con body `{"code": "conflict"}`
- **AND** el evento no cambia de estado

#### Scenario: Optimistic lock — evento ya no está pending
- **WHEN** el evento tiene `status != 'pending'` (ya fue aprobado, rechazado, etc.)
- **THEN** la respuesta es `409 Conflict`

#### Scenario: Approve de evento absent sin confirmación
- **WHEN** `event.hash is None` y el body no incluye `"confirm_absent": true`
- **THEN** la respuesta es `422 Unprocessable Entity` con `{"code": "absent_confirmation_required"}`
- **AND** el evento no cambia de estado

#### Scenario: Approve de evento absent con confirmación
- **WHEN** `event.hash is None` y el body incluye `"confirm_absent": true`
- **THEN** la respuesta es `200 OK`
- **AND** `baseline_entries` tiene la fila con `hash=null` y `status='absent'`
- **AND** el comando `baseline_update` publicado tiene `baseline_status='absent'` y `hash=null`

#### Scenario: Sin autenticación
- **WHEN** `POST /actions/approve` sin header `Authorization`
- **THEN** la respuesta es `401 Unauthorized`

### Requirement: POST /actions/reject — reject single pending event

El sistema SHALL exponer `POST /actions/reject` (requiere JWT de admin) que acepta `{event_id: int, version: int, action: "restore" | "quarantine"}`. MUST ejecutar UPDATE optimista idéntico al de approve pero con `status='rejected'`. Si rowcount=0 → 409. En éxito MUST publicar `restore_file` o `quarantine_file` (según `action`) al stream `commands`. El baseline NO se actualiza en reject. Si `baseline_entries.status='absent'` para ese path (archivo ya registrado como eliminado), MUST hacer no-op del comando (log de advertencia) pero la transición de estado del evento sigue ocurriendo.

#### Scenario: Reject con action restore exitoso
- **WHEN** el admin hace `POST /actions/reject` con `action="restore"` sobre evento `pending`
- **THEN** la respuesta es `200 OK`
- **AND** `events.status` es `rejected`
- **AND** se publicó el mensaje `restore_file` en el stream `commands` con `target_agent_id=event.agent_id`
- **AND** `baseline_entries` NO fue modificada

#### Scenario: Reject con action quarantine exitoso
- **WHEN** el admin hace `POST /actions/reject` con `action="quarantine"` sobre evento `pending`
- **THEN** la respuesta es `200 OK`
- **AND** se publicó el mensaje `quarantine_file` en el stream `commands`
- **AND** `baseline_entries` NO fue modificada

#### Scenario: Reject de evento con baseline absent
- **WHEN** el admin hace `POST /actions/reject` sobre evento cuyo path tiene `baseline_entries.status='absent'`
- **THEN** la respuesta es `200 OK` y el evento transiciona a `rejected`
- **AND** NO se publica ningún comando al stream (no-op logueado)

#### Scenario: Optimistic lock fallido en reject
- **WHEN** el admin envía `version` incorrecta
- **THEN** la respuesta es `409 Conflict`

### Requirement: POST /actions/bulk-approve — bulk approve múltiples eventos

El sistema SHALL exponer `POST /actions/bulk-approve` (requiere JWT de admin) que acepta `{items: [{event_id: int, version: int, confirm_absent: bool = false}]}`. MUST procesar cada ítem de forma independiente (sin transacción global). MUST retornar `200 OK` con `{"succeeded": [event_id, ...], "failed": [{event_id, reason}, ...]}` independientemente de cuántos ítems fallen. Cada ítem exitoso MUST hacer upsert en `baseline_entries` y publicar `baseline_update`. Cada ítem MUST registrarse en `audit_log`.

#### Scenario: Bulk approve — todos exitosos
- **WHEN** el admin envía 3 ítems válidos en estado `pending` con versiones correctas
- **THEN** la respuesta es `200 OK`
- **AND** `succeeded` contiene los 3 `event_id`
- **AND** `failed` está vacío
- **AND** se publicaron 3 comandos `baseline_update`

#### Scenario: Bulk approve — resultado parcial
- **WHEN** el admin envía 3 ítems, 1 tiene versión incorrecta (conflicto)
- **THEN** la respuesta es `200 OK`
- **AND** `succeeded` tiene los 2 ítems válidos
- **AND** `failed` tiene el ítem conflictivo con `reason="conflict"`
- **AND** el ítem conflictivo no cambia de estado

#### Scenario: Bulk approve vacío
- **WHEN** el admin envía `items: []`
- **THEN** la respuesta es `200 OK` con `{"succeeded": [], "failed": []}`

### Requirement: POST /actions/bulk-reject — bulk reject múltiples eventos

El sistema SHALL exponer `POST /actions/bulk-reject` (requiere JWT de admin) que acepta `{items: [{event_id: int, version: int, action: "restore" | "quarantine"}]}`. MUST procesar cada ítem de forma independiente. MUST retornar `200 OK` con `{"succeeded": [event_id, ...], "failed": [{event_id, reason}, ...]}`. Cada ítem exitoso MUST publicar el comando correspondiente (`restore_file` o `quarantine_file`). Cada ítem MUST registrarse en `audit_log`.

#### Scenario: Bulk reject — resultado parcial
- **WHEN** el admin envía 2 ítems, 1 con versión incorrecta
- **THEN** la respuesta es `200 OK`
- **AND** `succeeded` tiene el ítem válido
- **AND** `failed` tiene el conflictivo con `reason="conflict"`

#### Scenario: Bulk reject mixto — restore y quarantine
- **WHEN** el admin envía 2 ítems: uno con `action="restore"` y otro con `action="quarantine"`
- **THEN** `succeeded` contiene ambos `event_id`
- **AND** se publicó un `restore_file` y un `quarantine_file` en el stream

### Requirement: Comando baseline_update publicado en Valkey al aprobar

Al aprobar exitosamente un evento, el sistema SHALL publicar en el stream `commands` de Valkey un mensaje con los campos: `type="baseline_update"`, `command_id` (UUID v4), `event_id`, `target_agent_id` (igual a `event.agent_id`), `path` (igual a `event.path`), `hash` (igual a `event.hash`, puede ser null), `baseline_status` ("present" | "absent"), `ruleset_version` (counter global incrementado, D5), `issued_at` (ISO8601 UTC), `signature` (HMAC-SHA256 hex del payload canónico con la clave `shared_secret` del agente). NO se publica ningún comando `get_file_hash` (D2, D8).

La publicación en Valkey MUST ejecutarse DESPUÉS de `db.commit()` — la transacción de PostgreSQL MUST ser durable antes de que el agente reciba el comando. El orden en `_approve_single` SHALL ser: (1) verificar hash/confirm_absent; (2) UPDATE optimista; (3) flush + refresh; (4) `_increment_ruleset_version`; (5) `upsert_baseline_entry`; (6) `_write_audit`; (7) `db.commit()`; (8) `db.refresh(event)`; (9) `publish_baseline_update` (FIX-02).

#### Scenario: Comando baseline_update contiene los campos requeridos
- **WHEN** se aprueba un evento exitosamente
- **THEN** el mensaje en el stream `commands` contiene exactamente los campos `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `hash`, `baseline_status`, `ruleset_version`, `issued_at`, `signature`
- **AND** `signature` verifica correctamente con HMAC-SHA256 y el `shared_secret` del agente objetivo

#### Scenario: Publicación en Valkey ocurre después del commit
- **WHEN** se aprueba un evento exitosamente
- **THEN** el mensaje `baseline_update` se publica en Valkey únicamente después de que `db.commit()` completó
- **AND** si el proceso falla entre `db.commit()` y la publicación, la DB tiene el estado correcto

#### Scenario: No se publica get_file_hash
- **WHEN** se procesa cualquier approve o reject
- **THEN** no aparece ningún mensaje de tipo `get_file_hash` en el stream `commands`

### Requirement: Comandos restore_file / quarantine_file publicados en Valkey al rechazar

Al rechazar exitosamente, el sistema SHALL publicar en el stream `commands` un mensaje con: `type="restore_file"` o `type="quarantine_file"`, `command_id` (UUID v4), `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`. No incluye `hash` ni `ruleset_version`.

La publicación en Valkey MUST ejecutarse DESPUÉS de `db.commit()`. El orden en `_reject_single` SHALL ser: (1) UPDATE optimista; (2) flush + refresh; (3) consultar `baseline_entry`; (4) `_write_audit`; (5) `db.commit()`; (6) `db.refresh(event)`; (7) `publish_restore_file` o `publish_quarantine_file` según corresponda (FIX-02).

#### Scenario: Comando restore_file contiene campos requeridos
- **WHEN** se rechaza con `action="restore"`
- **THEN** el mensaje en el stream contiene `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`
- **AND** la `signature` verifica con el `shared_secret` del agente

#### Scenario: Publicación en Valkey ocurre después del commit en reject
- **WHEN** se rechaza un evento exitosamente
- **THEN** el mensaje `restore_file` o `quarantine_file` se publica en Valkey únicamente después de que `db.commit()` completó
- **AND** si el proceso falla entre `db.commit()` y la publicación, la DB tiene el estado correcto (`status=rejected`)

### Requirement: audit_log en cada acción de approve/reject

El sistema SHALL insertar una fila en `audit_log` por cada approve o reject procesado (individual o bulk). La fila MUST incluir: `action` ("approve" | "reject"), `event_id`, `user_id`, `timestamp`, `details` (JSON con campos relevantes: versión esperada, action en caso de reject).

#### Scenario: Approve registrado en audit_log
- **WHEN** un admin aprueba un evento
- **THEN** existe una fila en `audit_log` con `action="approve"` y el `event_id` correcto

#### Scenario: Reject registrado en audit_log
- **WHEN** un admin rechaza un evento
- **THEN** existe una fila en `audit_log` con `action="reject"` y `details` que incluye el `action` elegido (restore/quarantine)

#### Scenario: Bulk registra una fila por ítem exitoso
- **WHEN** un bulk-approve procesa 3 ítems y 2 tienen éxito
- **THEN** existen 2 filas en `audit_log` (solo los exitosos)
