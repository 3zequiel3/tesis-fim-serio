# agent-change-detection-integrity Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

### Requirement: Pending-event ack lookup is O(1) and corruption-free

The detector SHALL maintain a reverse index mapping `event_id` to `path` alongside the forward `path → event_id` map, so that acknowledging an event resolves and removes the pending entry in constant time without iterating over the pending map. Both maps SHALL be updated together within the same synchronous section so they never diverge. (RN-40, RN-73)

#### Scenario: Ack removes the pending entry in O(1)

- **WHEN** the detector records a pending event for a path and later receives `on_ack(event_id)` for that event
- **THEN** the pending entry for that path is removed using the reverse index without scanning all pending entries
- **AND** the reverse index no longer contains that `event_id`.

#### Scenario: Forward and reverse maps stay consistent

- **WHEN** a new event for an already-pending path supersedes the previous one
- **THEN** the forward map points the path to the new `event_id`, the reverse index maps the new `event_id` to the path, and the superseded `event_id` is no longer present in the reverse index.

#### Scenario: Ack for an unknown event is a safe no-op

- **WHEN** `on_ack(event_id)` is called with an `event_id` not present in the reverse index
- **THEN** no entry is removed and no error is raised.

#### Scenario: Concurrent acks during active monitoring do not corrupt state

- **WHEN** the detector is recording new pending events while acks arrive for previously pending events within the same asyncio event loop
- **THEN** the pending map and reverse index remain consistent, with no lost or duplicated `parent_event_id` linkage and no `RuntimeError` from mutate-during-iterate.

### Requirement: Transient file disappearance does not produce false file_absent

The detector SHALL hash a changed file with bounded retries and backoff before concluding the file is absent. Only after the retries are exhausted with a persistent `FileNotFoundError` SHALL the detector emit a `file_absent` event and mark the baseline absent. When the file is present, hashing SHALL succeed on the first attempt with no added latency. (RN-01, RN-93)

#### Scenario: Atomic-write rename race does not destroy the baseline

- **WHEN** a fanotify event fires for a file that is momentarily missing because an editor used write-tmp + rename, and the file is present again within the retry window
- **THEN** a retry succeeds, the detector reads a valid hash, emits `file_modified` (not `file_absent`), and the baseline is NOT marked absent.

#### Scenario: Genuinely deleted file still emits file_absent

- **WHEN** a fanotify event fires for a file that remains absent across all retry attempts
- **THEN** the detector emits a `file_absent` event and marks the baseline absent for that path.

#### Scenario: Present file has zero added latency

- **WHEN** the file exists at the moment of hashing
- **THEN** the hash is computed on the first attempt with no backoff sleeps incurred.

#### Scenario: Retry budget is bounded

- **WHEN** the file is persistently absent
- **THEN** the total time spent retrying does not exceed the configured backoff budget (3 attempts, ≤150 ms total) before emitting `file_absent`.
