## Context

The FIM agent runs as a single `asyncio` process (`agent/__main__.py:main`) that launches three coroutines on one event loop via `asyncio.gather`: `publisher.run`, `heartbeat.run`, and `detector.start`. There is no HTTP server (D8, RN-108); all backend↔agent communication flows through Valkey Streams (`events`, `commands`). Because everything shares one event loop, concurrency is **cooperative** — tasks interleave only at `await` points, never preemptively.

The April 2026 audit (`docs/audit_bugs.md`, C1–C5) found five critical defects in already-shipped agent code (C05, C13, C14). This change is pure remediation: it enforces rules that are already closed in the canonical appendices (RN-79 HMAC verification, RN-75 version monotonicity, RN-83 journal rehydration, RN-01/RN-93 detection robustness). No new assumptions are introduced, so no implementation-appendix entry is required.

Current verified facts from the code:
- `agent/__main__.py:135` calls `publisher.register_callbacks(...)` but never `publisher.register_command_handlers(...)`. The dispatch guard in `_handle_command_async` (`self._baseline_engine is not None and self._agent_state is not None`) is therefore always false → destructive commands log `publisher.command_handler_not_registered` and do nothing.
- `agent/publisher.py:182-216` parses JSON and acts on `event_ack` / `update_config` / `rule_sync` with NO call to `verify_payload`. Only the C13/C14 branch reaches `commands.dispatch`, which does verify.
- `agent/streams.py`: `verify_payload(secret, payload)` is constant-time (`hmac.compare_digest`) and `canonical_json` already strips the `signature` field, so it is safe to call on the full received payload.
- `agent/publisher.py:202-206` has a direct `elif cmd_type == "update_config"` branch that runs BEFORE the C13/C14 block, so even with C1 fixed, `update_config` would never reach `handle_update_config`.
- `agent/detector.py`: `_pending: dict[path → event_id]`; `on_ack` does an O(N) reverse scan. `_hash_file` (sync) returns `None` on any `FileNotFoundError`. `_process_event` is already `async`.

## Goals / Non-Goals

**Goals:**
- Restore destructive command dispatch to functional (C1).
- Enforce RN-79: every inbound command is HMAC-verified at one chokepoint, future-proof for new command types (C2).
- Enforce RN-75: `update_config` only via the versioned handler (C3).
- Make ack lookup O(1) and structurally corruption-free (C4).
- Stop false `file_absent` from atomic-write editor patterns, with zero cost on the happy path (C5).
- Add regression tests for the three previously-uncovered failure modes (invalid HMAC, concurrent pending mutation, fanotify/hash race).

**Non-Goals:**
- No refactor of the publisher/detector dependency-injection wiring beyond adding the missing call (C1 is a one-call fix; the registration method already exists).
- No change to the wire protocol, command schema, or `shared_secret` provisioning.
- No fix for the other audit findings (H*, M*, C6–C10) — those belong to separate changes.
- No threading changes; the single-event-loop model is kept (D8).

## Decisions

### D-C1: Add the missing `register_command_handlers` call (no DI refactor)
The registration method `publisher.register_command_handlers(baseline_engine, state, journal, quarantine_dir, detector)` already exists and is correct; it is simply never invoked. We add the call in `agent/__main__.py` inside the `_LINUX` block, after the detector is constructed and right next to the existing `register_callbacks` call (the `engine`, `state`, `journal`, `quarantine_dir`, and `detector` instances are all already in scope there).

*Alternative considered*: refactor to constructor injection so the dependency can't be forgotten. Rejected for this change — it widens the blast radius beyond a critical-fix, and the existing pattern (`register_callbacks` + `register_command_handlers`) is intentional and symmetric. A constructor-injection refactor can be its own future change.

### D-C2: Single `_verify_and_parse` chokepoint, verify-before-filter
Extract `_verify_and_parse(self, msg_data: dict) -> dict | None` as the ONE place where raw stream messages become trusted payloads. It:
1. reads `msg_data.get("data", "{}")` and `json.loads` it (return `None` on `JSONDecodeError`/`TypeError`);
2. calls `verify_payload(self._shared_secret, payload)` — return `None` if false;
3. returns the parsed, verified payload.

`_ack_listener` calls `_verify_and_parse` and skips the message when it returns `None`; only verified payloads reach `_handle_command_async`, which no longer parses JSON itself. `target_agent_id` filtering stays in `_handle_command_async` and therefore runs **after** signature verification — verify first, then route. Because verification lives at the entry point and not per-branch, any future command type is covered automatically (this is the "escalable" requirement, not a per-command patch).

*Why this order*: an unsigned message must be discarded before we inspect any of its fields, including `target_agent_id`. Verifying first closes the RN-79 gap completely.

*Alternative considered*: call `verify_payload` inside each existing branch. Rejected — it repeats the check, is easy to forget for the next command type, and leaves a window where unsigned fields are read. The chokepoint is the scalable design the task explicitly asked for.

*Note on the dead sync `_handle_command` wrapper* (`publisher.py:243-278`): it duplicates the same unverified branches. It is unused (the live path is `_handle_command_async`). It will be removed as part of C2 so no unverified code path survives in the file.

### D-C3: Delete the duplicated direct `update_config` branch (depends on C1)
Remove the `elif cmd_type == "update_config": ...` branch in `_handle_command_async` (currently lines 202-206) so `update_config` falls through to the C13/C14 set and reaches `commands.dispatch` → `handle_update_config`, which checks `ruleset_version` and persists. This only works once C1 has registered the handlers; otherwise `update_config` would hit the `command_handler_not_registered` warning. Hence the ordering: C1 then C3.

*Alternative considered*: keep the direct branch but add a version check inline. Rejected — it would duplicate the versioning logic that already lives correctly in `handle_update_config`, violating single-source-of-truth and re-creating the divergence the audit flagged.

### D-C4: Reverse index `_event_to_path`, no extra lock
Add `self._event_to_path: dict[str, str]` (event_id → path) maintained in lockstep with `self._pending` (path → event_id). On recording a new event in `_process_event`: if the path already had a pending event, drop that stale `event_id` from the reverse index, then set both maps to the new event. On `on_ack(event_id)`: `path = self._event_to_path.pop(event_id, None)`; if found and `self._pending.get(path) == event_id`, delete the forward entry too. This makes ack O(1) and removes the O(N) `for p, eid in self._pending.items()` scan that risked mutate-during-iterate.

**No `asyncio.Lock` is added.** The audit suggested a lock "or" guaranteeing same-loop execution. The agent already guarantees same-loop execution: `on_ack` is registered as `on_ack=detector.on_ack` and invoked from the publisher's `_ack_listener`, which runs on the same single event loop as `detector._process_event` (both are tasks in the one `asyncio.gather`). The map mutations are synchronous (no `await` between reads and writes), so cooperative scheduling already serializes them — a lock would add contention with zero correctness benefit. This relies on the D8 single-loop model and is documented here so a future maintainer who introduces threads knows the invariant they must preserve.

*Alternative considered*: `asyncio.Lock` around both maps. Rejected as unnecessary under the single-loop invariant and because the mutation regions contain no `await`. *Alternative considered*: `loop.call_soon_threadsafe`. Rejected — there is no foreign thread calling `on_ack` today (the fanotify reader thread only feeds `_raw_queue` via `call_soon_threadsafe`; it never touches `_pending`).

### D-C5: `_hash_file_async` with bounded exponential backoff
Convert `_hash_file(path)` into `async def _hash_file_async(path, retries=3, base_delay=0.05)`:
- attempt to hash; on success return the digest immediately (happy path: zero sleeps, zero added latency);
- on `FileNotFoundError`, if attempts remain, `await asyncio.sleep(base_delay * 2**attempt)` and retry;
- after `retries` exhausted return `None`.

Backoff schedule: 50 ms, 100 ms → total ≤150 ms worst case across 3 attempts. `_process_event` (already async) awaits it. Only a persistent `None` produces `file_absent` + `mark_absent`. Using `asyncio.sleep` (not `time.sleep`) keeps the event loop free during the brief wait.

*Alternative considered*: synchronous `time.sleep` retries. Rejected — it would block the event loop, stalling the publisher and heartbeat for up to 150 ms per racing event. *Alternative considered*: stat-then-hash to detect existence. Rejected — TOCTOU; the file can vanish between `stat` and `open`. Retrying the actual `open` is the honest check.

### Implementation ordering
C1 → C2 → C3 (C3 depends on C1 wiring + C2 chokepoint) → C4 and C5 (independent of each other and of the command path). Tests land with their respective fix.

## Risks / Trade-offs

- **[C2 verify-first could reject a legitimately-unsigned internal message]** → Audit confirms RN-79/C7 applies to *all* commands toward the agent with no exceptions; `event_ack`, `update_config`, `rule_sync` are all signed by the backend. Mitigation: the regression test asserts a correctly-signed `event_ack` still acks, so we don't over-reject.
- **[C2 removing the dead `_handle_command` wrapper could break a hidden caller]** → Mitigation: grep confirms the live path is `_handle_command_async`; remove the wrapper only after verifying no test or module imports it. If a test references it, update the test to the async path.
- **[C3 ordering hazard if shipped before C1]** → Mitigation: tasks enforce C1 before C3; a `restore_file`/`update_config` integration test exercises the full dispatch after both land.
- **[C4 no-lock assumption breaks if someone adds a thread that calls `on_ack`]** → Mitigation: the single-loop invariant is documented in code comment and here; the reverse-index updates are written to be atomic within a no-`await` region so even a future `call_soon_threadsafe` hop stays consistent.
- **[C5 retry window hides a real fast delete-recreate]** → Accepted trade-off: a file deleted and recreated within 150 ms is treated as a modification, which is the safer outcome (preserving baseline) than destroying it. The window is bounded and small relative to fanotify event cadence.
- **[C5 latency added to genuine deletions]** → ≤150 ms only for truly-absent files; negligible for FIM cadence and never paid on the happy path.

## Migration Plan

No data migration, no schema change, no protocol change. Pure code fix deployed by shipping the updated agent (systemd unit restart). Rollback = redeploy the previous agent build. The fixes are additive/corrective and do not alter persisted baseline, journal, or queue formats, so a rollback after running the fixed agent leaves on-disk state compatible.

## Open Questions

None. All five fixes enforce already-closed rules; the audit prescribes the approach and the code has been read to confirm feasibility. The only judgment call (no lock for C4) is resolved above under the documented single-loop invariant.
