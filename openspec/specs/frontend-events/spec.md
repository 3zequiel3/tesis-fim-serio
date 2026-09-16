# Spec: frontend-events

## Purpose
Proveer al admin la pantalla central de operación: revisar eventos de integridad de archivos, inspeccionar el diff de cada cambio de forma segura, ver el contexto de proceso y la cadena de eventos, y aprobar o rechazar cambios (individual o masivamente) consumiendo los endpoints REST del backend (C11, C13) y el stream SSE de alertas (C16).
## Requirements
### Requirement: Página de eventos paginada con filtros multi-select sincronizados en URL

El frontend SHALL proveer `frontend/src/pages/Events.tsx` que renderiza una tabla paginada de 50 ítems por página consumiendo `GET /events`. Todos los filtros (`status` multi-select, `path_prefix`, `date_from`, `date_to`), el toggle `include_superseded` y el número de `page` SHALL vivir en los query params de la URL vía `useSearchParams` de `react-router-dom`. El query key de TanStack Query SHALL derivarse de los filtros parseados desde la URL, de modo que cambiar cualquier filtro dispare un refetch. Por defecto (`include_superseded` ausente) la lista SHALL excluir eventos `superseded` (RN-22, RN-98). La página SHALL registrarse en la ruta protegida `/events` de `App.tsx`, reemplazando el placeholder de C17.

#### Scenario: Listado default excluye superseded y muestra 50 por página
- **WHEN** el admin navega a `/events` sin query params
- **THEN** se hace `GET /events?page=1&page_size=50` (sin `include_superseded`)
- **AND** la tabla muestra solo eventos con `status != superseded`
- **AND** el control de paginación refleja `total`, `page` y `page_size` de la respuesta

#### Scenario: Filtro multi-select de status se refleja en la URL
- **WHEN** el admin selecciona los estados `pending` y `approved` en el filtro
- **THEN** la URL pasa a contener `?status=pending&status=approved`
- **AND** se hace `GET /events?status=pending&status=approved&page=1&page_size=50`
- **AND** la tabla muestra solo eventos con esos estados

#### Scenario: Filtros de path_prefix y fechas se reflejan en la URL
- **WHEN** el admin ingresa `path_prefix=/etc/`, `date_from` y `date_to`
- **THEN** la URL contiene esos query params
- **AND** la petición a `GET /events` incluye los mismos parámetros

#### Scenario: Toggle "Mostrar superseded" persiste en la URL e incluye superseded
- **WHEN** el admin activa el toggle "Mostrar superseded"
- **THEN** la URL pasa a contener `?include_superseded=true`
- **AND** se hace `GET /events?include_superseded=true&...`
- **AND** los eventos `superseded` aparecen con ícono de cadena rota y un link a su `parent_event_id`

#### Scenario: Deep-link reconstruye el estado de la vista
- **WHEN** se carga directamente la URL `/events?status=pending&page=2&include_superseded=true`
- **THEN** la vista arranca con esos filtros aplicados, en la página 2, con superseded visibles
- **AND** la petición inicial a `GET /events` refleja exactamente esos parámetros

#### Scenario: Navegación del browser (back/forward) restaura filtros
- **WHEN** el admin cambia filtros y luego presiona "atrás" en el browser
- **THEN** la vista vuelve al estado de filtros anterior sin recargar la página completa

#### Scenario: Cambio de página dispara refetch
- **WHEN** el admin avanza a la página 2
- **THEN** la URL contiene `page=2` y se hace `GET /events?page=2&page_size=50&...`

### Requirement: Tabla de eventos con selección múltiple

El frontend SHALL proveer `frontend/src/components/ui/EventsTable.tsx` que renderiza las filas de eventos con un checkbox por fila y un checkbox "seleccionar todos en la página". La selección SHALL mantenerse en estado local efímero (no en la URL) como un conjunto de `event_id`. Cada fila SHALL mostrar al menos `path`, `status`, `detected_at` y permitir abrir el detalle del evento. Las filas de eventos `superseded` SHALL mostrar un indicador visual de cadena rota.

#### Scenario: Seleccionar una fila la agrega a la selección
- **WHEN** el admin marca el checkbox de una fila
- **THEN** ese `event_id` queda en la selección
- **AND** la BulkActionBar se vuelve visible

#### Scenario: Seleccionar todos en la página
- **WHEN** el admin marca el checkbox de cabecera "seleccionar todos en la página"
- **THEN** todos los eventos visibles de la página actual quedan seleccionados

#### Scenario: La selección se limpia al cambiar de página o filtro
- **WHEN** el admin cambia de página o modifica un filtro con filas seleccionadas
- **THEN** la selección se vacía (solo se acciona sobre lo visible)

#### Scenario: Abrir el detalle de un evento desde una fila
- **WHEN** el admin hace click en una fila (fuera del checkbox)
- **THEN** se navega a `/events/:id` o se abre el drawer de detalle de ese evento

### Requirement: Detalle de evento con timestamps dobles, contexto de proceso y diff seguro

El frontend SHALL proveer una vista de detalle de evento (`frontend/src/pages/EventDetail.tsx` o drawer) que consume `GET /events/{id}` y muestra: `path`, `hash_detected`, los timestamps dobles `detected_at` y `received_at` (RN-90), el contexto de proceso `process_pid`, `process_uid`, `process_exe` (RN-03), el `status`, el `resolved_at`/`resolved_by` cuando existan, y la cadena de eventos vía `parent_event_id`. El detalle SHALL incluir un `DiffViewer` seguro y un `EventTimeline`.

#### Scenario: Detalle muestra timestamps dobles y contexto de proceso
- **WHEN** el admin abre el detalle de un evento existente
- **THEN** se hace `GET /events/{id}`
- **AND** se muestran `detected_at` y `received_at` como timestamps separados
- **AND** se muestran `process_pid`, `process_uid` y `process_exe`

#### Scenario: Evento inexistente muestra estado de no encontrado
- **WHEN** se abre el detalle de un `id` que retorna `404`
- **THEN** la vista muestra un mensaje de "evento no encontrado" sin romper la app

### Requirement: DiffViewer seguro sin dangerouslySetInnerHTML

El frontend SHALL proveer `frontend/src/components/ui/DiffViewer.tsx` que usa `react-diff-viewer-continued` con las opciones de escapado activas (RN-96, W8). El uso de `dangerouslySetInnerHTML` SHALL estar prohibido en este componente y en todo el codebase frontend. El componente SHALL auto-detectar contenido binario (presencia de byte nulo o secuencias no-UTF8); para contenido binario SHALL mostrar el hash y un hex dump de los primeros 256 bytes en lugar de un diff de texto. Para contenido de texto SHALL mostrar un diff (vista split por defecto).

#### Scenario: Diff de texto se renderiza escapado
- **WHEN** se muestra el diff de un archivo de texto cuyo contenido incluye caracteres HTML (`<script>`)
- **THEN** el contenido se renderiza escapado como texto literal, nunca interpretado como HTML
- **AND** no se usa `dangerouslySetInnerHTML` en ningún punto del render

#### Scenario: Contenido binario muestra hash y hex dump
- **WHEN** el contenido a diffear contiene un byte nulo (es binario)
- **THEN** el componente NO intenta un diff de texto
- **AND** muestra el hash del archivo y un hex dump de los primeros 256 bytes

#### Scenario: Diff de texto usa vista split por defecto
- **WHEN** se muestra el diff de un archivo de texto
- **THEN** la vista por defecto es split (lado a lado)

### Requirement: Timeline de cadena de eventos por parent_event_id

El frontend SHALL proveer `frontend/src/components/ui/EventTimeline.tsx` que visualiza la cadena de eventos enlazados por `parent_event_id` (RN-21–24). Los eventos `superseded` de la cadena SHALL marcarse como tales, y el evento accionable más reciente SHALL distinguirse visualmente.

#### Scenario: Cadena con superseded se visualiza ordenada
- **WHEN** un evento tiene una cadena de predecesores `superseded` vía `parent_event_id`
- **THEN** el timeline muestra la cadena en orden cronológico
- **AND** los eventos `superseded` aparecen marcados y el más reciente queda destacado

#### Scenario: Evento sin cadena muestra timeline trivial
- **WHEN** un evento no tiene `parent_event_id`
- **THEN** el timeline muestra solo ese evento como único nodo

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

### Requirement: Bulk approve y bulk reject con modal de confirmación y resultado parcial

El frontend SHALL proveer `frontend/src/components/ui/BulkActionBar.tsx` que aparece cuando hay ≥1 evento seleccionado y permite aprobar o rechazar la selección, siempre con un modal de confirmación (RN-99, W15). El bulk approve SHALL mostrar el conteo y las primeras 10 paths y llamar `POST /actions/bulk-approve` con el contrato canónico `{event_ids:[...]}`. El bulk reject SHALL pedir adicionalmente una acción común (`restore`|`quarantine`) y llamar `POST /actions/bulk-reject` con `{event_ids:[...], action}`. La respuesta `{succeeded[], failed[]}` SHALL traducirse en un toast con los conteos y SHALL invalidar la query de la lista.

El contrato canónico es una migración breaking: el frontend MUST NOT emitir `items`, `version`, `confirm_absent`, acciones por ítem ni `baseline_absent` en el bulk wire. No hay alias legacy; un body con `items` MUST ser rechazado por el backend con `422`.

#### Scenario: BulkActionBar aparece con selección
- **WHEN** hay al menos un evento seleccionado
- **THEN** la BulkActionBar se muestra con acciones aprobar/rechazar y el conteo de seleccionados

#### Scenario: Bulk approve confirma antes de ejecutar
- **WHEN** el admin pulsa "aprobar selección"
- **THEN** se abre un modal mostrando el conteo y las primeras 10 paths
- **AND** al confirmar se hace `POST /actions/bulk-approve` con `{event_ids:[...]}`

#### Scenario: Bulk reject pide acción restore/quarantine
- **WHEN** el admin pulsa "rechazar selección"
- **THEN** el modal pide elegir `restore` o `quarantine`
- **AND** al confirmar se hace `POST /actions/bulk-reject` con `{event_ids:[...], action}`

#### Scenario: El frontend no conserva el wire legacy
- **WHEN** se serializa una acción masiva
- **THEN** el body no contiene `items`, versiones ni campos de baseline
- **AND** una forma legacy con `items` recibe `422` del backend

#### Scenario: Resultado parcial se refleja en un toast con conteos
- **WHEN** una acción masiva retorna `{succeeded:[...], failed:[...]}` con fallos
- **THEN** se muestra un toast indicando cuántos tuvieron éxito y cuántos fallaron
- **AND** se invalida la query de la lista para reflejar los cambios

### Requirement: Feed de alertas en tiempo real vía SSE

El frontend SHALL proveer `frontend/src/hooks/useAlertsSSE.ts` que abre una conexión `EventSource` a `GET /alerts/stream?ticket=<ticket>`. Antes de cada conexión y de cada reconexión, el hook SHALL obtener un ticket nuevo mediante `POST /alerts/stream-ticket` a través del cliente HTTP autenticado (JWT en header, con el refresh automático del interceptor), porque `EventSource` no admite headers y el ticket es de un solo uso (D64/RN-158). La URL del stream MUST NOT contener el access token. Cada alerta nueva recibida SHALL disparar un toast de notificación e invalidar las queries `['alerts']`, `['dashboard']` y `['alerts-failed-count']`, y el hook SHALL registrar el `lastEventId` de la última alerta recibida.

Como la reconexión nativa de `EventSource` reutilizaría la URL con un ticket ya consumido, ante cualquier error de la conexión el hook SHALL cerrar el `EventSource` de inmediato y SHALL reabrir manualmente con un ticket nuevo tras un backoff exponencial (1 s inicial, duplicando hasta un máximo de 30 s, reiniciado al abrir con éxito). Al reabrir, si ya recibió alguna alerta, el hook SHALL pasar el último id en el query param `last_event_id` para no perder alertas (D-EV-6). Tras una reapertura exitosa, el hook SHALL invalidar las mismas queries para reflejar cambios ocurridos durante el corte. Si la obtención del ticket falla por sesión inválida (401 tras el intento de refresh) o falta de permisos (403), el hook SHALL dejar de reintentar. La conexión SHALL depender de la existencia de sesión y no del valor puntual del access token: una rotación del access token MUST NOT reabrir el stream. El hook SHALL cerrar la conexión y cancelar cualquier reintento pendiente al desmontar o al cerrar la sesión.

#### Scenario: Alerta nueva dispara un toast
- **WHEN** el backend emite un evento SSE de alerta y el hook está conectado
- **THEN** el frontend muestra un toast con la información de la alerta
- **AND** invalida las queries `['alerts']`, `['dashboard']` y `['alerts-failed-count']`

#### Scenario: La conexión usa un ticket y no el access token
- **WHEN** el hook se monta con una sesión activa
- **THEN** hace `POST /alerts/stream-ticket` antes de crear el `EventSource`
- **AND** la URL del `EventSource` contiene `ticket=<ticket recibido>` y no contiene `token=` ni el valor del access token

#### Scenario: La conexión se cierra al desmontar
- **WHEN** el componente que usa `useAlertsSSE` se desmonta
- **THEN** la conexión `EventSource` se cierra
- **AND** no se ejecuta ningún reintento programado

#### Scenario: Reconexión tras corte con ticket nuevo y último id
- **WHEN** el hook recibió la alerta con id 9 y la conexión SSE emite un error
- **THEN** el hook cierra el `EventSource` sin esperar la reconexión nativa
- **AND** tras el backoff pide un ticket nuevo y abre un `EventSource` nuevo con `ticket=<ticket nuevo>` y `last_event_id=9`

#### Scenario: Reconexión sin alertas previas no envía last_event_id
- **WHEN** la conexión falla antes de recibir cualquier alerta
- **THEN** la nueva URL contiene un ticket nuevo y no contiene `last_event_id`

#### Scenario: Backoff exponencial acotado
- **WHEN** la obtención del ticket o la conexión fallan de forma consecutiva por errores de red
- **THEN** los reintentos se programan a 1 s, 2 s, 4 s, … hasta un máximo de 30 s entre intentos
- **AND** una apertura exitosa reinicia el backoff a 1 s

#### Scenario: Sesión inválida detiene los reintentos
- **WHEN** `POST /alerts/stream-ticket` responde 401 tras el intento de refresh o responde 403
- **THEN** el hook no programa más reintentos

#### Scenario: Rotación del access token no reabre el stream
- **WHEN** el access token se renueva mientras el stream está abierto
- **THEN** el `EventSource` existente permanece abierto y no se pide un ticket nuevo

### Requirement: The date filters query the range the operator asked for

The `Desde` and `Hasta` filters are `<input type="datetime-local">` controls, which yield a wall-clock string in the browser's own zone and carry no offset. That value SHALL be converted to UTC before it reaches the API.

Today it is sent raw and compared against UTC columns (`Events.tsx:125,136` → `frontend/src/api/events.ts:93-94` → `backend/app/modules/events/router.py:97-101`), so in a UTC−3 zone the window queried is displaced three hours from the window requested. The range filtered MUST be the range requested.

The conversion SHALL happen when the HTTP request is built, not when the filter is written to the URL. The URL is shared state — bookmarked, pasted into a ticket — and keeping it in the operator's own wall-clock reading preserves both its legibility and the meaning of links saved before this change. This yields exactly one conversion point, which is where the test goes.

#### Scenario: A local range is sent as the corresponding instants
- **WHEN** the operator selects a range in a browser fixed to `America/Argentina/Buenos_Aires`
- **THEN** the request carries the equivalent UTC instants with explicit offsets

#### Scenario: The events returned are the ones inside the requested wall-clock window
- **WHEN** the operator filters from 09:00 to 10:00 local time
- **THEN** the events returned are those whose `created_at` falls in that local hour, and an event at 08:30 local is excluded

#### Scenario: The URL keeps the operator's local reading
- **WHEN** a date filter is active
- **THEN** the query string carries the local wall-clock value the operator entered, so the URL remains legible and a link saved earlier keeps its original meaning

#### Scenario: The input repopulates from the URL without conversion
- **WHEN** a URL carrying date filters is opened
- **THEN** the `datetime-local` inputs show the same values the URL carries, with no local-to-UTC-to-local round trip

#### Scenario: An absent filter sends nothing
- **WHEN** a date filter is cleared
- **THEN** the parameter is omitted from the request rather than sent as an empty or epoch value

### Requirement: Event timestamps are displayed with their zone through the shared helper

The event table, the event detail and the event timeline SHALL render every instant through the shared display helper (`frontend-time-display`), showing the zone alongside the absolute time.

The double timestamps of RN-90 — `detected_at` from the agent and `received_at` from the backend — are the primary forensic instrument of the console, and the interval between them is only meaningful once both are read against a stated clock.

#### Scenario: The event detail shows both instants with their zone
- **WHEN** an event detail is displayed
- **THEN** `detected_at` and `received_at` are each shown as an absolute instant in the viewer's zone, with the zone visible

#### Scenario: A resolved event shows its resolution instant, and a pending one shows none
- **WHEN** an event has `resolved_at` set, and another does not
- **THEN** the first shows the instant with its zone and the second shows an explicit absence, never `Invalid Date`

#### Scenario: The timeline preserves ordering under the viewer's zone
- **WHEN** a chain of events is displayed in the timeline
- **THEN** the instants shown are ordered as the underlying instants are, and converting to the viewer's zone does not reorder them

### Requirement: Indicador secundario de estado de ejecución del comando por evento

El frontend SHALL exponer, en la vista de eventos (tabla y/o detalle), un indicador secundario que refleje el estado de ejecución del comando asociado al evento (`pending | acked | failed | timeout`), derivado del tracking de `PublishedCommand` expuesto por el backend. Este indicador SHALL ser visualmente distinto del `status` del evento y NO SHALL introducir un nuevo valor en la máquina de estados del evento: `approved` y `rejected` siguen siendo terminales (RN-72). Cuando un evento no tiene comando asociado con estado de ejecución, el indicador SHALL omitirse (no mostrar un estado vacío o engañoso). El tipo de dato correspondiente SHALL declararse en `frontend/src/api/events.ts`.

#### Scenario: Comando confirmado muestra indicador acked
- **WHEN** el evento tiene un comando asociado con `ack_status = acked`
- **THEN** la vista muestra un indicador secundario "acked" distinguible del `status` del evento

#### Scenario: Comando fallido o vencido se distingue
- **WHEN** el comando asociado está en `failed` o `timeout`
- **THEN** el indicador secundario refleja ese estado, sin cambiar el `status` terminal del evento (`approved`/`rejected`)

#### Scenario: Evento sin comando confirmable no muestra indicador
- **WHEN** el evento no tiene un comando asociado con estado de ejecución
- **THEN** el indicador secundario se omite

#### Scenario: El estado del evento no gana nuevos valores
- **WHEN** se renderiza el filtro/columna de `status` del evento
- **THEN** los valores posibles siguen siendo los de RN-72 (`pending | approved | rejected | superseded | ...`), sin agregar `acked`/`timeout`

### Requirement: Events UI distinguishes symlink events with a badge and target

The events table and the event detail view SHALL visually distinguish an event that represents a symlink from an event that represents a regular file, using a badge/indicator, and SHALL show the `symlink_target` string. The event type in `frontend/src/api/events.ts` SHALL gain the `is_symlink: boolean` and `symlink_target: string | null` fields consumed from `EventOut`. The badge MUST render only when `is_symlink` is true; regular-file events MUST render unchanged. (D33 / RN-127)

#### Scenario: Symlink event shows a badge and its target in the table
- **WHEN** the events table renders a row whose `is_symlink` is true
- **THEN** the row shows a symlink badge/indicator and surfaces the `symlink_target`

#### Scenario: Symlink event detail shows the target
- **WHEN** the event detail view opens for an event whose `is_symlink` is true
- **THEN** the detail displays the symlink indicator and the `symlink_target` string

#### Scenario: Regular-file event renders without the symlink indicator
- **WHEN** the table or detail renders an event whose `is_symlink` is false
- **THEN** no symlink badge is shown and the existing regular-file rendering is unchanged

