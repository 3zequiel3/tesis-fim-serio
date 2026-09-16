## ADDED Requirements

### Requirement: Event model persists symlink metadata columns

The `Event` model (`backend/app/modules/events/models.py`) SHALL gain two columns: `is_symlink: bool = False` and `symlink_target: str | None = None`. Both MUST be nullable/defaulted so that existing rows and events lacking the metadata remain valid. The columns SHALL be added via an idempotent SQL migration in `backend/db/migrations/` following the D3 convention (raw SQL, no Alembic), using the next sequence number after `004_add_command_ack_tracking.sql`, and MUST use `ADD COLUMN IF NOT EXISTS` so re-running the migration is safe. (D33 / RN-127)

#### Scenario: Migration adds the columns idempotently
- **WHEN** the symlink-metadata migration runs against a database that already has the columns
- **THEN** it completes without error because it uses `ADD COLUMN IF NOT EXISTS`

#### Scenario: Existing events without symlink metadata remain valid
- **WHEN** an event row created before this change is read
- **THEN** `is_symlink` defaults to `false` and `symlink_target` is `null`, and the row loads without error

### Requirement: EventOut exposes symlink metadata

The event output schema `EventOut` SHALL expose `is_symlink` and `symlink_target` alongside the other event fields, following the same pattern used to expose `ack_status` (D30/C36). Both `GET /events` and `GET /events/{id}` responses SHALL include these fields for every event. (D33 / RN-127)

#### Scenario: Symlink event is serialized with its metadata
- **WHEN** a client fetches an event that represents a symlink
- **THEN** the response includes `is_symlink: true` and `symlink_target` set to the reported target string

#### Scenario: Regular-file event serializes symlink metadata as defaults
- **WHEN** a client fetches an event that represents a regular file
- **THEN** the response includes `is_symlink: false` and `symlink_target: null`
