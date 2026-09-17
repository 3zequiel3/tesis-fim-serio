## ADDED Requirements

### Requirement: Event carries a nullable action failure cause exposed by the API

The `Event` model SHALL gain a nullable, bounded-length string column holding the cause of a failed automatic action, added by an idempotent raw SQL migration in the project's migrations directory following the established convention (no Alembic, manual application through `psql`, header naming the migration number, the decision and the change).

The column SHALL be nullable with no default and SHALL NOT be indexed: no endpoint or filter queries it, and indexing a low-cardinality column with no query behind it buys nothing. No new filter, sort or query parameter SHALL be added to the events endpoints.

`EventOut` SHALL expose the field additively, following the pattern already used for the acknowledgement status, the symlink metadata and the action failure flag. This is not a breaking change for existing clients. (D36 / RN-130, D3)

#### Scenario: The column is added idempotently

- **WHEN** the migration is applied twice against the same database
- **THEN** both runs succeed and the column exists exactly once

#### Scenario: Pre-existing rows keep a null cause

- **WHEN** the migration is applied to a database holding events created before this change
- **THEN** those rows have a null cause and are otherwise unchanged

#### Scenario: The list endpoint exposes the cause

- **WHEN** an event with a failure cause is returned by the events list endpoint
- **THEN** the response carries the cause field

#### Scenario: The detail endpoint exposes the cause

- **WHEN** an event with a failure cause is fetched by identifier
- **THEN** the response carries the cause field

#### Scenario: No new query parameter is introduced

- **WHEN** the events endpoints are inspected after this change
- **THEN** their accepted filters are unchanged
