## Why

La auditoría V10 de la tesis (riesgo M-4) dejó dos pendientes de privacidad en el backend. El stream SSE de alertas recibe el JWT de acceso completo en `?token=` (contrato C16), por lo que ese JWT queda en los logs de acceso de nginx y de uvicorn y en el historial del navegador durante toda su vigencia. Además, `rejected_events_audit` (D4) guarda payloads rechazados truncados y crece sin límite. Las decisiones D64/RN-158 y D65/RN-159 ya cerraron la respuesta; este change las implementa (Change 54 de `CHANGES.md`).

## What Changes

- **BREAKING** `GET /alerts/stream` deja de aceptar `?token=<jwt>`. La autenticación pasa a un ticket opaco de un solo uso (D64/RN-158); una request con `?token=` y sin `?ticket=` se rechaza con 401.
- Nuevo endpoint `POST /alerts/stream-ticket` (JWT en `Authorization` + rol admin) que emite un ticket aleatorio con TTL de 30 s guardado en Valkey y ligado al `user_id`.
- `GET /alerts/stream?ticket=` consume el ticket de forma atómica (`GETDEL`); un ticket reutilizado, vencido, inexistente o ausente recibe 401. Se conservan la exigencia de rol admin, el rate limit por usuario y los eventos emitidos.
- La continuidad de D-EV-6 se preserva: el backend acepta el último id recibido tanto por el header `Last-Event-ID` como por el query param `last_event_id`.
- `useAlertsSSE` pide un ticket nuevo antes de cada conexión y reconexión, desactiva la reconexión nativa de `EventSource` (que reutilizaría un ticket ya consumido) y reabre manualmente con backoff, pasando el último id recibido.
- Redacción del valor del ticket (y de cualquier `token=` residual) en los logs: procesador del pipeline structlog para los strings de uvicorn access y `log_format` redactado en nginx.
- Nueva tarea periódica del lifespan que elimina en lotes filas de `rejected_events_audit` con `received_at` anterior a `REJECTED_EVENTS_RETENTION_DAYS` (90 por defecto). `audit_log` no se purga (W18/RN-94 ratificada).

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `sse-alerts`: autenticación del stream por ticket de un solo uso en lugar de JWT en query; nuevo endpoint de emisión de ticket; `last_event_id` como equivalente en URL del header `Last-Event-ID`.
- `frontend-events`: el feed SSE obtiene un ticket por conexión y gestiona la reconexión manualmente sin perder alertas.
- `backend-core`: redacción de credenciales de query string en las líneas de log.
- `backend-event-consumer`: retención periódica de `rejected_events_audit` y garantía de no purga de `audit_log`.
- `frontend-shell`: access log de nginx con el ticket SSE redactado.

## Impact

- **Reglas y decisiones**: D64/RN-158 y D65/RN-159 (nuevas, ya cerradas); RN-94 (ratificada); D4 (completada con retención); RN-89 (sanitización, extendida); D-EV-6 (continuidad preservada); contrato C16 (reemplazado en autenticación).
- **Backend**: `backend/app/modules/alerts/router.py` (dependencia de auth del stream, nuevo endpoint), nuevo módulo de tickets bajo `backend/app/modules/alerts/`, `backend/app/core/logging.py`, `backend/app/core/config.py` (`rejected_events_retention_days`), `backend/app/modules/events/service.py` (nueva tarea de retención), `backend/app/main.py` (registro y cancelación de la tarea).
- **Frontend**: `frontend/src/hooks/useAlertsSSE.ts`, `frontend/src/api/alerts.ts`, tests del hook; `frontend/nginx/` (formato de log).
- **Configuración**: nueva variable `REJECTED_EVENTS_RETENTION_DAYS` en `.env.example`.
- **Dependencias del DAG**: 16 (`backend-sse-alerts`) y 32 (`backend-sse-security-fixes`), ambas archivadas. Comparte el módulo `alerts` con el Change 55 (`backlog-partial-stories-completion`): los applies deben ejecutarse en serie.
- **Sin dependencias externas nuevas**: `GETDEL` está disponible en Valkey 9.0.3; `secrets` es stdlib.
