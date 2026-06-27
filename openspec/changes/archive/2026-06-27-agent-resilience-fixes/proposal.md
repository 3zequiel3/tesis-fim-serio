# Proposal: agent-resilience-fixes (C29)

## Intent

Apply 9 targeted resilience fixes to the FIM agent, addressing bugs and gaps identified
after the C24-C28 implementation cycle. All fixes are backed by closed decisions D18, D19,
and D20 in the canonical docs (2026-06-26).

## Problem Statement

After implementing mTLS, reconnect order, fanotify masks, and baseline tracking, a set of
medium-to-low severity issues remain unaddressed:

- Auto-restore generates infinite loop via `.fim_restore_tmp` events (D19).
- `rehydrate()` crashing before the main gather means cleanup is never run.
- XADD failure in `publish()` silently drops the event from retry tracking.
- File handlers accept paths outside `watch_paths`, enabling arbitrary fs ops (D18).
- Plaintext Valkey connections are silent when mTLS is expected (D20).
- Corrupt state backup overwrites previous backup (data loss on repeated corruption).
- OSError in `rehydrate()` inner loop crashes remaining entries.
- `verify_cert()` does not check the certificate validity window.
- `save_state()` lacks fsync, risking torn writes on crash.

## Scope

**In:** 9 targeted fixes across `detector.py`, `__main__.py`, `publisher.py`, `commands.py`,
`transport.py`, `config.py`, `state.py`, `decision.py`, `bootstrap.py`, plus config example
and new test file.

**Out:** No new features, no schema changes, no backend changes.

## Decisions

- D18 (RN-116): path containment validation in `handle_quarantine_file` / `handle_restore_file`.
- D19 (RN-117): `.fim_restore_tmp` filtered at the top of `_process_event`.
- D20 (RN-118): `allow_plaintext_valkey: bool = False` + warning in `create_valkey_client`.
