## 1. Root conftest — canonical harness

- [x] 1.1 Create `backend/tests/conftest.py` (root) that sets canonical env BEFORE any app import: `ADMIN_USERNAME=admin`, fixed `ADMIN_PASSWORD`, `DATABASE_URL=postgresql+psycopg://fim:test@localhost:5432/fim_test`, `VALKEY_URL=valkey://localhost:6379`.
- [x] 1.2 Add a session-scoped autouse fixture that runs `SQLModel.metadata.create_all(engine)` on the configured test engine once per run.
- [x] 1.3 Add a single-seed helper that creates the canonical admin (mirrors `seed_admin` semantics) and assert it sets `must_change_password=True`.
- [x] 1.4 Add a function-scoped autouse isolation fixture that runs `TRUNCATE <all tables> RESTART IDENTITY CASCADE` and re-seeds the admin around every test.
- [x] 1.5 Correct the conftest docstring: remove the false claim that the lifespan runs under `ASGITransport`; document that schema/seed/isolation are owned by this conftest.

## 2. Valkey fakes

- [x] 2.1 Keep the existing autouse `_patch_async_valkey`; add a symmetric autouse fake for the SYNC Valkey client used by consumers/streams so unit tests need no live broker.
- [x] 2.2 Add an opt-in fixture/marker for integration transport tests that require a real Valkey at `localhost:6379` (Streams contract checks).

## 3. Auth seed fix + forced-change helper

- [x] 3.1 Fix `backend/app/modules/auth/service.py::seed_admin` to set `must_change_password=True` (RN-62, RN-100/W20; existing `backend-auth` spec).
- [x] 3.2 Add an `admin_token` / `authenticated_client` fixture that logs in, performs `POST /users/change-password` (policy-compliant new password: ≥12 chars, upper + lower + digit) using the `password_change_only`-scoped token, and yields a fully-scoped token/client.
- [x] 3.3 Add a fixture exposing the raw first-login (still-forced) token for tests that assert the 403 `password_change_required` gate.

## 4. Consolidate Pattern B and Pattern C

- [x] 4.1 Migrate `test_consumer.py`, `test_notifications.py`, `test_agent_mgmt.py`, `test_actions.py`, `test_event_consumer_c11.py`, `test_heartbeat_consumer.py`, `test_retention_task.py`, `test_rules_service.py`, `tests/modules/events/test_retention.py` off per-file `create_all`/no-teardown fixtures onto the root harness.
- [x] 4.2 Migrate `test_auth.py` and `tests/modules/users/test_user_management.py` onto the root harness; remove their `os.environ.setdefault` admin overrides and align `test_user_management.py` to the canonical `admin` username.
- [x] 4.3 Update any migrated authenticated-endpoint tests to use the forced-change helper (task 3.2) instead of assuming an immediately fully-scoped admin.

## 5. Pattern A (leave isolated) — verify only

- [x] 5.1 Confirm `test_c22_auth.py`, `test_rules_router.py`, `test_c22_scope_gate.py` still pass unchanged under the root conftest (no migration; in-memory + `dependency_overrides` retained).

## 6. Logging sanitizer tests

- [x] 6.1 Rewrite `test_logging_sanitize.py` to exercise the real sanitizer instead of `structlog.testing.capture_logs()` (call `sanitize_secrets` directly or assert against the real configured chain output). Do NOT change `app/core/logging.py` — the production sanitizer is already correct.

## 7. SSE hang + timeout

- [x] 7.1 Make `test_sse_alerts.py::test_stream_alerts_*` bounded (consume a fixed number of events or apply a client-side read timeout / cancellation) so it terminates deterministically.
- [x] 7.2 Add `pytest-timeout` to `backend/requirements-dev.txt` and configure a generous global per-test timeout (e.g. 60s) as a safety net.

## 8. Docs and roadmap

- [x] 8.1 Correct `backend/README.md`: replace "Los tests montan la app en memoria (no necesitan DB ni Valkey)" with the real run instructions (ephemeral Postgres+Valkey bootstrap, `uv run pytest` from `backend/`, default `DATABASE_URL`).
- [x] 8.2 Add Change 33 `backend-test-harness` to `CHANGES.md` (table row + section) as a remediation entry depending on Change 30, following the C28/C30 style.

## 9. Verification

- [x] 9.1 Bootstrap ephemeral Postgres+Valkey, run `uv run pytest` from `backend/` against a FRESH `fim_test` DB → fully green.
- [x] 9.2 Confirm order-independence (re-run; if `pytest-randomly` is available, run with random order) and that no test hangs.
