## ADDED Requirements

### Requirement: EventOut expone detected_offline

El esquema de salida `EventOut` (`backend/app/modules/events/router.py`) SHALL exponer `detected_offline: bool | None = None`, con el mismo patrón aditivo usado para `is_symlink`, `action_failed` y `action_error`. Las respuestas de `GET /events` y `GET /events/{id}` SHALL incluir el campo en todo evento. No SHALL agregarse filtro, orden ni parámetro de consulta nuevo. El cambio MUST NOT romper a los clientes existentes. (D80 / RN-174)

#### Scenario: Evento detectado offline
- **WHEN** un cliente obtiene un evento ingerido con `detected_offline = true`
- **THEN** la respuesta incluye `detected_offline: true`

#### Scenario: Evento anterior a la columna
- **WHEN** un cliente obtiene un evento con `detected_offline IS NULL`
- **THEN** la respuesta incluye `detected_offline: null`
