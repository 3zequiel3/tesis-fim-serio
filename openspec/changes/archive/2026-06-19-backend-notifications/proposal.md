## Why

Los eventos críticos se ingieren y persisten en DB pero nadie es notificado; los administradores solo se enteran cuando abren el dashboard. Este change agrega el canal de notificación asincrónico (webhook n8n + fallback SMTP + fallback log), los endpoints de gestión de la DLQ de alertas fallidas y el endpoint `GET /health/components` para visibilidad operacional del sistema.

## What Changes

- Servicio de notificación asincrónico no bloqueante: se dispara tras ingerir un evento con severidad `critical` o `high` (determinada por la regla de mayor severidad que matchee el path del evento en la tabla `rules`).
- Retry 3x exponencial: 5s → 30s → 120s antes de marcar como fallido en `alerts`.
- Cascada de canales: n8n webhook → SMTP directo → webhook directo alternativo → log crítico (D6, RN-107).
- Cada intento actualiza la fila en la tabla `alerts` unificada (D6): `channel`, `delivered_at`, `failed_at`, `last_error`, `retry_count`.
- Eventos `superseded` no notifican (RN-22).
- `GET /alerts/failed` — DLQ: filas con `delivered_at IS NULL AND failed_at IS NOT NULL`.
- `POST /alerts/{id}/retry` — reintento manual desde la DLQ.
- `DELETE /alerts/{id}` — descarte de la DLQ.
- `GET /health/components` — estado de postgres, valkey, n8n y todos los agentes; cambios de estado disparan webhook n8n.

Reglas cubiertas: RN-52, RN-53, RN-54, RN-86 (D6), RN-87, RN-101, RN-102 (D6), RN-103, RN-107.
Decisiones aplicadas: D6.

## Capabilities

### New Capabilities

- `backend-notifications`: Servicio de notificación asincrónico — determinación de severidad por lookup de reglas, retry exponencial, cascada de canales, tabla `alerts` como única fuente de verdad del estado de entrega, endpoints DLQ (`/alerts/failed`, retry, delete).
- `backend-health`: Endpoint `GET /health/components` con verificación real de postgres, valkey, n8n y agentes; trigger de webhook n8n en cambio de estado.

### Modified Capabilities

- `backend-events-api`: El consumer de eventos (`consumer.py`) dispara notificación asincrónica tras persistir un evento exitosamente (ADDED hook post-ingesta).

## Impact

- **Backend**: nuevo módulo `backend/app/modules/alerts/` — `service.py`, `router.py`, `notifier.py` (lógica de envío); nuevo módulo o función en `core/health.py`; modificación de `modules/events/consumer.py` para llamar notificación post-ingesta.
- **Config**: nuevas variables de entorno: `N8N_WEBHOOK_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TO`, `SMTP_FROM` (todas opcionales con defaults seguros).
- **DB**: tabla `alerts` ya existe (C03); este change la puebla por primera vez.
- **Dependencias nuevas**: `httpx` (async HTTP para webhook), `aiosmtplib` (async SMTP para fallback).
