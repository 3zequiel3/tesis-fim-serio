## MODIFIED Requirements

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

This replaces a floor of "at least `path`, `status`, `detected_at`". That floor is what the implementation faithfully built, and it is narrower than what US-06 (`docs/historias_de_usuario.md:151`) requires: *"Cada fila muestra: path del archivo, estado, tipo de acción, severidad, fecha de creación y proceso causante (PID, UID, `exe`…)"*. The gap was recorded in `docs/trazabilidad_us_tests.md:298` as a criterion with neither test nor implementation. Because that document's own rule (`:49-53`) states that a test of a narrower implementation does not close a wider criterion, the missing fields close together or not at all.

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

### Requirement: Bulk approve y bulk reject con modal de confirmación y resultado parcial

The frontend SHALL provide `frontend/src/components/ui/BulkActionBar.tsx`, which appears when at least one event is selected and allows approving or rejecting the selection, always behind a confirmation modal (RN-99, W15). Bulk approve SHALL show the count and the first 10 paths and call `POST /actions/bulk-approve` with `{items:[{event_id, version, confirm_absent:false}]}`.

**Bulk reject SHALL additionally ask for the action (`restore` | `quarantine`) applied to the whole selection, and SHALL call `POST /actions/bulk-reject` with `{items:[{event_id, version, action}]}` — the action inside each item.**

This corrects the requirement, not only the code. The previous text prescribed `{items:[{event_id, version}], action}`, with the action at the top level, and the implementation complied with it. That body is rejected by the backend with 422 on every call: `BulkRejectItem` (`backend/app/modules/actions/schemas.py:57-61`) declares `action: RejectAction` as required, with no default, inside each element of `items`, and Pydantic ignores the surplus top-level key while failing on the missing per-item one. Verified live: the top-level form returns `422 {"loc":["body","items",0,"action"],"type":"missing"}` and the per-item form returns 200. Fixing the client without fixing this text would leave the defect alive in the artifact that governs the client.

The single choice made in the modal is the UX that US-25 describes; mapping it onto every item is what the wire requires. Both hold at once. The frontend's `BulkRejectItem` type SHALL declare `action`, mirroring the backend schema, so that omitting it stops compiling.

The `{succeeded[], failed[]}` response SHALL become a toast with the counts and SHALL invalidate the list query. A **422 on a bulk action SHALL be surfaced as a contract violation**, distinctly from an operational failure. Presenting a rejected body with the same generic text as a timeout is how this defect stayed invisible for the entire life of the project.

#### Scenario: BulkActionBar aparece con selección
- **WHEN** at least one event is selected
- **THEN** the BulkActionBar shows the approve/reject actions and the selected count

#### Scenario: Bulk approve confirma antes de ejecutar
- **WHEN** the admin presses "aprobar selección"
- **THEN** a modal opens showing the count and the first 10 paths
- **AND** confirming issues `POST /actions/bulk-approve` with the selected `items`

#### Scenario: Bulk reject pide la acción y la aplica a cada ítem
- **WHEN** the admin presses "rechazar selección", chooses `quarantine` and confirms over three selected events
- **THEN** `POST /actions/bulk-reject` is issued with three items, each carrying `event_id`, `version` and `action: "quarantine"`
- **AND** no `action` key is present at the top level of the body

#### Scenario: Un rechazo en lote válido no es rechazado por el backend
- **WHEN** the body the client emits for a bulk reject is validated against the backend contract
- **THEN** it is accepted, and specifically does not fail with a missing per-item `action`

#### Scenario: Resultado parcial se refleja en un toast con conteos
- **WHEN** a bulk action returns `{succeeded:[...], failed:[...]}` with failures
- **THEN** a toast reports how many succeeded and how many failed
- **AND** the list query is invalidated

#### Scenario: Un 422 se distingue de una falla operativa
- **WHEN** a bulk action returns 422
- **THEN** the message identifies it as a rejected request rather than a generic failure

## ADDED Requirements

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
