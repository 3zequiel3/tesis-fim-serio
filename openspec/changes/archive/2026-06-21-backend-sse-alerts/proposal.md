## Why

C15 (`backend-notifications`) implementó la tabla `alerts` unificada (D6) y los endpoints DLQ (`/alerts/failed`, retry, delete). Sin embargo, el frontend aún no tiene forma de recibir alertas en tiempo real ni de listar el historial completo de alertas (entregadas, fallidas, pendientes). Este change cierra ese gap exponiendo un stream SSE autenticado y un endpoint de listado paginado sobre la tabla `alerts` existente.

## What Changes

- Nuevo endpoint `GET /alerts/stream`: stream SSE con auth JWT que emite eventos `alert` cada vez que se inserta una nueva fila en la tabla `alerts`; reconexión no pierde alertas posteriores (usa `Last-Event-ID`).
- Nuevo endpoint `GET /alerts`: listado paginado de todas las alertas (`delivered`, `failed`, `pending`), con filtros por estado y severidad.
- Sin cambios al modelo `Alert` (ya definido en C03/D6) ni a la lógica de notificaciones (C15).

## Capabilities

### New Capabilities

- `sse-alerts`: Stream SSE autenticado sobre la tabla `alerts` + endpoint de listado paginado completo.

### Modified Capabilities

*(ninguna — el modelo `Alert` y los endpoints DLQ de `backend-notifications` no cambian)*

## Impact

- **Código nuevo**: `backend/app/modules/alerts/stream.py` (SSE broadcaster), router SSE, endpoint `GET /alerts`.
- **Dependencia**: requiere C15 archivado (tabla `alerts` y módulo `notifier.py` existentes) y C04 (auth JWT).
- **Reglas cubiertas**: RN-53, RN-54, RN-107.
- **Sin cambios de schema**: `Alert` ya existe en DB desde C03.
