## MODIFIED Requirements

### Requirement: Modelo RejectedEventAudit con RejectionReason tipado (D4, RN-105)

El sistema SHALL definir `class RejectedEventAudit(SQLModel, table=True)` en `backend/app/modules/events/models.py` con: `id: int` (PK), `event_id: str | None` (UUID si pudo parsearse), `agent_id: str`, `reason: RejectionReason`, `received_at: datetime`, `detected_at: datetime | None`, `payload_dump: str` (JSON truncado a 4 KB). El enum `RejectionReason(str, Enum)` SHALL tener exactamente los valores: `clock_skew`, `invalid_schema`, `invalid_signature`, `unknown_agent`, `duplicate_event`, `rate_limited`.

#### Scenario: Tabla rejected_events_audit creada

- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `rejected_events_audit` existe con columnas `id`, `event_id`, `agent_id`, `reason`, `received_at`, `detected_at`, `payload_dump`

#### Scenario: RejectionReason rechaza valores no canónicos

- **WHEN** se intenta construir `RejectionReason("expired")`
- **THEN** se lanza `ValueError`

#### Scenario: Los 6 valores canónicos son aceptados

- **WHEN** se crean instancias con `clock_skew`, `invalid_schema`, `invalid_signature`, `unknown_agent`, `duplicate_event`, `rate_limited`
- **THEN** cada instancia se crea sin error

#### Scenario: Rechazo por rate limit registrado con reason=rate_limited

- **WHEN** el consumer supera el rate limit para un `agent_id`
- **THEN** se inserta en `rejected_events_audit` con `reason=rate_limited`
- **AND** el `payload_dump` es el JSON del evento truncado a 4 KB
