## Why

C20 cierra los últimos gaps operativos de M4: la plataforma no permite crear administradores adicionales (RN-45), los parámetros de rate limiting están hardcodeados impidiendo tuning de producción, y faltan workflows de n8n y documentación operativa para un deploy real.

## What Changes

- `GET /users` + `POST /users`: creación de administradores adicionales por admin existente (RN-45); reutiliza `require_admin`, modelo `User`, `hash_password` (Argon2id) y `write_audit_log` ya existentes
- Rate limit: mover buckets hardcodeados de `core/rate_limit.py` a settings en `config.py`; agregar tests de carga del rate limiter
- `n8n/workflows/*.json`: workflows de ejemplo con casos comunes (Slack, email, ticketing) para conectar alertas de la plataforma a canales externos
- Docs operativos: variables de entorno requeridas, formato de logs estructurados, paths de retención, instalación del agente como systemd unit
- Verificación (no reimplementación) de retención de eventos (30d terminales — RN-98) y compactación de cadenas >10, ya implementados en C11 (`retention_task()`, `compact_chain()` en `backend/app/modules/events/service.py`)

## Capabilities

### New Capabilities

- `backend-user-management`: gestión de usuarios administradores via `GET /users` (listado paginado) y `POST /users` (crear admin adicional); protegido por `require_admin`; escribe `audit_log` en cada mutación

### Modified Capabilities

_(ninguna — tuning de rate limit, workflows n8n y docs operativos son configuración y documentación, no cambian behavioral requirements de specs existentes)_

## Impact

- `backend/app/modules/users/router.py`: agregar GET /users + POST /users
- `backend/app/modules/users/schemas.py`: UserListResponse, CreateUserRequest
- `backend/app/core/rate_limit.py`: buckets → referencias a config
- `backend/app/core/config.py`: nuevas settings RATE_LIMIT_*
- `backend/tests/modules/users/test_user_management.py`: tests de los endpoints nuevos
- `backend/tests/core/test_rate_limit_load.py`: tests de carga del rate limiter
- `n8n/workflows/`: slack_alert.json, email_alert.json, ticketing_alert.json (nuevos)
- `docs/operations.md`: documentación operativa completa (nuevo)
- Reglas cubiertas: RN-45, RN-94, RN-98
- Decisiones aplicadas: D7 (cross-cutting con primer feature que lo necesita)
