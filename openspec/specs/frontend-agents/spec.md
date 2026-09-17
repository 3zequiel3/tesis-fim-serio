# frontend-agents Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: Admin can view the agent list with operational status (RN-92, RN-93)
The system SHALL display all registered agents with their status (online/offline/draining/dead), queue_pressure indicator, and last-seen timestamp.

#### Scenario: Agent list loads
- **WHEN** admin navigates to /agents
- **THEN** system fetches GET /agents and displays each agent with status badge, queue_pressure bar, and last-seen time

#### Scenario: Draining agent disables all actions (RN-92)
- **WHEN** an agent has status "draining"
- **THEN** all action buttons (config, rescan) are disabled and a tooltip explains the draining state

### Requirement: Admin can manage agent watch paths
The system SHALL allow an admin to edit the list of paths monitored by an agent via POST /agents/{id}/config using replace-all semantics.

#### Scenario: Path added and saved
- **WHEN** admin adds a new path to the list and saves
- **THEN** system calls POST /agents/{id}/config with the complete updated path list and shows a success confirmation

#### Scenario: Path removed and saved
- **WHEN** admin removes a path from the list and saves
- **THEN** system calls POST /agents/{id}/config with the reduced path list and shows a success confirmation

### Requirement: Admin can trigger rescan with pending-events confirmation (RN-70)
The system SHALL show a confirmation dialog with the count of pending events to be superseded before forcing a rescan.

#### Scenario: Rescan with no pending events
- **WHEN** admin clicks rescan and POST /agents/{id}/rescan?force=false returns 200
- **THEN** system confirms success without showing a dialog

#### Scenario: Rescan blocked by pending events — dialog shown
- **WHEN** POST /agents/{id}/rescan?force=false returns 409 with code "pending_events_exist"
- **THEN** system displays a confirmation dialog showing the count of pending events that will be superseded

#### Scenario: Rescan confirmed after 409
- **WHEN** admin clicks "Force rescan" in the confirmation dialog
- **THEN** system calls POST /agents/{id}/rescan?force=true

#### Scenario: Rescan cancelled after 409
- **WHEN** admin clicks "Cancel" in the confirmation dialog
- **THEN** system takes no action and closes the dialog

### Requirement: Time since last heartbeat is correct and cannot be negative

The agent card SHALL compute the interval since `last_heartbeat` from the instant the backend reported, parsed unambiguously, and render it through the shared display helper (`frontend-time-display`).

`formatLastSeen` in `frontend/src/components/ui/AgentCard.tsx:59-66` computes `Date.now() - d.getTime()` over a value the API emits without a zone designator. ECMAScript reads such a string as local time, so in a UTC−3 zone the parsed instant lands three hours ahead of the real one and a **healthy agent that has just sent a heartbeat produces a negative elapsed time**. It is the most visible symptom of the defect and the one that makes the agent view untrustworthy: the card that is supposed to answer "is this agent alive?" answers with an impossibility.

#### Scenario: A fresh heartbeat shows a small positive interval
- **WHEN** an agent's `last_heartbeat` is a few seconds in the past and the viewer's zone is `America/Argentina/Buenos_Aires`
- **THEN** the card shows a small positive interval, and never a negative one

#### Scenario: The interval is correct across zones
- **WHEN** the same `last_heartbeat` is rendered under two viewer zones with different offsets
- **THEN** the elapsed interval shown is the same in both, because the interval is a property of the instants and not of the display zone

#### Scenario: An agent that has never reported shows an absence
- **WHEN** `last_heartbeat` is `null`
- **THEN** the card shows an explicit "nunca", not a computed interval

#### Scenario: A heartbeat dated in the future is surfaced
- **WHEN** an agent reports a `last_heartbeat` later than the viewer's clock, as a desynchronised host would
- **THEN** the card indicates a future instant rather than showing a negative interval, since a skewed agent clock is the condition RN-90 and RN-131 exist to detect

### Requirement: The agent card exposes the absolute instant of the last heartbeat

The card SHALL make the absolute instant of the last heartbeat available with its zone, alongside the relative form.

The relative form alone ("hace 4 min") is what the card shows today. It is the right primary reading for deciding whether an agent is alive, but it cannot be correlated against anything: an operator reconciling the console with `journalctl` on the agent host needs the instant and the clock it is stated in.

#### Scenario: The absolute instant is reachable from the card
- **WHEN** the agent card is displayed for an agent that has reported a heartbeat
- **THEN** the absolute instant is available with its zone, without navigating away from the agent view

#### Scenario: The relative and absolute forms agree
- **WHEN** both forms are shown for the same heartbeat
- **THEN** they denote the same instant

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

