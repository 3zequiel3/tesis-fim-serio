## ADDED Requirements

### Requirement: Every persisted instant is stored in a column that declares its time zone

Every column that holds a point in time SHALL be `timestamp with time zone` (`timestamptz`). The instant a row records MUST be determined by the stored value and its type alone, and MUST NOT depend on the `TimeZone` setting of the session that reads or writes it.

This covers exactly the 19 columns that exist today, across 11 tables:

| Table | Columns |
|---|---|
| `agents` | `last_heartbeat` |
| `alerts` | `created_at`, `delivered_at`, `failed_at` |
| `audit_log` | `created_at` |
| `baseline_entries` | `last_updated` |
| `events` | `created_at`, `detected_at`, `received_at`, `resolved_at` |
| `published_commands` | `acked_at`, `published_at` |
| `rejected_events_audit` | `detected_at`, `received_at` |
| `revoked_certificates` | `revoked_at` |
| `rules` | `created_at`, `updated_at` |
| `ruleset_versions` | `updated_at` |
| `users` | `created_at` |

The requirement is stated as a property of **every** instant-valued column, not as a list. A column added later that holds a point in time MUST satisfy it too; the table above is the inventory at the time of writing, not the definition.

The migration MUST preserve every stored instant unchanged. The values already hold UTC by convention, so the conversion changes the declared type and not the instant.

#### Scenario: The 19 columns report as time-zone aware
- **WHEN** `information_schema.columns` is queried for the schema the backend uses
- **THEN** each of the 19 columns above reports `data_type` of `timestamp with time zone`

#### Scenario: No instant-valued column is left without a zone
- **WHEN** `information_schema.columns` is queried for every column whose `data_type` starts with `timestamp`
- **THEN** the result contains no column of type `timestamp without time zone`

#### Scenario: The stored instant survives the migration
- **WHEN** a row written before the migration is read after it
- **THEN** the value denotes the same instant it denoted before, now carrying a `+00` offset

#### Scenario: The migration is idempotent
- **WHEN** the migration script is applied a second time against an already-migrated database
- **THEN** it completes without error and changes nothing

#### Scenario: The migration refuses to run under a non-UTC session
- **WHEN** the migration script is applied by a session whose effective time zone is not UTC
- **THEN** it aborts with an explicit error before altering any column, because interpreting the naive values under another zone would silently shift every instant

### Requirement: Model definitions produce time-zone-aware columns and time-zone-aware defaults

The SQLModel definitions SHALL declare instant-valued fields as time-zone aware, so that a schema built from the models — as the test harness does with `SQLModel.metadata.create_all` — produces the same column type as the schema built by the migrations. Declaring the type in the migration alone is insufficient: it would leave the entire test suite validating a schema that does not exist in production.

Every default that produces a timestamp SHALL use `datetime.now(timezone.utc)`. `datetime.utcnow` SHALL NOT be used in any form — neither called nor passed as a factory. It returns a naive value that resembles UTC without declaring it, it is the origin of the naive/aware mixture, and it is deprecated as of Python 3.12.

#### Scenario: A schema built from the models is time-zone aware
- **WHEN** the schema is created from the model metadata rather than from the migrations
- **THEN** every instant-valued column reports `timestamp with time zone`

#### Scenario: Default-generated timestamps are aware
- **WHEN** a row is created without supplying a value for a timestamp field that has a default
- **THEN** the value stored is time-zone aware and denotes the current instant in UTC

#### Scenario: utcnow is absent from production modules in every form
- **WHEN** the production sources under `backend/app/` are scanned for `datetime.utcnow`
- **THEN** no occurrence is found, whether written as a call `datetime.utcnow()` or as a bare reference such as `default_factory=datetime.utcnow`

#### Scenario: The guard against utcnow is proven to fail on its own negative case
- **WHEN** the guard that scans for `datetime.utcnow` is given a source fragment containing `default_factory=datetime.utcnow`
- **THEN** the guard reports it as a violation

### Requirement: Existing temporal comparisons keep their meaning

The change SHALL NOT alter the semantics of any comparison over instants. The anti-replay skew window (RN-90, RN-131), the 30-day retention of terminal events (RN-98), the agent offline/dead sweep and the command sweep MUST continue to select the same rows for the same data.

These comparisons are evaluated by PostgreSQL, with an aware Python datetime compared against the column. Before the change PostgreSQL coerces the aware value using the session's zone and reaches the right answer because that zone happens to be UTC; after the change it compares instants directly. The outcome is unchanged; what is removed is the dependency on the session.

#### Scenario: The retention cutoff selects the same events
- **WHEN** the retention task runs against a fixed set of events with known ages
- **THEN** it selects exactly the terminal events older than the retention window, as it did before the migration

#### Scenario: The agent sweep transitions the same agents
- **WHEN** the offline/dead sweep runs against agents with known last-heartbeat instants
- **THEN** it transitions exactly the agents whose last heartbeat falls outside the corresponding threshold

#### Scenario: The skew window accepts and rejects the same events
- **WHEN** an event carrying a `sent_at` inside the skew window is ingested, and another carrying one outside it
- **THEN** the first is accepted and the second is rejected with `clock_skew`, unchanged from before the migration
