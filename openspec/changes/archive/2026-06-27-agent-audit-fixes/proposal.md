## Why

A second-pass audit of the FIM agent (`agent/`) surfaced 14 defects that violate already-closed business rules and decisions. Five are CRITICAL: they break the core integrity-protection semantics (auto_restore on delete always fails, restore can serve the attacker's content, auto-quarantine fails on every event) or push the agent into a crash-restart loop under systemd. The rest weaken durability, security (bootstrap MITM, mTLS hostname spoofing), and operational stability. None require a new assumption — decisions D14–D17 (RN-112–RN-115) were closed in the canonical appendices on 2026-06-26, and the remaining fixes enforce rules already in force (RN-30, RN-79, RN-83, RN-85, RN-36).

## What Changes

This change corrects implementation defects only. It introduces no new feature and no new assumption.

- **BUG-01 / D14 (CRITICAL)** — `detector.py` `file_deleted`: stop mutating the baseline (`mark_absent`) before the decision engine runs; evaluate first, `mark_absent` only if not restored, so auto_restore on delete can read `content_b64`.
- **BUG-02 / D14 (CRITICAL)** — `detector.py` `file_created`: stop writing the baseline (`write_entry`) before evaluation; evaluate first, `write_entry` only if not quarantined.
- **BUG-03 / D14 (CRITICAL)** — `detector.py` `file_modified` non-restore: keep the active baseline pointing at the known-good state; only `add_snapshot(path, new_hash, new_content)` for audit, never `write_entry` with attacker content.
- **BUG-04 (CRITICAL)** — `decision.py` `rehydrate()`: wrap `publisher.publish()` in `try/except` so a Valkey outage at restart cannot abort `asyncio.run()` into a crash loop.
- **BUG-05 (CRITICAL)** — `decision.py` `_quarantine()`: create `quarantine_dir` (`mkdir(parents=True, exist_ok=True)`) before `shutil.move()`, matching `commands.handle_quarantine_file`.
- **BUG-06 (HIGH)** — `__main__.py` `_cert_renewal_loop`: load `agent-key.pem` and pass it to `verify_cert(..., private_key=...)` so the cert↔key binding check runs during renewal.
- **BUG-07 / D16 (HIGH)** — `bootstrap.py`: replace `verify=False` with `verify=str(config.ca_cert_path)`; require the CA file to exist before the call (`sys.exit(1)` otherwise). **BREAKING (operational)**: operators must pre-provision `ca_cert_path` before first bootstrap.
- **BUG-08 / D17 (HIGH)** — `transport.py`: add `ssl_check_hostname=True` to the `valkeys://` client so a valid-but-wrong CA cert cannot MITM Valkey.
- **BUG-09 (HIGH)** — `publisher.py` `_ack_listener`: persist the cursor (`save_state`) AFTER dispatch, restoring at-least-once command delivery.
- **BUG-10 / D15 (MEDIUM)** — `decision.py` commit path deletes the journal entry after `mark_completed`; `journal.delete()` already exists — wire it into the main `commit_fn`.
- **BUG-11 (MEDIUM)** — `state.py` `load_state`: self-heal a corrupt `state.json` (rename to `.bak`, reinitialize defaults, warn) instead of `sys.exit(1)` into a loop.
- **BUG-12 (MEDIUM)** — `commands.py` `handle_update_config`: add the monotonic `ruleset_version` guard already present in `handle_baseline_update`.
- **BUG-13 (MEDIUM)** — `publisher.py` `_flush_commands`: wrap the inline `save_state` in `try/except`, matching `_ack_listener`.
- **BUG-14 (MEDIUM)** — `__main__.py`: do not let the `finally` block force `sys.exit(0)` when a core coroutine crashes; surface exit code 1 so systemd `Restart=on-failure` triggers.

## Capabilities

### New Capabilities
<!-- None — this is a remediation change. -->

### Modified Capabilities

No requirement-level behavior changes. Every fix makes the implementation honor a contract already specified in the canonical docs (RN-112–RN-115 / D14–D17 and pre-existing RN-30, RN-36, RN-79, RN-83, RN-85) and in the existing agent specs (`agent-decision-engine`, `agent-fanotify-detector`, `agent-journal-integrity`, `agent-bootstrap`, `agent-valkey-transport`, `agent-command-cursor`, `agent-cert-renewal`, `agent-core`, `agent-config-commands`). No delta spec files are required; existing specs remain the contract and this change corrects the code to meet them.

## Impact

- **Affected code** (agent only):
  - `agent/detector.py` — BUG-01, BUG-02, BUG-03 (operation ordering in the three event branches)
  - `agent/decision.py` — BUG-04, BUG-05, BUG-10
  - `agent/bootstrap.py` — BUG-07
  - `agent/transport.py` — BUG-08
  - `agent/publisher.py` — BUG-09, BUG-13
  - `agent/__main__.py` — BUG-06, BUG-14
  - `agent/journal.py` — BUG-10 (`delete` already present; verify)
  - `agent/state.py` — BUG-11
  - `agent/commands.py` — BUG-12
  - `agent/tests/` — regression tests for all 14 fixes
- **Config / operations**: D16 makes `config.ca_cert_path` mandatory at bootstrap; the deploy example and install docs must state the operator pre-provisions the CA cert.
- **Dependencies**: none added. Uses existing `cryptography`, `httpx`, `valkey`, `cffi/pyfanotify`.
- **Decisions applied**: D14 (RN-112), D15 (RN-113), D16 (RN-114), D17 (RN-115). **Rules enforced**: RN-30, RN-36, RN-79, RN-83, RN-85, RN-112–RN-115.
- **Roadmap**: this is change C28 (`agent-audit-fixes`), the remediation successor to C27 `agent-stability-fixes`. The D14–D17 status table in the canonical appendices already assigns these decisions to C28; the CHANGES.md roadmap table still needs a C28 row appended.
