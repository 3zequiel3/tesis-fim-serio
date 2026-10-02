## ADDED Requirements

### Requirement: Event registra si el cambio se detectó con el agente detenido

El modelo `Event` SHALL tener la columna `detected_offline: bool | None`, anulable, sin default y sin índice, agregada por la migración SQL manual, aditiva e idempotente `023_add_event_detected_offline.sql` en `backend/db/migrations/`, con el encabezado de convención (número, decisión y change) y sin backfill. `NULL` SHALL significar que el agente no informó el dato (agente anterior a D80); `false`, que el cambio se detectó en línea; `true`, que lo detectó la reconciliación al arrancar. La columna MUST NOT influir en la derivación del status, la severidad ni la supersesión. (D80 / RN-174, D3)

#### Scenario: Migración aditiva e idempotente
- **WHEN** se aplica `023_add_event_detected_offline.sql` dos veces sobre una base con eventos existentes
- **THEN** la segunda aplicación no falla, la columna existe y las filas previas tienen `detected_offline IS NULL`

#### Scenario: El modelo acepta los tres valores
- **WHEN** se insertan eventos con `detected_offline` en `true`, `false` y `None`
- **THEN** cada inserción completa sin error y la fila conserva el valor
