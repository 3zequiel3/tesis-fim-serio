## ADDED Requirements

### Requirement: ingest_event persists symlink metadata from the payload

`ingest_event` (`backend/app/modules/events/service.py`) SHALL read `is_symlink` and `symlink_target` from the incoming stream payload using tolerant `.get()` access (defaulting to `False` and `None` respectively) and persist them onto the `Event` row. Because the reader is tolerant, events published by older agents that omit these keys MUST ingest without error. The existing cheap-to-expensive validation order and the superseded-chain / optimistic-locking behavior MUST remain unchanged. (D33 / RN-127)

#### Scenario: Symlink event payload is persisted with its metadata
- **WHEN** the consumer ingests a payload with `is_symlink=true` and `symlink_target` set
- **THEN** `ingest_event` persists both values onto the `Event` row

#### Scenario: Payload without symlink keys ingests with defaults
- **WHEN** the consumer ingests a payload from an older agent that omits `is_symlink`/`symlink_target`
- **THEN** `ingest_event` defaults them to `false`/`null` via `.get()` and ingests the event without error

#### Scenario: Symlink metadata extraction does not alter validation or supersede behavior
- **WHEN** a symlink event participates in a superseded chain or optimistic-locking race
- **THEN** the existing validation order and supersede/locking behavior are unchanged by the added metadata extraction
