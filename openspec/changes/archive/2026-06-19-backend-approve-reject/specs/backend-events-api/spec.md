# Spec: backend-events-api (delta)

Capability: Delta sobre la API REST de consulta de eventos — agrega el comportamiento explícito de `resolved_at` y `resolved_by` tras approve/reject.

---

## ADDED Requirements

### Requirement: resolved_at y resolved_by se populan al aprobar o rechazar un evento

Cuando un evento transiciona de `pending` a `approved` o `rejected` via `POST /actions/approve` o `POST /actions/reject`, el sistema SHALL poblar los campos `resolved_at` (timestamp UTC de la acción) y `resolved_by` (user_id del admin que ejecutó la acción). Estos campos SHALL ser retornados en la respuesta de `GET /events/{id}` y en los ítems de `GET /events`.

#### Scenario: GET /events/{id} tras approve muestra resolved_at y resolved_by
- **WHEN** un evento fue aprobado y se hace `GET /events/{id}` para ese evento
- **THEN** la respuesta incluye `resolved_at` con el timestamp de la aprobación
- **AND** la respuesta incluye `resolved_by` con el `user_id` del admin que aprobó
- **AND** `status` es `approved`

#### Scenario: GET /events/{id} de evento pending tiene resolved_at null
- **WHEN** un evento tiene `status=pending`
- **THEN** `resolved_at` y `resolved_by` son `null` en la respuesta

#### Scenario: GET /events filtra por status=approved correctamente
- **WHEN** se hace `GET /events?status=approved`
- **THEN** todos los ítems retornados tienen `status=approved` y `resolved_at` no nulo
