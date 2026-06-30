## Why

The backend test suite is not reproducibly green. It only ever passed against the
running dev compose database (`fim`), which already had the schema created and an
admin seeded by the real FastAPI app lifespan. Run against a fresh database it
produces 38 failures (`relation "users" does not exist`); run with no database it
produces 49 failures (`connection refused`). The suite cannot be trusted as a gate
for the C30/C31/C32 audit-remediation family because it is order- and
environment-dependent, and a streaming SSE test hangs the run indefinitely.

The broken harness was also masking a real production bug (the seeded admin is
created with `must_change_password=False`, violating RN-62 and RN-100/W20) and a
set of logging-sanitizer tests that never actually exercised the production
sanitizer. This change makes the suite reproducible and isolated, and fixes the
defects the broken harness was hiding. All root causes are pre-existing and
independent of C30 (confirmed against `git diff HEAD`).

## What Changes

- Add a root `backend/tests/conftest.py` that owns schema creation, single admin
  seeding, and per-test isolation on the configured test engine, so every test
  runs against a known-clean Postgres state regardless of import order.
- Adopt one canonical test pattern. Today three inconsistent patterns coexist:
  - Pattern A (isolated, correct): in-memory engine + `dependency_overrides`.
  - Pattern B (schema created, no isolation, no teardown): real shared engine with
    per-file `create_all`.
  - Pattern C (nothing — relies on an externally pre-seeded DB).
  Consolidate Pattern B and C onto the canonical real-Postgres harness with
  per-test cleanup. Decide per design whether Pattern A files migrate or stay.
- Resolve the `ADMIN_USERNAME` collision between `test_auth.py` (`admin`) and
  `test_user_management.py` (`admin@fim.local`). `Settings()` is instantiated once
  at import time, so the first import wins and the loser's expectations break. Set
  a single canonical test admin in the root conftest before any `Settings()` load.
- Provide a forced-password-change test helper. Once the seed admin is correctly
  created with `must_change_password=True`, authenticated-endpoint tests receive a
  `password_change_only`-scoped token and get 403 until the change is performed.
  The helper completes that flow once and yields a fully-scoped client/token.
- **BREAKING (production fix)** — `auth/service.py::seed_admin` sets
  `must_change_password=True`, enforcing RN-62, RN-100/W20 and the existing
  `backend-auth` spec. The current `False` is a defect.
- Fix the logging-sanitizer tests in `test_logging_sanitize.py`. They use
  `structlog.testing.capture_logs()`, which replaces the configured processor chain
  and therefore never runs `sanitize_secrets`. The production sanitizer is already
  correct (case-insensitive, recursive); the tests must exercise the real chain.
- Handle the hanging SSE stream test (`test_sse_alerts.py`): make the stream test
  bounded and add `pytest-timeout` to `requirements-dev.txt` as a global safety net.
- Correct the stale test docs: `backend/README.md` ("Los tests montan la app en
  memoria — no necesitan DB ni Valkey") and the conftest docstring are both wrong.
- Add `backend-test-harness` (Change 33) to `CHANGES.md` as a remediation entry
  depending on Change 30.

## Capabilities

### New Capabilities
<!-- The only NEW contract this change establishes is the test harness itself.
     These are test-infrastructure requirements (reproducible/isolated suite,
     canonical admin, forced-change helper, no-hang), not product requirements. -->
- `backend-test-harness`: the contract for the backend automated test suite —
  reproducible and isolated against real Postgres/Valkey, single canonical seeded
  admin, forced-password-change test helper, and deterministic (non-hanging)
  termination.

### Modified Capabilities
<!-- None. The seed_admin fix enforces the EXISTING backend-auth spec
     (must_change_password=True, RN-62 / RN-100); the code was simply
     non-compliant, so re-stating it as a delta would be redundant. The logging
     fix corrects tests against the existing backend-core sanitizer requirement
     (RN-89) and changes no production behavior. -->
- _None_

## Impact

- **Test infrastructure**: new `backend/tests/conftest.py` (root); consolidation of
  per-file fixtures in `test_consumer.py`, `test_notifications.py`,
  `test_agent_mgmt.py`, `test_actions.py`, `test_event_consumer_c11.py`,
  `test_heartbeat_consumer.py`, `test_retention_task.py`, `test_sse_alerts.py`,
  `test_rules_service.py`, `tests/modules/events/test_retention.py`,
  `test_auth.py`, `tests/modules/users/test_user_management.py`,
  `test_logging_sanitize.py`.
- **Production code**: `backend/app/modules/auth/service.py::seed_admin`
  (`must_change_password=True`). No other production behavior changes.
- **Dependencies**: `backend/requirements-dev.txt` adds `pytest-timeout`.
- **Docs**: `backend/README.md`, conftest docstring, `CHANGES.md`.
- **RN covered**: RN-62, RN-100/W20 (seed admin forced change), RN-89 (log
  sanitization, via corrected tests). **Decisions applied**: D3 (lifespan
  seed/create_all — the test harness mirrors it explicitly).
- **DAG**: depends on Change 30 (`backend-async-io-fixes`, in working tree). The
  harness must green the suite including C30's async-consumer and heartbeat-HMAC
  changes.
