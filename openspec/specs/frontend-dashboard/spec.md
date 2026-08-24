# frontend-dashboard Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

### Requirement: Dashboard shows event counters by status (RN-101)
The system SHALL display aggregate counts of events grouped by status (pending, approved, rejected, auto_restored, quarantined), refreshed automatically.

#### Scenario: Event counters load
- **WHEN** admin navigates to /dashboard
- **THEN** system displays event counts per status, refreshed every 30 seconds

### Requirement: Dashboard highlights critical and high pending events (RN-101, RN-102)
The system SHALL display the count of pending events with severity critical or high prominently, distinct from the total pending count.

#### Scenario: Critical/high pending shown prominently
- **WHEN** there are pending events with severity critical or high
- **THEN** system displays their count with visual emphasis separate from total pending count

### Requirement: Dashboard shows agent summary
The system SHALL display the count of registered agents grouped by status (online/offline/draining/dead).

#### Scenario: Agent summary loads
- **WHEN** admin navigates to /dashboard
- **THEN** system displays agent counts per status, refreshed every 30 seconds
