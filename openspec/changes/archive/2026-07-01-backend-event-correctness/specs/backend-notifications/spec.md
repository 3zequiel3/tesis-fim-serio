## MODIFIED Requirements

### Requirement: Cascada de canales — SMTP → webhook_fallback → log_only

Si n8n falla en todos sus reintentos, el sistema SHALL intentar los canales en orden:
1. `smtp_fallback` — solo si `SMTP_HOST` está configurado; envía email async con `aiosmtplib`.
2. `webhook_fallback` — solo si `WEBHOOK_FALLBACK_URL` está configurado; `POST` async con httpx.
3. `log_only` — SIEMPRE ejecutado como piso (RN-54); emite log estructurado de nivel `critical`.

El valor de retorno de `_try_cascade` MUST distinguir dos escenarios (D23, RN-120):
- Al menos un canal configurado (n8n / SMTP / webhook_fallback) tuvo éxito → retorna `(True, canal)`. La alerta queda marcada como entregada con `delivered_at=now()` y `channel=<canal>`.
- Todos los canales configurados fallaron → `log_only` se ejecuta igualmente como piso (RN-54, no puede fallar), pero `_try_cascade` retorna `(False, None)`. El retry loop de `notify_event` continúa su ciclo de espera (RETRY_DELAYS) y, tras agotar todos los reintentos, setea `failed_at=now()` en la fila `alerts`. La alerta queda en la DLQ (`failed_at NOT NULL AND delivered_at IS NULL`).
- Si NO hay ningún canal primario configurado (n8n, SMTP y webhook_fallback todos ausentes), `log_only` es el canal intencional y `_try_cascade` retorna `(True, AlertChannel.log_only)`.

Cada canal actualiza `alerts.channel` con el canal que finalmente se usó para la entrega exitosa.

#### Scenario: SMTP entrega cuando n8n está caído
- **WHEN** n8n falla 4 veces y SMTP_HOST está configurado
- **THEN** se intenta envío SMTP; si exitoso, `alerts.channel = smtp_fallback` y `delivered_at` poblado

#### Scenario: log_only cuando no hay canales configurados — entrega exitosa
- **WHEN** `N8N_WEBHOOK_URL`, `SMTP_HOST` y `WEBHOOK_FALLBACK_URL` son None (no configurados)
- **THEN** se emite log crítico y `alerts.channel = log_only`, `delivered_at = now()`

#### Scenario: Canales configurados fallan — log_only como piso y alerta a DLQ
- **WHEN** `N8N_WEBHOOK_URL` está configurado pero n8n falla en los 4 intentos
- **AND** SMTP y webhook_fallback no están configurados
- **THEN** en cada intento se emite log crítico vía log_only (RN-54)
- **AND** tras agotar RETRY_DELAYS, `alerts.failed_at` está poblado y `delivered_at IS NULL`
- **AND** la alerta aparece en `GET /alerts/failed`

#### Scenario: Canal configurado como N8N_WEBHOOK_URL vacío — degraded
- **WHEN** `N8N_WEBHOOK_URL` no está configurado
- **THEN** el canal n8n se salta y se intenta directamente el siguiente canal disponible
