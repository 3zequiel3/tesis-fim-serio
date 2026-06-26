## ADDED Requirements

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
