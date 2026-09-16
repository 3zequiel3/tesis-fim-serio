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

