## Context

Four independent contract mismatches span three processes (agent, backend, frontend). Each is a case where the producing side and the consuming side disagree on the shape of a payload, and both sides' unit tests pass because they never exercise the real cross-process serialization. The canonical contracts already exist (RN-71 event lexicon, RN-17/D2 event hash, C16 SSE contract); the code drifted from them. This design records the boundary each fix must respect so the correction is applied on exactly one side and does not paper over the mismatch on the other.

Verified against current code (2026-07-02):
- `agent/detector.py`: `DetectedChange` declares `previous_hash`/`current_hash`; `to_event_data()` is `dataclasses.asdict(self)`.
- `backend/app/modules/events/service.py:172`: `hash_detected=event_data.get("hash_detected", "")`. The persisted `Event` row carries `hash_detected`.
- `backend/app/modules/alerts/router.py:150,174`: yields `{"id","data"}`; keepalive yields `{"comment": "keepalive"}`.
- `frontend/src/hooks/useAlertsSSE.ts:21`: `es.addEventListener('alert', ...)`.
- `backend/app/modules/agents/models.py`: `AgentResponse` = `agent_id`/`status`/`last_heartbeat`/`queue_pressure`/`ruleset_version_applied`/`watch_paths`. The `Agent` table, `AgentRegisterRequest`, and the agent `heartbeat.py` payload have **no** `hostname`. `AgentRescanRequest` = `{force: bool}`.
- `frontend/src/api/agents.ts:8-13`: `Agent` = `id`/`hostname`/`status`/`watch_paths`/`queue_pressure`/`last_seen`/`ruleset_version_applied`. `triggerRescan` posts `null` with `force` as a query param.
- `backend/app/modules/actions/service.py:337,373`: per-item `except Exception` with no `session.rollback()`, single `Session` reused across the loop.
- Precedent for rollback-per-item: `backend/app/modules/users/router.py:130` (`except IntegrityError: session.rollback()`).
- Precedent for `agent_id` as display identity: `backend/app/core/health.py:97` (`"hostname": a.agent_id`).

## Goals / Non-Goals

**Goals:**
- Make every real detected event persist a non-empty `hash_detected` by aligning the agent payload to the canonical lexicon (RN-71), fixing the producing side only.
- Restore the alert SSE push channel end-to-end and make it reachable app-wide.
- Make the frontend Agent contract match the backend response schema so agent rows key correctly and config/rescan hit real IDs.
- Make bulk approve/reject isolate per-item failures so one bad item no longer cascades into false `internal_error` for the rest.
- Add the missing cross-boundary tests that would have caught each defect.

**Non-Goals:**
- No backend change to the event hash key (`hash_detected` stays; the agent conforms to it).
- No new `Agent.hostname` column and no change to the agent registration/heartbeat payload. Displaying a real hostname is explicitly OUT OF SCOPE (see Decision 3 and Open Questions).
- No change to the SSE reconnection / Last-Event-ID semantics (C16) beyond adding the `event` type.
- No new capability, no new business rule, no new decision.

## Decisions

### Decision 1 — FIX-01: rename on the agent, map to the canonical lexicon
The canonical event lexicon (RN-71) and both consumers (backend `Event.hash_detected`, frontend `EventDetail`/`RejectModal`) already speak `hash_detected` / `hash_expected`. Only the agent's `DetectedChange` drifted to `current_hash`/`previous_hash`. Fix the producer:
- Rename `DetectedChange.current_hash` → `hash_detected` and `previous_hash` → `hash_expected` (semantics: `hash_detected` = the hash observed now, `hash_expected` = the baseline/previous hash). Update all `DetectedChange(...)` construction sites in `detector.py`.
- `to_event_data()` stays a thin serializer over the dataclass; after the rename `asdict()` emits the correct keys.
- **Alternatives rejected**: (a) remap keys inside `to_event_data()` while keeping the dataclass field names — leaves two names for one concept and violates RN-71 in-code; (b) change the backend to read `current_hash` — moves the contract off the canonical lexicon that the frontend and DB already use, and would ripple into specs.

### Decision 2 — FIX-02: emit `event: "alert"` on real yields only, mount SSE globally
- Add `"event": "alert"` to the two real-alert yields (replay at line 150, real-time at line 174). The keepalive yield stays a `{"comment": ...}` (comments carry no event type and must not trigger the `alert` listener). This matches the frontend `addEventListener('alert', ...)` and the C16 contract.
- Move the `useAlertsSSE()` mount from `Events.tsx` into the authenticated global layout so a single connection delivers toasts across the app. Keep exactly one mount to avoid duplicate `EventSource` connections; if `Events.tsx` also mounts it, remove the page-level mount.
- **Alternatives rejected**: changing the frontend to listen for the default `message` type — throws away the ability to multiplex event types on the same stream and diverges from C16.

### Decision 3 — FIX-03: align the frontend to the real backend schema; drop `hostname`
- Retype the frontend `Agent` interface to the backend `AgentResponse`: `agent_id` (not `id`), `last_heartbeat` (not `last_seen`), keep `status`/`watch_paths`/`queue_pressure`/`ruleset_version_applied`. `AgentStatus` on the backend also includes `revoked` — extend the frontend union to match.
- Every consumer that reads `agent.id` / `agent.last_seen` migrates to `agent.agent_id` / `agent.last_heartbeat`; `key={agent.agent_id}`; rescan/config paths use `agent.agent_id`.
- `hostname` does not exist in the backend response, the `Agent` table, the registration request, or the agent heartbeat payload. The frontend stops referencing `hostname` and displays `agent_id` as the identity, mirroring `core/health.py:97` which already treats `agent_id` as the hostname value. **This introduces no new column and no new decision.**
- `triggerRescan(id, force)` sends `force` in a JSON body `{ force }` (matching `AgentRescanRequest`) instead of a query param with `null` body. Preserve the documented 409 `pending_events_exist` handling.
- **Alternatives rejected**: adding `hostname` to the backend — requires a new `Agent` column AND the agent to report it in registration/heartbeat, which is a new assumption not closed in any appendix; therefore out of scope and flagged, not assumed.

### Decision 4 — FIX-04: rollback per failed item in both bulk paths
- In `approve_bulk` and `reject_bulk`, call `db.rollback()` inside every `except` branch (both the specific `ConflictError`/`AbsentConfirmationRequired` and the generic `Exception`) before appending to `failed`, so a Postgres-aborted transaction is cleared before the next item runs. This follows the existing `users/router.py:130` precedent (`except ...: session.rollback()`).
- Rationale for rollback-per-item over per-item sub-transactions/savepoints: minimal, matches the established codebase pattern, and the single shared `Session` is already the calling convention for these functions. A per-item `begin_nested()` savepoint is a valid alternative but is a larger structural change than the defect warrants.
- **Alternatives rejected**: opening a fresh `Session` per item — heavier and inconsistent with how the router injects the session.

### Decision 5 — tests exercise the real boundary
- FIX-01: an integration test constructs a real `DetectedChange`, calls the real `to_event_data()`, feeds the dict through the backend event consumer path, and asserts the persisted `Event.hash_detected` is the detected hash (not `""`). This is the class of test that was missing.
- FIX-04: a regression test runs a batch where a middle item raises, asserting that later valid items still succeed (no false cascade `internal_error`).

## Risks / Trade-offs

- **[Renaming `DetectedChange` fields breaks in-flight payloads already on the Valkey stream]** → The stream carries transient events; a coordinated agent+backend deploy (backend already reads `hash_detected`) means only the agent changes. Old in-flight messages with `current_hash` would have persisted `""` anyway (the current bug), so there is no regression. Mitigation: deploy note that agent and backend ship together.
- **[Double SSE mount if the page-level mount is not removed]** → Two `EventSource` connections and duplicate toasts. Mitigation: single global mount; explicitly remove the `Events.tsx` mount.
- **[Frontend Agent rename misses a consumer]** → residual `undefined` in an unmigrated component. Mitigation: grep for `.hostname`, `.last_seen`, `.id` on agent objects across `frontend/src` during apply; TypeScript compile fails on the removed fields, which surfaces every site.
- **[Rollback-per-item hides a systemic failure as many per-item failures]** → if the DB is down, every item fails individually. Acceptable: the response already reports per-item `failed` reasons, and this is strictly better than the current false cascade.

## Migration Plan

- No schema migration. No new dependency.
- Deploy order: ship agent + backend together (FIX-01 is a producer/consumer pair already converged on the backend side). Frontend can ship independently once the backend is deployed (FIX-02/FIX-03 are frontend-aligns-to-backend).
- Rollback: revert per fix; each fix is independent and touches disjoint files except that FIX-02 spans backend router + frontend hook.

## Open Questions

- **Displaying a real agent hostname** is out of scope for this change. If the product wants to show a hostname distinct from `agent_id`, it requires (a) the agent to report `hostname` in registration or heartbeat and (b) a new `Agent.hostname` column — a new assumption that must be closed in the "Decisiones de implementación — Abril 2026" appendix before any code. Flagged, not assumed.
