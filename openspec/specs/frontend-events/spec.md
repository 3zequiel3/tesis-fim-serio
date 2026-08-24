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

El frontend SHALL permitir aprobar (`POST /actions/approve` con `{event_id, version, confirm_absent?}`) y rechazar (`POST /actions/reject` con `{event_id, version, action}`) un evento individual desde el detalle o la tabla, enviando siempre el `version` del último dato fetcheado (optimistic locking). Ante respuesta `409` el frontend SHALL mostrar un toast indicando que el evento ya fue resuelto por otro admin e invalidar las queries del evento y de la lista (RN-74). Ante `422` con `{code:"absent_confirmation_required"}` en approve, el frontend SHALL solicitar confirmación de archivo ausente y reintentar con `confirm_absent:true`.

#### Scenario: Approve exitoso refresca el estado
- **WHEN** el admin aprueba un evento `pending` con `version` correcto
- **THEN** se hace `POST /actions/approve` con `{event_id, version}`
- **AND** ante `200` se muestra un toast de éxito y se invalidan las queries del evento y la lista

#### Scenario: 409 muestra toast y refresca
- **WHEN** una acción approve/reject retorna `409`
- **THEN** se muestra un toast "Este evento ya fue resuelto por otro admin"
- **AND** se invalidan las queries del evento afectado y de la lista para reflejar el estado real

#### Scenario: Approve de evento ausente pide confirmación
- **WHEN** approve retorna `422` con `{code:"absent_confirmation_required"}`
- **THEN** el frontend solicita confirmación de archivo ausente
- **AND** al confirmar reintenta `POST /actions/approve` con `confirm_absent:true`

### Requirement: RejectModal con branch baseline_absent

El frontend SHALL proveer `frontend/src/components/ui/RejectModal.tsx` que, para un reject normal, ofrece elegir la acción `restore` o `quarantine` y llama `POST /actions/reject` con `{event_id, version, action}`. Cuando el evento tiene `hash_detected === null` (o el backend indica baseline ausente), el modal SHALL ocultar el selector restore/quarantine, mostrar el mensaje "El archivo no existe en el baseline — no hay nada que restaurar ni poner en cuarentena", y al confirmar SHALL llamar `POST /actions/reject` con `action:"restore"` (el backend hace no-op del comando y retorna `200`), transicionando el evento a `rejected` (RN-77, C10).

#### Scenario: Reject normal permite elegir acción
- **WHEN** el admin abre el RejectModal sobre un evento con `hash_detected` no nulo
- **THEN** el modal muestra el selector `restore`/`quarantine`
- **AND** al confirmar se hace `POST /actions/reject` con la acción elegida

#### Scenario: Branch baseline_absent oculta el selector
- **WHEN** el admin abre el RejectModal sobre un evento con `hash_detected === null`
- **THEN** el modal oculta el selector restore/quarantine
- **AND** muestra el mensaje de archivo ausente
- **AND** al confirmar se hace `POST /actions/reject` con `action:"restore"` y el evento transiciona a `rejected`

### Requirement: Bulk approve y bulk reject con modal de confirmación y resultado parcial

El frontend SHALL proveer `frontend/src/components/ui/BulkActionBar.tsx` que aparece cuando hay ≥1 evento seleccionado y permite aprobar o rechazar la selección, siempre con un modal de confirmación (RN-99, W15). El bulk approve SHALL mostrar el conteo y las primeras 10 paths y llamar `POST /actions/bulk-approve` con `{items:[{event_id, version, confirm_absent:false}]}`. El bulk reject SHALL pedir adicionalmente la acción (`restore`|`quarantine`) y llamar `POST /actions/bulk-reject` con `{items:[{event_id, version}], action}`. La respuesta `{succeeded[], failed[]}` SHALL traducirse en un toast con los conteos y SHALL invalidar la query de la lista.

#### Scenario: BulkActionBar aparece con selección
- **WHEN** hay al menos un evento seleccionado
- **THEN** la BulkActionBar se muestra con acciones aprobar/rechazar y el conteo de seleccionados

#### Scenario: Bulk approve confirma antes de ejecutar
- **WHEN** el admin pulsa "aprobar selección"
- **THEN** se abre un modal mostrando el conteo y las primeras 10 paths
- **AND** al confirmar se hace `POST /actions/bulk-approve` con los `items` seleccionados

#### Scenario: Bulk reject pide acción restore/quarantine
- **WHEN** el admin pulsa "rechazar selección"
- **THEN** el modal pide elegir `restore` o `quarantine`
- **AND** al confirmar se hace `POST /actions/bulk-reject` con `{items, action}`

#### Scenario: Resultado parcial se refleja en un toast con conteos
- **WHEN** una acción masiva retorna `{succeeded:[...], failed:[...]}` con fallos
- **THEN** se muestra un toast indicando cuántos tuvieron éxito y cuántos fallaron
- **AND** se invalida la query de la lista para reflejar los cambios

### Requirement: Feed de alertas en tiempo real vía SSE

El frontend SHALL proveer `frontend/src/hooks/useAlertsSSE.ts` que abre una conexión `EventSource` a `GET /alerts/stream?token=<accessToken>` (el access token va en query param porque `EventSource` no admite headers). Cada alerta nueva recibida SHALL disparar un toast de notificación. La conexión SHALL aprovechar la reconexión automática nativa de `EventSource` (con `Last-Event-ID` para no perder alertas, soportado por el backend en C16). El hook SHALL cerrar la conexión al desmontar.

#### Scenario: Alerta nueva dispara un toast
- **WHEN** el backend emite un evento SSE de alerta y el hook está conectado
- **THEN** el frontend muestra un toast con la información de la alerta

#### Scenario: La conexión se cierra al desmontar
- **WHEN** el componente que usa `useAlertsSSE` se desmonta
- **THEN** la conexión `EventSource` se cierra

#### Scenario: Reconexión automática tras corte
- **WHEN** la conexión SSE se interrumpe
- **THEN** `EventSource` reintenta conectar automáticamente
- **AND** al reconectar el browser envía `Last-Event-ID` para recuperar alertas perdidas
