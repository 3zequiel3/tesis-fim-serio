## Why

A dual-judge audit on 2026-07-02 (6 subagents, 2 judges per component) surfaced 4 cross-process **contract mismatches** where one side emits a payload the other side does not read. Each was verified by hand against the current code. They are invisible to the existing unit tests because those tests build payloads by hand with the correct keys and never cross the real process boundary (`to_event_data()`, the real `EventSource`). Two of them are CRITICAL: every real event persists with an empty `hash_detected`, and the only real-time push channel in the system (alert SSE) is silently dead. None of the four requires a new design decision — each enforces a contract or lexicon that was already closed.

## What Changes

This change corrects implementation defects only. It introduces no new feature and no new assumption.

- **FIX-01 (CRITICAL)** — `agent/detector.py`: `DetectedChange.to_event_data()` is a raw `dataclasses.asdict()` that emits `current_hash`/`previous_hash`, but the backend reads `event_data.get("hash_detected", "")` (`events/service.py:172`). The keys do not match, so **every real event persists with `hash_detected == ""`** and the frontend renders it as "archivo ausente". Align the AGENT payload to the canonical lexicon the backend and frontend already use — `hash_detected` (newly detected hash) / `hash_expected` (baseline hash) per RN-71. Do NOT change the backend.
- **FIX-02 (CRITICAL)** — `backend/app/modules/alerts/router.py:150,174`: the SSE generator yields `{"id","data"}` without the `event` key, so the browser assigns the default type `message`, but the frontend listens with `es.addEventListener('alert', ...)` (`useAlertsSSE.ts:21`) → the listener never fires and the system's only push channel is dead. Emit `event: "alert"` on every real alert yield (contract C16). Complementary: `useAlertsSSE` is only mounted in `/events` (`Events.tsx:32`); mount it in the global layout so alerts arrive app-wide.
- **FIX-03 (HIGH)** — Agent contract front↔backend: `AgentResponse` (`agents/models.py:65+`) exposes `agent_id`/`last_heartbeat`/`ruleset_version_applied` and has **no `hostname`, `id`, or `last_seen`**, but the frontend (`api/agents.ts:8-13`) types `id`/`hostname`/`last_seen` → `key={agent.id}` is `undefined` for every row (React key collision), "Visto hace NaNd", and config/rescan hit `/agents/undefined` → 404. Align the frontend to the real backend schema (`agent_id`/`last_heartbeat`). `hostname` does not exist anywhere in the backend or the agent payloads; the frontend stops referencing it and displays `agent_id` as the identity (the backend already does this in `core/health.py:97`). Additionally, `triggerRescan` (`api/agents.ts:49-53`) sends `force` as a query param with a `null` body, but the backend requires an `AgentRescanRequest` JSON body → 422; send the body.
- **FIX-04 (MEDIUM)** — `backend/app/modules/actions/service.py:337,373`: `approve_bulk`/`reject_bulk` catch `except Exception` per item while reusing a single `Session` across the loop **without `session.rollback()`** → on Postgres an error on item N leaves the transaction aborted and every item N+1 fails in cascade as false `internal_error`. Roll back after each failed item (the pattern already used in `users/router.py:130`) so each item is isolated.

## Capabilities

### New Capabilities
<!-- None — this is a remediation change. -->

### Modified Capabilities
<!-- None. No requirement-level behavior changes. -->

No requirement-level behavior changes. Every fix makes the code honor a contract already specified in the canonical docs (RN-71 canonical event lexicon, RN-17/D2 event hash, C16 SSE contract) and in the existing specs (`backend-event-ingestion`, `sse-alerts`, `backend-agents`, `frontend-events`, `frontend-rules-agents-dashboard`, `backend-approve-reject`). No delta spec files are required; existing specs remain the contract and this change corrects the code to meet them. Precedent for a cross-layer remediation change without delta specs: C28 (`agent-audit-fixes`), C33 (`backend-test-harness`).

## Impact

- **Affected code**:
  - `agent/detector.py` — FIX-01 (`DetectedChange` field names + `to_event_data()` mapping to `hash_detected`/`hash_expected`)
  - `agent/tests/` — FIX-01 integration test exercising the real `to_event_data()` against the backend consumer contract (none exists today)
  - `backend/app/modules/alerts/router.py` — FIX-02 (`event: "alert"` on real alert yields)
  - `frontend/src/hooks/useAlertsSSE.ts` + global layout mount point — FIX-02 (app-wide mount)
  - `frontend/src/api/agents.ts` — FIX-03 (`Agent` type aligned to `agent_id`/`last_heartbeat`; `triggerRescan` JSON body)
  - `frontend/src/pages/*` + components consuming `agent.id`/`agent.hostname`/`agent.last_seen` — FIX-03 (rename to `agent_id`/`last_heartbeat`, drop `hostname`)
  - `backend/app/modules/actions/service.py` — FIX-04 (`session.rollback()` per failed item in both bulk paths)
  - `backend/tests/` — FIX-04 regression test with a failing item mid-batch
- **Dependencies**: none added.
- **Rules enforced**: RN-71 (canonical event lexicon), RN-17 / D2 (event hash).
- **Decisions applied**: none new.
- **Roadmap**: this is change C35 (`e2e-contract-fixes`), depends on C34 (`backend-residual-fixes`) per CHANGES.md. The other 2 findings from the same audit (#3 event_ack loop, #6 fanotify over-collection) require closing decisions in the appendices and are handled separately.
