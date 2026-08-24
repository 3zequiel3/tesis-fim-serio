# frontend-alerts Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

### Requirement: Admin can view alerts history with filters (RN-103, D6)
The system SHALL display a paginated list of all alerts from the unified alerts table with filters by status (pending/delivered/failed) and severity.

#### Scenario: Alerts list loads
- **WHEN** admin navigates to /alerts
- **THEN** system fetches GET /alerts and displays alerts with created_at, severity, status, and delivery channel columns

#### Scenario: Filter by status applied
- **WHEN** admin selects a status filter
- **THEN** system refetches GET /alerts with the status query param and updates the list

#### Scenario: Filter by severity applied
- **WHEN** admin selects a severity filter
- **THEN** system refetches GET /alerts with the severity query param and updates the list

### Requirement: Admin can view failed alerts (RN-103)
The system SHALL display a filtered list of failed alerts (delivered_at IS NULL AND failed_at IS NOT NULL) available at /alerts/failed.

#### Scenario: Failed alerts list loads
- **WHEN** admin navigates to /alerts/failed
- **THEN** system fetches GET /alerts/failed and displays only failed alerts

### Requirement: Admin can retry a failed alert individually
The system SHALL allow an admin to retry a single failed alert via POST /alerts/{id}/retry.

#### Scenario: Individual retry succeeds
- **WHEN** admin clicks retry on a single failed alert
- **THEN** system calls POST /alerts/{id}/retry and refreshes the failed alerts list

### Requirement: Admin can retry failed alerts in bulk
The system SHALL allow an admin to select multiple failed alerts and retry them in a single action.

#### Scenario: Bulk retry
- **WHEN** admin selects multiple failed alerts and clicks bulk retry
- **THEN** system calls POST /alerts/{id}/retry for each selected alert and refreshes the list upon completion

### Requirement: Admin can discard a failed alert
The system SHALL allow an admin to permanently discard a failed alert via DELETE /alerts/{id}.

#### Scenario: Alert discarded
- **WHEN** admin confirms discard of a failed alert
- **THEN** system calls DELETE /alerts/{id} and removes it from the failed alerts list
