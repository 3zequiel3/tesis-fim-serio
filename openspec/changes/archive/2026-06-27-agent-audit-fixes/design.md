## Context

The FIM agent (`agent/`) runs as a single-loop asyncio process under systemd (`Restart=on-failure`), as root with `CAP_SYS_ADMIN`, with no HTTP server (RN-108, D8). It talks to the backend exclusively over Valkey Streams (mTLS) and protects file integrity through three coordinated subsystems:

- **Detector** (`detector.py`): fanotify event loop that classifies events and drives the decision engine.
- **Decision engine** (`decision.py` + `journal.py`): evaluates rules, performs `auto_restore` / `quarantine`, and journals each action transactionally (write `pending` → execute → `commit_fn` on successful publish).
- **Baseline engine** (`baseline.py`): the encrypted store of known-good content (`content_b64`, `hash`) plus audit `snapshots`. `select_restorable_content(entry)` chooses what `_auto_restore` writes back to disk.

A second-pass audit found 14 defects. The two structural classes are:

1. **Baseline-ordering defects (D14 / RN-112)** — the detector mutated the baseline *before* the decision engine evaluated the event. This destroys restore material on delete (BUG-01), corrupts state on quarantine (BUG-02), and — worst — lets `restore_file` serve the attacker's content because the active baseline was overwritten with the modified bytes (BUG-03). The invariant D14 restores: *the active baseline always reflects the last approved / known-good state; non-restore modifications only append an audit snapshot.*

2. **Crash-loop and security-boundary defects** — unguarded I/O and publish calls that turn a transient failure into a systemd crash loop (BUG-04, BUG-11, BUG-13, BUG-14), a missing directory that fails every auto-quarantine (BUG-05), at-most-once command delivery from a misordered cursor persist (BUG-09), and three weakened trust boundaries: bootstrap MITM via `verify=False` (BUG-07 / D16), Valkey hostname spoofing (BUG-08 / D17), and a skipped cert↔key binding check on renewal (BUG-06).

Constraints that shape the fixes:
- Single event loop: `_process_event` and `on_ack` never interleave mid-mutation; no `asyncio.Lock` needed (existing invariant comment in `detector.py`).
- Decisions D14–D17 (RN-112–RN-115) are already closed in the canonical appendices (2026-06-26). No new assumptions are introduced.
- This is a remediation change: no new dependencies, no requirement-level spec changes, existing agent specs remain the contract.

## Goals / Non-Goals

**Goals:**
- Restore the D14 baseline invariant in all three detector branches so `auto_restore` always restores known-good content and never the attacker's bytes.
- Make every transient failure (Valkey down, disk full, corrupt `state.json`, missing quarantine dir) survivable rather than a crash loop, and make genuine core-coroutine crashes visible to systemd (exit 1).
- Close the three trust-boundary gaps (bootstrap CA pinning, Valkey hostname verification, cert↔key binding on renewal).
- Restore at-least-once command delivery (cursor persisted after dispatch) and bounded journal growth (delete on commit).
- Ship a focused regression test per bug.

**Non-Goals:**
- No new features, no protocol changes, no new config keys beyond honoring the existing `ca_cert_path`.
- No delta specs — requirement-level behavior is unchanged; this corrects implementation to meet existing contracts.
- No refactor of the baseline storage format or the decision-engine API surface.
- No retroactive cleanup of `failed` journal entries (D15 explicitly leaves that out of MVP).

## Decisions

### D-1: Reorder detector branches — evaluate first, mutate baseline after (D14 / RN-112)

The fix is purely about ordering and conditionality in `detector.py`. The `file_modified` branch (lines ~479–504) already follows the correct pattern; the bug is that `file_deleted` (line 366) and `file_created` (line 409) mutate the baseline *before* `evaluate_and_act`, and the `file_modified` non-restore else-branch (line 503) calls `write_entry` with the new content.

- `file_deleted` / `file_moved_from`: call `evaluate_and_act` first; call `mark_absent(path)` **only if** the action was not a successful `auto_restore`. On successful restore the file exists again, so `write_entry(path)` (re-record known-good) instead of `mark_absent`.
- `file_created` / `file_moved_to`: call `evaluate_and_act` first; call `write_entry(path)` **only if** the action was not a successful `quarantine`. On successful quarantine the file is gone, so `mark_absent(path)`.
- `file_modified` non-restore (alert_only / manual_review): call only `add_snapshot(path, new_hash, new_content)`. **Do not** call `write_entry`. The active `content_b64` / `hash` stay pinned to the known-good state, so `select_restorable_content` keeps returning known-good.

**Why this over alternatives:** moving the ordering decision into `decision.py` (have the engine own baseline mutation) was considered and rejected — it couples the engine to detector-specific baseline transitions (`create` vs `delete` vs `modify`) and breaks the existing single-responsibility split where the detector owns baseline lifecycle and the engine owns actions. Keeping the reorder in the detector is the minimal, local change and matches the already-correct `file_modified` restore branch.

**Note on `add_snapshot` signature:** the current non-restore else-branch calls `self._baseline.add_snapshot(path)` then `write_entry(path)`. D14 requires `add_snapshot` to capture the *new* hash and content for audit without touching the active entry. The implementer must confirm `baseline.add_snapshot` accepts `(path, new_hash, new_content)` (per D14 text "`add_snapshot` ya existe"); if the current signature is `add_snapshot(path)` and reads the file itself, that already captures new content — the load-bearing fix is simply *removing the `write_entry` call*. Verify the snapshot does not overwrite active `content_b64`.

### D-2: Make restart-path I/O and publish non-fatal; make real crashes fatal

Four independent guards, each converting an unhandled exception that aborts `asyncio.run()` into a logged-and-continue, plus one that does the opposite:

- **BUG-04** — wrap `await publisher.publish(payload)` inside `rehydrate()` in `try/except Exception`, log a warning, continue. The event is already durably journaled (`pending`) and queued on disk, so a Valkey outage at restart must not abort startup.
- **BUG-11** — in `load_state`, on `JSONDecodeError`/`ValueError`, rename `state.json` → `state.json.bak`, log a warning, and return `AgentState(state_path=path)` defaults instead of `sys.exit(1)`. Self-heals a corrupt file instead of looping.
- **BUG-13** — wrap the inline `save_state(self._agent_state)` in `_flush_commands` (line 224) in `try/except Exception` + warning, matching `_ack_listener`. A full disk must not prevent startup.
- **BUG-14** — in `main()`, capture the exception from `await asyncio.gather(...)` in the `try` block and record a non-zero exit code, so the `finally` cleanup runs but the process exits 1 on an unexpected core-coroutine crash. Normal shutdown (signal-driven drain) still exits 0.

**Why:** the system's safety property is *the agent keeps running and protecting files*. Transient I/O at the restart boundary should degrade gracefully; a genuine logic crash in a core coroutine should be loud so systemd restarts it. BUG-14 and BUG-11 pull in opposite directions deliberately — corrupt persistent state is recoverable (heal + continue), an unexpected coroutine exception is not (exit 1).

**Trade-off on BUG-14:** distinguishing "expected shutdown" from "unexpected crash". `gather` propagates the first exception; the signal path sets `stop_event` and the coroutines return normally, so `gather` returns without raising. Therefore: any exception escaping `gather` is by definition unexpected → exit 1. Cancellation during drain is handled by the existing `_drain_then_stop` path and does not raise out of `gather`.

### D-3: Order cursor persistence after dispatch (BUG-09)

In `_ack_listener`, move `self._agent_state.last_stream_command_id = msg_id` + `save_state(...)` (lines 267–269) to *after* `await self._handle_command_async(payload)`. A crash between persist and dispatch currently loses the command permanently (at-most-once). Persisting after dispatch yields at-least-once: a crash mid-dispatch re-reads the same command on restart. Command handlers must therefore be idempotent — they already are (event_ack is a lookup, `baseline_update`/`update_config` are guarded by monotonic `ruleset_version`, which BUG-12 completes).

**Why over a transactional cursor:** Valkey Streams + a JSON state file give no cross-resource transaction. At-least-once + idempotent handlers is the standard, correct choice and matches the journal's own "publish then commit" pattern. `_verify_and_parse` runs before dispatch and has no side effects, so messages that fail verification can still advance the cursor (they are not retried) — that path keeps persisting `msg_id` for `payload is None`.

### D-4: Pin trust anchors (D16, D17, BUG-06)

Three independent boundary fixes, no shared mechanism:

- **BUG-07 / D16** — `bootstrap.run`: validate `config.ca_cert_path` exists at the top of `run()` (`sys.exit(1)` with an explicit message if not), then pass `verify=str(config.ca_cert_path)` to `httpx.post`. The `ca_cert_pem` in the bootstrap *response* is the mTLS-signing CA and is unrelated to the HTTPS trust anchor — it does not replace `ca_cert_path`. This closes the circular-trust MITM where the CA that validates the response arrived inside the same unauthenticated response.
- **BUG-08 / D17** — `create_valkey_client`: add `ssl_check_hostname=True` to the `valkeys://` `Valkey.from_url(...)` kwargs. No opt-out flag. The server cert CN/SAN must match the host in `valkey_url`.
- **BUG-06** — `_cert_renewal_loop`: load the private key from `certs_dir/agent-key.pem` (`serialization.load_pem_private_key`) and pass it as `private_key=` to `verify_cert`, so the existing cert↔key binding check (`bootstrap.py:115`) runs. A renewed cert minted for a different key is rejected before it is persisted.

**Why:** these are the agent's three pre-established-trust seams. Each fix uses the trust material the operator/agent already controls (`ca_cert_path`, the Valkey URL hostname, the local private key) rather than trusting attacker-influenceable data from the wire.

### D-5: Bounded journal growth via delete-on-commit (D15 / RN-113)

`journal.delete(event_id)` already exists (`journal.py:101`) and `rehydrate()` already calls `mark_completed` + `delete`. The remaining gap is the *main* commit path: `evaluate_and_act`'s success `commit_fn` (line 75–76) calls only `mark_completed`. Add `self._journal.delete(event_id)` immediately after `mark_completed(event_id)` inside that `commit_fn`. Leave the `mark_failed` path untouched (D15: no auto-cleanup of `failed` entries in MVP).

**Why:** without delete-on-commit the journal grows one file per detected event forever, exhausting inodes/disk on an active host. Deleting only after `mark_completed` preserves the crash-recovery guarantee: a crash before commit leaves the entry `pending` for rehydration.

### D-6: Monotonic version guard on update_config (BUG-12)

`handle_update_config` (`commands.py:~473`) must replicate the guard from `handle_baseline_update` (`commands.py:217`): read `cmd_version = command.get("ruleset_version", 0)`; if `cmd_version < state.ruleset_version`, log `stale_version` and return without applying. This makes config updates replay-safe and is the idempotency property D-3 (at-least-once delivery) depends on.

## Risks / Trade-offs

- **At-least-once now redelivers commands (D-3)** → handlers must be idempotent. Mitigation: event_ack is a pure lookup; `baseline_update` and (post-BUG-12) `update_config` are guarded by monotonic `ruleset_version`; `quarantine_file`/`restore` are keyed by `event_id`. Verify each handler in the apply phase before relying on this.
- **`add_snapshot` semantics (D-1 / BUG-03)** → if the current `add_snapshot(path)` reads and stores the file's *current* (modified) bytes as a snapshot but the active entry is left untouched, behavior is correct; the only load-bearing change is dropping `write_entry`. Risk if `add_snapshot` internally promotes the snapshot to active — must be confirmed against `baseline.py` during apply. Mitigation: a regression test that modifies a watched file with an `alert_only` rule, then asserts `select_restorable_content` still returns the original known-good content.
- **D16 makes `ca_cert_path` mandatory at bootstrap** → existing/automated deployments that relied on `verify=False` will now `sys.exit(1)` if the CA file is absent. This is intended (operational BREAKING). Mitigation: update `deploy/config.yaml.example` and install docs to state the operator pre-provisions the CA cert; surface a clear error message.
- **BUG-14 exit-code change** → if some coroutine currently raises during *normal* shutdown, the new exit-1 path could mask clean exits. Mitigation: confirm the signal/drain path returns normally from `gather` (it sets `stop_event`; coroutines return, not raise) and add a shutdown test asserting exit 0 on SIGTERM.
- **Self-healing state (BUG-11) discards `ruleset_version`/`rules`** → on corruption the agent restarts from defaults (`ruleset_version=0`) and re-syncs from the backend via the command stream. Acceptable: the backend is the source of truth and the cursor/version converge on next sync. Mitigation: log the `.bak` path so the corrupt file is recoverable for diagnostics.

## Migration Plan

1. Land code fixes grouped by file in the apply order below (simplest/independent first, then the structural detector + ordering fixes).
2. Add per-bug regression tests under `agent/tests/`; run the full agent suite.
3. Update `agent/deploy/config.yaml.example` and the agent install doc for the D16 mandatory-CA requirement.
4. Append the C28 `agent-audit-fixes` row to the CHANGES.md roadmap table (docs edit, outside OPSX) — dependency: C27 `agent-stability-fixes` (archived).
5. **Rollback**: each bug is an isolated, self-contained edit with its own test; revert per-file or per-commit. No data migration, no schema change, no new dependency — rollback is a code revert only. The D16 config requirement is the only operational change to communicate on rollback.

## Open Questions

None blocking. One item to confirm during apply (not a new assumption): the exact `baseline.add_snapshot` signature/semantics — whether it already stores new content without promoting it to the active entry (D14 states `add_snapshot` already exists and needs no interface change). The regression test for BUG-03 is the gate that proves this.
