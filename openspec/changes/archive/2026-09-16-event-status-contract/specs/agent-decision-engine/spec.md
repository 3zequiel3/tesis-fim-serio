## ADDED Requirements

### Requirement: The decision engine never overwrites event_type with the action result

`_auto_restore` (`agent/decision.py`) SHALL NOT overwrite `payload["event_type"]` with the literal `"auto_restored"`. That field has a declared closed vocabulary — `file_modified | file_absent | file_deleted | file_created` (`agent/detector.py:66`) — and overwriting it violates the RN-71 canonical lexicon by mixing a filesystem operation type with an action outcome. The asymmetry is itself evidence of the defect: `_quarantine` never performed the symmetric overwrite, so `event_type` could not be a reliable carrier of the action result in the first place. After this change `event_type` SHALL always carry the filesystem operation type, and the outcome of the automatic action SHALL travel exclusively in `action` and `action_failed`. No symmetric overwrite SHALL be added to `_quarantine` or to any other action handler. (D35 / RN-129, RN-71)

#### Scenario: Auto-restored event keeps its filesystem operation type
- **WHEN** the decision engine auto-restores a modified file
- **THEN** the published payload has `event_type = "file_modified"` and `action = "auto_restore"`, and `event_type` is never set to `"auto_restored"`

#### Scenario: Quarantined event keeps its filesystem operation type
- **WHEN** the decision engine quarantines a file
- **THEN** the published payload keeps its original `event_type` and carries `action = "quarantine"`, with no new overwrite introduced

#### Scenario: Detector logging observes the real operation type
- **WHEN** the detector logs the enriched payload after `evaluate_and_act`
- **THEN** the logged `event_type` is the real filesystem operation type rather than the action outcome

### Requirement: Journal rehydration produces a payload consistent with the status derivation

The journal rehydration path (`agent/decision.py`, `rehydrate`) hand-builds its event payload as a dict literal rather than deriving it from a `DetectedChange`, and sets `action` on it directly. That payload SHALL carry `action` and `action_failed` with the same semantics as the normal path, so that the backend derivation of D35/RN-129 yields the same status for a rehydrated event as it would have for the original one. Because rehydration calls `_auto_restore`, it inherits the removal of the `event_type` overwrite and MUST NOT reintroduce it: its `event_type` SHALL remain the value the journal entry carries. This path executes only after an agent crash and has no contract coverage, so conformance SHALL be established by test rather than by inspection. (D35 / RN-129, RN-75)

#### Scenario: Rehydrated auto_restore entry yields the same status as the normal path
- **WHEN** a pending journal entry with `action = "auto_restore"` is rehydrated and republished after an agent restart
- **THEN** the backend derives `auto_restored` for it, identically to an event produced by the normal detection path

#### Scenario: Rehydrated failed entry yields pending
- **WHEN** a rehydrated entry sets `action_failed = true`
- **THEN** the backend derives `pending` for it, keeping the incident in the operator queue

#### Scenario: Rehydrated payload does not carry a polluted event_type
- **WHEN** a rehydrated entry passes through `_auto_restore`
- **THEN** its `event_type` retains the journal entry's value and is not overwritten with `"auto_restored"`
