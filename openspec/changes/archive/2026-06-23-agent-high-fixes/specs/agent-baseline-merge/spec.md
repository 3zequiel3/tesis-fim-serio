## ADDED Requirements

### Requirement: Baseline update preserves existing encrypted content

When applying a `baseline_update` command, `update_from_command` SHALL read the existing baseline entry (if any) and merge: it MUST preserve the existing `snapshots` and `content_b64`, updating only `hash`, `status`, and the metadata derived from the command. It MUST NOT overwrite an existing entry with empty `snapshots` or null `content_b64` when prior content existed (RN-16, RN-17, RN-30).

#### Scenario: Existing snapshots are preserved across a baseline update
- **WHEN** a baseline entry already has snapshots and a `baseline_update` command arrives for the same path
- **THEN** the resulting entry keeps the existing snapshots and reflects the new hash/status

#### Scenario: Existing content_b64 is preserved across a baseline update
- **WHEN** a baseline entry already has `content_b64` and a `baseline_update` command arrives for the same path
- **THEN** the resulting entry keeps the existing `content_b64`, so a later `restore_file` does not fail with `no_baseline_content`

#### Scenario: No prior entry creates a fresh entry
- **WHEN** a `baseline_update` command arrives for a path with no existing baseline entry
- **THEN** a new entry is created with the command's hash and status, and empty content fields (no prior content to preserve)

#### Scenario: Re-delivery of the same command is idempotent
- **WHEN** the same `baseline_update` command is applied twice
- **THEN** the preserved content remains intact and the entry is not corrupted
