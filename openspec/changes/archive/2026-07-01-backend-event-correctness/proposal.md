## Why

La auditoría del 2026-06-26 identificó nueve bugs en la lógica de eventos, notificaciones y acciones del backend. Los más críticos comprometen la durabilidad de las notificaciones (canal de falla silenciosa en la cascada) y la consistencia transaccional (mensajes Valkey publicados antes de que el commit sea durable). Esta change remedia los nueve bugs sin introducir features nuevas.

Las decisiones de diseño están cerradas: D23/RN-120 (semántica de `log_only` en la cascada) y D25/RN-121 (inserción del evento nuevo cuando falla `mark_superseded`).

## What Changes

- **FIX-01 (CRÍTICO)** — `alerts/service.py`: `_try_cascade` ya no retorna silenciosamente `(False, None)` cuando los canales primarios configurados fallan. En cambio, activa el retry loop, registra `failed_at` y encola en DLQ. Comportamiento de `log_only` se preserva como piso garantizado (D23, RN-120).
- **FIX-02 (ALTO)** — `actions/service.py`: `publish_baseline_update`, `publish_restore_file` y `publish_quarantine_file` se mueven a DESPUÉS de `db.commit()` en `_approve_single` y `_reject_single`. Elimina la ventana de inconsistencia en la que el agente recibe un comando antes de que la transacción sea durable.
- **FIX-03 (ALTO)** — `events/service.py`: en `ingest_event`, cuando `mark_superseded` retorna `False` (race concurrente), se re-consulta si existe un pending activo para el mismo path. Si no hay pending → el nuevo evento se inserta; si sigue habiendo pending → skip legítimo (D25, RN-121).
- **FIX-04 (ALTO)** — `events/router.py`: `list_events` implementa paginación SQL real con `LIMIT/OFFSET/ORDER BY`. Elimina el full table scan.
- **FIX-05 (MEDIO)** — `events/service.py`: `compact_chain` corregido de `.desc()` a `.asc()` para retener los eventos más viejos (semántica correcta de compactación).
- **FIX-06 (MEDIO)** — `events/consumer.py`: el check de rate limit se mueve a DESPUÉS del dedup, de modo que las re-entregas no gastan presupuesto de rate.
- **FIX-07 (MEDIO)** — `events/consumer.py`: se valida que `event_id` sea no-vacío antes del dedup; si está ausente o vacío, el evento se rechaza con estado `invalid_schema`.
- **FIX-08 (MEDIO)** — `events/consumer.py`: `detected_at` se normaliza a UTC-aware antes de calcular el clock skew. Si no es parseable, el evento se rechaza con estado `clock_skew` explícito.
- **FIX-09 (INFO)** — `events/service.py`, `rules/service.py`, `actions/service.py`: `datetime.utcnow()` (deprecated) reemplazado por `datetime.now(timezone.utc)` en todos los puntos de uso (5+ ocurrencias).
- Tests de regresión para cada fix.

## Capabilities

### New Capabilities

_(ninguna — change de remediación pura)_

### Modified Capabilities

- `backend-notifications`: La semántica de `_try_cascade` cambia: cuando los canales primarios configurados fallan, se activa el retry loop y la DLQ (no retorno silencioso). El comportamiento de `log_only` como piso garantizado queda explicitado en el spec (D23, RN-120).
- `backend-event-consumer`: Se reordenan los pasos de dedup y rate limit, se agrega validación de `event_id` no-vacío (rechazo `invalid_schema`) y normalización de `detected_at` a UTC-aware (rechazo `clock_skew`).
- `backend-approve-reject`: El requisito de publicar en Valkey únicamente después de `db.commit()` se hace explícito en el spec.
- `backend-events-api`: `list_events` requiere paginación SQL real (`LIMIT/OFFSET/ORDER BY`); el spec existente no lo mandataba.

## Impact

- **Archivos modificados**: `backend/app/modules/alerts/service.py`, `backend/app/modules/actions/service.py`, `backend/app/modules/events/service.py`, `backend/app/modules/events/router.py`, `backend/app/modules/events/consumer.py`, `backend/app/modules/rules/service.py`.
- **Tests**: nuevas pruebas de regresión en `backend/tests/` para cada uno de los nueve fixes (harness C33, aislamiento por función con TRUNCATE + RESTART IDENTITY CASCADE).
- **Sin cambios de schema DB**: ningún fix requiere migración.
- **Sin cambios de API pública**: los contratos de los endpoints no cambian, solo su implementación.
- **Reglas de negocio**: RN-120, RN-121 (ya cerradas en appendices canónicos).
- **Decisiones de implementación**: D23, D25 (ya cerradas en appendices canónicos).
