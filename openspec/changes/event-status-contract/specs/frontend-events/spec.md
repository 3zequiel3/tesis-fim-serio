## ADDED Requirements

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
