## 1. C6 — Token-type enforcement

- [x] 1.1 In `backend/app/core/security.py`, add `"type": "access"` to the payload built by `create_access_token`
- [x] 1.2 In `backend/app/core/deps.py`, in `get_current_user`, immediately after `decode_token(token)` reject any token whose `payload.get("type") != "access"` with `HTTPException(401, detail="token_type_invalid")`
- [x] 1.3 Add regression tests: a refresh token presented as Bearer → 401 `token_type_invalid`; a token with no `type` claim → 401; a valid access token (`type=access`) → passes; assert `create_access_token` output decodes with `type == "access"`

## 2. C7 — Scope-gate on business-data reads

- [x] 2.1 In `backend/app/modules/events/router.py`, change the dependency of `GET /events` and `GET /events/{id}` from `Depends(get_current_user)` to `Depends(require_full_access)`
- [x] 2.2 In `backend/app/modules/rules/router.py`, change the dependency of `GET /rules` and `GET /rules/{id}` from `Depends(get_current_user)` to `Depends(require_full_access)`
- [x] 2.3 Add regression tests: a `scope=password_change_only` token → 403 `password_change_required` on all four endpoints; a full-access token → 200; verify actions/agents/alerts endpoints are unchanged (already `require_admin`)

## 3. C8 — Result taxonomy in the event consumer

- [x] 3.1 In `backend/app/modules/events/consumer.py`, make `_ingest` (or its caller) surface outcomes distinctly: success returns the `Event`; `InvalidTransitionError` is a non-retryable data error; `SQLAlchemyError` propagates as a transient DB error (do not swallow it as `None`)
- [x] 3.2 In `_handle_message`, replace the unconditional `xack` with conditional acking per the taxonomy: success → xack + event_ack + notification; legitimate skip (dedup / supersede race) → xack; `InvalidTransitionError` → xack + audit log; `SQLAlchemyError` → NO xack, log with `exc_info=True`, leave in PEL
- [x] 3.3 Add regression tests: success path acks and publishes event_ack; dedup/supersede-race path acks without re-insert; `InvalidTransitionError` acks + audits; `SQLAlchemyError` does NOT ack and the message stays pending (PEL)

## 4. C9 — FK-safe chain compaction (no Alembic)

- [x] 4.1 In `backend/app/modules/events/models.py`, add `ondelete="SET NULL"` to the self-referential `parent_event_id` foreign key
- [x] 4.2 In `backend/app/modules/events/service.py`, change `compact_chain` ordering from `order_by(Event.created_at.asc())` to `.desc()` (delete newest-first so children are removed before parents)
- [x] 4.3 Create `db/migrations/001_fix_parent_event_id_ondelete.sql`: idempotent script that drops the existing `parent_event_id` FK constraint and recreates it with `ON DELETE SET NULL`, guarded so re-running is safe (e.g. `information_schema` check / `DROP CONSTRAINT IF EXISTS`)
- [x] 4.4 Add regression tests: deleting a parent event nulls the child's `parent_event_id` (no `IntegrityError`); compacting a long chain where deleted events are parents completes without `IntegrityError` and `ingest_event` keeps the new event

## 5. C10 — mTLS server on the main event loop

- [x] 5.1 In `backend/app/core/pki.py`, rewrite `start_mtls_server` to build the `uvicorn.Config`/`uvicorn.Server` with `config.install_signal_handlers = False`, keep `lifespan="off"`, and RETURN the configured `Server` (or `None` when certs are absent) — remove the `threading.Thread` and the inner `asyncio.run`
- [x] 5.2 In `backend/app/main.py`, in the lifespan, capture `mtls_server = start_mtls_server(...)`, start it with `mtls_task = asyncio.create_task(mtls_server.serve())` when not `None`, and on shutdown `cancel()` it and add it to the existing `asyncio.gather(..., return_exceptions=True)`
- [x] 5.3 Add regression tests: `start_mtls_server` returns a `Server` with `install_signal_handlers == False` and does not spawn a thread; returns `None` when cert paths are missing; (integration) port 8443 listens after startup and an mTLS handshake reaches a FastAPI handler

## 6. Verification

- [x] 6.1 Run the full backend test suite; all new regression tests for C6–C10 pass and no existing tests regress
- [x] 6.2 Run `openspec validate "backend-critical-fixes" --strict` and confirm it passes
- [x] 6.3 Manual smoke per design Migration Plan: fresh DB starts clean; on an existing DB the `001_*.sql` script applies idempotently; port 8443 accepts an mTLS connection
