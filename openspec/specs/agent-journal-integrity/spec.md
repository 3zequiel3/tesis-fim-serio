# agent-journal-integrity Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

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

### Requirement: A journal entry stays pending until backend publish is confirmed

A journal entry SHALL NOT transition out of `state: "pending"` to a terminal state (`completed` or `failed`) until the corresponding event has been successfully published to the `events` stream. The terminal-state commit MUST be deferred behind a `commit_fn` callable that the caller invokes only after `await publisher.publish(...)` returns without raising. If publish raises (e.g., Valkey outage between the physical action and publish), the entry MUST remain `pending` so it is rehydrated and re-published on the next restart, with no permanent event loss. (FA3, RN-75, RN-83)

#### Scenario: Publish failure leaves the entry pending for rehydration
- **WHEN** the physical action completes but `publisher.publish(...)` raises before the terminal commit
- **THEN** the journal entry remains `state: "pending"` and is returned by `load_pending` on the next restart for re-publication

#### Scenario: Terminal commit happens only after a successful publish
- **WHEN** `publisher.publish(...)` returns without raising
- **THEN** the deferred `commit_fn` is invoked, moving the entry from `pending` to its terminal state (`completed` or `failed`)

#### Scenario: A completed entry is never observed without a confirmed publish
- **WHEN** the agent inspects journal state immediately after the physical action but before publish confirmation
- **THEN** the entry is still `pending`, never prematurely `completed`
