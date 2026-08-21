## ADDED Requirements

### Requirement: A successful auto_restore converges in one turn and the event count per path is bounded by the real modifications

The detect → remediate → observe cycle SHALL be a fixed point. When a rule with `action: "auto_restore"` matches a path, N real modifications to that path MUST produce **at most N** published events — never N×k. The restore writes content that RN-32 verifies against the baseline hash and RN-33 declares identical to it, so the `FAN_MOVED_TO` that `os.replace` delivers on the final path is observed as "no change" and discarded by the detector. The engine itself is unchanged: it neither tracks how many times it restored a path nor refuses to act.

Rules are evaluated by path, not by event type — `RulesCache.evaluate` matches the path against glob patterns and never receives the `event_type`. Therefore **any** `auto_restore` rule covering the path is sufficient to close the cycle; no special `file_created` rule is required, contrary to what D19 / RN-117 assumed when it described the loop. The bound above MUST hold for the ordinary `auto_restore` rule that RN-30 describes as the normal case.

The event that survives is the one describing the tampering, not the one describing the repair: the `file_modified` event carries `action: "auto_restore"` and, per D35 / RN-129, is ingested as `auto_restored`. The restore emits nothing of its own.

#### Scenario: One tamper under an auto_restore rule produces exactly one event
- **WHEN** a monitored file covered by an `auto_restore` rule is modified once and the engine restores it successfully
- **THEN** exactly one event is published, with `event_type: "file_modified"`, `action: "auto_restore"` and `action_failed: false`

#### Scenario: N tampers produce at most N events
- **WHEN** the same path is modified N times in sequence, each followed by a successful restore and by the `MOVED_TO` the kernel delivers for it
- **THEN** the total number of published events is at most N

#### Scenario: The restore is observable on the real filesystem
- **WHEN** the engine restores a tampered file
- **THEN** the file's on-disk content equals the known-good baseline content, its mode, uid and gid are the ones recorded in the baseline entry (D36 / RN-130), and the journal entry for the event reaches its completed state

#### Scenario: A failed restore emits once and does not loop either
- **WHEN** the engine attempts an `auto_restore` that fails (for example `no_restorable_content`)
- **THEN** exactly one event is published with `action_failed: true`, no filesystem mutation reaches the monitored path, and no further events follow

#### Scenario: The baseline is not rewritten by the restore round trip
- **WHEN** a tamper-and-restore cycle completes
- **THEN** the baseline entry for that path still holds the original known-good hash, content and metadata, so a later restore has the same source available (RN-33)
