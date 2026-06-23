## Why

A multi-agent audit of the FIM backend (`docs/audit_bugs.md`, 2026-06-23) surfaced 5 critical bugs (C6–C10) that break core platform guarantees: a refresh token can be used as an access token (TTL bypass), `must_change_password` is bypassed on data endpoints, integrity events are silently lost under load, chain compaction crashes ingestion with an `IntegrityError`, and the mTLS server on port 8443 never starts — leaving every agent unable to connect. These are merge-blocking security and reliability defects on already-shipped code (changes 02, 04, 13). This is a remediation change, not a new feature: each fix enforces a rule or decision that is already closed.

## What Changes

- **C6 — Token-type enforcement (security)**: `create_access_token` stamps `"type": "access"`; `get_current_user` rejects any token whose `type` is not `access` immediately after `decode_token`. One control point covers every protected endpoint. **BREAKING**: invalidates active sessions on deploy (acceptable — single-instance, RN-76, thesis/dev context).
- **C7 — Scope-gate on business-data reads (security)**: `GET /events`, `GET /events/{id}`, `GET /rules`, `GET /rules/{id}` switch from `Depends(get_current_user)` to `Depends(require_full_access)`. Establishes the convention: `get_current_user` only for own-user endpoints; `require_full_access` is the minimum for any business-data read.
- **C8 — Result taxonomy in the event consumer (reliability)**: `xack` becomes conditional on an explicit outcome classification — success and legitimate skips and data errors ack; transient DB errors do **not** ack and stay in the PEL for automatic consumer-group retry. Removes silent loss of integrity events.
- **C9 — FK-safe chain compaction (reliability)**: `parent_event_id` FK gets `ondelete="SET NULL"`; `compact_chain` deletes children-before-parents via `order_by … DESC`; a versioned idempotent SQL script ships for already-running environments. Honors D3 (no Alembic).
- **C10 — mTLS server on the main event loop (reliability)**: the secondary thread is removed; `start_mtls_server` returns a configured `uvicorn.Server` with `install_signal_handlers=False`, and the lifespan drives it with `asyncio.create_task(...)` + cancel-on-shutdown — the same pattern as `consumer_task`/`heartbeat_task`/`retention_task_handle`. Port 8443 starts reliably.

## Capabilities

### New Capabilities
<!-- None. This is a remediation change against existing capabilities. -->

### Modified Capabilities
- `backend-auth`: access tokens carry an explicit `type` claim; refresh-typed (or otherwise non-access) tokens are rejected when presented as Bearer credentials (C6).
- `backend-events-api`: events read endpoints require full access (scope-gated), and chain compaction no longer violates the `parent_event_id` foreign key (C7, C9).
- `backend-rules`: rules read endpoints require full access (scope-gated) (C7).
- `backend-event-consumer`: stream-message acknowledgement is governed by an explicit result taxonomy; transient DB failures are retried instead of silently dropped (C8).
- `backend-pki`: the mTLS listener on 8443 runs on the main event loop as a managed lifespan task and starts reliably (C10).

## Impact

- **Code**:
  - `backend/app/core/security.py` — C6 (`type: access` claim)
  - `backend/app/core/deps.py` — C6 (token-type check in `get_current_user`)
  - `backend/app/modules/events/router.py` — C7 (`require_full_access` on 2 endpoints)
  - `backend/app/modules/rules/router.py` — C7 (`require_full_access` on 2 endpoints)
  - `backend/app/modules/events/consumer.py` — C8 (conditional ack / result taxonomy)
  - `backend/app/modules/events/models.py` — C9 (`ondelete="SET NULL"`)
  - `backend/app/modules/events/service.py` — C9 (`order_by DESC` in `compact_chain`)
  - `backend/app/core/pki.py` — C10 (return server, no thread, no signal handlers)
  - `backend/app/main.py` — C10 (drive mTLS server as lifespan task)
  - `db/migrations/001_fix_parent_event_id_ondelete.sql` — C9 (new file, idempotent migration for live environments)
- **APIs**: no contract shape changes. Behavior changes: refresh tokens stop working as access tokens (401 `token_type_invalid`); `must_change_password` users get 403 `password_change_required` on events/rules reads.
- **Operational**: active sessions are invalidated on deploy (C6). Existing databases need the C9 SQL script run once; fresh databases get the corrected `ondelete` from `create_all` automatically (D3).
- **Rules/Decisions**: enforces RN-76 (single-instance), RN-79 (signed-command integrity context), and is governed by D3 (schema via `create_all`, no Alembic), D7 (cross-cutting), D8 (no HTTP on agent — backend ↔ agent over mTLS/Streams).
- **Dependencies**: builds on already-shipped changes 02 (auth/lifespan), 04 (access control), 13 (event consumer/mTLS). No new third-party dependencies.
