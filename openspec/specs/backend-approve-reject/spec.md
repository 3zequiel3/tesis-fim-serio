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

El sistema SHALL exponer `POST /actions/reject` (requiere JWT de admin) que acepta `{event_id: int, version: int, action: "restore" | "quarantine"}`. MUST ejecutar UPDATE optimista idéntico al de approve pero con `status='rejected'`. Si rowcount=0 → 409. En éxito MUST publicar `restore_file` o `quarantine_file` (según `action`) al stream `commands`. El baseline NO se actualiza en reject. Si `baseline_entries.status='absent'` para ese path (archivo ya registrado como eliminado), MUST hacer no-op del comando (log de advertencia) pero la transición de estado del evento sigue ocurriendo (RN-74, "Excepciones: Ninguna").

Cuando la operación resulta en el no-op por baseline `absent`, la respuesta MUST incluir el flag `baseline_absent: true` para que el frontend pueda avisar al admin que no se publicó ningún comando de acción. Cuando NO hubo no-op (baseline presente y comando publicado), la respuesta MUST reflejar `baseline_absent: false`. Este flag NO altera el comportamiento de no-op: solo lo hace observable en la respuesta.

#### Scenario: Reject con action restore exitoso
- **WHEN** el admin hace `POST /actions/reject` con `action="restore"` sobre evento `pending`
- **THEN** la respuesta es `200 OK`
- **AND** `events.status` es `rejected`
- **AND** se publicó el mensaje `restore_file` en el stream `commands` con `target_agent_id=event.agent_id`
- **AND** `baseline_entries` NO fue modificada
- **AND** la respuesta lleva `baseline_absent: false`

#### Scenario: Reject con action quarantine exitoso
- **WHEN** el admin hace `POST /actions/reject` con `action="quarantine"` sobre evento `pending`
- **THEN** la respuesta es `200 OK`
- **AND** se publicó el mensaje `quarantine_file` en el stream `commands`
- **AND** `baseline_entries` NO fue modificada
- **AND** la respuesta lleva `baseline_absent: false`

#### Scenario: Reject de evento con baseline absent
- **WHEN** el admin hace `POST /actions/reject` sobre evento cuyo path tiene `baseline_entries.status='absent'`
- **THEN** la respuesta es `200 OK` y el evento transiciona a `rejected`
- **AND** NO se publica ningún comando al stream (no-op logueado)
- **AND** la respuesta lleva `baseline_absent: true`

#### Scenario: Optimistic lock fallido en reject
- **WHEN** el admin envía `version` incorrecta
- **THEN** la respuesta es `409 Conflict`

### Requirement: POST /actions/bulk-approve — bulk approve múltiples eventos

El sistema SHALL exponer `POST /actions/bulk-approve` (requiere JWT de admin) con el contrato canónico único `{event_ids: [int, ...]}`. El servidor MUST cargar cada evento por ID, distinguir `not_found` de `not_pending`, capturar su versión vigente y conservar el conflicto optimista si una carrera cambia esa versión antes del update. MUST procesar cada ID de forma independiente (sin transacción global) y retornar `200 OK` con `{"succeeded": [event_id, ...], "failed": [{event_id, reason}, ...]}` independientemente de cuántos fallen. Cada aprobación exitosa MUST hacer upsert en `baseline_entries`, registrar `audit_log` y publicar `baseline_update`. Un evento con baseline ausente MUST fallar con `reason="baseline_absent"`.

Esta es una migración breaking: el bulk wire y su respuesta no admiten `items`, `version`, `confirm_absent` ni `baseline_absent`. El body legacy con `items` MUST responder `422`; no existe alias de compatibilidad. `baseline_absent` se mantiene únicamente en la acción individual.

#### Scenario: Bulk approve — todos exitosos
- **WHEN** el admin envía `{event_ids:[1,2,3]}` y los tres eventos existen y están `pending`
- **THEN** la respuesta es `200 OK`
- **AND** `succeeded` contiene los 3 `event_id`
- **AND** `failed` está vacío
- **AND** se publicaron 3 comandos `baseline_update`

#### Scenario: Bulk approve — resultado parcial
- **WHEN** el admin envía 3 IDs y una carrera cambia la versión vigente de uno después de cargarlo
- **THEN** la respuesta es `200 OK`
- **AND** `succeeded` tiene los 2 ítems válidos
- **AND** `failed` tiene el ítem conflictivo con `reason="conflict"`
- **AND** el ítem conflictivo no cambia de estado

#### Scenario: Bulk approve vacío
- **WHEN** el admin envía `{event_ids: []}`
- **THEN** la respuesta es `200 OK` con `{"succeeded": [], "failed": []}`

#### Scenario: Bulk approve distingue IDs no procesables
- **WHEN** un ID no existe y otro identifica un evento que ya no está `pending`
- **THEN** `failed` contiene respectivamente `reason="not_found"` y `reason="not_pending"`

#### Scenario: Bulk approve legacy es rechazado
- **WHEN** el admin envía un body con `items`
- **THEN** la respuesta es `422 Unprocessable Entity`

### Requirement: POST /actions/bulk-reject — bulk reject múltiples eventos

El sistema SHALL exponer `POST /actions/bulk-reject` (requiere JWT de admin) con el contrato canónico único `{event_ids: [int, ...], action: "restore" | "quarantine"}`. La acción top-level MUST aplicarse a toda la selección. El servidor MUST cargar cada evento por ID, distinguir `not_found` de `not_pending`, capturar su versión vigente y conservar el conflicto optimista ante carreras. MUST procesar cada ID de forma independiente y retornar `200 OK` con `{"succeeded": [event_id, ...], "failed": [{event_id, reason}, ...]}`. Cada rechazo exitoso MUST registrarse en `audit_log` y publicar el comando correspondiente, excepto cuando el baseline está ausente: ese caso MUST ser éxito y no publicar comando, conforme RN-74.

Esta es una migración breaking: no se admiten `items`, `version` ni acciones por ítem; el body legacy con `items` MUST responder `422` y no existe alias de compatibilidad.

#### Scenario: Bulk reject — resultado parcial
- **WHEN** el admin envía 2 IDs y una carrera cambia la versión vigente de uno después de cargarlo
- **THEN** la respuesta es `200 OK`
- **AND** `succeeded` tiene el ítem válido
- **AND** `failed` tiene el conflictivo con `reason="conflict"`

#### Scenario: Bulk reject aplica una acción común
- **WHEN** el admin envía `{event_ids:[1,2], action:"quarantine"}`
- **THEN** `succeeded` contiene ambos `event_id`
- **AND** se publicaron dos comandos `quarantine_file`

#### Scenario: Bulk reject con baseline ausente es no-op exitoso
- **WHEN** uno de los eventos tiene baseline ausente
- **THEN** su ID aparece en `succeeded`
- **AND** no se publica comando para ese evento

#### Scenario: Bulk reject legacy es rechazado
- **WHEN** el admin envía un body con `items`
- **THEN** la respuesta es `422 Unprocessable Entity`

### Requirement: Comando baseline_update publicado en Valkey al aprobar

Al aprobar exitosamente un evento, el sistema SHALL publicar en el stream `commands` de Valkey un mensaje con los campos: `type="baseline_update"`, `command_id` (UUID v4), `event_id`, `target_agent_id` (igual a `event.agent_id`), `path` (igual a `event.path`), `hash` (igual a `event.hash`, puede ser null), `baseline_status` ("present" | "absent"), `ruleset_version` (counter global incrementado, D5), `issued_at` (ISO8601 UTC), `signature` (HMAC-SHA256 hex del payload canónico con la clave `shared_secret` del agente). NO se publica ningún comando `get_file_hash` (D2, D8).

**La emisión del comando SHALL pasar por el outbox transaccional (D37 / RN-131, prevalece sobre FIX-02).** La fila `PublishedCommand` con el payload ya firmado SHALL insertarse con `status="pending"` y `published_at=None` **dentro de la misma transacción** que la mutación del evento, y el `XADD` SHALL ejecutarlo el despachador del outbox después del commit. El orden en `_approve_single` SHALL ser: (1) verificar hash/confirm_absent; (2) UPDATE optimista; (3) flush + refresh; (4) `_increment_ruleset_version`; (5) `_upsert_baseline_entry`; (6) `_write_audit`; (7) **encolar el comando en el outbox**; (8) `db.commit()`; (9) `db.refresh(event)`; (10) intento inmediato best-effort de publicación del outbox.

La inversión respecto de FIX-02 es deliberada. FIX-02 protegía contra que el agente recibiera un comando de una transacción que después se revirtiera; con el outbox esa protección la da la **atomicidad**, y de forma más fuerte: la fila del comando vive o muere con el evento. Si la transacción se revierte, no queda nada que publicar. Si comitea, el comando está garantizado y el despachador lo entrega con reintento. Deja de existir el estado en que un evento es terminal y su comando no se emitió.

Si el `shared_secret` del agente destino no puede obtenerse, la excepción SHALL propagarse y revertir la transacción. El endpoint SHALL responder un error. NO se permite loguear y retornar dejando el evento terminal y ningún comando emitido.

Las columnas `command_id`, `event_id` y `ack_status` de `PublishedCommand` conservan su semántica de D30/RN-124 sin cambios: `status` es el estado de outbox y `ack_status` el de ejecución confirmada por el agente, y no se fusionan.

#### Scenario: Comando baseline_update contiene los campos requeridos
- **WHEN** se aprueba un evento exitosamente
- **THEN** el mensaje en el stream `commands` contiene exactamente los campos `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `hash`, `baseline_status`, `ruleset_version`, `issued_at`, `signature`
- **AND** `signature` verifica correctamente con HMAC-SHA256 y el `shared_secret` del agente objetivo

#### Scenario: La fila del comando nace pending en la transacción del evento
- **WHEN** se aprueba un evento exitosamente
- **THEN** existe una fila `PublishedCommand` con `command_type="baseline_update"`, `status="pending"` y `published_at` nulo, comiteada junto con la mutación del evento

#### Scenario: Valkey caído deja el evento aprobado y el comando pendiente
- **WHEN** se aprueba un evento y el `XADD` falla porque Valkey no responde
- **THEN** el endpoint responde exitosamente, el evento queda `approved` y la fila del comando queda `pending`
- **AND** el despachador del outbox publica el comando en una corrida posterior y la marca `published`

#### Scenario: Una transacción revertida no deja comando encolado
- **WHEN** la aprobación falla después de encolar el comando y la transacción se revierte
- **THEN** no queda ninguna fila `PublishedCommand` para ese evento y el evento conserva su estado anterior

#### Scenario: Un agente sin shared_secret hace fallar la aprobación
- **WHEN** se aprueba un evento cuyo agente no tiene `shared_secret_hex`
- **THEN** la transacción se revierte, el evento NO queda `approved` y el endpoint responde un error

#### Scenario: No se publica get_file_hash
- **WHEN** se procesa cualquier approve o reject
- **THEN** no aparece ningún mensaje de tipo `get_file_hash` en el stream `commands`

### Requirement: Comandos restore_file / quarantine_file publicados en Valkey al rechazar

Al rechazar exitosamente, el sistema SHALL publicar en el stream `commands` un mensaje con: `type="restore_file"` o `type="quarantine_file"`, `command_id` (UUID v4), `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`. No incluye `hash` ni `ruleset_version`.

**La emisión del comando SHALL pasar por el outbox transaccional (D37 / RN-131, prevalece sobre FIX-02)**, con el mismo criterio que `baseline_update`: la fila `PublishedCommand` con el payload firmado se inserta con `status="pending"` dentro de la transacción del evento, y el despachador hace el `XADD` después del commit. El orden en `_reject_single` SHALL ser: (1) UPDATE optimista; (2) flush + refresh; (3) consultar `baseline_entry`; (4) `_write_audit`; (5) **encolar el comando en el outbox** según corresponda, salvo en el no-op de baseline `absent` (RN-74); (6) `db.commit()`; (7) `db.refresh(event)`; (8) intento inmediato best-effort de publicación del outbox.

El no-op de baseline `absent` (RN-74) conserva su comportamiento: no se encola comando alguno.

Si el `shared_secret` del agente destino no puede obtenerse, la excepción SHALL propagarse y revertir la transacción; el endpoint SHALL responder un error en lugar de dejar el evento `rejected` sin comando emitido.

#### Scenario: Comando restore_file contiene campos requeridos
- **WHEN** se rechaza con `action="restore"`
- **THEN** el mensaje en el stream contiene `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `issued_at`, `signature`
- **AND** la `signature` verifica con el `shared_secret` del agente

#### Scenario: La fila del comando nace pending en la transacción del rechazo
- **WHEN** se rechaza un evento exitosamente con `action="quarantine"`
- **THEN** existe una fila `PublishedCommand` con `command_type="quarantine_file"`, `status="pending"` y `published_at` nulo, comiteada junto con la mutación del evento

#### Scenario: Valkey caído deja el evento rechazado y el comando pendiente
- **WHEN** se rechaza un evento y el `XADD` falla porque Valkey no responde
- **THEN** el endpoint responde exitosamente, el evento queda `rejected` y la fila del comando queda `pending`
- **AND** el despachador del outbox lo publica en una corrida posterior

#### Scenario: El no-op de baseline absent no encola comando
- **WHEN** se rechaza un evento cuyo `baseline_entry` tiene `status=absent`
- **THEN** no se inserta ninguna fila `PublishedCommand` y el evento queda `rejected`

#### Scenario: Un agente sin shared_secret hace fallar el rechazo
- **WHEN** se rechaza un evento cuyo agente no tiene `shared_secret_hex`
- **THEN** la transacción se revierte, el evento NO queda `rejected` y el endpoint responde un error

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

