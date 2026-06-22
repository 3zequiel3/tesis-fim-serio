## ADDED Requirements

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
