## ADDED Requirements

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
