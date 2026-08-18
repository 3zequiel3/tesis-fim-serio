## ADDED Requirements

### Requirement: The agent card distinguishes a remediable watch path from a detection-only one

The watch path list on the agent card SHALL show, per path, whether that path is remediation-capable or detection-only, together with the reason when it is not. Today each path renders as a plain truncated string with no health signal, so an operator has no way to know that automatic remediation cannot run there.

The classification SHALL be rendered through a pure mapper that turns the raw value into a label and a style, following the isolated-and-tested mapper pattern already used elsewhere in the frontend, rather than another inline class map.

Labels SHALL be prose, not the raw field value, and SHALL communicate that the path is still monitored. A degraded path is a **partial** capability, not a failure: reading "detection-only" as "the agent is broken" is the specific misreading this requirement exists to prevent, so the visual treatment SHALL be distinct from the treatment of an offline or dead agent.

An agent that reports no status map — an older agent, or one that has not yet sent a heartbeat — SHALL render the path list exactly as it does today, with no indicator, rather than defaulting every path to either state. (D36 / RN-130, RN-92)

#### Scenario: A non-writable path is marked detection-only with its cause

- **WHEN** an agent reports a watch path as being on a read-only mount
- **THEN** the card shows that path as detection-only with a label conveying that it is monitored but not remediable

#### Scenario: A writable path shows no alarming indicator

- **WHEN** every reported watch path is writable
- **THEN** the card shows no degradation indicator on the path list

#### Scenario: A missing path is distinguished from a permission problem

- **WHEN** an agent reports one path as missing and another as permission-denied
- **THEN** the two render with distinct labels

#### Scenario: The degraded indicator is not confused with an offline agent

- **WHEN** an online agent reports a detection-only path
- **THEN** the agent's own status badge still reads online and the path indicator is visually distinct from it

#### Scenario: An agent with no reported status renders unchanged

- **WHEN** an agent has no status map
- **THEN** its watch paths render as plain entries with no indicator
