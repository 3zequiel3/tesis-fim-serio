## ADDED Requirements

### Requirement: The agent stamps sent_at at every publication and signs at publication time

The agent SHALL stamp `sent_at` with the current UTC time immediately before every `XADD` to the `events` stream — the first publication, every retry, and every republication during a queue drain — and SHALL compute the HMAC-SHA256 signature over the canonical JSON of that stamped payload at that same moment.

`sent_at` MUST be covered by the signature. A field outside the signed canonical JSON could be re-stamped by a third party who captured the message, which is exactly the replay the skew window exists to detect.

Consequently the signature SHALL NOT be a property of the stored event: the queued payload SHALL be persisted without `signature` and without `sent_at`, and both SHALL be produced per transmission. `detected_at` SHALL remain in the persisted payload unchanged, as the forensic timestamp of the observed change. (D37 / RN-131, RN-79, RN-91)

#### Scenario: Two publications of the same event carry different sent_at and both signatures verify

- **WHEN** the agent publishes event `e1` and, having received no response, republishes it later
- **THEN** the two stream entries carry different `sent_at` values
- **AND** each entry's signature verifies against the canonical JSON of its own payload with the agent's shared secret

#### Scenario: detected_at is preserved across republications

- **WHEN** an event detected during an outage is drained hours later
- **THEN** its `detected_at` is the original detection time and its `sent_at` is the time of the drain

#### Scenario: The queued payload carries no signature and no sent_at

- **WHEN** an event is enqueued
- **THEN** the persisted payload contains `event_id`, `detected_at`, `schema_version` and the change data, and contains neither `signature` nor `sent_at`

#### Scenario: A rotated shared secret does not invalidate the existing queue

- **WHEN** the shared secret is rotated while the queue holds unsent events
- **THEN** the queued events are published successfully, signed with the new secret

### Requirement: The agent consumes a typed response and acts on it per reason

The agent SHALL treat `event_ack` and `event_nack` on the `commands` stream as the only authorities over the fate of a queued event, after the existing HMAC verification and `target_agent_id` filter.

- On `event_ack` for an `event_id`: remove the event from the queue and from the in-memory pending set.
- On `event_nack` carrying no `retry_after` (terminal — reasons `invalid_schema` and `clock_skew`): remove the event from the queue, stop publishing it, and record it in the local discard directory with the nack's reason as the discard reason.
- On `event_nack` carrying `retry_after` (reason `rate_limited`): **retain** the event in the queue, do not count the attempt, and enter backpressure.

The agent SHALL ignore any `event_ack` or `event_nack` whose `event_id` does not correspond to an event present in its local queue, logging the fact and taking no other action. A backend response for an unknown `event_id` MUST NOT cause any file operation. (D37 / RN-131, RN-40, RN-73, RN-106)

#### Scenario: A terminal nack removes the event and files it under discard

- **WHEN** the agent receives a signed `event_nack` for a queued `e1` with reason `clock_skew` and no `retry_after`
- **THEN** the queue file for `e1` is removed, `e1` is no longer published, and a discard record for `e1` exists with reason `clock_skew`

#### Scenario: A rate-limited nack retains the event

- **WHEN** the agent receives a signed `event_nack` for a queued `e1` with reason `rate_limited` and a `retry_after`
- **THEN** the queue file for `e1` still exists and its attempt count is unchanged

#### Scenario: A response for an event the agent does not hold is ignored

- **WHEN** the agent receives a correctly signed `event_nack` for an `event_id` that is not in its local queue
- **THEN** no queue file is removed, no discard record is written, and backpressure is not affected

#### Scenario: An unsigned or wrongly signed response is discarded before any effect

- **WHEN** a message of type `event_nack` arrives with an invalid signature
- **THEN** it is rejected by the existing verification step and no queue file is touched

### Requirement: Rate limiting triggers agent-wide backpressure and never destroys an event

On an `event_nack` with reason `rate_limited`, the agent SHALL suspend publication for the whole agent — not for the single event — until a deadline computed as the current monotonic time plus the `retry_after` value, clamped to a configured ceiling.

While backpressure is in effect:

- `publish()` SHALL continue to enqueue newly detected events to disk. Detection is never suspended; only transmission is.
- No `XADD` to the `events` stream SHALL be issued, from the initial publication, from the retry loop, or from the queue drain.
- No event SHALL be discarded on account of backpressure. The only bound on queue growth remains the 100 MB drop-oldest policy (RN-40, RN-84), which is unchanged.

The `retry_after` value SHALL be clamped to a ceiling before use, so that a malformed or hostile value cannot silence the agent for an unbounded period. A signature proves origin, not sanity.

Backpressure is agent-wide because the backend budget is per `agent_id`: if one event has no budget, none does, and retrying the others would generate guaranteed rejections. (D37 / RN-131, RN-88, RN-84)

#### Scenario: Detection continues while transmission is paused

- **WHEN** backpressure is in effect and a new change is detected
- **THEN** the event is written to the queue and no `XADD` is issued for it

#### Scenario: No stream traffic while paused

- **WHEN** backpressure is in effect and the retry loop and the drain both run
- **THEN** no entry is added to the `events` stream

#### Scenario: Publication resumes after the deadline

- **WHEN** the backpressure deadline passes
- **THEN** the next retry cycle republishes the queued events with a fresh `sent_at`

#### Scenario: An excessive retry_after is clamped

- **WHEN** an `event_nack` arrives with a `retry_after` far above the configured ceiling
- **THEN** the pause lasts at most the ceiling

#### Scenario: A rate-limited event is never discarded

- **WHEN** an event receives repeated `rate_limited` nacks
- **THEN** its attempt count does not increase and it is never moved to the discard directory

### Requirement: A per-event attempt ceiling bounds retries and ends in a local discard record

The agent SHALL maintain a durable per-event attempt count, incremented on every `XADD` of that event, and SHALL stop publishing an event once the count reaches a configured ceiling. The count MUST survive an agent restart: an in-memory count would be reset by every restart, and the queue drain republishes the whole queue on startup, so a volatile count bounds nothing.

On reaching the ceiling the agent SHALL move the event out of the queue and into the local discard directory with reason `max_attempts_exceeded`, and SHALL stop publishing it.

The discard directory SHALL hold, per event, the payload, the discard reason, the attempt count and the discard timestamp. Discard reasons form a closed lowercase snake_case vocabulary (RN-71): `max_attempts_exceeded`, `invalid_schema`, `clock_skew`.

The discard directory SHALL NOT count toward the 100 MB queue budget nor toward `queue_pressure`, and SHALL have its own bound by file count with its own drop-oldest policy. Mixing the two budgets would let a discard evict a live event.

The agent SHALL expose a cumulative count of discarded events since process start in the heartbeat, under the key `discarded_events`, following the existing pattern of the detector's drop counter. (D37 / RN-131, RN-71, RN-84, RN-92)

#### Scenario: An unanswered event is discarded once the ceiling is reached

- **WHEN** an event is published repeatedly and receives no response of any kind until its attempt count reaches the ceiling
- **THEN** the event is removed from the queue, a discard record with reason `max_attempts_exceeded` exists, and no further `XADD` is issued for it

#### Scenario: The attempt count survives a restart

- **WHEN** an event has been published several times, the agent restarts, and the drain republishes it
- **THEN** the attempt count continues from the persisted value rather than from zero

#### Scenario: Discard does not affect queue pressure

- **WHEN** events are moved to the discard directory
- **THEN** `queue_pressure` reflects only the remaining queue files and the discard directory does not contribute

#### Scenario: The discard directory is bounded

- **WHEN** the discard directory exceeds its configured file-count bound
- **THEN** the chronologically oldest discard records are removed first

#### Scenario: The heartbeat carries the cumulative discard count

- **WHEN** three events have been discarded since process start
- **THEN** the heartbeat payload carries `discarded_events` equal to 3

#### Scenario: An agent that has discarded nothing reports zero

- **WHEN** no event has been discarded since process start
- **THEN** the heartbeat payload carries `discarded_events` equal to 0
