## ADDED Requirements

### Requirement: Events UI distinguishes symlink events with a badge and target

The events table and the event detail view SHALL visually distinguish an event that represents a symlink from an event that represents a regular file, using a badge/indicator, and SHALL show the `symlink_target` string. The event type in `frontend/src/api/events.ts` SHALL gain the `is_symlink: boolean` and `symlink_target: string | null` fields consumed from `EventOut`. The badge MUST render only when `is_symlink` is true; regular-file events MUST render unchanged. (D33 / RN-127)

#### Scenario: Symlink event shows a badge and its target in the table
- **WHEN** the events table renders a row whose `is_symlink` is true
- **THEN** the row shows a symlink badge/indicator and surfaces the `symlink_target`

#### Scenario: Symlink event detail shows the target
- **WHEN** the event detail view opens for an event whose `is_symlink` is true
- **THEN** the detail displays the symlink indicator and the `symlink_target` string

#### Scenario: Regular-file event renders without the symlink indicator
- **WHEN** the table or detail renders an event whose `is_symlink` is false
- **THEN** no symlink badge is shown and the existing regular-file rendering is unchanged
