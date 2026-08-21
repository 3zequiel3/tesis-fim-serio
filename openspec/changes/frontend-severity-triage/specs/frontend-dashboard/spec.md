## MODIFIED Requirements

### Requirement: Dashboard shows event counters by status (RN-101)

The system SHALL display aggregate counts of events grouped by status (`pending`, `approved`, `rejected`, `superseded`, `auto_restored`, `quarantined`, `alert_only`), refreshed automatically every 30 seconds.

**Each counter SHALL be a link to the event list filtered by that status**, and SHALL be labelled with the canonical value itself.

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

---

### Requirement: Dashboard highlights critical and high pending events (RN-101, RN-102)

The system SHALL display the count of pending events with severity `critical` or `high` prominently, distinct from the total pending count, **and SHALL link it to the event list pre-filtered to exactly that set**.

Without the link the dashboard is a strictly incomplete instrument: it computes how many needles there are and then sends the operator to look for them by hand. The live numbers make the size of that gap concrete — 142 pending events, of which 140 are `low`, 1 is `critical` and 1 is `high`. The card says "2". The list it sends the operator to has 142 rows across three pages, ordered by date, visually identical. The link is what turns a number into an action.

The destination SHALL carry the severities as repeatable parameters — `/events?status=pending&severity=critical&severity=high` — matching the request the KPI itself already issues (`frontend/src/api/dashboard.ts:52-59`). A destination carrying only one of the two severities is the plausible mistake here and MUST NOT pass.

The count shown on the card and the `total` reported by the list it navigates to SHALL be the same number, because both derive from the same filter. A discrepancy means the link and the KPI are asking different questions.

#### Scenario: Critical/high pending shown prominently
- **WHEN** there are pending events with severity `critical` or `high`
- **THEN** the system displays their count with visual emphasis, separate from the total pending count

#### Scenario: The KPI navigates to exactly the set it counts
- **WHEN** the admin activates the critical/high pending card
- **THEN** the app navigates to the event list filtered by `status=pending` and by both `critical` and `high`
- **AND** both severities are present in the destination, not just one

#### Scenario: The KPI and its destination agree
- **WHEN** the card reports N and the operator follows the link
- **THEN** the list reports the same N as its total

#### Scenario: The emphasis is conditional, not permanent
- **WHEN** there are no pending critical or high events
- **THEN** the card is rendered without the emphasis treatment
