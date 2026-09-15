## ADDED Requirements

### Requirement: GET /alerts/failed/count — conteo de la DLQ para el banner

El sistema SHALL exponer `GET /alerts/failed/count` (requiere JWT admin) que responde `{"count": int}` con la cantidad de alertas que cumplen `delivered_at IS NULL AND failed_at IS NOT NULL` (US-29, US-05, D6/RN-102) — la misma definición de fallo terminal que `list_failed_alerts`, **sin** umbral adicional de `retry_count`: una alerta agotada con `retry_count = 0` (n8n sin configurar) MUST contarse igual que una con `retry_count = 3`. La ruta MUST resolverse antes que cualquier ruta con parámetro `/{alert_id}`.

#### Scenario: Cuenta alertas en fallo terminal, sin importar retry_count
- **WHEN** existen una alerta entregada, una alerta fallida con `retry_count = 3`, una alerta fallida con `retry_count = 0` (n8n sin configurar) y una alerta pendiente
- **THEN** `GET /alerts/failed/count` responde `{"count": 2}`

#### Scenario: DLQ vacía cuenta cero
- **WHEN** no hay alertas con `failed_at IS NOT NULL`
- **THEN** la respuesta es `{"count": 0}`

#### Scenario: Requiere admin
- **WHEN** se llama `GET /alerts/failed/count` sin token válido
- **THEN** la respuesta es `401`

## MODIFIED Requirements

### Requirement: POST /alerts/{id}/retry — reintento manual desde DLQ

El sistema SHALL exponer `POST /alerts/{id}/retry` (requiere JWT admin) que toma una alerta fallida (`failed_at IS NOT NULL`) y la re-intenta enviando la notificación. MUST resetear `failed_at=null`, `last_error=null`, `retry_count=0` antes de re-intentar. Si el alerta no existe o ya fue entregada → 404 o 409. Cada reintento aceptado MUST registrar una fila en `audit_log` (RN-94, US-29) con `action="alert_retry"`, `user_id` del admin, `target_type="alert"`, `target_id` igual al id de la alerta y `detail` con el `event_id`, confirmada en el mismo commit que el reset. Un reintento rechazado con 404 o 409 MUST NOT dejar fila en `audit_log`. El reintento masivo del frontend, que emite una llamada por alerta, MUST producir una fila por alerta reintentada.

#### Scenario: Retry exitoso
- **WHEN** un admin hace `POST /alerts/42/retry` y el canal n8n responde 2xx
- **THEN** `alerts.delivered_at` está poblado y la alerta ya no aparece en `GET /alerts/failed`

#### Scenario: Retry registra audit_log
- **WHEN** un admin hace `POST /alerts/42/retry` sobre una alerta fallida
- **THEN** existe una fila en `audit_log` con `action="alert_retry"`, `user_id` del admin, `target_type="alert"` y `target_id=42`

#### Scenario: Reintento masivo deja una fila por alerta
- **WHEN** un admin reintenta las alertas fallidas 41, 42 y 43 con una llamada `POST /alerts/{id}/retry` por cada una
- **THEN** existen tres filas `alert_retry` en `audit_log`, con `target_id` 41, 42 y 43

#### Scenario: Retry de alerta ya entregada retorna 409
- **WHEN** la alerta ya tiene `delivered_at NOT NULL`
- **THEN** la respuesta es `409 Conflict`
- **AND** no se escribe ninguna fila en `audit_log`

#### Scenario: Alerta no encontrada retorna 404
- **WHEN** el `id` no existe en `alerts`
- **THEN** la respuesta es `404 Not Found`
- **AND** no se escribe ninguna fila en `audit_log`

### Requirement: DELETE /alerts/{id} — descartar alerta de la DLQ

El sistema SHALL exponer `DELETE /alerts/{id}` (requiere JWT admin) que elimina la fila de `alerts`. Permite descartar alertas de la DLQ que no se desean reintentar. Cada descarte MUST registrar una fila en `audit_log` (RN-94, US-29) con `action="alert_discard"`, `user_id` del admin, `target_type="alert"`, `target_id` igual al id de la alerta y `detail` con el `event_id`, confirmada en el mismo commit que la eliminación. Un descarte rechazado con 404 MUST NOT dejar fila en `audit_log`.

#### Scenario: Delete exitoso
- **WHEN** existe la alerta con `id=42` y se hace `DELETE /alerts/42`
- **THEN** la respuesta es `204 No Content` y la fila ya no existe en DB

#### Scenario: Delete registra audit_log
- **WHEN** un admin hace `DELETE /alerts/42` sobre una alerta existente con `event_id=7`
- **THEN** existe una fila en `audit_log` con `action="alert_discard"`, `target_type="alert"`, `target_id=42` y `detail` que contiene `event_id=7`

#### Scenario: Delete de alerta inexistente retorna 404
- **WHEN** el `id` no existe
- **THEN** la respuesta es `404 Not Found`
- **AND** no se escribe ninguna fila en `audit_log`
