## ADDED Requirements

### Requirement: `_build_payload` produce el contrato canónico

`_build_payload` en `app/modules/alerts/service.py` SHALL producir el payload definido por la capability `notification-payload-contract` (D40/RN-134). El payload SHALL derivarse de la fila `Event` asociada a la alerta, leyendo las columnas ya persistidas — SHALL NO requerir captura adicional por parte del agente ni migración de esquema.

El mismo payload SHALL usarse en todos los canales de la cascada (n8n, `smtp_fallback`, `webhook_fallback`, `log_only`), de modo que un fallback no entregue menos información que el canal principal.

#### Scenario: El payload se arma desde el Event persistido
- **WHEN** se notifica una alerta cuyo `Event` tiene `process_pid=4242`, `process_uid=0` y `process_exe="/usr/bin/curl"`
- **THEN** el payload emitido contiene esos tres valores
- **AND** no se consulta al agente para obtenerlos

#### Scenario: El fallback entrega la misma información
- **WHEN** n8n falla y la cascada entrega por `smtp_fallback`
- **THEN** el contenido enviado por SMTP se deriva del mismo payload que se intentó enviar a n8n

---

### Requirement: Configuración explícita de TLS para SMTP

`Settings` SHALL exponer `smtp_starttls` y `smtp_ssl` como booleanos configurables. `send_smtp` SHALL NO forzar `start_tls=True` de manera incondicional.

El comportamiento SHALL ser:
- `smtp_ssl=true` → conexión TLS implícita (SMTPS, típicamente puerto 465); `start_tls` no se aplica.
- `smtp_starttls=true` y `smtp_ssl=false` → conexión en claro con `STARTTLS` (típicamente puerto 587). Este SHALL ser el default, preservando el comportamiento actual.
- ambos `false` → conexión sin cifrar, admitida sólo para relays internos.

Declarar ambos en `true` SHALL considerarse configuración inválida y SHALL registrarse como error.

#### Scenario: Relay en 465 con TLS implícito
- **WHEN** `smtp_ssl=true` y el relay escucha SMTPS en 465
- **THEN** el envío se realiza sobre TLS implícito y no se invoca `STARTTLS`

#### Scenario: Default preserva el comportamiento actual
- **WHEN** no se configura `smtp_starttls` ni `smtp_ssl`
- **THEN** el envío usa `STARTTLS`, igual que antes de este change

#### Scenario: Relay interno sin TLS
- **WHEN** `smtp_starttls=false` y `smtp_ssl=false`
- **THEN** el envío se realiza sin cifrado y no falla por ausencia de `STARTTLS`

#### Scenario: Configuración contradictoria
- **WHEN** `smtp_starttls=true` y `smtp_ssl=true`
- **THEN** el sistema registra un error de configuración identificando ambas variables

## MODIFIED Requirements

### Requirement: Cascada de canales — SMTP → webhook_fallback → log_only

Si n8n falla en todos sus reintentos, el sistema SHALL intentar los canales en orden:
1. `smtp_fallback` — solo si `SMTP_HOST` está configurado; envía email async con `aiosmtplib`, respetando `smtp_starttls` / `smtp_ssl`.
2. `webhook_fallback` — solo si `WEBHOOK_FALLBACK_URL` está configurado; `POST` async con httpx.
3. `log_only` — SIEMPRE ejecutado como piso (RN-54); emite log estructurado de nivel `critical`.

El valor de retorno de `_try_cascade` MUST distinguir dos escenarios (D23, RN-120):
- Al menos un canal configurado (n8n / SMTP / webhook_fallback) tuvo éxito → retorna `(True, canal)`. La alerta queda marcada como entregada con `delivered_at=now()` y `channel=<canal>`.
- Todos los canales configurados fallaron → `log_only` se ejecuta igualmente como piso (RN-54, no puede fallar), pero `_try_cascade` retorna `(False, None)`. El retry loop de `notify_event` continúa su ciclo de espera (RETRY_DELAYS) y, tras agotar todos los reintentos, setea `failed_at=now()` en la fila `alerts`. La alerta queda en la DLQ (`failed_at NOT NULL AND delivered_at IS NULL`).
- Si NO hay ningún canal primario configurado (n8n, SMTP y webhook_fallback todos ausentes), `log_only` es el canal intencional y `_try_cascade` retorna `(True, AlertChannel.log_only)`.

Cada canal actualiza `alerts.channel` con el canal que finalmente se usó para la entrega exitosa.

El payload que recorre la cascada SHALL ser el definido por `notification-payload-contract` (D40/RN-134), idéntico en todos los canales.

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

#### Scenario: El payload no se degrada en el fallback
- **WHEN** la cascada entrega por `webhook_fallback` tras fallar n8n
- **THEN** el cuerpo enviado contiene los mismos campos de `notification-payload-contract` que se habrían enviado a n8n
