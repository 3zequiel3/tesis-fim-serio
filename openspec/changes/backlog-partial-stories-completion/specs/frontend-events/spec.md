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

### Requirement: RejectModal con branch baseline_absent

El frontend SHALL proveer `frontend/src/components/ui/RejectModal.tsx` que, para un reject normal, ofrece elegir la acción `restore` o `quarantine` y llama `POST /actions/reject` con `{event_id, version, action}`. `RejectModal` (abierto desde `EventDetail`) MUST leer `baseline_status` del evento (`GET /events/{event_id}`, capability `backend-events-api`) en lugar de `hash_detected === null` — `hash_detected` describe el evento, no el baseline, y puede estar vacío con el baseline todavía `present` (ver D2/"hash actual"). Cuando `baseline_status === "absent"`, el modal SHALL ocultar el `fieldset` de elección de acción correctiva ("Restaurar archivo" / "Poner en cuarentena") y SHALL mostrar el texto "No hay archivo a restaurar (baseline ausente). Confirmar rechazará el evento sin acción en filesystem." (US-12, C10), conservando los botones Confirmar / Cancelar. Cuando `baseline_status` es `"present"` o `null`, el modal SHALL mostrar el `fieldset` de acción correctiva como en un reject normal. Al confirmar con `baseline_status === "absent"`, el frontend llama `POST /actions/reject` con `action:"restore"` (el backend hace no-op del comando y retorna `200`, RN-74), transicionando el evento a `rejected`. Si la respuesta de `POST /actions/reject` trae `baseline_absent: true` sobre un evento cuyo modal mostró las opciones correctivas (condición de carrera entre el fetch del detalle y la confirmación), el frontend SHALL mostrar un toast informativo en lugar del toast de éxito genérico. Este requisito no alcanza al rechazo masivo (`BulkActionBar` / `POST /actions/bulk-reject`), que no invoca `RejectModal` y no expone `baseline_absent` por ítem (ver design.md → Non-Goals).

#### Scenario: Baseline absent oculta las opciones correctivas
- **WHEN** el admin abre el modal de rechazo de un evento cuyo `baseline_status` es `"absent"`
- **THEN** no se muestran los radios "Restaurar archivo" ni "Poner en cuarentena"
- **AND** se muestra el texto "No hay archivo a restaurar (baseline ausente). Confirmar rechazará el evento sin acción en filesystem."

#### Scenario: Baseline present muestra las opciones correctivas
- **WHEN** el admin abre el modal de rechazo de un evento cuyo `baseline_status` es `"present"`
- **THEN** se muestran los radios "Restaurar archivo" y "Poner en cuarentena" como hoy

#### Scenario: Baseline null (evento sin path) muestra las opciones correctivas
- **WHEN** el admin abre el modal de rechazo de un evento cuyo `baseline_status` es `null`
- **THEN** se muestran los radios "Restaurar archivo" y "Poner en cuarentena" como hoy

#### Scenario: Condición de carrera — baseline_absent en la respuesta muestra un toast informativo
- **WHEN** el admin confirma el rechazo desde un modal que mostraba las opciones correctivas
- **AND** la respuesta de `POST /actions/reject` trae `baseline_absent: true`
- **THEN** se muestra un toast informativo indicando que el rechazo no ejecutó ninguna acción sobre el filesystem, en vez del toast de éxito genérico
