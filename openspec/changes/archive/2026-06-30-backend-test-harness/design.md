## Context

The backend test suite passes only against the long-lived dev compose database
`fim`, which the real FastAPI lifespan already populated (`create_all` + seeded
admin). Three findings make it non-reproducible:

1. **The `client` fixture never runs the lifespan.** `httpx.AsyncClient` +
   `ASGITransport` does NOT execute FastAPI startup/shutdown, so the conftest's
   `create_all` + `seed_admin` never actually run there. The conftest docstring
   claims otherwise and is wrong.
2. **Three coexisting patterns.**
   - Pattern A (correct, isolated): in-memory engine + `app.dependency_overrides[get_session]`
     — `test_c22_auth.py`, `test_rules_router.py`, `test_c22_scope_gate.py`.
   - Pattern B (schema yes, no isolation, no teardown): real shared `engine` +
     per-file `SQLModel.metadata.create_all(engine)` — `test_consumer.py`,
     `test_notifications.py`, `test_agent_mgmt.py`, `test_actions.py`,
     `test_event_consumer_c11.py`, `test_heartbeat_consumer.py`,
     `test_retention_task.py`, `test_sse_alerts.py`, `test_rules_service.py`,
     `tests/modules/events/test_retention.py`.
   - Pattern C (nothing — relies on an externally pre-seeded DB): `test_auth.py`,
     `tests/modules/users/test_user_management.py`.
3. **No per-test isolation** on the shared real engine → order/state dependence.
   Fresh DB → 38 fail (`relation "users" does not exist`); no DB → 49 fail
   (`connection refused`).

Additional facts grounding this design:

- **Infra reality**: the compose containers do NOT publish Postgres/Valkey to the
  host (5432/6379 are internal-only). Running the suite locally requires Postgres
  and Valkey reachable at `localhost:5432` / `localhost:6379`. The conftest default
  is `DATABASE_URL=postgresql+psycopg://fim:test@localhost:5432/fim_test`. Test
  runner: `uv run pytest` from `backend/`.
- **Settings is import-time global.** `Settings()` is built once at first import, so
  `ADMIN_USERNAME` is frozen by whichever test module imports first
  (`os.environ.setdefault` → first-writer-wins). `test_auth.py` expects `admin`;
  `test_user_management.py` expects `admin@fim.local`. They cannot both win.
- **Many tests bypass `get_session`.** Consumers and services open `Session(engine)`
  directly rather than receiving the FastAPI-injected session. A
  `dependency_overrides`-only isolation strategy CANNOT isolate them.
- **`_patch_async_valkey` exists** (autouse) for the async Valkey client; the SYNC
  Valkey client used by consumers/streams is NOT mocked.
- **A streaming SSE test hangs** (`test_sse_alerts.py::test_stream_alerts_*`).
  `pytest-timeout` is not installed, so a hang stalls the whole run.

This change also covers two defects the broken harness masked (see Decision 7).

## Goals / Non-Goals

**Goals:**
- A reproducible, isolated backend suite that is green from a clean Postgres on a
  fresh checkout, including C30's async-consumer and heartbeat-HMAC changes.
- One canonical harness pattern with a single source of truth for schema creation,
  admin seeding, and per-test cleanup.
- Fix `seed_admin` to satisfy RN-62 / RN-100 and the existing `backend-auth` spec.
- Correct the logging-sanitizer tests so they exercise the real processor chain.
- Remove the indefinite hang and add a timeout safety net.
- Accurate run instructions in `backend/README.md`, the conftest docstring, and a
  `CHANGES.md` roadmap entry.

**Non-Goals:**
- No new product features and no new requirement contracts (no delta specs;
  follows the C28 remediation precedent).
- No migration to SQLite (see Decision 2).
- No CI pipeline / GitHub Actions wiring — out of scope for this change.
- No change to production logging behavior (the sanitizer is already correct).
- No re-architecture of consumers/services to route through `get_session`.

## Decisions

### Decision 1 — Per-test isolation: TRUNCATE + reseed on the real engine

**Choice**: A function-scoped autouse fixture in the root conftest that, after each
test (or before, with reseed), runs `TRUNCATE <all tables> RESTART IDENTITY CASCADE`
on the configured test engine and re-seeds the canonical admin. Schema is created
once per session (autouse session-scoped `SQLModel.metadata.create_all(engine)`),
admin seeded once and re-seeded after each truncate.

**Why over transaction-rollback**: the rollback pattern (open one connection per
test, begin a transaction / SAVEPOINT, bind every session to it, roll back at
teardown) only isolates code that uses the *bound* connection. This codebase opens
`Session(engine)` directly inside consumers and services, which would acquire
independent connections and escape the rolled-back transaction — leaving state
behind. TRUNCATE+reseed on the real engine isolates regardless of how each unit
obtains its session. All existing per-file DB fixtures are function-scoped, so
per-test cleanup is safe and does not fight a wider-scoped fixture.

**Trade-off**: TRUNCATE per test is slower than an in-transaction rollback and
serializes around a shared database. Acceptable for this suite's size; revisit only
if runtime becomes a problem.

### Decision 2 — Stay on real Postgres; do NOT migrate to in-memory SQLite

**Choice**: Keep tests on a real Postgres instance (ephemeral container is fine).

**Why**: The code relies on Postgres-specific semantics — FK/`CASCADE` behavior,
JSON column types, and `TRUNCATE ... RESTART IDENTITY CASCADE` itself — that SQLite
does not faithfully reproduce. Testing on SQLite would test a different database
than production and silently diverge.

**Canonical run** (document in README + conftest docstring): bring up ephemeral
backing services, then `uv run pytest` from `backend/`:

```
docker run --rm -d --name fim-test-db \
  -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fim_test \
  -p 5432:5432 postgres:18.3
docker run --rm -d --name fim-test-valkey -p 6379:6379 valkey/valkey:9.0.3
```

Default `DATABASE_URL=postgresql+psycopg://fim:test@localhost:5432/fim_test`.

**Trade-off**: requires a running Postgres (and Valkey) — tests are not pure unit
tests. This matches how the application actually behaves and is the only way to keep
the consumer/service tests meaningful.

### Decision 3 — Pattern A (in-memory) files: leave as-is

**Choice**: Do not migrate the Pattern A files (`test_c22_auth.py`,
`test_rules_router.py`, `test_c22_scope_gate.py`). They already run isolated and
green via in-memory engine + `dependency_overrides`. Only consolidate Pattern B and
Pattern C onto the canonical real-Postgres harness.

**Why**: Migrating working, already-isolated tests adds churn and risk for no gain.
The goal is reproducibility, not pattern monoculture. Document both patterns and the
rule for when each applies (router/endpoint tests that go through `get_session` may
use the in-memory override; tests that touch consumers/services directly use the
real engine).

**Trade-off**: two patterns remain in the tree. Mitigated by documenting the
boundary explicitly and centralizing the real-engine machinery in the root conftest.

### Decision 4 — Single canonical test admin set before any `Settings()` import

**Choice**: The root conftest sets, before importing any app module:
`ADMIN_USERNAME=admin`, a fixed `ADMIN_PASSWORD` for the seed, and the test
`DATABASE_URL` / `VALKEY_URL`. `test_user_management.py` is migrated off
`admin@fim.local` to the canonical `admin`.

**Why**: `Settings()` is import-time-global and first-writer-wins. A single root
conftest that runs before any `Settings()` instantiation is the only place that can
make the value deterministic across modules. `admin` matches the compose convention
and the larger of the two existing expectations.

**Trade-off**: one test module changes its expected username. Mechanical and
low-risk.

### Decision 5 — Forced password-change test helper

**Choice**: Provide an `admin_token` / `authenticated_client` fixture that logs in
the seeded admin (now `must_change_password=True`), performs
`POST /users/change-password` with a `password_change_only`-scoped token to a
policy-compliant new password (≥12 chars, upper + lower + digit per RN-100), then
returns a fully-scoped token/client. A separate fixture exposes the raw
first-login (still-forced) token for tests that assert the 403 gate.

**Why**: Flipping `seed_admin` to `must_change_password=True` (Decision 7) means any
authenticated-endpoint test now hits 403 `password_change_required` until the change
is done. Centralizing the flow keeps individual tests focused and avoids each test
re-implementing it.

**Trade-off**: tests that previously assumed an immediately fully-scoped admin must
use the new fixture. This is the correct behavior per the existing `backend-auth`
spec.

### Decision 6 — Sync Valkey: add a fake symmetric to the async patch; real Valkey only for integration transport tests

**Choice**: Add an autouse fake for the SYNC Valkey client (mirroring the existing
autouse `_patch_async_valkey`), so consumer/stream unit tests are deterministic and
do not require a live Valkey. Integration transport tests that must exercise real
Streams opt in explicitly (dedicated fixture/marker) against the ephemeral
`localhost:6379` Valkey.

**Why**: Most consumer/service tests only need the client to not explode and to
record calls; a fake gives determinism and removes a hidden external dependency. The
few genuine end-to-end transport tests still need a real Stream, so they opt in
rather than the default requiring a live broker.

**Alternative considered**: require real Valkey for the whole suite. Rejected — it
couples every unit test to a running broker and makes failures noisier and slower.

**Trade-off**: a fake can drift from real Valkey semantics. Mitigated by keeping the
real-Valkey integration tests as the contract check for Stream behavior.

### Decision 7 — Fix the two masked defects

**7a — `seed_admin` (production bug).** `auth/service.py::seed_admin` currently sets
`must_change_password=False`. RN-62 (line 459) and RN-100/W20 (line 747) of
`reglas_de_negocio.md`, and the existing `backend-auth` spec (Requirement
"seed_admin() con cuerpo completo (D3)"), all mandate `True`. Fix to `True`. This
enforces an already-closed rule and an existing spec — no delta spec, no new
decision.

**7b — logging-sanitizer tests (test bug, NOT production).** Investigation finding:
six tests in `test_logging_sanitize.py` fail (not just `test_case_insensitive_match`
— `test_password_redacted_direct_kwarg` with a plain lowercase `password` fails
too). Root cause: the tests use `structlog.testing.capture_logs()`, which swaps the
configured processor chain for a single `LogCapture`, so the production
`sanitize_secrets` processor never runs. The production sanitizer is already correct
— it matches `k.lower() in SENSITIVE_KEYS` (case-insensitive) and recurses into
nested dicts/lists (`logging.py` lines 85, 106). **The fix belongs in the tests**:
either call `sanitize_secrets` directly (as the already-passing
`test_sanitize_secrets_processor_direct` does) or assert against output produced by
the real configured chain (e.g. capture the rendered JSON), not via `capture_logs()`.
No production logging change; RN-89 is already satisfied.

### Decision 8 — SSE hang: bound the test + add `pytest-timeout`

**Choice**: Make the SSE stream test bounded — consume a fixed number of events (or
use a client-side read timeout / cancellation) so it terminates deterministically —
AND add `pytest-timeout` to `requirements-dev.txt` with a global per-test timeout as
a safety net so any future hang fails loudly instead of stalling the run.

**Why**: Fixing the test removes the actual hang; the timeout is defense-in-depth so
the suite can never again hang indefinitely in CI or local runs.

**Trade-off**: a global timeout can flake on a very slow machine. Mitigated by
setting a generous bound (e.g. 60s) far above normal test runtime.

## Risks / Trade-offs

- [TRUNCATE+reseed slows the suite and serializes on one DB] → Acceptable at current
  size; the alternative (transaction-rollback) cannot isolate the direct
  `Session(engine)` consumers/services, so correctness wins over speed here.
- [Flipping `must_change_password=True` breaks tests that assumed a fully-scoped
  admin] → Provide the forced-change helper (Decision 5) and migrate affected tests
  in the same change.
- [Sync Valkey fake drifts from real semantics] → Keep real-Valkey integration
  transport tests as the contract check (Decision 6).
- [Tests now require a running Postgres/Valkey, not pure unit tests] → Document the
  ephemeral-container bootstrap as the canonical run; it matches production behavior.
- [Global `pytest-timeout` could flake on slow hardware] → Generous bound well above
  normal runtime.
- [Two test patterns remain (A and the canonical real-engine)] → Document the
  boundary and centralize machinery in the root conftest.

## Migration Plan

1. Add the root `backend/tests/conftest.py` (session schema create, single admin
   seed, function-scoped TRUNCATE+reseed, canonical env, sync+async Valkey fakes,
   forced-password-change helpers). Correct its docstring.
2. Fix `seed_admin` → `must_change_password=True`.
3. Migrate Pattern B/C files onto the canonical fixtures; remove their per-file
   `create_all`/no-teardown fixtures and `os.environ.setdefault` admin overrides.
4. Rewrite `test_logging_sanitize.py` to exercise the real sanitizer.
5. Bound the SSE stream test; add `pytest-timeout` to `requirements-dev.txt` and set
   the global timeout.
6. Update `backend/README.md` run instructions; add Change 33 to `CHANGES.md`.
7. Verify: bootstrap ephemeral Postgres+Valkey, `uv run pytest` from `backend/` →
   fully green and order-independent (re-run with `-p randomly` if available).

**Rollback**: the change is test-infra plus one one-line production fix
(`must_change_password`). Reverting the commit restores prior behavior; the only
production-visible effect to re-validate on rollback is the seed admin flag.

## Open Questions

- None blocking. One scope clarification for the user (does not block apply): the
  audit brief framed the logging issue as "make the sanitizer case-insensitive",
  but the production sanitizer is already case-insensitive — the defect is in the
  tests (they bypass the processor chain). This design fixes the tests, not the
  production code. Flag for confirmation only; no new decision or appendix entry is
  required.
