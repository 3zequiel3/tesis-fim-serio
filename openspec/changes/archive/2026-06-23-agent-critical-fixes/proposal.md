## Why

The April 2026 multi-agent code audit (`docs/audit_bugs.md`) found 5 critical defects in the FIM agent that silently break core integrity-monitoring guarantees. The most severe one disables every destructive command (`restore_file`, `quarantine_file`, `rescan_baseline`, `baseline_update`) as a silent no-op; another bypasses the mandatory HMAC verification of inbound commands (violating RN-79); and two more corrupt or destroy the local baseline under concurrent or write-tmp+rename workloads. These are not feature gaps — they are correctness failures in already-shipped agent code (introduced across changes C05 `agent-core-scaffold`, C13, C14), so they must be remediated before the agent can be trusted end-to-end.

## What Changes

- **C1 — Wire `register_command_handlers()`**: call `publisher.register_command_handlers(engine, state, journal, quarantine_dir, detector)` from `agent/__main__.py` so the destructive-command dispatch branch is no longer dead. Restores `baseline_update`, `restore_file`, `quarantine_file`, `rescan_baseline` from silent no-op to functional. (RN-79, RN-83)
- **C2 — Single HMAC verification entry point** **BREAKING (security)**: extract `_verify_and_parse(msg_data) -> dict | None` as the sole entry point of the command listener. It JSON-parses, verifies the HMAC signature with `shared_secret`, and returns a clean payload or `None`. `event_ack`, `update_config`, and `rule_sync` — currently executed without signature verification — are now rejected when the signature is invalid. Future command types are covered automatically. (RN-79)
- **C3 — Remove duplicated `update_config` branch**: delete the direct `elif cmd_type == "update_config"` branch in `agent/publisher.py` that shadowed the versioned `commands.dispatch` path. Once C1 is active, `update_config` flows through `handle_update_config`, restoring `ruleset_version` monotonicity enforcement. (RN-75)
- **C4 — O(1) ack lookup via reverse index**: add `_event_to_path: dict[str, str]` (event_id → path) to the detector so `on_ack` resolves the pending entry in O(1) instead of O(N) iteration over `_pending.items()`, eliminating the iterate-while-mutate hazard. (RN-40, RN-73)
- **C5 — Hash retry to avoid false `file_absent`**: convert `_hash_file` into `async def _hash_file_async(path, retries=3, base_delay=0.05)` with exponential backoff (3 attempts, ≤150 ms total). Only emit `file_absent` after retries are exhausted, preventing atomic-write editor patterns from destroying the baseline. (RN-01, RN-93)

## Capabilities

### New Capabilities
- `agent-command-dispatch`: how the agent listens to the `commands` stream, verifies inbound command authenticity (HMAC), filters by `target_agent_id`, and dispatches destructive commands through the versioned handler. Covers C1, C2, C3.
- `agent-change-detection-integrity`: how the detector tracks pending events and reads file hashes without losing or corrupting baseline under concurrent acks and atomic-write workloads. Covers C4, C5.

### Modified Capabilities
<!-- None. No prior openspec/specs/ exist; these are the first formal specs for this agent behavior. -->

## Impact

- **Code**:
  - `agent/__main__.py` — C1: add the `register_command_handlers` call after detector construction.
  - `agent/publisher.py` — C2: new `_verify_and_parse`; rewire `_ack_listener`/`_handle_command_async` to receive only verified payloads. C3: delete the duplicated `update_config` branch.
  - `agent/detector.py` — C4: reverse index `_event_to_path`. C5: `_hash_file_async` with retry/backoff; `_process_event` awaits it.
- **Behavioral contract**: destructive commands transition from no-op to functional; unsigned/invalid commands are now dropped (RN-79 enforced); baseline survives concurrent acks and atomic-write editors.
- **Dependencies**: none added. Reuses existing `agent/streams.py` (`verify_payload`, `load_shared_secret`) and `agent/commands.py` (`dispatch`).
- **Tests**: `agent/tests/` gains coverage for invalid-HMAC rejection (C2), concurrent `_pending` mutation (C4), and the fanotify/hash race (C5).
- **Rules covered**: RN-01, RN-40, RN-73, RN-75, RN-79, RN-83, RN-93. **Decisions applied**: D5 (`target_agent_id` filtering), D8 (no HTTP server — asyncio single-loop concurrency model).
- **No new assumptions**: every fix enforces an already-closed rule or robustness expectation; nothing requires a new decision in the implementation appendix.
