## ADDED Requirements

### Requirement: An operator-initiated restore does not report its own write as a detection

`handle_restore_file` performs the same atomic write as `DecisionEngine._auto_restore` — a `.fim_restore_tmp` file opened with `O_EXCL`, `fchown` before `fchmod` (D36 / RN-130), then `os.replace` onto the final path — and therefore delivers the same `FAN_MOVED_TO` on that final path. The agent SHALL NOT publish an integrity event for that write. The guarantee is inherited from the detector's discard invariant and requires no separate mechanism in the command handler; the outcome of the command already reaches the backend through the handler's `event_ack`, carrying its reason in the closed vocabulary of D36 / RN-130. A second `file_created` event for the same path would be a duplicate notification of the same fact, presented as if it were a detection.

Because the write path is duplicated between `agent/decision.py` and `agent/commands.py` — deliberately, and documented as such — this guarantee MUST be asserted by a test rather than deduced from the duplication. A future divergence between the two copies, such as a different temporary suffix, would otherwise break it silently.

#### Scenario: A successful restore_file publishes an ack and no integrity event
- **WHEN** the agent handles a valid `restore_file` command for a monitored path and the restore succeeds
- **THEN** the file's on-disk content matches the baseline content, an `event_ack` reporting success is published, and the resulting `FAN_MOVED_TO` on that path publishes no event

#### Scenario: A failed restore_file still publishes only its ack
- **WHEN** the agent handles a `restore_file` command that fails before `os.replace` (for example `no_baseline_content` or a write error)
- **THEN** an `event_ack` reporting the failure reason is published, the monitored path is unmodified, and no integrity event is published

### Requirement: quarantine_file keeps reporting the absence it creates

`handle_quarantine_file` moves the file out of the monitored path with `shutil.move`, and the resulting `FAN_MOVED_FROM` MUST continue to produce a `file_deleted` event. The file genuinely is gone, so this is a true observation and not the false positive the restore path exhibits. It also does not feed back: the baseline entry becomes `absent` with a null hash, and `select_restorable_content` returns nothing for an absent entry, so a subsequent `auto_restore` fails with `no_restorable_content` instead of retrying.

This requirement exists to pin the asymmetry: the discard invariant applies to classifications that yield a hash, and quarantine's departure event yields none.

#### Scenario: Quarantine still produces a file_deleted event
- **WHEN** the agent handles a valid `quarantine_file` command and the move succeeds
- **THEN** an `event_ack` reporting success is published, the baseline entry for the path is marked absent, and the `FAN_MOVED_FROM` produces a `file_deleted` event

#### Scenario: A later auto_restore on the quarantined path fails instead of looping
- **WHEN** a rule with `action: "auto_restore"` covers a path whose baseline entry is absent, and a new event arrives for it
- **THEN** the action fails with `no_restorable_content`, the event is published once with `action_failed: true`, and no filesystem mutation occurs
