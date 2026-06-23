## Context

Five critical backend bugs (C6–C10, `docs/audit_bugs.md`) were found by audit on already-shipped code (changes 02, 04, 13). They span four backend modules (`core`, `events`, `rules`, `pki`) plus the app entrypoint, and cross three concerns: authentication, stream-consumer reliability, and async lifecycle management. Two of them (C6, C9) carry deploy-time migration consequences, which is why this remediation gets a design doc rather than going straight to tasks.

Relevant constraints:
- **Single-instance backend (RN-76)**: no horizontal coordination needed; idempotent startup is acceptable.
- **D3 — schema via `SQLModel.metadata.create_all()` in the FastAPI lifespan; no Alembic.** Fresh databases pick up schema changes from the model; already-running databases need a hand-applied SQL script. The canonical doc (`arquitectura_stack.md`) explicitly anticipates "versioned SQL migrations" without an ORM migration tool — that is exactly the C9 approach.
- **Lifespan task pattern (existing)**: `main.py` already manages `consumer_task`, `heartbeat_task`, `retention_task_handle` via `asyncio.create_task(...)` at startup and `task.cancel()` + `asyncio.gather(..., return_exceptions=True)` at shutdown. C10 must join this pattern, not invent a new one.
- **Dual-key JWT (existing)**: `decode_token` already tries CURRENT then PREVIOUS secret. The C6 type check happens *after* decode, so it is orthogonal to key rotation.

## Goals / Non-Goals

**Goals:**
- Close the refresh-as-access TTL bypass at a single control point that covers every protected endpoint (C6).
- Make `must_change_password` actually gate business-data reads on events and rules (C7).
- Guarantee that an integrity event is never silently dropped: transient DB failures retry; only genuinely-processed or genuinely-invalid messages are acked (C8).
- Make chain compaction FK-safe so `ingest_event` cannot crash with `IntegrityError` on long histories (C9).
- Make the mTLS listener on 8443 start reliably as a first-class lifespan task (C10).
- Ship a once-off, idempotent SQL migration for already-running databases (C9).

**Non-Goals:**
- No Alembic, no ORM migration framework (D3). The SQL script is hand-applied, not auto-run.
- No refresh-token rotation/blacklist redesign — C6 only adds a type guard. Refresh-token mechanics are unchanged.
- No graceful-session-migration on deploy — invalidating active sessions (C6) is accepted, not mitigated.
- No fix for the High/Medium audit findings (H1–H8, M1–M9) — those are out of scope for this change.
- No new endpoints, no API shape changes, no new dependencies.

## Decisions

### D-C6 — Add a `type` claim and reject non-access tokens in `get_current_user`

`create_refresh_token` already sets `"type": "refresh"`; `create_access_token` sets no type. The fix is symmetric: stamp `"type": "access"` on the access token, then in `get_current_user`, immediately after `decode_token`, reject any token whose `payload.get("type") != "access"` with `401 token_type_invalid`.

- **Why a single check in `get_current_user`**: every protected dependency (`require_full_access`, `require_admin`) chains through `get_current_user`, so one guard covers the entire surface. No per-router change needed for C6.
- **Why check `== "access"` (allow-list) and not `== "refresh"` (deny-list)**: an allow-list rejects any unexpected/missing type, so future token kinds cannot accidentally pass. The audit's suggested `if type == "refresh"` deny-list is narrower; the allow-list is the more defensive of the two and is the chosen form.
- **Alternative considered — validate at `decode_token`**: rejected. `decode_token` is also used by `blacklist`/logout flows that operate on refresh tokens; embedding an access-only rule there would couple unrelated call sites.

### D-C7 — Swap dependency to `require_full_access` on the four read endpoints

`GET /events`, `GET /events/{id}`, `GET /rules`, `GET /rules/{id}` currently depend on `get_current_user`, which admits a `scope=password_change_only` token. Switch them to `require_full_access` (which raises `403 password_change_required` for that scope). Audit confirmed actions/agents/alerts already use `require_admin` correctly, so only these four endpoints change.

- **Convention established**: `get_current_user` is reserved for own-user endpoints (e.g. change-password, /me); any read of business data requires at minimum `require_full_access`. This convention is recorded in the spec so future endpoints inherit it.
- **Alternative considered — middleware-level scope enforcement**: rejected for this change. It would be a broader cross-cutting refactor (D7 territory) and risks over-gating own-user endpoints. Per-dependency is precise and minimal.

### D-C8 — Explicit result taxonomy governs `xack`

Replace the unconditional `xack` with a classification of `_handle_message` outcomes, acking only when the message is truly done:

| Outcome | Trigger | Action |
| --- | --- | --- |
| Success | `_ingest` returns an `Event` | `xack` + `event_ack` to agent + fire notification |
| Dedup / legitimate skip | `event_exists` (re-delivery) or `mark_superseded` race returns `None` | `xack` (already processed by another consumer) |
| Data error | `InvalidTransitionError` | `xack` + audit log (invalid, not retryable) |
| Transient DB error | `SQLAlchemyError` | **no `xack`**, log with `exc_info=True`, leave in PEL for consumer-group retry |

- **Why distinguish "skip" from "transient error"**: the current code conflates `_ingest` returning `None` (which today means either a legitimate race or a swallowed failure) into one unconditional ack. The taxonomy makes the transient-DB path the only one that withholds the ack, so genuinely lost work is retried while genuine no-ops are not endlessly redelivered.
- **Why PEL retry rather than manual requeue**: the consumer group's Pending Entries List is the native Redis/Valkey retry mechanism. Not acking is sufficient; a future claimer (or restart) re-reads the pending entry. No custom dead-letter logic is introduced here.
- **Where `InvalidTransitionError` vs `SQLAlchemyError` are separated**: `_ingest` must surface these distinctly to `_handle_message`. Today `_ingest` catches `InvalidTransitionError` and returns `None`; the design requires it to let `SQLAlchemyError` propagate (or return a typed result) so the caller can choose not to ack.
- **Alternative considered — always ack + manual reinsert on failure**: rejected. Reinserting rewrites stream IDs and ordering, and duplicates the at-least-once guarantee the consumer group already provides.

### D-C9 — `ondelete="SET NULL"` + delete-children-first + idempotent SQL script (no Alembic)

Three coordinated edits:
1. `models.py`: the self-referential FK `parent_event_id` gains `ondelete="SET NULL"` (via `sa_column`/`ForeignKey` arg as the model defines it). New databases get this from `create_all`.
2. `service.py`: `compact_chain` changes `order_by(Event.created_at.asc())` to `.desc()`, deleting newest-first so a child is removed before (or together with the null-out of) its parent reference.
3. `db/migrations/001_fix_parent_event_id_ondelete.sql`: an idempotent script that drops the existing FK constraint and recreates it with `ON DELETE SET NULL`, guarded so re-running is safe (check `information_schema` / `IF EXISTS`). For already-running databases only.

- **Why both `ondelete=SET NULL` and `DESC` ordering**: belt-and-suspenders. `SET NULL` prevents the `IntegrityError` even if ordering is wrong; `DESC` ordering keeps the chain semantically clean (a surviving child never points at a deleted parent — it gets nulled). Either alone would stop the crash; together they keep data consistent.
- **Why a SQL script and not Alembic (D3)**: D3 closed this — schema is `create_all` + hand-applied versioned SQL when needed. Introducing Alembic is explicitly out of scope and would itself require closing a new decision. The `001_` prefix establishes the `db/migrations/` numbering convention for future scripts.
- **Alternative considered — recreate the table**: rejected. Destructive, loses event history, unnecessary for an FK-constraint change.

### D-C10 — mTLS server as a managed lifespan task on the main loop

`start_mtls_server` stops spawning a `threading.Thread` that calls `asyncio.run(server.serve())`. The root cause is that `uvicorn.Server.serve()` calls `install_signal_handlers()` → `signal.signal()`, which raises `ValueError` off the main thread. Fix:
1. `pki.py`: `start_mtls_server` builds the `uvicorn.Config`/`uvicorn.Server` with `config.install_signal_handlers = False` and **returns the configured `Server`** (or `None` when certs are absent) instead of starting a thread.
2. `main.py`: in the lifespan, `mtls_task = asyncio.create_task(mtls_server.serve())` after the other tasks; on shutdown, `mtls_task.cancel()` and include it in the existing `asyncio.gather(..., return_exceptions=True)`.

- **Why the main loop and not a fixed thread**: the whole app already runs one asyncio loop with a managed task set. Co-locating the mTLS server means signals work (main thread), shutdown is coordinated, and the failure is no longer swallowed silently. It mirrors `consumer_task`/`heartbeat_task` exactly.
- **Why keep `lifespan="off"` on the mTLS uvicorn config**: the app lifespan must not re-run inside the secondary server; the primary uvicorn instance owns lifespan. This is preserved from the current code.
- **Alternative considered — `signal.signal` only in main thread + keep the thread**: rejected. Keeping a second thread/loop for one server adds a parallel lifecycle to manage for no benefit when the main loop is right there.

## Risks / Trade-offs

- [C6 invalidates all active sessions on deploy] → Accepted, not mitigated. Single-instance, thesis/dev context; users re-login. Documented in proposal and release notes.
- [C8 transient-error path could redeliver a poison message indefinitely if a "transient" error is actually permanent] → Mitigation: only `SQLAlchemyError` (DB-layer) withholds ack; `InvalidTransitionError` (data) acks. A truly stuck DB is an operational alert, not a silent loss — the PEL growing is observable. No max-retry/dead-letter in this change (noted as a follow-up).
- [C9 SQL script not run on an existing DB → the crash persists there] → Mitigation: script is idempotent and part of the deploy checklist; fresh databases are correct automatically via `create_all`. Migration Plan below makes the manual step explicit.
- [C9 `SET NULL` orphans a child's `parent_event_id` rather than cascading] → Intended: a compacted (deleted) parent should leave a chain head, not delete the live child. `SET NULL` is the correct semantic for chain compaction.
- [C10 mTLS `serve()` task raising at startup could now surface differently than the old swallowed log] → Mitigation: this is the goal — failures become visible. The task is gathered with `return_exceptions=True` so a shutdown-time cancel is clean, but a startup bind failure will now log loudly instead of silently.

## Migration Plan

**Deploy (fresh database):** no manual step. `create_all` applies the corrected `ondelete`; the code changes take effect on restart. Active sessions are invalidated by C6 — users re-login.

**Deploy (existing database):**
1. Apply code changes (restart backend).
2. Run `db/migrations/001_fix_parent_event_id_ondelete.sql` once against the live database (idempotent — safe to re-run).
3. Verify port 8443 is listening and an agent can complete an mTLS handshake (C10).

**Rollback:** revert the backend code (git). The C9 SQL change (`SET NULL` on the FK) is backward-compatible with the previous code and need not be rolled back; a stricter constraint could be re-applied later if desired. No data migration to undo.

## Open Questions

- None blocking. Max-retry / dead-letter handling for the C8 transient-error path is intentionally deferred — if PEL growth becomes an operational concern, it should be closed as its own decision before adding retry caps. Recorded here so it is not lost.
