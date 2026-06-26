## Context

The FIM agent is an asyncio process (`agent/__main__.py`) that bridges a blocking fanotify reader thread to async consumers, runs a decision engine with a durable journal, and talks to the backend exclusively over Valkey Streams (RN-108/D8 — no HTTP server). The 2026-06-23 multi-agent audit found seven defects that do not surface on the happy path but fail under realistic conditions: signal races at startup, Python event-loop API removal, Valkey outages, `SIGTERM` mid-blocking-syscall, event storms, non-default config paths, and `ruleset_version` replay. This change is a focused remediation pass; it introduces no new capability and no new external dependency. All target modules already have specs from C11–C26.

Current grounding (verified against the tree at C26):
- `__main__.py:197-198` registers signal handlers; `:202-203` constructs `queue`/`publisher` afterwards. `_shutdown` captures both by closure.
- `__main__.py:132-133`, `publisher.py:90,161,338`, `detector.py:533-534` call `asyncio.get_event_loop().time()` inside coroutines.
- `decision.py:66` marks `completed` inside `evaluate_and_act`, before the caller publishes.
- `__main__.py:262` exits via `sys.exit(0)` in `finally` with no fd close and no thread join.
- `detector.py:198` creates `asyncio.Queue()` with no `maxsize`; `:296` enqueues via `call_soon_threadsafe(put_nowait, ...)`.
- `commands.py:454` reads `getattr(config, "_config_path", None)` which is always `None` because `AgentConfig` has no such attribute → always falls back to the default path.
- `rules.py:85` rejects `ruleset_version <= state.ruleset_version`; `commands.py:217` rejects only `cmd_version < state.ruleset_version`.

## Goals / Non-Goals

**Goals:**
- Eliminate the startup signal race and make `_shutdown` reentrancy-safe (FA1).
- Make the agent forward-compatible with Python 3.12+ deprecations and the 3.14 removal of `get_event_loop()` in coroutines (FA2).
- Guarantee no permanent event loss when Valkey is unavailable between physical action and publish (FA3).
- Deterministic, leak-free shutdown: fanotify fd closed and reader thread joined (FA4).
- Bound in-memory growth under event storms and make drops observable (FA5).
- Persist `update_config` to the config file the agent actually loaded (FA6).
- Make `ruleset_version` gating uniform and idempotent across the command and rules paths (M7).

**Non-Goals:**
- No change to the wire protocol, command set, or HMAC/mTLS scheme.
- No new capability, no HTTP/listener of any kind (RN-108/D8 preserved).
- No change to the on-disk queue (100 MB drop-oldest, RN-83/RN-84) — FA5 concerns only the in-memory raw bridge queue.
- No backend changes beyond tolerating the additive `event_drops` heartbeat field.

## Decisions

### D-C27-1: Deferred journal commit via `commit_fn` (FA3)
`evaluate_and_act` returns `(payload, commit_fn)` where `commit_fn` is a zero-arg callable that applies the terminal journal transition (`completed` or `failed`). The detector calls `commit_fn()` only after `await publisher.publish(payload)` returns without raising. **Why over alternatives**: (a) marking `completed` before publish is the bug; (b) marking `completed` and rolling back on publish failure is racy and requires a rewrite-to-pending that can itself fail; (c) a deferred callable keeps the entry in its already-durable `pending` state until the single success edge is reached — the simplest correct ordering. Rehydration already reprocesses `pending` entries, and the physical actions are idempotent (auto_restore re-verifies hash; quarantine fails gracefully if already moved), so re-publishing a rehydrated entry is safe.

### D-C27-2: `get_running_loop()` everywhere inside coroutines (FA2)
Mechanical replacement of all 7 `asyncio.get_event_loop().time()` call sites with `asyncio.get_running_loop().time()`. These are all inside running coroutines, so a running loop is guaranteed. No behavior change today; removes the 3.12 `DeprecationWarning` and the future 3.14 `RuntimeError`. Not modeled as a spec requirement because there is no observable behavior change.

### D-C27-3: Signal handler registration after dependencies + guard (FA1)
Initialize `queue = None` and `publisher = None` before the try block; construct them; register handlers after. `_shutdown` early-returns if either is still `None`. **Why**: closure capture of not-yet-assigned names is fragile and only works because CPython does not dispatch callbacks until the next `await`. Explicit ordering plus a guard makes correctness independent of interpreter scheduling.

### D-C27-4: `detector.close()` closes fd then joins thread (FA4)
The `fan-reader` thread blocks in `_fan_mod.read(self._fan)`. The only portable way to unblock it is to close the underlying fd, which makes the syscall return/raise. `close()` therefore closes the fanotify fd first, then `join(timeout=5.0)`. It is idempotent (guard on an already-closed fd). The main `finally` calls `detector.close()` before exit; `sys.exit(0)` is retained but is now reached after a clean teardown. **Why over a daemon thread that is simply abandoned**: abandoning leaks the fanotify fd and risks the kernel queue staying mapped; explicit close is deterministic.

### D-C27-5: Bounded raw queue with a drop counter, surfaced in heartbeat (FA5)
`asyncio.Queue(maxsize=1000)`. Because the producer runs on the reader thread via `loop.call_soon_threadsafe`, a raw `put_nowait` that raises `QueueFull` would have its exception swallowed by the event loop. The enqueue is wrapped in a function scheduled on the loop that catches `QueueFull`, increments a monotonic `event_drops` counter on the detector, and logs a `warning`. The heartbeat publisher reads that counter and adds `event_drops` to its payload. **Why 1000**: bounds worst-case memory while comfortably absorbing normal bursts; the existing `queue_pressure` flag (on-disk queue, RN-83) is orthogonal. Cross-cutting drop logging travels with this feature per D7.

### D-C27-6: `config_path` as a `PrivateAttr` on `AgentConfig` (FA6)
Add `config_path: Path | None = PrivateAttr(default=None)`. `load_config(path)` sets it after `model_validate`. `handle_update_config` resolves `config.config_path or Path("/etc/fim-agent/config.yaml")`. **Why a `PrivateAttr`**: keeps the loaded path out of the serialized/validated config surface (it is runtime provenance, not configuration data) while making it reliably available, replacing the always-`None` `getattr` hack.

### D-C27-7: Uniform strictly-less `ruleset_version` gate (M7)
Change `rules.py:85` from `<=` to `<`. RN-75 states the agent "discards messages with a *lower* version" — equal is a safe idempotent replay, not a reject. `commands.py` already uses `<`; this aligns the rules-cache path. Note: the existing `agent-config-commands` spec prose mentions a `<=` boundary for `update_config`, but the actual code uses `<` (accepts equal); the canonical rule is strictly-less-rejected. This change touches only `rules.py`; no code change is needed in `commands.py`.

## Risks / Trade-offs

- **[FA5 adds `event_drops` to the heartbeat schema]** → The canonical heartbeat payload (RN-92/RN-93) is `{agent_id, timestamp, queue_size, ruleset_version, queue_pressure, shutdown}` (the code already adds `schema_version`). Adding `event_drops` is additive and backward-compatible for a consumer that reads keys by name, but it is a new cross-domain contract surface. **Mitigation**: close decision D-C27-1-DOC in the implementation-decisions appendix before apply (see Open Questions); verify the backend `heartbeat_consumer` ignores unknown fields. Listed as the headline open question.
- **[FA3 re-publishes rehydrated `pending` entries that physically completed]** → A duplicate event could reach the backend if publish actually succeeded but the process died before `commit_fn()`. **Mitigation**: backend event ingestion is already idempotent by `event_id` (C18/RN consumer dedup); re-publishing the same `event_id` is absorbed. Net trade-off favors at-least-once over the current lossy at-most-once.
- **[FA4 join timeout of 5 s]** → If the reader thread does not exit within 5 s after fd close, the agent proceeds to exit anyway. **Mitigation**: closing the fd reliably unblocks `read()`; the timeout is a backstop, not the expected path. A warning is logged if the join times out.
- **[FA1 ordering change]** → Moving handler registration later means a signal in the narrow pre-registration window uses the default disposition (process terminates). **Mitigation**: acceptable — there is nothing to drain before `queue`/`publisher` exist; abrupt termination at that point loses no durable state.

## Migration Plan

1. Apply fixes module-by-module in dependency order: FA2 (mechanical, no behavior) → FA6 → M7 → FA1 → FA4 (`detector.close()`) → FA5 → FA3 (touches decision + detector caller).
2. Each fix lands with its unit test(s). No data migration; no schema migration on disk.
3. **Rollback**: every fix is self-contained and revertible per-commit. FA3 is the only behavior-ordering change; reverting it restores prior (lossy) ordering without data structure changes. No persisted state format changes, so downgrade is safe.
4. Deploy as a normal agent upgrade (systemd restart). On restart, any `pending` journal entries written by the new ordering rehydrate cleanly.

## Open Questions

- **[BLOCKING before apply]** `event_drops` heartbeat field (FA5): confirm and close a decision in the `Decisiones de implementación — Abril 2026` appendix of `reglas_de_negocio.md`/`arquitectura_stack.md` formally extending the `agent_heartbeat` payload schema (RN-92/RN-93) with `event_drops: int`, and confirm the backend `heartbeat_consumer` tolerates/persists it. Until closed, FA5's heartbeat exposure should not be merged (the bounded queue + internal counter + warning log can ship independently if needed).
- Should the raw-queue `maxsize` (1000) be configurable via `config.yaml`, or is a constant acceptable for the thesis MVP? Current decision: constant, revisit only if load testing shows otherwise.
