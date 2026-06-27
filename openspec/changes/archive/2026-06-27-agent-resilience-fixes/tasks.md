# Tasks: agent-resilience-fixes (C29)

## Batch 1 — Core agent fixes

- [x] FIX-01: detector.py — add `.fim_restore_tmp` guard at top of `_process_event`
- [x] FIX-02: __main__.py — move `rehydrate()` call inside the main try block
- [x] FIX-03: publisher.py — assign `_pending[event_id]` before `_xadd`, wrap xadd in try/except

## Batch 2 — Command security and transport config

- [x] FIX-04: commands.py — add path containment guard to `handle_quarantine_file` and `handle_restore_file`
- [x] FIX-05a: config.py — add `allow_plaintext_valkey: bool = False` to `AgentConfig`
- [x] FIX-05b: transport.py — emit log.warning when plaintext and `allow_plaintext_valkey` is False
- [x] FIX-05c: agent/deploy/config.yaml.example — document `allow_plaintext_valkey` field

## Batch 3 — State durability and decision loop

- [x] FIX-06: state.py — use timestamped `.bak` filename in `load_state()` on corruption
- [x] FIX-07: decision.py — add `except Exception` after `except _ActionFailed` in rehydrate loop
- [x] FIX-08: bootstrap.py — add cert validity period check in `verify_cert()`
- [x] FIX-09: state.py — add `f.flush(); os.fsync(f.fileno())` in `save_state()`

## Batch 4 — Tests

- [x] Write `agent/tests/test_resilience_fixes.py` with at minimum one test per fix
- [x] Run `uv run --with pytest --with pytest-asyncio --with pyyaml --with valkey --with cryptography --with pydantic-settings --with structlog --with httpx pytest agent/tests/ -q --tb=short` and confirm all pass

## Batch 5 — Roadmap

- [x] Add C29 row to CHANGES.md
