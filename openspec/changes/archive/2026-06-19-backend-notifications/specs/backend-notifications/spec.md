# Spec: backend-notifications

Capability: Servicio de notificación asincrónico del backend FIM — determinación de severidad por lookup de reglas, retry exponencial 3x, cascada de canales n8n→SMTP→webhook→log, tabla `alerts` como fuente de verdad del estado de entrega, y endpoints de gestión de la DLQ.

---

## ADDED Requirements

### Requirement: Notificación asincrónica post-ingesta de eventos críticos o altos

El sistema SHALL disparar una notificación asincrónica no bloqueante (`asyncio.create_task`) tras persistir exitosamente un evento en DB. La notificación MUST evaluarse solo para eventos con `status != superseded` (RN-22). La severidad SHALL determinarse buscando en la tabla `rules` las reglas cuyo `pattern` (glob) matchee el `event.path` usando `fnmatch.fnmatch`; si hay matches, se usa la severidad más alta; si no hay matches, se usa `low`. La notificación solo se envía si la severidad resultante es `critical` o `high` (RN-52).

#### Scenario: Evento critical o high dispara notificación
- **WHEN** se ingiere un evento cuyo path matchea una regla con `severity=critical`
- **THEN** se crea una fila en `alerts` con `severity=critical` y se intenta el envío al canal primario

#### Scenario: Evento con severidad low o medium no notifica
- **WHEN** se ingiere un evento cuyo path matchea solo reglas con `severity=low` o `severity=medium`
- **THEN** no se crea ninguna fila en `alerts`

#### Scenario: Evento sin regla matching no notifica
- **WHEN** se ingiere un evento cuyo path no matchea ninguna regla
- **THEN** no se crea ninguna fila en `alerts`

#### Scenario: Evento superseded no notifica
- **WHEN** se ingiere un evento que resulta en `status=superseded`
- **THEN** no se crea ninguna fila en `alerts`

#### Scenario: Notificación no bloquea el consumer
- **WHEN** el envío del webhook n8n tarda 5 segundos
- **THEN** el consumer procesa el siguiente evento de Valkey sin esperar al webhook

---

### Requirement: Envío al canal n8n con retry exponencial 3x

El sistema SHALL intentar enviar `POST {N8N_WEBHOOK_URL}` con timeout 10s. Si falla, MUST esperar 5 segundos y reintentar; si vuelve a fallar, MUST esperar 30 segundos; si falla de nuevo (3er intento), MUST esperar 120 segundos. Si el 4to intento (contando el primero) también falla, MUST marcar la fila en `alerts` con `failed_at=now()`, `last_error=<mensaje>`, `retry_count=3`. En cualquier intento exitoso MUST actualizar `alerts` con `delivered_at=now()`, `channel=n8n`, `retry_count=<intentos_realizados>`.

#### Scenario: Entrega exitosa en primer intento
- **WHEN** n8n responde 2xx en el primer intento
- **THEN** `alerts.delivered_at` está poblado, `alerts.channel = n8n`, `retry_count = 0`

#### Scenario: Entrega exitosa en tercer intento
- **WHEN** n8n falla los primeros 2 intentos y responde 2xx en el 3ro
- **THEN** `alerts.delivered_at` está poblado, `retry_count = 2`

#### Scenario: Fallo total de n8n — DLQ
- **WHEN** n8n falla en los 4 intentos
- **THEN** la cascada continúa con el canal SMTP (si configurado); si todos los canales fallan, `alerts.failed_at` está poblado y `delivered_at IS NULL`

---

### Requirement: Cascada de canales — SMTP → webhook_fallback → log_only

Si n8n falla en todos sus reintentos, el sistema SHALL intentar los canales en orden:
1. `smtp_fallback` — solo si `SMTP_HOST` está configurado; envía email async con `aiosmtplib`.
2. `webhook_fallback` — solo si `WEBHOOK_FALLBACK_URL` está configurado; `POST` async con httpx.
3. `log_only` — siempre disponible; emite log estructurado de nivel `critical` y marca `delivered_at=now()` con `channel=log_only` (RN-54 — canal de último recurso, siempre exitoso).

Cada canal actualiza `alerts.channel` con el canal que finalmente usó.

#### Scenario: SMTP entrega cuando n8n está caído
- **WHEN** n8n falla 4 veces y SMTP_HOST está configurado
- **THEN** se intenta envío SMTP; si exitoso, `alerts.channel = smtp_fallback` y `delivered_at` poblado

#### Scenario: log_only siempre entrega
- **WHEN** n8n falla, SMTP no está configurado y WEBHOOK_FALLBACK_URL no está configurado
- **THEN** se emite log crítico y `alerts.channel = log_only`, `delivered_at = now()`

#### Scenario: Canal configurado como N8N_WEBHOOK_URL vacío — degraded
- **WHEN** `N8N_WEBHOOK_URL` no está configurado
- **THEN** el canal n8n se salta y se intenta directamente el siguiente canal disponible

---

### Requirement: GET /alerts/failed — DLQ de alertas fallidas

El sistema SHALL exponer `GET /alerts/failed` (requiere JWT admin) que retorna alertas con `delivered_at IS NULL AND failed_at IS NOT NULL`, ordenadas por `failed_at DESC`. La respuesta SHALL ser `{"items": [...], "total": int}`. Cada ítem incluye `id`, `event_id`, `severity`, `channel`, `failed_at`, `last_error`, `retry_count`, `created_at`.

#### Scenario: DLQ retorna solo alertas fallidas
- **WHEN** existen 2 alertas entregadas y 1 fallida, y se hace `GET /alerts/failed`
- **THEN** la respuesta contiene `total=1` con solo la alerta fallida

#### Scenario: DLQ vacía retorna lista vacía
- **WHEN** no hay alertas fallidas
- **THEN** la respuesta es `{"items": [], "total": 0}`

---

### Requirement: POST /alerts/{id}/retry — reintento manual desde DLQ

El sistema SHALL exponer `POST /alerts/{id}/retry` (requiere JWT admin) que toma una alerta fallida (`failed_at IS NOT NULL`) y la re-intenta enviando la notificación. MUST resetear `failed_at=null`, `last_error=null`, `retry_count=0` antes de re-intentar. Si el alerta no existe o ya fue entregada → 404 o 409.

#### Scenario: Retry exitoso
- **WHEN** un admin hace `POST /alerts/42/retry` y el canal n8n responde 2xx
- **THEN** `alerts.delivered_at` está poblado y la alerta ya no aparece en `GET /alerts/failed`

#### Scenario: Retry de alerta ya entregada retorna 409
- **WHEN** la alerta ya tiene `delivered_at NOT NULL`
- **THEN** la respuesta es `409 Conflict`

#### Scenario: Alerta no encontrada retorna 404
- **WHEN** el `id` no existe en `alerts`
- **THEN** la respuesta es `404 Not Found`

---

### Requirement: DELETE /alerts/{id} — descartar alerta de la DLQ

El sistema SHALL exponer `DELETE /alerts/{id}` (requiere JWT admin) que elimina la fila de `alerts`. Permite descartar alertas de la DLQ que no se desean reintentar.

#### Scenario: Delete exitoso
- **WHEN** existe la alerta con `id=42` y se hace `DELETE /alerts/42`
- **THEN** la respuesta es `204 No Content` y la fila ya no existe en DB

#### Scenario: Delete de alerta inexistente retorna 404
- **WHEN** el `id` no existe
- **THEN** la respuesta es `404 Not Found`
