## ADDED Requirements

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
