## ADDED Requirements

### Requirement: Admin can list monitoring rules
The system SHALL display a list of all monitoring rules with pattern, severity, action, and sync status.

#### Scenario: Rules list loads
- **WHEN** admin navigates to /rules
- **THEN** system fetches GET /rules and displays each rule with pattern, severity, action columns

#### Scenario: Empty state
- **WHEN** no rules exist
- **THEN** system displays an empty state message prompting to create the first rule

### Requirement: Admin can create a rule
The system SHALL allow an admin to create a new rule specifying a glob pattern (supporting `!` exclusions), severity (critical/high/medium/low), and action (auto_restore/quarantine/manual_review/alert_only).

#### Scenario: Successful rule creation
- **WHEN** admin submits a valid rule form
- **THEN** system calls POST /rules, closes the form, and invalidates the rules query to refresh the list

#### Scenario: Form validation blocks submission
- **WHEN** admin submits a rule with an empty pattern
- **THEN** system displays a validation error and does not call the API

### Requirement: Admin can edit an existing rule
The system SHALL allow an admin to modify an existing rule's pattern, severity, or action via PUT /rules/{id}.

#### Scenario: Successful edit
- **WHEN** admin saves edits to a rule
- **THEN** system calls PUT /rules/{id} and refreshes the rules list

### Requirement: Admin can delete a rule with confirmation
The system SHALL require explicit confirmation before deleting a rule.

#### Scenario: Delete confirmed
- **WHEN** admin confirms the delete dialog
- **THEN** system calls DELETE /rules/{id} and removes the rule from the list

#### Scenario: Delete cancelled
- **WHEN** admin cancels the delete dialog
- **THEN** system takes no action and the rule remains in the list

### Requirement: Rule sync status is visible (RN-87)
The system SHALL display a visual indicator when an agent's applied ruleset version differs from the current version after a rule mutation.

#### Scenario: Sync pending after rule save
- **WHEN** a rule is created, edited, or deleted
- **THEN** system displays a "sync pending" indicator until the next heartbeat confirms the new ruleset_version_applied matches
