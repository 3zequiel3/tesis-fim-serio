# backend-test-harness

The contract for the backend automated test harness: a reproducible, isolated
test suite that runs against a real Postgres/Valkey and owns its own schema,
seeding, and per-test cleanup. These requirements describe the test
infrastructure itself, not product behavior. The production `seed_admin` fix
that this change ships enforces the existing `backend-auth` spec
(`must_change_password=True`, RN-62 / RN-100) and therefore introduces no delta
to `backend-auth`.

## ADDED Requirements

### Requirement: Test harness owns schema, seeding, and isolation

The backend test harness SHALL provide a single root `backend/tests/conftest.py`
that owns database setup. It SHALL create the schema via
`SQLModel.metadata.create_all(engine)` exactly once per session on the configured
test engine, seed the canonical admin once, and isolate every test by running
`TRUNCATE ... RESTART IDENTITY CASCADE` on all tables followed by re-seeding the
admin. The harness SHALL NOT rely on the FastAPI lifespan running under
`httpx.AsyncClient` + `ASGITransport` (which does not execute startup/shutdown).
The harness SHALL run against a real PostgreSQL instance, not in-memory SQLite.

#### Scenario: Fresh database produces a green, order-independent suite

- **WHEN** the suite runs against a freshly created empty `fim_test` database with
  Valkey reachable, via `uv run pytest` from `backend/`
- **THEN** the schema and seeded admin are created by the root conftest
- **AND** the full suite passes regardless of test execution order
- **AND** no test depends on state left behind by a previous test

#### Scenario: Per-test isolation resets database state

- **WHEN** one test inserts rows and a subsequent test runs
- **THEN** the subsequent test observes only the freshly re-seeded admin and no
  leftover rows from the previous test

### Requirement: Single canonical test admin

The test harness SHALL define exactly one canonical admin identity, configured in
the root conftest BEFORE any application module (and therefore `Settings()`) is
imported. All test modules SHALL use this canonical `ADMIN_USERNAME`; no test
module SHALL override it via a conflicting `os.environ.setdefault`.

#### Scenario: No admin-username collision across modules

- **WHEN** multiple test modules that authenticate as the seed admin run in the
  same session in any import order
- **THEN** every module resolves the same `ADMIN_USERNAME`
- **AND** none fails because a different module's username won the import-time
  `Settings()` instantiation

### Requirement: Harness supports the forced password-change flow

The test harness SHALL provide a helper that completes the forced
password-change flow for the seeded admin (created with a forced-change flag per
RN-62 / RN-100) and yields a fully-scoped authenticated client/token. The harness
SHALL also expose the raw first-login token whose scope is `password_change_only`
for tests that assert the gate.

#### Scenario: Helper yields a fully-scoped client

- **WHEN** a test requests the authenticated-admin fixture
- **THEN** the helper logs in, changes the password to a policy-compliant value
  (≥12 chars, at least one uppercase, one lowercase, one digit) using the
  `password_change_only`-scoped token
- **AND** yields a token without the `password_change_only` scope

#### Scenario: Forced-change gate is testable

- **WHEN** a test uses the raw first-login token against a normal protected endpoint
- **THEN** the response is 403 with `password_change_required`

### Requirement: Test suite terminates deterministically

The test harness SHALL NOT hang. Streaming/SSE tests SHALL be bounded so they
terminate without external intervention, and the harness SHALL configure a global
per-test timeout as a safety net so any future hang fails the run instead of
stalling it.

#### Scenario: Streaming test terminates

- **WHEN** the SSE stream test runs
- **THEN** it consumes a bounded number of events (or applies a read
  timeout/cancellation) and completes

#### Scenario: Runaway test fails instead of hanging

- **WHEN** any test exceeds the configured global timeout
- **THEN** that test fails with a timeout error and the rest of the suite continues
