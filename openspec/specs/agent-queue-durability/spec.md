# agent-queue-durability Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: FIFO ordering survives variable-length timestamps

The offline event queue SHALL order its files chronologically regardless of the number of digits in the epoch-millisecond timestamp. The file name MUST encode the timestamp zero-padded to a fixed width of 16 digits (`{detected_at_ms:016d}_{event_id}.json`) so that a lexicographic sort of file names is equivalent to a chronological sort. This enforces FIFO drain order (RN-39).

#### Scenario: Timestamps of different digit length sort chronologically
- **WHEN** the queue contains one event with a 12-digit timestamp and one with a 13-digit timestamp
- **THEN** the file whose timestamp is chronologically older sorts first in `_json_files`, independent of digit count

#### Scenario: FIFO drain returns oldest first
- **WHEN** events are enqueued out of timestamp order and then drained
- **THEN** they are returned oldest-timestamp-first

### Requirement: drop-oldest removes the chronologically oldest event

When enqueuing an event would exceed the 100 MB queue limit, the queue SHALL delete the chronologically oldest event(s) until the new event fits (RN-84). The deletion MUST target the file with the smallest timestamp, never the newest.

#### Scenario: Eviction under pressure deletes the oldest event
- **WHEN** the queue is at capacity and a new event is enqueued
- **THEN** the event with the smallest (oldest) timestamp is unlinked, and the newest events are retained

#### Scenario: Eviction with mixed-length legacy and padded names
- **WHEN** the queue holds both legacy (non-padded) and new (16-digit padded) file names and eviction runs
- **THEN** the chronologically oldest event is deleted, not a newer one mis-ordered by lexicographic comparison

### Requirement: Legacy queue file names are tolerated

The queue SHALL continue to operate correctly on file names written by a previous version without the zero-pad. Removal by `event_id` MUST keep working because `event_id` (UUID v4) contains no underscore and the name is split on the first underscore only.

#### Scenario: Remove by event_id works for padded and legacy names
- **WHEN** `remove(event_id)` is called and a matching file exists under either the padded or the legacy naming scheme
- **THEN** the file is unlinked and the call returns `true`

### Requirement: Queue files carry retry metadata in an envelope and tolerate the previous bare-payload format

Each queue file SHALL hold an envelope containing the event payload plus the durable retry metadata: the payload under a `payload` key, an integer attempt count, and the timestamp of the first publication attempt.

Reading SHALL detect the format: a loaded object that does not carry a `payload` key is a file written by an earlier agent version and SHALL be wrapped as an envelope with an attempt count of zero. No migration script, no manual step, and no loss of an existing queue. This is the same tolerance criterion already applied to legacy queue file names.

The file naming scheme (`{detected_at_epoch_ms:016d}_{event_id}.json`), the FIFO ordering by name prefix, the atomic write via temporary file plus rename, the removal by `event_id`, the 100 MB budget and the drop-oldest policy SHALL all remain unchanged (RN-38 to RN-41, RN-84).

Incrementing the attempt count SHALL rewrite the envelope with the same atomic write used for enqueueing. (D37 / RN-131)

#### Scenario: An enqueued event starts at zero attempts

- **WHEN** a newly detected event is enqueued
- **THEN** its queue file holds an envelope whose attempt count is zero and whose `payload` key carries the event payload

#### Scenario: A queue file written by an earlier version is read as zero attempts

- **WHEN** the queue directory contains a file holding a bare payload object with no `payload` key
- **THEN** it is read as an event with an attempt count of zero and is published normally

#### Scenario: A mixed queue directory drains in FIFO order

- **WHEN** the queue holds both envelope files and bare-payload files from an earlier version
- **THEN** all of them are drained in timestamp-prefix order and none is skipped

#### Scenario: The attempt count is durable across a restart

- **WHEN** an event's attempt count is incremented and the agent restarts
- **THEN** the count read from disk is the incremented value

#### Scenario: The envelope rewrite is atomic

- **WHEN** the process is interrupted while rewriting an envelope
- **THEN** the queue directory holds either the previous complete file or the new complete file, and any orphaned temporary file is swept on the next startup

#### Scenario: Removal by event_id still works on the envelope format

- **WHEN** an `event_ack` arrives for an event stored as an envelope
- **THEN** its queue file is removed by `event_id` exactly as before

### Requirement: Discarded events are archived in a bounded local directory separate from the queue

The agent SHALL maintain a discard directory, configurable and defaulting to a sibling of the queue directory, holding events that will never be published again. Each discard record SHALL carry the event payload, the discard reason, the attempt count and the discard timestamp, and SHALL use the same name scheme as the queue so that chronological ordering is preserved.

The discard reason SHALL come from a closed lowercase snake_case vocabulary (RN-71): `max_attempts_exceeded`, `invalid_schema`, `clock_skew`.

The discard directory SHALL NOT count toward the queue's 100 MB budget and SHALL NOT contribute to `queue_pressure`. Mixing the two budgets would let a discard evict a live event through drop-oldest.

The discard directory SHALL be bounded by a configurable file count with its own drop-oldest policy, so that a host with a persistent problem cannot fill its disk. (D37 / RN-131, RN-71, RN-84)

#### Scenario: A discarded event leaves the queue and enters the discard directory

- **WHEN** an event reaches its attempt ceiling
- **THEN** its queue file no longer exists and a discard record for it exists carrying reason `max_attempts_exceeded` and its final attempt count

#### Scenario: A terminal nack files the event with the nack's reason

- **WHEN** an event is removed because of a terminal `event_nack` with reason `invalid_schema`
- **THEN** the discard record carries reason `invalid_schema`

#### Scenario: Discards do not consume the queue budget

- **WHEN** the discard directory holds several records
- **THEN** `queue_pressure` and the 100 MB accounting reflect only the queue files

#### Scenario: The discard directory drops the oldest records past its bound

- **WHEN** the number of discard records exceeds the configured bound
- **THEN** the chronologically oldest records are removed until the bound is met

#### Scenario: The discard directory is created on demand with restrictive permissions

- **WHEN** the first event is discarded and the directory does not exist
- **THEN** it is created before the record is written, following the same permission conventions as the queue directory

