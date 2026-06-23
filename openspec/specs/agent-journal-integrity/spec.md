## ADDED Requirements

### Requirement: Journal entries are written atomically

Every journal write SHALL be atomic: the entry MUST be written to a temporary file, flushed and `fsync`-ed, then moved into place with `os.replace`. A process death mid-write MUST NOT leave a partially-written (truncated) entry at the target path (RN-83).

#### Scenario: Process death mid-write leaves no truncated entry
- **WHEN** the process is interrupted while writing a journal entry
- **THEN** the target path either contains the complete previous entry or no entry, never a truncated one, because the partial write lives only in the temporary file

#### Scenario: Pending action survives restart
- **WHEN** a pending entry was written atomically and the agent restarts
- **THEN** `load_pending` returns that entry for rehydration

### Requirement: Journal entries carry an HMAC over their content

Each journal entry SHALL include an HMAC-SHA256 computed with the agent `shared_secret` over the entry's serialized content. On read, the journal MUST recompute and verify the HMAC using a constant-time comparison before returning the entry. The HMAC field itself MUST be excluded from the signed content.

#### Scenario: Entry with a valid HMAC is returned
- **WHEN** an entry written by the agent is read back with the same `shared_secret`
- **THEN** the HMAC verifies and the entry is returned

#### Scenario: Entry with an invalid HMAC is discarded
- **WHEN** an entry's content was modified on disk so its stored HMAC no longer matches
- **THEN** the read treats it as corrupt, logs a warning, and returns `None` (the entry is not rehydrated)

#### Scenario: Truncated entry is discarded on load
- **WHEN** a truncated or unparseable entry is encountered during `load_pending`
- **THEN** it is skipped with a warning and not included in the pending set
