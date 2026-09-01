## MODIFIED Requirements

### Requirement: Tabla de eventos con selección múltiple

El frontend SHALL proveer `frontend/src/components/ui/EventsTable.tsx` que renderiza las filas de
eventos con un checkbox por fila y un checkbox "seleccionar todos en la página". La selección SHALL
mantenerse en estado local efímero (no en la URL) como un conjunto de `event_id`. Cada fila SHALL
mostrar al menos `path`, `status`, `detected_at` y permitir abrir el detalle del evento. Las filas de
eventos `superseded` SHALL mostrar un indicador visual de cadena rota.

El tipo `EventListItem` (`frontend/src/api/events.ts`) SHALL declarar `event_type: string` y SHALL
relajar `path` a `string | null` (D51/RN-145). Cuando `path` es nulo, la celda de ruta SHALL
renderizar una etiqueta legible derivada del **`event_type`** —no del nulo del path—, porque
`event_type` es el discriminador que la decisión introduce para eso y produce una etiqueta con
significado en vez de un hueco. La fila SHALL seguir siendo navegable al detalle del evento. La
celda MUST NOT renderizar un guion, una cadena vacía ni un `path ?? '—'`.

El contexto de proceso SHALL seguir omitiéndose por completo cuando `process_pid`, `process_uid` y
`process_exe` son los tres nulos, sin renderizar guiones ni vacíos (D49/RN-143): un nulo significa
atribución no resuelta y no debe presentarse como si fuera un dato.

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

#### Scenario: Una fila sin ruta muestra el tipo de evento en lugar de la ruta
- **WHEN** la tabla renderiza un evento con `path: null` y `event_type: "detection_gap"`
- **THEN** la celda de ruta muestra una etiqueta legible para la brecha de detección
- **AND** no muestra un guion, una cadena vacía ni el literal `null`
- **AND** la fila sigue enlazando a `/events/:id`

#### Scenario: Una fila con ruta no cambia su render
- **WHEN** la tabla renderiza un evento con `path: "/etc/hosts"`
- **THEN** la celda de ruta muestra `/etc/hosts` como enlace al detalle, igual que antes

### Requirement: Detalle de evento con timestamps dobles, contexto de proceso y diff seguro

El frontend SHALL proveer una vista de detalle de evento (`frontend/src/pages/EventDetail.tsx` o
drawer) que consume `GET /events/{id}` y muestra: `event_type`, `path`, `hash_detected`, los
timestamps dobles `detected_at` y `received_at` (RN-90), el contexto de proceso `process_pid`,
`process_uid`, `process_exe` (RN-03), el `status`, el `resolved_at`/`resolved_by` cuando existan, y
la cadena de eventos vía `parent_event_id`. El detalle SHALL incluir un `DiffViewer` seguro y un
`EventTimeline`.

Cuando `path` es nulo, el detalle SHALL sustituir la fila de ruta por la del tipo de evento y su
causa, sin guiones ni celdas vacías (D51/RN-145). Cuando los tres campos de contexto de proceso son
nulos, el detalle SHALL omitir el bloque completo en vez de renderizar valores vacíos: un nulo
significa atribución no resuelta y no es un dato que mostrar (D49/RN-143).

#### Scenario: Detalle muestra timestamps dobles y contexto de proceso
- **WHEN** el admin abre el detalle de un evento existente
- **THEN** se hace `GET /events/{id}`
- **AND** se muestran `detected_at` y `received_at` como timestamps separados
- **AND** se muestran `process_pid`, `process_uid` y `process_exe`

#### Scenario: Evento inexistente muestra estado de no encontrado
- **WHEN** se abre el detalle de un `id` que retorna `404`
- **THEN** la vista muestra un mensaje de "evento no encontrado" sin romper la app

#### Scenario: Detalle de un evento sin ruta muestra el tipo y la causa
- **WHEN** el admin abre el detalle de un evento con `path: null` y `event_type: "detection_gap"`
- **THEN** la vista muestra el tipo de evento y su causa en lugar de la fila de ruta
- **AND** la vista no renderiza guiones ni celdas vacías donde iría la ruta
- **AND** la vista no lanza error al renderizar

#### Scenario: Detalle omite el contexto de proceso cuando no se resolvió
- **WHEN** el admin abre el detalle de un evento con `process_pid`, `process_uid` y `process_exe` nulos
- **THEN** el bloque de contexto de proceso no se renderiza
- **AND** no se muestra `uid 0` ni ningún valor de relleno
