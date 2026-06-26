## 1. FA2 — Event-loop API (mechanical, no behavior change)

- [x] 1.1 Replace `asyncio.get_event_loop().time()` with `asyncio.get_running_loop().time()` in `agent/__main__.py:132,133` (`_drain_then_stop`)
- [x] 1.2 Replace the 3 occurrences in `agent/publisher.py:90,161,338` (`publish`, `_drain_queue`, `_retry_loop`)
- [x] 1.3 Replace the 2 occurrences in `agent/detector.py:533,534` (`drain`)
- [x] 1.4 Grep the whole `agent/` tree to confirm zero remaining `get_event_loop()` calls inside coroutines
- [x] 1.5 Add/adjust a unit test asserting no `DeprecationWarning` is raised by the drain/publish paths under `-W error::DeprecationWarning`

## 2. FA6 — update_config persists to the loaded config path

- [x] 2.1 Add `_config_path: Path | None = PrivateAttr(default=None)` to `AgentConfig` in `agent/config.py` (import `PrivateAttr`, `Path`; Pydantic v2 sunder naming)
- [x] 2.2 In `load_config(path)`, set `cfg._config_path = Path(path)` after `model_validate`
- [x] 2.3 In `agent/commands.py:handle_update_config`, resolve the write target as `config._config_path or Path("/etc/fim-agent/config.yaml")`, removing the always-`None` `getattr(config, "_config_path", None)` hack
- [x] 2.4 Unit test: `load_config("/opt/fim/custom.yaml")` then `handle_update_config` writes back to `/opt/fim/custom.yaml`, not the default
- [x] 2.5 Unit test: `config_path is None` falls back to `/etc/fim-agent/config.yaml`

## 3. M7 — Uniform strictly-less ruleset_version gate

- [x] 3.1 Change `agent/rules.py:85` from `ruleset_version <= state.ruleset_version` to `ruleset_version < state.ruleset_version`
- [x] 3.2 Unit test: a `rule_sync` re-delivered with an equal `ruleset_version` is reapplied idempotently and acked (not rejected)
- [x] 3.3 Unit test: a `rule_sync` with a strictly lower `ruleset_version` is still discarded
- [x] 3.4 Confirm `agent/commands.py` already uses `<` and needs no change (regression test for the equal-version accept path)

## 4. FA1 — Signal handler registration ordering + guard

- [x] 4.1 In `agent/__main__.py`, initialize `queue = None` and `publisher = None` before the try block
- [x] 4.2 Move `loop.add_signal_handler(SIGTERM/SIGINT, ...)` to after `queue` and `publisher` are constructed (after current lines 202-203)
- [x] 4.3 Add an early-return guard at the top of `_shutdown`: return if `queue is None or publisher is None`
- [x] 4.4 Unit test: invoking `_shutdown` before `publisher` is constructed is a safe no-op (no exception)

## 5. FA4 — Clean shutdown closes fanotify fd and joins reader thread

- [x] 5.1 Add `FanotifyDetector.close()` in `agent/detector.py`: close the fanotify fd, then `self._thread.join(timeout=5.0)`; make it idempotent (guard already-closed fd); log a warning if the join times out
- [x] 5.2 Call `detector.close()` in the `finally` block of `agent/__main__.py` before process exit (around line 262)
- [x] 5.3 Unit test: `close()` while the reader thread is blocked in `read()` unblocks and joins it within the timeout
- [x] 5.4 Unit test: `close()` is idempotent (second call is a safe no-op)

## 6. FA5 — Bounded raw queue with drop counter surfaced in heartbeat

- [x] 6.1 Change `agent/detector.py:198` to `asyncio.Queue(maxsize=1000)`
- [x] 6.2 Add an `event_drops` monotonic counter on the detector and a `try_enqueue` wrapper that catches `asyncio.QueueFull`, increments the counter, and logs a `warning`; schedule it via `call_soon_threadsafe` (replace the raw `put_nowait` at line 296)
- [x] 6.3 Expose the counter to the heartbeat (e.g., detector accessor or shared reference) and add `event_drops` to the `agent_heartbeat` payload in `agent/heartbeat.py:_publish`
- [x] 6.4 Unit test: enqueue under a full queue increments `event_drops`, logs a warning, and does not raise
- [x] 6.5 Unit test: heartbeat payload includes `event_drops` reflecting the current count
- [x] 6.6 Unit test: enqueue under capacity does not change `event_drops`
- [x] 6.7 **GATE**: confirm the `event_drops` heartbeat-schema decision is closed in the implementation-decisions appendix before merging task group 6.3/6.5 (see design Open Questions). The bounded queue + counter + log (6.1, 6.2, 6.4, 6.6) may land independently if the decision is still open.

## 7. FA3 — Journal stays pending until publish is confirmed

- [x] 7.1 In `agent/decision.py`, change `evaluate_and_act` to NOT call `mark_completed`/`mark_failed` inline; instead build a `commit_fn` callable that applies the terminal transition and return it alongside the payload (e.g., `return payload, commit_fn`)
- [x] 7.2 Update the detector caller so it invokes `commit_fn()` only after `await publisher.publish(payload)` returns without raising; on publish exception, leave the entry `pending` and log
- [x] 7.3 Update any other callers of `evaluate_and_act` to the new return signature; keep the journal rehydration path (`load_pending`) unchanged
- [x] 7.4 Unit test: publish raises → entry remains `pending` and is returned by `load_pending` on restart
- [x] 7.5 Unit test: publish succeeds → `commit_fn()` marks `completed` (auto_restore) and `failed` (no baseline content) appropriately
- [x] 7.6 Unit test: journal state is never `completed` between the physical action and a confirmed publish

## 8. Validation

- [x] 8.1 Run the full agent unit test suite; all green (227/227)
- [x] 8.2 Run with `python -W error::DeprecationWarning` to confirm FA2 removed the event-loop warnings
- [ ] 8.3 Run `openspec validate agent-stability-fixes --strict` (or equivalent) to confirm specs/tasks integrity
- [ ] 8.4 Manual smoke: start agent with a non-default config, trigger `update_config`, send `SIGTERM`, confirm clean shutdown (fd closed, thread joined) and that a Valkey outage during a detected change leaves a `pending` journal entry that rehydrates on restart

