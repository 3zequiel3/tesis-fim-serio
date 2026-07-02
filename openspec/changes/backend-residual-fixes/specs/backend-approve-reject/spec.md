## MODIFIED Requirements

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
