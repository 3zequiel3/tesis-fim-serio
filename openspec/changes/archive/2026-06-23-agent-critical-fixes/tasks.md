## 1. C1 — Wire register_command_handlers

- [x] 1.1 In `agent/__main__.py`, inside the `_LINUX` block after the detector is constructed (next to the existing `publisher.register_callbacks(...)` call), add `publisher.register_command_handlers(baseline_engine=engine, state=state, journal=journal, quarantine_dir=quarantine_dir, detector=detector)`.
- [x] 1.2 Confirm `engine`, `state`, `journal`, `quarantine_dir`, and `detector` are all in scope at the call site (they are constructed earlier in `main`).
- [x] 1.3 Verify the dispatch guard in `publisher._handle_command_async` (`_baseline_engine is not None and _agent_state is not None`) now passes, so destructive commands no longer log `publisher.command_handler_not_registered`.

## 2. C2 — Single HMAC verification entry point

- [x] 2.1 In `agent/publisher.py`, add `_verify_and_parse(self, msg_data: dict[str, Any]) -> dict[str, Any] | None`: read `msg_data.get("data", "{}")`, `json.loads` it (return `None` on `JSONDecodeError`/`TypeError`), then call `verify_payload(self._shared_secret, payload)` and return `None` if verification fails; otherwise return the parsed payload.
- [x] 2.2 Import `verify_payload` from `agent.streams` in `publisher.py` (alongside the existing `load_shared_secret`, `sign_payload` imports).
- [x] 2.3 Rewire `_ack_listener` to call `payload = self._verify_and_parse(msg_data)`; if `payload is None`, advance `last_id` and `continue`; otherwise call `await self._handle_command_async(payload)`.
- [x] 2.4 Change `_handle_command_async` to accept an already-parsed, verified `payload: dict` (remove its internal `json.loads`); keep `target_agent_id` filtering and command branching, so verification runs before routing.
- [x] 2.5 Remove the dead synchronous `_handle_command` wrapper (the unverified duplicate at lines ~243-278) so no unverified code path remains; first grep the repo/tests to confirm nothing imports or calls it, and update any test that does to the async path.

## 3. C3 — Remove duplicated update_config branch (depends on C1, C2)

- [x] 3.1 In `_handle_command_async`, delete the direct `elif cmd_type == "update_config": ...` branch (the one that calls `_on_update_config_cb(new_paths)` without a version check).
- [x] 3.2 Confirm `update_config` now falls through to the C13/C14 set (`baseline_update`, `restore_file`, `quarantine_file`, `update_config`, `rescan_baseline`) and reaches `commands.dispatch` → `handle_update_config`, which enforces `ruleset_version` monotonicity and persists state.

## 4. C4 — O(1) ack lookup via reverse index

- [x] 4.1 In `agent/detector.py`, add `self._event_to_path: dict[str, str] = {}` next to `self._pending` in `__init__`.
- [x] 4.2 In `_process_event`, when assigning the new event for a path: if a previous `event_id` was pending for that path, remove it from `_event_to_path`; then set `self._pending[path] = event_id` and `self._event_to_path[event_id] = path` together (no `await` between the two writes).
- [x] 4.3 Rewrite `on_ack(event_id)` to be O(1): `path = self._event_to_path.pop(event_id, None)`; if `path is not None` and `self._pending.get(path) == event_id`, `del self._pending[path]`. Safe no-op when `event_id` is unknown.
- [x] 4.4 Add a code comment documenting the single-event-loop invariant (no lock needed: `on_ack` and `_process_event` run on the same loop; mutation regions contain no `await`).

## 5. C5 — Hash retry to avoid false file_absent

- [x] 5.1 In `agent/detector.py`, convert `_hash_file(path)` into `async def _hash_file_async(path: str, retries: int = 3, base_delay: float = 0.05) -> str | None`: hash and return on success; on `FileNotFoundError` with attempts remaining, `await asyncio.sleep(base_delay * 2 ** attempt)` and retry; return `None` only after retries are exhausted.
- [x] 5.2 Update `_process_event` to `current_hash = await self._hash_file_async(path)`; keep the existing `file_absent` vs `file_modified` branching driven by a `None` result.
- [x] 5.3 Confirm the happy path (file present) returns on the first attempt with no `asyncio.sleep` incurred, and that the worst-case retry budget stays ≤150 ms (50 ms + 100 ms).

## 6. Tests

- [x] 6.1 C2: add a test (e.g. in `agent/tests/test_publisher.py`) asserting a `command` message with an invalid/missing signature is dropped — queue not modified, `update_config`/`rule_sync` callbacks not invoked — and that a correctly-signed `event_ack` still acks and clears pending.
- [x] 6.2 C4: add a test (e.g. in `agent/tests/test_detector_dedup.py` or a new `test_detector_ack.py`) that records multiple pending events and interleaves `on_ack` calls within one event loop, asserting `_pending` and `_event_to_path` stay consistent, ack is O(1) (no full scan), and superseded `parent_event_id` linkage is preserved with no `RuntimeError`.
- [x] 6.3 C5: add a test (e.g. in `agent/tests/test_detector_hash.py`) simulating a fanotify/hash race where the file is briefly missing then present (e.g. `_hash_file_async` raises `FileNotFoundError` on the first call, succeeds on retry), asserting the detector emits `file_modified` (not `file_absent`) and does NOT call `mark_absent`; plus a test for a persistently absent file that DOES emit `file_absent` after retries.
- [x] 6.4 C1/C3 integration: add a test asserting a validly-signed `restore_file` (or `update_config`) command is dispatched through `commands.dispatch` after `register_command_handlers` is called, and is NOT logged as `command_handler_not_registered`.

## 7. Verification

- [x] 7.1 Run the agent test suite (`agent/tests/`) and confirm all new and existing tests pass.
- [x] 7.2 Confirm no unverified command code path remains in `agent/publisher.py` (single chokepoint is `_verify_and_parse`).
