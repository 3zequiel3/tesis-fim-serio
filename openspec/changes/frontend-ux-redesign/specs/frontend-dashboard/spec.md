## MODIFIED Requirements

### Requirement: Dashboard shows event counters by status (RN-101)

The system SHALL display aggregate counts of events grouped by status (`pending`, `approved`, `rejected`, `superseded`, `auto_restored`, `quarantined`, `alert_only`), refreshed automatically every 30 seconds. The `superseded` count MUST be requested with `include_superseded=true`, because the backend excludes superseded events by default and would otherwise always report `0` (D93/RN-187).

**Each counter SHALL be a link to the event list filtered by that status**, and SHALL be labelled with the canonical value itself. The link for `superseded` MUST also carry `include_superseded=true`.

Both additions come from the same place. Today the counters are inert text: the dashboard knows the answer and makes the operator rebuild the query by hand. And today `Dashboard.tsx:8-16` labels them `Pending`, `Auto-restored`, `Alert only` while the event table renders `pending`, `auto_restored`, `alert_only` — the same state named two different ways on adjacent screens. C1/RN-71 (`docs/flujo_de_usuario.md:1074`) is explicit that event statuses are shown in lowercase snake_case **throughout the UI**, with a single exception for action buttons (`APPROVE`, `REJECT`) used as emphasis; a counter label is not an action button.

The link makes the divergence functional rather than cosmetic: the operator would click `Auto-restored` to land on a URL reading `auto_restored` over rows reading `auto_restored`. The name has to be the same in all three places, and only one of the three is wrong.

#### Scenario: Event counters load
- **WHEN** the admin navigates to `/dashboard`
- **THEN** the system displays event counts per status, refreshed every 30 seconds

#### Scenario: A counter navigates to its filtered list
- **WHEN** the admin activates the `pending` counter
- **THEN** the app navigates to the event list filtered by `status=pending`

#### Scenario: Counter labels use the canonical lexicon
- **WHEN** the counters are rendered
- **THEN** each label is the canonical status value in lowercase snake_case, identical to the value the event table renders for the same state

#### Scenario: Superseded count is real
- **WHEN** the backend holds 4 superseded events
- **THEN** the dashboard requests `GET /events?status=superseded&include_superseded=true&page_size=1` and shows `4`
- **AND** the `superseded` counter links to the list with `status=superseded&include_superseded=true`
