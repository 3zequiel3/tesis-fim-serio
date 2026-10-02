## ADDED Requirements

### Requirement: POST /events/{id}/quarantine/release encola una liberación firmada

El backend SHALL exponer `POST /events/{id}/quarantine/release` con cuerpo `{mode, reason}`
(`extra="forbid"`), donde `mode ∈ {restore_original, restore_baseline, discard}` y `reason` es
obligatorio, de 1 a 500 caracteres tras recortar espacios. El endpoint SHALL requerir
`require_admin` y operar sobre un único evento. En una sola transacción SHALL: bloquear la fila del
evento, verificar elegibilidad, insertar en el outbox `published_commands` el comando
`release_quarantine` firmado con HMAC-SHA256 con `command_id`, `event_id`, `source_event_id`,
`target_agent_id`, `path`, `mode`, `expected_sha256 = event.hash_detected`, `issued_at` y
`schema_version` (y `ruleset_version` incrementado sólo en `restore_original`), con
`ack_status = pending`, e insertar la entrada de `audit_log`. SHALL responder `202 Accepted` con
`{event_id, command_id, mode, ack_status: "pending"}` y luego intentar la publicación inmediata
best-effort del outbox (D37/RN-131). (D83/RN-177)

#### Scenario: Liberación aceptada
- **WHEN** un admin envía `{"mode": "discard", "reason": "falso positivo confirmado"}` para un evento con `quarantine_state = quarantined`
- **THEN** la respuesta es `202` con `ack_status = "pending"`
- **AND** existe un `PublishedCommand` `release_quarantine` con el mismo `command_id`, `ack_status = pending` y payload firmado con `mode = "discard"`

#### Scenario: restore_original lleva ruleset_version
- **WHEN** un admin solicita `restore_original`
- **THEN** el payload incluye `ruleset_version` igual al valor recién incrementado y la fila lo persiste

#### Scenario: Motivo vacío
- **WHEN** el cuerpo trae `reason` vacío o sólo espacios
- **THEN** la respuesta es `422` y no se inserta comando ni entrada de auditoría

#### Scenario: Modo inválido
- **WHEN** el cuerpo trae `mode = "restore"`
- **THEN** la respuesta es `422`

#### Scenario: Usuario no admin
- **WHEN** un usuario con rol distinto de admin llama al endpoint
- **THEN** la respuesta es `403` y no se inserta nada

#### Scenario: Evento inexistente
- **WHEN** el `id` no existe
- **THEN** la respuesta es `404`

### Requirement: Sólo se libera una cuarentena vigente y a lo sumo una vez

El endpoint SHALL responder `409 {code: "quarantine_not_releasable"}` cuando `quarantine_state` del
evento no es `quarantined` o `hash_detected` está vacío, y `409 {code: "release_in_progress"}` cuando
existe un `release_quarantine` del evento con `ack_status ∈ {pending, acked}`. Un
`release_quarantine` previo en `failed` o `timeout` MUST NOT impedir un nuevo intento. Dos pedidos
concurrentes sobre el mismo evento MUST producir a lo sumo un comando. (D83/RN-177)

#### Scenario: Evento sin cuarentena
- **WHEN** se solicita la liberación de un evento `approved` sin cuarentena
- **THEN** la respuesta es `409` con `code = "quarantine_not_releasable"`

#### Scenario: Liberación ya confirmada
- **WHEN** el evento tiene un `release_quarantine` con `ack_status = acked`
- **THEN** la respuesta es `409` con `code = "quarantine_not_releasable"` (su `quarantine_state` ya no es `quarantined`)

#### Scenario: Liberación pendiente
- **WHEN** el evento tiene un `release_quarantine` con `ack_status = pending`
- **THEN** la respuesta es `409` con `code = "release_in_progress"`

#### Scenario: Reintento tras fallo
- **WHEN** el último `release_quarantine` del evento terminó `failed` con `path_occupied`
- **THEN** un nuevo pedido es aceptado con `202`

#### Scenario: Pedidos concurrentes
- **WHEN** dos pedidos válidos para el mismo evento llegan al mismo tiempo
- **THEN** uno recibe `202` y el otro `409` con `code = "release_in_progress"`

### Requirement: La liberación no cambia el estado del evento y queda auditada

El endpoint MUST NOT modificar `status`, `version`, `resolved_at` ni `resolved_by` del evento. SHALL
registrar en `audit_log` una entrada con `user_id` del admin, `action = "quarantine_release"`,
`target_type = "event"`, `target_id = event.id` y `detail` con `mode`, `reason` y `command_id`, en la
misma transacción que el comando (RN-94). El `reason` MUST NOT viajar en el comando al agente.
(D83/RN-177)

#### Scenario: Estado intacto
- **WHEN** se acepta la liberación de un evento `quarantined` con `version = 3`
- **THEN** tras la respuesta el evento sigue `quarantined` con `version = 3`

#### Scenario: Evento rechazado con cuarentena
- **WHEN** se acepta la liberación de un evento `rejected` cuyo `quarantine_file` está `acked`
- **THEN** el evento sigue `rejected`

#### Scenario: Entrada de auditoría
- **WHEN** se acepta una liberación
- **THEN** existe exactamente una entrada `audit_log` con `action = "quarantine_release"` y `detail` con `mode`, `reason` y el mismo `command_id` del outbox

#### Scenario: Fallo de firma revierte todo
- **WHEN** el agente destino no tiene `shared_secret_hex`
- **THEN** la transacción se revierte y no queda ni comando ni entrada de auditoría
