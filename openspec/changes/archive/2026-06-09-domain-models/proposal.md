## Why

El backend necesita un esquema de datos completo antes de que cualquier módulo (eventos, agentes, auth, alertas) pueda implementarse. Change 02 dejó el directorio `modules/` vacío: sin modelos SQLModel no hay tablas, sin tablas no hay nada que hacer en el resto de M1 ni en M2/M3.

## What Changes

- Nuevo modelo `Event` con `EventStatus` (7 valores canónicos), optimistic locking (`version`), contexto fanotify (PID/UID/exe), timestamps dobles (`detected_at` / `received_at`), y campo `hash` usado directamente en approve (D2).
- Nuevo modelo `Rule` con `RuleAction` enum (4 valores) y `RulesetVersion` (counter monotónico global). Los comandos de sync llevan `target_agent_id` (D5).
- Nuevo modelo `Agent` con `AgentStatus` enum, `last_heartbeat`, `ruleset_version_applied` (semántica D5), `queue_pressure`, `bootstrap_secret_hash`. Tabla auxiliar `revoked_certificates`.
- Nuevo modelo `BaselineEntry` (D1): metadata por path monitorado en backend, sin contenido cifrado. Campos: `path`, `agent_id`, `hash | null`, `status` (`present | absent`), `last_updated`, `ruleset_version`.
- Nuevo modelo `RejectedEventAudit` (D4) con enum `RejectionReason` (5 valores) y `payload_dump` truncado a 4 KB.
- Nuevo modelo `Alert` (D6): tabla unificada con lifecycle completo (`severity`, `channel`, `delivered_at`, `failed_at`, `last_error`, `retry_count`). Elimina la tabla `failed_notifications` que mencionaba RN-86 en su versión original.
- Nuevo modelo `AuditLog` para trazabilidad de operaciones admin.
- Nuevo modelo `User` (con `must_change_password`), que el seed de change 02 ya usa pero cuyo `table=True` se formaliza aquí.

## Capabilities

### New Capabilities

- `domain-models`: Todos los modelos SQLModel del backend con sus enums canónicos, relaciones FK y constraints. Cada modelo tiene `table=True`; la creación física ocurre via `SQLModel.metadata.create_all()` en el lifespan (D3, ya implementado en change 02).

### Modified Capabilities

- `backend-core`: `User` pasa de placeholder (seed en `main.py`) a modelo formal con todos sus campos definidos en `modules/auth/models.py`.

## Impact

- **Archivos nuevos**: `backend/app/modules/events/models.py`, `backend/app/modules/rules/models.py`, `backend/app/modules/agents/models.py`, `backend/app/modules/alerts/models.py`, `backend/app/modules/auth/models.py`, `backend/app/modules/audit/models.py`.
- **Archivos modificados**: `backend/app/main.py` (import de todos los módulos para que `create_all()` los registre), `backend/app/core/database.py` (sin cambios funcionales, solo validación de importación).
- **Sin migraciones**: SQLModel crea las tablas al iniciar. En dev, se recrea el volumen si hay schema conflicts.
- **Dependencias**: ninguna nueva — todos los paquetes (sqlmodel, python-jose, argon2-cffi) ya están en `requirements.txt`.
- **Reglas**: RN-08, RN-10, RN-44, RN-66, RN-71, RN-72, RN-77, RN-94. **Decisiones**: D1, D4, D5, D6.
