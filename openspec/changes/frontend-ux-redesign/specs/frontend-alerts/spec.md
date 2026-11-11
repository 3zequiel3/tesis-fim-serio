## MODIFIED Requirements

### Requirement: Admin can view failed alerts (RN-103)
The system SHALL display a filtered list of failed alerts (delivered_at IS NULL AND failed_at IS NOT NULL) available at /alerts/failed. Each row MUST show a link to the related event (`/events/{event_id}`), the severity, `failed_at` through the shared time helper, `retry_count`, `last_error` (truncated with the full text available on demand), and the channel; a `null` channel MUST read «sin canal entregado». The view MUST offer «Reintentar todas», which retries every listed alert sequentially, reports how many succeeded and failed, and refreshes the list and the failed-alerts banner count. The view MUST have loading, empty («No hay alertas fallidas.») and error-with-retry states, and its mutation controls are visible only to a user with `role = admin` (D93/RN-187).

#### Scenario: Failed alerts list loads
- **WHEN** admin navigates to /alerts/failed
- **THEN** system fetches GET /alerts/failed and displays only failed alerts

#### Scenario: Row shows the delivery context
- **WHEN** a failed alert has `event_id = 42`, `retry_count = 3`, `last_error = "n8n: 502"` and `channel = null`
- **THEN** the row links to `/events/42` and shows `3`, `n8n: 502` and «sin canal entregado»

#### Scenario: Retry all
- **WHEN** admin clicks «Reintentar todas» with three failed alerts listed and one retry fails
- **THEN** system calls POST /alerts/{id}/retry for each of the three, reports 2 succeeded and 1 failed, and refreshes the list and the banner count

#### Scenario: Empty list
- **WHEN** GET /alerts/failed returns no items
- **THEN** the view shows «No hay alertas fallidas.»
