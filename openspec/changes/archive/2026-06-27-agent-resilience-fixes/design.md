# Design: agent-resilience-fixes (C29)

## Fix-by-fix approach

### FIX-01 — detector.py: filter `.fim_restore_tmp` (D19)
Guard at the very first line of `_process_event`. Uses `str.endswith` on the full path
string — equivalent to `Path(path).name.endswith(...)` since the suffix is only meaningful
as a tail. No import required.

### FIX-02 — __main__.py: rehydrate() inside try block
Move `await decision_engine.rehydrate(publisher)` from inside the `if _LINUX:` block to
inside the main `try:` block (before `await asyncio.gather(...)`). This guarantees the
`finally:` cleanup (detector.close(), valkey_client.aclose()) runs on any rehydrate failure.

### FIX-03 — publisher.py: _pending before XADD
Assign `_pending[event_id]` before calling `_xadd`. Wrap `_xadd` in try/except that passes
silently — the entry stays in `_pending` and `_retry_loop` will retry it.

### FIX-04 — commands.py: path containment (D18)
Add a guard at the start of `handle_quarantine_file` and `handle_restore_file` that:
1. Calls `os.path.realpath(path)`.
2. Checks `config.watch_paths` (empty → log.error + ack error + return).
3. Checks `any(real.startswith(w) for w in config.watch_paths)` (outside → log.warning + ack error + return).

Note: D18 references `state.watch_paths` but AgentState has no `watch_paths` field — the
canonical watch_paths live in `config.watch_paths`, which is available in both handlers.
Using `config.watch_paths` is the correct implementation.

### FIX-05 — config.py + transport.py: plaintext warning (D20)
Add `allow_plaintext_valkey: bool = False` to `AgentConfig`. In `create_valkey_client`,
when scheme is plain and flag is False, emit `log.warning`. Connection continues (not exit).

### FIX-06 — state.py: timestamped bak on corruption
Replace `path.with_suffix(".json.bak")` with `path.with_name(f"state.{int(time.time())}.json.bak")`.
Import `time` at module level (it is in stdlib and not yet imported).

### FIX-07 — decision.py: OSError in rehydrate inner loop
Add a second `except Exception` clause after `except _ActionFailed` in the rehydrate loop.
The generic handler logs a warning and `continue`s — skipping publish for that entry to
avoid double-publishing on journal corruption.

### FIX-08 — bootstrap.py: cert validity period check
After verifying CA signature and CN, check `not_valid_before_utc <= now <= not_valid_after_utc`.
Use `datetime.now(timezone.utc)` — already imported at module level via `import datetime`.

### FIX-09 — state.py: fsync in save_state()
After `f.write(payload)`, call `f.flush(); os.fsync(f.fileno())` inside the `with os.fdopen` block,
consistent with `journal.py`, `queue.py`, and `baseline.py` patterns.
