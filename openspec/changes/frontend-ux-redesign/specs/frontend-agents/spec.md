## MODIFIED Requirements

### Requirement: Admin can manage agent watch paths
The system SHALL allow an admin to edit the list of paths monitored by an agent via POST /agents/{id}/config using replace-all semantics. When the admin saves, a path typed in the input but not yet added MUST be included in the saved list if it is a valid path, and MUST block the save with an inline message if it is not. The editor MUST NOT send an empty list: the save action is disabled while the resulting list would be empty, with the message «El agente necesita al menos una ruta vigilada.». The editor MUST apply the same client-side checks as the backend (absolute, no `..` segment, no control characters, at most 1.024 characters, at most 64 paths, no duplicates ignoring a trailing slash; D91/RN-185) and MUST show a backend `422` through the shared error reader, pointing at the entry given by `detail.index` when present. The editor is visible only to a user with `role = admin` (D93/RN-187).

#### Scenario: Path added and saved
- **WHEN** admin adds a new path to the list and saves
- **THEN** system calls POST /agents/{id}/config with the complete updated path list and shows a success confirmation

#### Scenario: Path removed and saved
- **WHEN** admin removes a path from the list and saves
- **THEN** system calls POST /agents/{id}/config with the reduced path list and shows a success confirmation

#### Scenario: Typed path without Add is included
- **WHEN** the list is `["/etc"]`, the admin types `/var/www` in the input without pressing Add, and saves
- **THEN** system calls POST /agents/{id}/config with `["/etc", "/var/www"]`

#### Scenario: Empty list cannot be saved
- **WHEN** the admin removes the last path and leaves the input empty
- **THEN** the save action is disabled, the message «El agente necesita al menos una ruta vigilada.» is shown, and no request is sent

#### Scenario: Invalid typed path blocks the save
- **WHEN** the admin types `var/www` and saves
- **THEN** an inline message explains that the path must be absolute and no request is sent

#### Scenario: Backend rejection points at the entry
- **WHEN** POST /agents/{id}/config returns 422 with `{"detail": {"code": "watch_path_duplicate", "message": "...", "index": 1}}`
- **THEN** the message is shown next to the second entry

### Requirement: Admin can trigger rescan with pending-events confirmation (RN-70)
The system SHALL show a confirmation dialog with the count of pending events to be superseded before forcing a rescan. The count MUST be read from `detail.count` of the 409 body through the shared error reader (D90/RN-184). The path selection for a rescan MUST start with every current watch path selected, MUST be rebuilt from the agent's current `watch_paths` each time the dialog opens, and MUST disable the confirm action while no path is selected instead of rescanning every path; selecting every path sends the explicit list. The dialog MUST NOT close while its request is in flight.

#### Scenario: Rescan with no pending events
- **WHEN** admin clicks rescan and POST /agents/{id}/rescan?force=false returns 200
- **THEN** system confirms success without showing a dialog

#### Scenario: Rescan blocked by pending events — dialog shown
- **WHEN** POST /agents/{id}/rescan?force=false returns 409 with body `{"detail": {"code": "pending_events_exist", "count": 3}}`
- **THEN** system displays a confirmation dialog stating that 3 pending events will be superseded

#### Scenario: Rescan confirmed after 409
- **WHEN** admin clicks "Force rescan" in the confirmation dialog
- **THEN** system calls POST /agents/{id}/rescan?force=true

#### Scenario: Rescan cancelled after 409
- **WHEN** admin clicks "Cancel" in the confirmation dialog
- **THEN** system takes no action and closes the dialog

#### Scenario: Empty selection cannot rescan everything
- **WHEN** the admin unchecks every path in the rescan selection
- **THEN** the confirm action is disabled and no request is sent

#### Scenario: Selection follows the current watch paths
- **WHEN** the agent's watch paths change from `["/etc"]` to `["/etc", "/srv"]` and the admin opens the rescan dialog again
- **THEN** both paths are listed and selected
