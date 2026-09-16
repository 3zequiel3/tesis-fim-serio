## ADDED Requirements

### Requirement: Event model persists the action_failed column

The `Event` model (`backend/app/modules/events/models.py`) SHALL gain a column `action_failed: bool = False`. It MUST be non-nullable with a `false` default so that existing rows and payloads lacking the key remain valid. The column SHALL be added via an idempotent SQL migration in `backend/db/migrations/` following the D3 convention (raw SQL, no Alembic), using the next sequence number after `006_add_event_severity.sql`, and MUST use `ADD COLUMN IF NOT EXISTS` so that re-running the migration is safe. Pre-existing rows SHALL be backfilled to `false` by the column's `NOT NULL DEFAULT FALSE` clause, with no separate `UPDATE` statement — no pre-existing row can have been produced by a failed action, because the backend never read `action_failed` before this change. No index SHALL be created on the column: no endpoint or filter in this change queries by it. (D35 / RN-129)

#### Scenario: Migration adds the column idempotently
- **WHEN** the `action_failed` migration runs against a database that already has the column
- **THEN** it completes without error because it uses `ADD COLUMN IF NOT EXISTS`

#### Scenario: Existing events are backfilled to false
- **WHEN** an event row created before this change is read after the migration runs
- **THEN** `action_failed` is `false` and the row loads without error

#### Scenario: Migration header documents manual application
- **WHEN** an operator opens the migration file
- **THEN** its header names the decision (D35/RN-129) and the change, states that it is idempotent, and gives the exact `psql $DATABASE_URL -f` invocation, matching the convention of migrations 005 and 006

### Requirement: EventOut exposes action_failed

The event output schema `EventOut` (`backend/app/modules/events/router.py`) SHALL expose `action_failed: bool = False` alongside the other event fields, following the same additive pattern used to expose `ack_status` (D30/C36) and `is_symlink` (D33/C39). Both `GET /events` and `GET /events/{id}` responses SHALL include the field for every event. The addition is purely additive and MUST NOT break existing clients. (D35 / RN-129)

#### Scenario: Event whose remediation failed is serialized with the flag set
- **WHEN** a client fetches an event that was ingested with `action_failed = true`
- **THEN** the response includes `action_failed: true` alongside `status: "pending"`

#### Scenario: Ordinary event serializes the flag as false
- **WHEN** a client fetches an event whose action succeeded or that had no automatic action
- **THEN** the response includes `action_failed: false`

#### Scenario: Terminal agent-originated event exposes its automatic resolution
- **WHEN** a client fetches an event with `status` `auto_restored`, `quarantined` or `alert_only`
- **THEN** the response carries `resolved_at` set to the event's `received_at` and `resolved_by: null`, identifying an automatic resolution with no human operator
