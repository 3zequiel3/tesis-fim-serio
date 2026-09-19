# Spec: frontend-events

## Purpose
Proveer al admin la pantalla central de operación: revisar eventos de integridad de archivos, inspeccionar el diff de cada cambio de forma segura, ver el contexto de proceso y la cadena de eventos, y aprobar o rechazar cambios (individual o masivamente) consumiendo los endpoints REST del backend (C11, C13) y el stream SSE de alertas (C16).
## Requirements
### Requirement: Página de eventos paginada con filtros multi-select sincronizados en URL

The frontend SHALL provide `frontend/src/pages/Events.tsx`, rendering a paginated table of 50 items per page against `GET /events`. Every filter (`status` multi-select, **`severity` multi-select**, `path_prefix`, `date_from`, `date_to`), the `include_superseded` toggle and the `page` number SHALL live in the URL query params via `useSearchParams` from `react-router-dom`. The TanStack Query key SHALL derive from the filters parsed out of the URL, so that changing any filter triggers a refetch. By default (`include_superseded` absent) the list SHALL exclude `superseded` events (RN-22, RN-98). The page SHALL be registered on the protected `/events` route of `App.tsx`.

**`severity` is new in this requirement.** It SHALL be handled exactly as `status` already is — a repeatable query parameter, read with `getAll`, written with `append`, and emitted repeated on the wire — because that is the form `GET /events` accepts (`backend/app/modules/events/router.py:73`, `Annotated[list[RuleSeverity], Query(alias="severity")]`, verified live against `?severity=critical&severity=high`).

Living in the URL is not symmetry for tidiness: **it is the precondition for the dashboard deep-link**. `/events?status=pending&severity=critical&severity=high` must be a state reconstructible from a URL pasted into a ticket, exactly like every other filter. Without the URL round-trip the dashboard KPI would have nowhere to point.

`severity` SHALL be typed as `string[]`, matching `status`, rather than as a narrowed severity union. A query string is untrusted input, and a strict type here would assert a guarantee the value does not carry; the backend validates against its enum and answers 422 for an invalid value, which is where that validation belongs.

#### Scenario: Listado default excluye superseded y muestra 50 por página
- **WHEN** the admin navigates to `/events` with no query params
- **THEN** `GET /events?page=1&page_size=50` is issued (no `include_superseded`)
- **AND** the table shows only events with `status != superseded`
- **AND** the pagination control reflects `total`, `page` and `page_size` from the response

#### Scenario: Filtro multi-select de status se refleja en la URL
- **WHEN** the admin selects statuses `pending` and `approved`
- **THEN** the URL contains `?status=pending&status=approved`
- **AND** `GET /events?status=pending&status=approved&page=1&page_size=50` is issued

#### Scenario: Filtro multi-select de severidad se refleja en la URL
- **WHEN** the admin selects severities `critical` and `high`
- **THEN** the URL contains `?severity=critical&severity=high`
- **AND** the request carries one `severity` parameter per selected value, not a single comma-joined value nor a bracketed array

#### Scenario: Los filtros de estado y severidad se combinan
- **WHEN** `status=pending` and `severity=critical` are both active
- **THEN** the list shows only pending events of critical severity, and `total` reflects that intersection rather than either filter alone

#### Scenario: Un deep-link con severidad reconstruye el estado de la vista
- **WHEN** `/events?status=pending&severity=critical&severity=high` is loaded directly
- **THEN** the view starts with the pending status filter and both severities selected
- **AND** the initial request reflects exactly those parameters

#### Scenario: Quitar el filtro de severidad lo saca de la URL y de la petición
- **WHEN** the last selected severity is deselected
- **THEN** no `severity` parameter remains in the URL or in the request

#### Scenario: Filtros de path_prefix y fechas se reflejan en la URL
- **WHEN** the admin enters `path_prefix`, `date_from` and `date_to`
- **THEN** the URL carries those query params and the request to `GET /events` carries the same ones

#### Scenario: Toggle "Mostrar superseded" persiste en la URL e incluye superseded
- **WHEN** the admin activates the "Mostrar superseded" toggle
- **THEN** the URL carries `?include_superseded=true` and superseded events appear with the broken-chain icon and a link to their `parent_event_id`

#### Scenario: Navegación del browser (back/forward) restaura filtros
- **WHEN** the admin changes filters and then presses back
- **THEN** the view returns to the previous filter state without a full page reload

#### Scenario: Cambio de página dispara refetch
- **WHEN** the admin moves to page 2
- **THEN** the URL carries `page=2` and `GET /events?page=2&page_size=50&...` is issued

---

### Requirement: Tabla de eventos con selección múltiple

The frontend SHALL provide `frontend/src/components/ui/EventsTable.tsx`, rendering event rows with a per-row checkbox and a "select all on this page" checkbox. The selection SHALL live in ephemeral local state (not in the URL) as a set of `event_id`. Rows for `superseded` events SHALL carry a broken-chain indicator.

**Each row SHALL carry `path`, `status`, `severity`, `detected_at` and the causing process context (`process_pid`, `process_uid`, `process_exe`), and SHALL allow opening the event detail.**

This replaces a floor of "at least `path`, `status`, `detected_at`". That floor is what the implementation faithfully built, and it is narrower than what US-06 (`docs/historias_de_usuario.md:151`) requires: *"Cada fila muestra: path del archivo, estado, tipo de acción, severidad, fecha de creación y proceso causante (PID, UID, `exe`…)"*. The gap was recorded in `tesis/trazabilidad_us_tests.md:298` as a criterion with neither test nor implementation. Because that document's own rule (`:49-53`) states that a test of a narrower implementation does not close a wider criterion, the missing fields close together or not at all.

The **action type** of US-06 is already carried by the `status` column and needs no new field: since D35/RN-129 the backend derives `status` from the action and whether it failed, so `auto_restored`, `quarantined` and `alert_only` *are* the executed action and `pending` means no automatic action was taken. `EventOut` therefore does not need an `action` field, and the backend is not touched.

Severity SHALL be presented through the shared contract of `frontend-severity-display` — leading-edge band plus canonical text — and MUST NOT be rendered as a fourth badge. The row already carries up to three (`status`, `action_failed`, `ack_status`), and a fourth would compete on the same axis rather than adding one.

The process context SHALL be presented as a secondary line under the path, in the same typographic register the row already uses for `symlink_target`, so that it adds information without consuming a column.

#### Scenario: Una fila muestra severidad, y dos severidades distintas se distinguen
- **WHEN** a list containing a `critical` event and a `low` event is rendered
- **THEN** each row shows its severity as text
- **AND** the two rows do not carry the same leading-edge treatment

#### Scenario: Una fila muestra el proceso causante
- **WHEN** an event carrying `process_exe`, `process_pid` and `process_uid` is rendered
- **THEN** the row shows the executable together with its pid and uid

#### Scenario: Un evento sin contexto de proceso no rompe la fila
- **WHEN** an event whose `process_exe`, `process_pid` and `process_uid` are null is rendered
- **THEN** the row renders without an empty or placeholder-looking process line, and nothing shows as `null`

#### Scenario: Seleccionar una fila la agrega a la selección
- **WHEN** the admin ticks a row checkbox
- **THEN** that `event_id` joins the selection and the BulkActionBar becomes visible

#### Scenario: Seleccionar todos en la página
- **WHEN** the admin ticks the header "select all on this page" checkbox
- **THEN** every visible event on the current page is selected

#### Scenario: La selección se limpia al cambiar de página o filtro
- **WHEN** the admin changes page or modifies a filter with rows selected
- **THEN** the selection is emptied

#### Scenario: Abrir el detalle de un evento desde una fila
- **WHEN** the admin clicks a row outside the checkbox
- **THEN** the app navigates to `/events/:id`

---

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

The frontend SHALL provide `frontend/src/components/ui/BulkActionBar.tsx`, which appears when at least one event is selected and allows approving or rejecting the selection behind a confirmation modal (RN-99, W15). Bulk approve SHALL show the count and first 10 paths and issue `POST /actions/bulk-approve` with the single canonical body `{event_ids:[...]}`. Bulk reject SHALL ask for one shared action (`restore` | `quarantine`) and issue `POST /actions/bulk-reject` with `{event_ids:[...], action}`.

This requirement supersedes the earlier `items[]` formulations in this change. The migration is intentionally breaking: neither endpoint accepts `items`, client-supplied `version`, `confirm_absent`, per-item actions or `baseline_absent`; there is no compatibility alias, and a legacy `items` body SHALL receive 422. The server loads each event and owns current-version capture. The response remains `{succeeded[], failed[]}`; the frontend SHALL present its counts in a toast and invalidate the list query. A 422 SHALL be surfaced as a contract violation, distinctly from an operational failure.

#### Scenario: BulkActionBar aparece con selección
- **WHEN** at least one event is selected
- **THEN** the BulkActionBar shows the approve/reject actions and selected count

#### Scenario: Bulk approve usa event_ids
- **WHEN** the admin confirms bulk approval over three selected events
- **THEN** `POST /actions/bulk-approve` is issued as `{event_ids:[id1,id2,id3]}`
- **AND** the body contains no `items`, versions, confirmation or baseline fields

#### Scenario: Bulk reject usa una acción común
- **WHEN** the admin chooses `quarantine` and confirms over three selected events
- **THEN** `POST /actions/bulk-reject` is issued as `{event_ids:[id1,id2,id3], action:"quarantine"}`
- **AND** the body contains no per-item action

#### Scenario: El wire legacy es rechazado
- **WHEN** a body containing `items` is submitted to either bulk endpoint
- **THEN** the backend responds 422 because no legacy alias exists

#### Scenario: Resultado parcial se refleja en un toast con conteos
- **WHEN** a bulk action returns `{succeeded:[...], failed:[...]}` with failures
- **THEN** a toast reports how many succeeded and how many failed
- **AND** the list query is invalidated

#### Scenario: Un 422 se distingue de una falla operativa
- **WHEN** a bulk action returns 422
- **THEN** the message identifies it as a rejected request rather than a generic failure

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

### Requirement: Events UI distinguishes a failed remediation from an ordinary pending

The events table and the event detail view SHALL visually distinguish an event whose `action_failed` is true from one whose `action_failed` is false, using a badge/indicator rendered adjacent to the status badge because the flag qualifies the status. A `pending` with `action_failed = true` means the file is still tampered AND automatic remediation already failed; it carries operational priority over an ordinary `pending`, and the indicator MUST communicate that rather than merely echoing the raw field value. The badge SHALL render whenever `action_failed` is true, without being coupled to `status === 'pending'`, so that no future combination becomes invisible. Events with `action_failed` false MUST render exactly as before. The event type in `frontend/src/api/events.ts` SHALL gain the `action_failed: boolean` field consumed from `EventOut`. (D35 / RN-129)

#### Scenario: Pending event with a failed remediation is visually distinct in the table
- **WHEN** the events table renders a row with `status = "pending"` and `action_failed = true`
- **THEN** the row shows a remediation-failure indicator next to the status badge, distinguishing it from an ordinary pending row

#### Scenario: Ordinary pending event renders unchanged
- **WHEN** the events table renders a row with `status = "pending"` and `action_failed = false`
- **THEN** no remediation-failure indicator is shown and the existing rendering is unchanged

#### Scenario: Event detail surfaces the failed remediation
- **WHEN** the event detail view opens for an event with `action_failed = true`
- **THEN** the header badge row displays the remediation-failure indicator alongside the status badge

#### Scenario: The indicator carries an explicit label, not the raw field name
- **WHEN** the remediation-failure indicator renders
- **THEN** its label is explicit prose conveying that automatic remediation failed, so an operator does not read the row as an ordinary pending

#### Scenario: The indicator is not confusable with the rejected status or the ack failure badge
- **WHEN** the indicator renders in a view that also shows a `rejected` status badge or a failed execution (ack) badge
- **THEN** it remains visually distinguishable from both

### Requirement: Remediation-failure presentation is a pure mapper with its own test

The mapping from `action_failed` to its label and CSS classes SHALL live in a single pure module under `frontend/src/utils/`, exposing a function that returns the presentation metadata or `null` when the flag is false, mirroring the contract of `getAckStatusMeta` (`frontend/src/utils/ackStatus.ts`). This avoids adding a fourth duplicated class map to the frontend, which already carries three copies of the status class map. The module SHALL have a unit test asserting the null case and the populated case, following `frontend/src/utils/ackStatus.test.ts` — the house pattern of testing the pure mapper rather than the render. (D35 / RN-129)

#### Scenario: The mapper returns null when no remediation failed
- **WHEN** the mapper is called with `action_failed = false`
- **THEN** it returns `null` and the calling component renders no indicator

#### Scenario: The mapper returns label and classes when remediation failed
- **WHEN** the mapper is called with `action_failed = true`
- **THEN** it returns presentation metadata containing a label and a className used by both the table and the detail view

#### Scenario: Both render sites consume the same mapper
- **WHEN** the table and the detail view render the remediation-failure indicator
- **THEN** both obtain their label and classes from the shared mapper rather than from a locally duplicated map

### Requirement: The event list keeps the server's ordering and never reorders a page client-side

The list SHALL be displayed in the order the backend returns it — `created_at` descending (`backend/app/modules/events/router.py:105`) — and the frontend SHALL NOT sort, group or otherwise reorder the rows it received.

Sorting by severity is the obvious impulse and it is wrong twice over. It contradicts a documented criterion: US-06 (`docs/historias_de_usuario.md:152`) fixes descending creation order as the default, and `test_list_events_orders_by_created_at_desc` asserts it. And it would not work: the backend paginates in SQL and exposes no ordering parameter, so a client-side sort reorders the 50 rows already fetched, not the 142 that exist. A `critical` on page 3 would remain on page 3 — now wearing the reassuring appearance of a sorted list. **Reordering a server-paginated window is not sorting; it is rearranging a window**, and it is strictly worse than not sorting, because it delivers the visual guarantee of order without the property.

The instrument that actually reduces 142 rows to 2 is the severity filter, reachable in one click from the dashboard. Server-side ordering by severity is a legitimate follow-up; it needs an ordering parameter, an index, and its own decision about whether the US-06 default changes.

#### Scenario: The rendered order matches the response order
- **WHEN** the API returns a page of events in a given order
- **THEN** the rows are rendered in exactly that order, regardless of their severities

#### Scenario: A high-severity event on a later page is not pulled forward
- **WHEN** the current page contains no `critical` event but a later page does
- **THEN** the current page does not display it, and no control suggests the list is ordered by severity

### Requirement: The event detail explains why an automatic remediation failed

The event detail view SHALL show the cause of a failed automatic action in prose, qualifying the remediation-failure indicator introduced by D35 / RN-129. The purpose is the one D36 states directly: an operator MUST be able to tell a deployment problem — the path was not writable — from a data problem — the baseline was missing or unusable — without leaving the interface.

The mapping SHALL be a pure function returning a label and a style, or nothing when there is no cause, following the isolated-and-tested mapper pattern already established in the frontend. Known values SHALL map to prose. An unknown value SHALL fall back to rendering the raw literal rather than being hidden, so an agent newer than the frontend degrades to "less readable" instead of "silently missing".

The events **table** SHALL NOT change. The remediation-failure indicator there already communicates the fact; the cause is second-level information that does not justify another column in an already dense table. (D36 / RN-130, D35 / RN-129, RN-71)

#### Scenario: A deployment cause reads as a deployment problem

- **WHEN** an event detail is opened for a failed remediation whose cause is a read-only mount
- **THEN** the view shows prose identifying it as a write-access problem on the host, distinct from a baseline problem

#### Scenario: A data cause reads as a data problem

- **WHEN** the cause is a missing baseline
- **THEN** the view shows prose identifying it as a baseline problem

#### Scenario: An unknown cause falls back to the raw value

- **WHEN** the cause is a literal the frontend does not recognize
- **THEN** the raw literal is displayed rather than nothing

#### Scenario: An event with no cause shows no extra element

- **WHEN** an event has no failure cause
- **THEN** no cause element is rendered and the existing badges are unaffected

#### Scenario: The events table is unchanged

- **WHEN** the events table is rendered after this change
- **THEN** it carries the same columns as before, with the remediation-failure indicator unchanged

### Requirement: El selector de estado enumera los siete estados y es coherente con include_superseded

El panel de filtros de `frontend/src/pages/Events.tsx` SHALL ofrecer un selector de estado con los siete
estados canónicos, siempre visibles y en este orden: `pending`, `approved`, `rejected`, `auto_restored`,
`quarantined`, `alert_only`, `superseded` (US-07, RN-71). La visibilidad de la opción `superseded` SHALL
NOT depender del toggle "Mostrar superseded".

Por defecto, sin parámetros de URL, ningún estado SHALL estar marcado, `superseded` SHALL quedar
desmarcado y el listado SHALL excluir los eventos `superseded` (W1, RN-22, RN-98).

La selección SHALL mantener la coherencia con `include_superseded`, porque el backend excluye
`superseded` antes de aplicar el filtro de estado y un filtro `status=superseded` sin
`include_superseded=true` devolvería siempre una lista vacía:

- Marcar `superseded` en el selector SHALL activar también `include_superseded=true`.
- Desmarcar `superseded` en el selector SHALL quitarlo del filtro de estado y SHALL dejar el toggle como
  estaba.
- Apagar el toggle "Mostrar superseded" SHALL quitar también `superseded` del filtro de estado.
- Encender el toggle SHALL reincorporar los `superseded` al listado sin marcar `superseded` en el selector.
- Una URL con `status=superseded` y sin `include_superseded=true` SHALL normalizarse al parsearla, tratando
  `include_superseded` como activo.

Los eventos `superseded` reincorporados SHALL conservar el ícono visual distintivo de US-31.

#### Scenario: El selector muestra los siete estados sin activar el toggle

- **WHEN** el admin navega a `/events` sin parámetros
- **THEN** el selector de estado muestra siete opciones, incluida `superseded`, todas desmarcadas
- **AND** la petición a `GET /events` no lleva `include_superseded` ni `status`

#### Scenario: Selección múltiple incluyendo superseded

- **WHEN** el admin marca `pending` y `superseded`
- **THEN** la URL contiene `status=pending&status=superseded&include_superseded=true`
- **AND** la petición a `GET /events` lleva los dos estados y `include_superseded=true`

#### Scenario: Apagar el toggle quita superseded del filtro

- **WHEN** `superseded` está marcado en el selector y el admin apaga "Mostrar superseded"
- **THEN** `superseded` queda desmarcado, la URL no lleva `include_superseded` y la petición excluye los superseded

#### Scenario: Desmarcar superseded no apaga el toggle

- **WHEN** `superseded` y el toggle están activos y el admin desmarca `superseded`
- **THEN** la URL conserva `include_superseded=true` y ya no lleva `status=superseded`

#### Scenario: Un deep-link con superseded sin toggle se normaliza

- **WHEN** se carga `/events?status=superseded` directamente
- **THEN** la opción `superseded` aparece marcada, el toggle aparece activo y la petición lleva `include_superseded=true`

#### Scenario: Quitar un filtro actualiza el listado

- **WHEN** el admin desmarca el último estado seleccionado
- **THEN** la URL deja de llevar `status` y se emite una nueva petición a `GET /events` sin ese parámetro

