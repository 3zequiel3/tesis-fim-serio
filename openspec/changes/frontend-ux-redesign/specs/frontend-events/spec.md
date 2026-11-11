## MODIFIED Requirements

### Requirement: Aprobar y rechazar un evento individual con manejo de 409

El frontend SHALL permitir aprobar (`POST /actions/approve` con `{event_id, version, confirm_absent?}`) y rechazar (`POST /actions/reject` con `{event_id, version, action}`) un evento individual desde el detalle o la tabla, enviando siempre el `version` del último dato fetcheado (optimistic locking). Los controles Aprobar y Rechazar MUST mostrarse sólo para eventos con `status = pending`, que es el único estado que el backend acepta resolver, y sólo a un usuario con `role = admin` (D93/RN-187). Ante respuesta `409` en approve o reject, el frontend SHALL mostrar el toast "Este evento ya fue resuelto o reemplazado. Refrescando lista..." (US-11, US-12, C5) e invalidar las queries del evento y de la lista (RN-77). Ante `422` cuyo código, leído de `detail.code` con el lector único de errores (D90/RN-184), es `absent_confirmation_required` en approve, el frontend SHALL mostrar el aviso "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline." (US-11), exigir una confirmación explícita y, al confirmar, reintentar con `confirm_absent:true`. Cancelar MUST descartar el aviso sin enviar la request. Cualquier otro error MUST mostrar el `detail.message` si existe o un mensaje genérico en español, nunca `[object Object]`. Un rechazo que encola una restauración o cuarentena MUST informar «Rechazo registrado; restauración solicitada» (o «cuarentena solicitada») y no un éxito de la acción, cuyo resultado se informa por el indicador de ejecución.

#### Scenario: Approve exitoso refresca el estado
- **WHEN** el admin aprueba un evento `pending` con `version` correcto
- **THEN** se hace `POST /actions/approve` con `{event_id, version}`
- **AND** ante `200` se muestra un toast de éxito y se invalidan las queries del evento y la lista

#### Scenario: 409 muestra toast y refresca
- **WHEN** una acción approve/reject retorna `409`
- **THEN** se muestra un toast "Este evento ya fue resuelto o reemplazado. Refrescando lista..."
- **AND** se invalidan las queries del evento afectado y de la lista para reflejar el estado real

#### Scenario: Approve de evento ausente pide confirmación
- **WHEN** approve retorna `422` con body `{"detail": {"code": "absent_confirmation_required"}}`
- **THEN** el frontend muestra el aviso "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline."
- **AND** al confirmar reintenta `POST /actions/approve` con `confirm_absent:true`

#### Scenario: Cancelar la aprobación de un archivo ausente no envía la request
- **WHEN** el aviso de archivo ausente está visible y el admin elige Cancelar
- **THEN** el aviso desaparece
- **AND** no se envía ningún `POST /actions/approve` adicional

#### Scenario: Un evento alert_only no ofrece Aprobar ni Rechazar
- **WHEN** el admin abre el detalle de un evento con `status = alert_only` u otro estado distinto de `pending`
- **THEN** no se muestran los botones Aprobar ni Rechazar

#### Scenario: Un error con detail objeto no muestra [object Object]
- **WHEN** approve retorna `422` con `{"detail": {"code": "otro_codigo", "message": "Mensaje del servidor."}}`
- **THEN** el toast muestra «Mensaje del servidor.»

#### Scenario: El rechazo con restauración no anuncia un éxito prematuro
- **WHEN** el admin rechaza con `action = restore` y el backend responde 200
- **THEN** el toast dice «Rechazo registrado; restauración solicitada»
- **AND** el indicador de ejecución del detalle queda en pendiente hasta que llegue el `ack_status`

## ADDED Requirements

### Requirement: El detalle y la cadena de un evento tienen estados de error explícitos

`EventDetail` y `EventChain` SHALL validar el parámetro `:id` antes de consultar: un valor que no sea un entero positivo MUST mostrar «Evento no encontrado» con un enlace a la lista, sin enviar ninguna request. Un `404` MUST mostrar el mismo estado. Cualquier otro error (red, `5xx`, `403`) MUST mostrar un estado de error con el mensaje leído por el lector único y un botón «Reintentar» que repite la consulta; la vista MUST NOT quedar indefinidamente en «Cargando...» (D93/RN-187).

#### Scenario: Id no numérico
- **WHEN** el usuario navega a `/events/abc`
- **THEN** se muestra «Evento no encontrado» y no se envía `GET /events/NaN` ni ninguna otra request de evento

#### Scenario: Error del servidor con reintento
- **WHEN** `GET /events/7` responde `500`
- **THEN** se muestra un estado de error con «Reintentar»
- **AND** al activarlo se repite `GET /events/7`

#### Scenario: La cadena maneja el error igual
- **WHEN** `GET /events/7/chain` responde `503`
- **THEN** `EventChain` muestra el estado de error con «Reintentar», no «Cargando...»

### Requirement: El detalle reconsulta el comando pendiente y explica su fallo

Mientras el `ack_status` del último comando de un evento sea `pending`, el detalle SHALL reconsultar `GET /events/{id}` cada 3 segundos durante a lo sumo 60 segundos desde que se observó el estado pendiente; al vencer ese plazo MUST dejar de reconsultar y ofrecer «Actualizar», indicando que el backend marca el comando como vencido a los 5 minutos. Cuando `ack_status` es `failed`, el detalle MUST mostrar el motivo leído de `ack_error` traducido al español con el mismo mapa de causas que usa `action_error` (p. ej. `no_restorable_content` → «el baseline no tiene contenido restaurable»); un código desconocido MUST mostrarse literal con el prefijo «Motivo:». Esto aplica a la liberación de cuarentena, al rechazo con restauración o cuarentena y a la aprobación (D93/RN-187, D30/RN-124).

#### Scenario: La liberación de cuarentena se refleja sin recargar
- **WHEN** el admin solicita liberar una cuarentena y el detalle muestra `ack_status = pending`
- **AND** a los 4 segundos el backend devuelve `ack_status = acked` y `quarantine_state = released`
- **THEN** el detalle muestra la ejecución confirmada y el estado liberado sin intervención del usuario

#### Scenario: La reconsulta se detiene
- **WHEN** `ack_status` sigue `pending` durante 60 segundos
- **THEN** no se envían más `GET /events/{id}` automáticos y se ofrece «Actualizar»

#### Scenario: Fallo con motivo legible
- **WHEN** el backend devuelve `ack_status = failed` y `ack_error = "no_restorable_content"`
- **THEN** el detalle muestra «Ejecución: falló» con el motivo «el baseline no tiene contenido restaurable»

### Requirement: El diff se compara por palabras y el proceso desconocido se nombra

El `DiffViewer` SHALL resaltar cambios dentro de una línea por palabras (`DiffMethod.WORDS_WITH_SPACE` de `react-diff-viewer-continued`), no por caracteres, y SHALL usar los colores de los tokens del tema activo con contraste suficiente en ambos temas. El contexto de proceso SHALL mostrar «desconocido» en lugar de `?`, `0` o vacío cuando `process_pid` es `null` o `0`, y cuando `process_exe` es `null` o `"?"`, tanto en la tabla como en el detalle; un `process_uid = 0` MUST seguir mostrándose como `0` (root es un dato válido).

#### Scenario: Una palabra cambiada no se fragmenta en letras
- **WHEN** el diff contiene la línea `PermitRootLogin no` cambiada a `PermitRootLogin yes`
- **THEN** el resaltado marca `no` y `yes` como palabras completas

#### Scenario: pid 0 se muestra como desconocido
- **WHEN** un evento tiene `process_pid = 0` y `process_exe = null`
- **THEN** la tabla y el detalle muestran «desconocido» para el pid y el ejecutable

### Requirement: La lista de eventos se mantiene al día y sanea su estado

La lista de eventos SHALL invalidar la query `['events']` ante cada mensaje del SSE de alertas y SHALL reconsultar cada 15 segundos mientras la pestaña está visible (`refetchIntervalInBackground: false`). El parámetro `page` de la URL SHALL sanearse a un entero ≥ 1 (un valor no numérico o menor vuelve a `1`) y `page_size` a uno de los valores admitidos, sin enviar `NaN` al backend. El filtro de ruta con debounce MUST enviar sólo el último valor escrito: una respuesta de un valor anterior que llega tarde MUST NOT reemplazar la de un valor más nuevo. «Seleccionar todo» MUST seleccionar sólo los ids de la página visible en ese momento y la selección MUST depurarse de ids que dejaron de estar en la lista tras un refresco. `RejectModal` MUST reiniciar su estado (acción elegida, confirmación) cada vez que se abre y MUST tolerar un evento con `path` nulo (detección por hueco, D50/RN-144) mostrando «ruta desconocida» (D93/RN-187).

#### Scenario: Un evento nuevo aparece sin recargar
- **WHEN** la lista está abierta y llega un mensaje por el SSE de alertas
- **THEN** se vuelve a consultar `GET /events` con los filtros vigentes

#### Scenario: Página no numérica
- **WHEN** el usuario navega a `/events?page=abc`
- **THEN** la request enviada usa `page=1`

#### Scenario: Respuesta tardía del filtro de ruta
- **WHEN** el usuario escribe `/et` y luego `/etc/ssh`, y la respuesta de `/et` llega después que la de `/etc/ssh`
- **THEN** la tabla muestra el resultado de `/etc/ssh`

#### Scenario: Seleccionar todo tras un refresco
- **WHEN** el admin selecciona todo, la lista se refresca y dos eventos dejan de estar `pending`
- **THEN** la selección contiene sólo los ids presentes en la lista refrescada

#### Scenario: RejectModal se reinicia
- **WHEN** el admin abre el modal de rechazo, elige una acción, lo cancela y lo vuelve a abrir
- **THEN** el modal muestra el estado inicial
