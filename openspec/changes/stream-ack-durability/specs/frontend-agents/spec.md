## ADDED Requirements

### Requirement: The agent card surfaces locally discarded events

The agent card SHALL display the count of events the agent discarded locally, alongside the queue pressure it already shows. A discarded event is a lost detection, and it is the one operational fact the current interface cannot express at all.

The presentation SHALL distinguish three states: never reported (an agent older than this change, or one that has not sent a heartbeat yet), reported as zero, and a positive count. A positive count SHALL be presented as an anomaly rather than as ordinary telemetry — it means the transport gave up on an integrity event.

Never reported SHALL NOT be rendered as zero. Conflating "we do not know" with "nothing was discarded" would hide exactly the case the operator needs to notice. (D37 / RN-131, RN-71)

#### Scenario: A positive count is shown as an anomaly

- **WHEN** the agent reports a discard count of 4
- **THEN** the card shows the count with the visual treatment reserved for anomalous state, not the neutral treatment used for queue pressure at rest

#### Scenario: Zero is shown as healthy

- **WHEN** the agent reports a discard count of 0
- **THEN** the card shows the healthy state and no anomaly indicator

#### Scenario: An agent that never reported is not shown as zero

- **WHEN** the agent has no reported discard count
- **THEN** the card indicates that the value is unknown rather than showing zero

### Requirement: The discard presentation is a pure mapper with its own test

The mapping from the raw discard count to its presented form SHALL live in a pure function under `frontend/src/utils/`, with its own unit test covering the three states, following the pattern already established by the existing status and error mappers. The component SHALL consume that function rather than branch inline. (RN-71)

#### Scenario: The mapper covers every state

- **WHEN** the mapper is called with a positive number, with zero, and with a null or undefined value
- **THEN** it returns three distinct results and never throws

#### Scenario: The component does not duplicate the branching

- **WHEN** the agent card renders the discard count
- **THEN** it derives the presentation from the mapper rather than from inline conditionals
