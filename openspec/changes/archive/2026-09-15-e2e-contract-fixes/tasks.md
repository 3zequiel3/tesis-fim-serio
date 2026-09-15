## 1. FIX-01 (CRITICAL) — agent event hash payload aligned to canonical lexicon

- [x] 1.1 Rename `DetectedChange` fields in `agent/detector.py`: `current_hash` → `hash_detected`, `previous_hash` → `hash_expected` (semantics: `hash_detected` = hash observed now, `hash_expected` = baseline/previous hash). RN-71.
- [x] 1.2 Update every `DetectedChange(...)` construction site in `agent/detector.py` (all event branches: file_modified, file_absent, file_deleted, file_created) to use the new field names.
- [x] 1.3 Confirm `to_event_data()` stays a thin `dataclasses.asdict(self)` and now emits `hash_detected`/`hash_expected`; do NOT add per-key remapping.
- [x] 1.4 Grep the agent (`agent/`) for any remaining reference to `current_hash`/`previous_hash` (publisher, queue, tests, docstrings) and migrate.
- [x] 1.5 Add an integration test in `agent/tests/` that builds a real `DetectedChange`, calls the real `to_event_data()`, and asserts the emitted dict contains a non-empty `hash_detected` matching the detected hash (the missing cross-boundary test).
- [x] 1.6 Add/extend a backend-side test that feeds the agent-shaped dict through `events/service.py` ingestion and asserts the persisted `Event.hash_detected` is the detected hash, not `""`. Do NOT modify `events/service.py`.

## 2. FIX-02 (CRITICAL) — alert SSE emits the `alert` event type and mounts app-wide

- [x] 2.1 In `backend/app/modules/alerts/router.py`, add `"event": "alert"` to the replay yield (line ~150) and the real-time yield (line ~174). Leave the keepalive yield as `{"comment": "keepalive"}` (no event type). Contract C16.
- [x] 2.2 Verify the SSE serialization layer forwards the `event` field to the wire as `event: alert` (inspect the response helper / sse library in use).
- [x] 2.3 Move the `useAlertsSSE()` mount out of `frontend/src/pages/Events.tsx` into the authenticated global layout so alerts arrive app-wide; ensure exactly ONE mount (remove the page-level mount to avoid duplicate `EventSource` connections).
- [x] 2.4 Add a backend test asserting the SSE stream frames carry `event: alert` for real alerts (and not for keepalives).

## 3. FIX-03 (HIGH) — frontend Agent contract aligned to backend schema

- [x] 3.1 In `frontend/src/api/agents.ts`, retype the `Agent` interface to match `AgentResponse`: `agent_id` (drop `id`), `last_heartbeat` (drop `last_seen`), keep `status`/`watch_paths`/`queue_pressure`/`ruleset_version_applied`. Remove `hostname`.
- [x] 3.2 Extend the `AgentStatus` union to include `revoked` (backend `AgentStatus` has `online|offline|draining|dead|revoked`).
- [x] 3.3 Fix `triggerRescan(id, force)` to POST a JSON body `{ force }` (matching `AgentRescanRequest`) instead of `null` + query param. Preserve the documented 409 `pending_events_exist` handling.
- [x] 3.4 Migrate every consumer in `frontend/src` that reads `agent.id` / `agent.hostname` / `agent.last_seen`: use `agent.agent_id` for `key=` and route params, `agent.last_heartbeat` for the "last seen" display, and display `agent_id` where `hostname` was shown (mirrors `core/health.py:97`). Let the TypeScript compiler surface every removed-field site.
- [x] 3.5 Run the frontend type-check/build to confirm no residual references to the removed fields (`.id`/`.hostname`/`.last_seen` on agent objects).

## 4. FIX-04 (MEDIUM) — bulk approve/reject isolates per-item failures

- [x] 4.1 In `backend/app/modules/actions/service.py` `approve_bulk`, call `db.rollback()` inside every `except` branch (`AbsentConfirmationRequired`, `ConflictError`, generic `Exception`) before appending to `failed`. Pattern: `users/router.py:130`.
- [x] 4.2 Apply the same rollback-per-item to `reject_bulk` (`ConflictError`, generic `Exception`).
- [x] 4.3 Add a regression test in `backend/tests/` where a middle item in a batch raises; assert later valid items still succeed and only the failing item is reported in `failed` (no false cascade `internal_error`).

## 5. Verification

- [x] 5.1 Run the agent test suite and the backend test suite; all green.
- [x] 5.2 Run the frontend type-check/build; no type errors from the Agent contract change.
- [x] 5.3 Confirm no new dependency, no schema migration, and no change to `events/service.py` hash key or the agent registration/heartbeat payload.
