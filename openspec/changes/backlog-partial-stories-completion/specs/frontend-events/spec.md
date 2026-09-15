## MODIFIED Requirements

### Requirement: Aprobar y rechazar un evento individual con manejo de 409

El frontend SHALL permitir aprobar (`POST /actions/approve` con `{event_id, version, confirm_absent?}`) y rechazar (`POST /actions/reject` con `{event_id, version, action}`) un evento individual desde el detalle o la tabla, enviando siempre el `version` del último dato fetcheado (optimistic locking). Ante respuesta `409` en approve o reject, el frontend SHALL mostrar el toast "Este evento ya fue resuelto o reemplazado. Refrescando lista..." (US-11, US-12, C5) e invalidar las queries del evento y de la lista (RN-77). Ante `422` con `{code:"absent_confirmation_required"}` en approve, el frontend SHALL mostrar el aviso "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline." (US-11), exigir una confirmación explícita y, al confirmar, reintentar con `confirm_absent:true`. Cancelar MUST descartar el aviso sin enviar la request.

#### Scenario: Approve exitoso refresca el estado
- **WHEN** el admin aprueba un evento `pending` con `version` correcto
- **THEN** se hace `POST /actions/approve` con `{event_id, version}`
- **AND** ante `200` se muestra un toast de éxito y se invalidan las queries del evento y la lista

#### Scenario: 409 muestra toast y refresca
- **WHEN** una acción approve/reject retorna `409`
- **THEN** se muestra un toast "Este evento ya fue resuelto o reemplazado. Refrescando lista..."
- **AND** se invalidan las queries del evento afectado y de la lista para reflejar el estado real

#### Scenario: Approve de evento ausente pide confirmación
- **WHEN** approve retorna `422` con `{code:"absent_confirmation_required"}`
- **THEN** el frontend muestra el aviso "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline."
- **AND** al confirmar reintenta `POST /actions/approve` con `confirm_absent:true`

#### Scenario: Cancelar la aprobación de un archivo ausente no envía la request
- **WHEN** el aviso de archivo ausente está visible y el admin elige Cancelar
- **THEN** el aviso desaparece
- **AND** no se envía ningún `POST /actions/approve` adicional
