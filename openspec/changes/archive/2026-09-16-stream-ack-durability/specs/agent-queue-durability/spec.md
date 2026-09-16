## ADDED Requirements

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
