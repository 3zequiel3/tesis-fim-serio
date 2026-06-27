# Tasks — agent-audit-fixes (C28)

Ordered by dependency and risk: simple, isolated guards first; structural detector/ordering and trust-boundary fixes last. Every fix ships with its own regression test. Decisions applied: D14 (RN-112), D15 (RN-113), D16 (RN-114), D17 (RN-115).

## 1. Self-contained guards (low risk, no cross-file coupling)

- [x] 1.1 BUG-05 — `decision.py` `_quarantine()`: add `self._quarantine_dir.mkdir(parents=True, exist_ok=True)` before `shutil.move()`. Test: auto-quarantine into a non-existent quarantine dir succeeds and the file lands in quarantine (regression for `move_failed`).
- [x] 1.2 BUG-11 — `state.py` `load_state`: on `json.JSONDecodeError`/`ValueError`, rename `state.json` → `state.json.bak`, log a warning, return `AgentState(state_path=path)` defaults instead of `sys.exit(1)`. Test: corrupt `state.json` → `load_state` returns defaults, `.bak` exists, no exit.
- [x] 1.3 BUG-13 — `publisher.py` `_flush_commands`: wrap the inline `save_state(self._agent_state)` (line ~224) in `try/except Exception as e: log.warning(...)`, matching `_ack_listener`. Test: `save_state` raising `OSError` during flush does not abort `_flush_commands`/startup.
- [x] 1.4 BUG-12 — `commands.py` `handle_update_config`: add `cmd_version = command.get("ruleset_version", 0)`; if `cmd_version < state.ruleset_version`, log `stale_version` and return without applying (mirror `handle_baseline_update` at line 217). Test: a replayed `update_config` with a lower `ruleset_version` is ignored; current config unchanged.
- [x] 1.5 BUG-14 — `__main__.py` `main()`: capture the exception from `await asyncio.gather(...)` in the `try` block, set a non-zero exit code for unexpected crashes; keep `finally` cleanup but exit 1 on crash, 0 on normal signal-driven shutdown. Tests: (a) a core coroutine raising → process exit code 1; (b) SIGTERM-driven drain → exit code 0.

## 2. Journal lifecycle (D15 / RN-113)

- [x] 2.1 BUG-10 — `journal.py`: confirm `delete(event_id)` exists and unlinks `{event_id}.json` tolerating `FileNotFoundError` (already present at line ~101). No change expected; add a unit test for `delete` of a present and an absent entry.
- [x] 2.2 BUG-10 — `decision.py` `evaluate_and_act` success `commit_fn` (line ~75): call `self._journal.delete(event_id)` immediately after `self._journal.mark_completed(event_id)`. Leave the `mark_failed` path untouched. Test: after a successful publish + commit, the journal file for that `event_id` no longer exists; a failed action leaves the entry on disk.

## 3. Restart-path resilience

- [x] 3.1 BUG-04 — `decision.py` `rehydrate()`: wrap `await publisher.publish(payload)` (line ~131) in `try/except Exception`, log `rehydrate.publish_failed` warning, continue the loop. Test: with a publisher whose `publish` raises (Valkey down), `rehydrate` completes over multiple pending entries without raising; journal entries remain for retry.

## 4. Command delivery ordering (at-least-once)

- [x] 4.1 BUG-09 — `publisher.py` `_ack_listener`: move `self._agent_state.last_stream_command_id = msg_id` + `save_state(...)` to AFTER `await self._handle_command_async(payload)`. Keep cursor advancement for `payload is None` (verification-failed) messages. Test: a crash simulated between receive and dispatch re-delivers the command on the next read (cursor not advanced past an undispatched command).

## 5. Trust boundaries (D16, D17, cert↔key binding)

- [x] 5.1 BUG-08 / D17 — `transport.py` `create_valkey_client`: add `ssl_check_hostname=True` to the `valkeys://` `Valkey.from_url(...)` kwargs (no opt-out). Test: the TLS client is constructed with `ssl_check_hostname=True` (assert kwargs / monkeypatched factory).
- [x] 5.2 BUG-07 / D16 — `bootstrap.py` `run()`: validate `config.ca_cert_path` exists at the top (`sys.exit(1)` with explicit message if absent); replace `verify=False` with `verify=str(config.ca_cert_path)` in `httpx.post`. Do not let the response `ca_cert_pem` replace `ca_cert_path`. Tests: (a) missing `ca_cert_path` → `SystemExit(1)`; (b) `httpx.post` is called with `verify=str(config.ca_cert_path)`.
- [x] 5.3 BUG-06 — `__main__.py` `_cert_renewal_loop`: load the private key from `certs_dir/agent-key.pem` via `serialization.load_pem_private_key` and pass it as `private_key=` to `verify_cert(new_cert_pem, ca_cert_pem, cfg.agent_id, private_key=key)`. Test: renewal where the new cert's public key does not match the local key raises and the new cert is NOT persisted (old cert intact).

## 6. Baseline ordering — detector (D14 / RN-112, structural; do last)

- [x] 6.1 BUG-01 — `detector.py` `file_deleted` branch (line ~366): call `evaluate_and_act` BEFORE touching the baseline; call `mark_absent(path)` only if the action was not a successful `auto_restore`; on successful restore call `write_entry(path)` (file recreated). Test: a watched file with an `auto_restore` rule is deleted → file is restored and the baseline reflects present/known-good (regression: restore on delete no longer always fails).
- [x] 6.2 BUG-02 — `detector.py` `file_created` branch (line ~409): call `evaluate_and_act` BEFORE `write_entry`; call `write_entry(path)` only if the action was not a successful `quarantine`; on successful quarantine call `mark_absent(path)`. Test: a created file matching a `quarantine` rule → file quarantined and baseline reflects absent (no inconsistent `present` entry).
- [x] 6.3 BUG-03 — `detector.py` `file_modified` non-restore else-branch (line ~503): for `alert_only`/`manual_review`, call only `add_snapshot(path, new_hash, new_content)`; REMOVE the `write_entry(path)` call so the active `content_b64`/`hash` stay pinned to the known-good state. Test: modify a watched file under an `alert_only` rule, then assert `select_restorable_content(entry)` still returns the original known-good content (not the attacker's bytes). This test is the gate that proves the D14 invariant.
- [x] 6.4 BUG-03 — confirm `baseline.add_snapshot` stores the new content for audit WITHOUT promoting it to the active entry (per D14: `add_snapshot` already exists, no interface change). If the current signature reads the file itself, verify it does not overwrite active `content_b64`; adjust the detector call to match the real signature. Covered by the 6.3 assertion.

## 7. Integration & docs

- [x] 7.1 Run the full agent test suite (`agent/tests/`); ensure all new regression tests pass and no existing test regresses.
- [x] 7.2 Update `agent/deploy/config.yaml.example` and the agent install doc to state that the operator must pre-provision `ca_cert_path` before first bootstrap (D16 operational requirement).
- [x] 7.3 Append the C28 `agent-audit-fixes` row to the CHANGES.md roadmap table (capa: agente; depende de: C27; origen: auditoría 2026-06-26; decisiones D14–D17). Docs edit, outside OPSX.
