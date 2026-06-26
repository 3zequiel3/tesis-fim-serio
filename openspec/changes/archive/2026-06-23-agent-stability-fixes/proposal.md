## Why

The 2026-06-23 multi-agent audit of the FIM agent surfaced seven remaining defects that compromise runtime stability, shutdown cleanliness, durability, and command idempotency. None of them are visible under happy-path manual testing, but each fails under realistic conditions: signal races during startup, Python 3.12+/3.14 event-loop API removal, Valkey outages between physical action and publish, file-descriptor and thread leaks on `SIGTERM`, unbounded in-memory queues under event storms, config writes to the wrong path, and a `ruleset_version` gate that rejects safe replays. This change closes all seven before the agent is considered production-ready for the thesis defense. It is the agent counterpart of the already-archived backend hardening passes (C21, C23, C24–C26).

## What Changes

- **FA1 — Signal-handler registration race**: register `SIGTERM`/`SIGINT` handlers only after `queue` and `publisher` exist; initialize them to `None` and add an early-return guard in `_shutdown` so a signal during startup is a safe no-op. (`agent/__main__.py`)
- **FA2 — `asyncio.get_event_loop()` inside coroutines**: replace all 7 occurrences with `asyncio.get_running_loop().time()` to avoid `DeprecationWarning` (3.12) and the future `RuntimeError` (3.14). Mechanical, no behavior change. (`agent/__main__.py`, `agent/publisher.py`, `agent/detector.py`)
- **FA3 — Journal marks `completed` before publish** *(BREAKING durability semantics)*: `evaluate_and_act` returns a `commit_fn` callable alongside the payload; the journal entry stays `pending` until `await publisher.publish()` returns without exception, at which point the caller invokes `commit_fn()`. A Valkey outage between physical action and publish now leaves the entry `pending` so it rehydrates on restart instead of being lost. (`agent/decision.py`, `agent/detector.py`)
- **FA4 — Unclean shutdown leaks fanotify fd and reader thread**: add `detector.close()` that closes the fanotify fd (unblocking the `fan-reader` thread parked in `read()`) and joins the thread with a 5 s timeout; call it from the `finally` block before process exit. (`agent/__main__.py`, `agent/detector.py`)
- **FA5 — Unbounded in-memory raw queue**: bound `_raw_queue` to `maxsize=1000`; the cross-thread producer wraps `put_nowait` to catch `QueueFull`, increment a drop counter, and emit a warning; the counter is surfaced in the heartbeat as `event_drops`. Prevents OOM under event storms. (`agent/detector.py`, `agent/heartbeat.py`)
- **FA6 — `update_config` always writes the default config path**: add `config_path: Path | None` as a `PrivateAttr` on `AgentConfig`, set it in `load_config(path)`, and resolve the write target as `config.config_path or Path("/etc/fim-agent/config.yaml")` in `handle_update_config`. (`agent/config.py`, `agent/commands.py`)
- **M7 — Inconsistent `ruleset_version` gate**: change `rules.py` from `ruleset_version <= state.ruleset_version` to `<`, aligning the rules cache with the command path (`commands.py` already uses `<`). An equal version is a safe, idempotent replay per RN-75. (`agent/rules.py`)

## Capabilities

### New Capabilities
<!-- None. This is a remediation change against existing, already-specified agent capabilities. -->

### Modified Capabilities
- `agent-core`: shutdown sequence now guarantees signal handlers are registered only after queue/publisher exist (FA1) and that the fanotify fd and reader thread are closed/joined before process exit (FA4).
- `agent-fanotify-detector`: detector exposes `close()` for deterministic teardown (FA4); the raw event queue is bounded with a drop counter surfaced via heartbeat `event_drops` (FA5).
- `agent-journal-integrity`: a journal entry remains `pending` until the backend publish is confirmed; `completed` is committed only after a successful publish (FA3).
- `agent-decision-engine`: `evaluate_and_act` returns a deferred `commit_fn` so journal commit is ordered after publish (FA3); `rule_sync` is idempotent on an equal `ruleset_version` (M7).
- `agent-config-commands`: `update_config` persists to the actual loaded config path rather than the hard-coded default (FA6).

## Impact

- **Code**: `agent/__main__.py`, `agent/detector.py`, `agent/publisher.py`, `agent/decision.py`, `agent/config.py`, `agent/commands.py`, `agent/rules.py`, `agent/heartbeat.py`.
- **Tests**: new/updated unit tests per fix (signal-race guard, event-loop API, publish-before-commit rehydration, clean shutdown join, bounded-queue drop counting, config-path resolution, version-gate idempotency).
- **Contract surface**: FA5 adds an additive `event_drops` field to the `agent_heartbeat` payload (canonical schema per RN-92/RN-93). The backend heartbeat consumer must tolerate the extra field. This extension requires a closed decision in the implementation-decisions appendix before apply (see design.md, open question).
- **Rules/Decisions covered**: RN-75 (`ruleset_version` monotonic, idempotent replay — M7, FA3 publish ordering), RN-92/RN-93 (heartbeat schema — FA5), RN-108/D8 (no HTTP server — preserved), D7 (cross-cutting with the feature that needs it — drop logging).
- **Dependencies**: depends on C26 (`agent-fanotify-and-lifecycle`, archived 2026-06-23). DAG satisfied.
- **No breaking API/HTTP changes**; FA3 changes internal durability ordering only.
