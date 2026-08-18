## ADDED Requirements

### Requirement: Ingestion persists the action failure cause with forward tolerance

`ingest_event` SHALL read the action failure cause from the event payload and persist it on the event row, truncating it to the column's length. The cause composes with the existing `action_failed` flag introduced by D35 / RN-129 and does not alter the status derivation in any way: an event whose action failed is still ingested as `pending`, and the cause only explains why.

The value SHALL NOT be validated against an enumeration, neither in the database nor at ingestion. The vocabulary evolves on the agent side, and a database-level constraint would turn an agent newer than the backend into lost integrity events — the very asset the system exists not to lose. An unrecognized value SHALL be stored as received; an absent value SHALL be stored as null. This is the same forward-tolerance criterion already applied to an unknown `action` and to the symlink metadata.

The cause SHALL NOT be derivable into any event status and SHALL NOT influence supersession. (D36 / RN-130, D35 / RN-129, RN-71)

#### Scenario: A known cause is persisted alongside the failure flag

- **WHEN** an event payload carries `action_failed` true and a cause of `read_only_mount`
- **THEN** the persisted row has status `pending`, the failure flag set, and the cause `read_only_mount`

#### Scenario: An unknown cause is stored rather than rejected

- **WHEN** an event payload carries a cause literal the backend does not recognize
- **THEN** the event is ingested normally and the cause is stored as received

#### Scenario: An absent cause is null

- **WHEN** an event payload from an older agent carries no cause key
- **THEN** the persisted cause is null and the rest of the ingestion is unchanged

#### Scenario: A successful action stores no cause

- **WHEN** an event payload reports a successful automatic action
- **THEN** the persisted cause is null and the derived status is the terminal one

#### Scenario: The cause does not affect status derivation or supersession

- **WHEN** two events for the same path arrive, the second carrying a failure cause
- **THEN** the derived statuses and the supersession of the active pending event are exactly what they would be without the cause
