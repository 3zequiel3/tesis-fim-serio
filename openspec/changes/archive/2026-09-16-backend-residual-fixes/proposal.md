## Why

La auditoría del 2026-06-23 ([docs/audit_bugs.md](docs/audit_bugs.md)) detectó 8 bugs backend (1 ALTO + 7 MEDIOS) que nunca tuvieron change asignada: C22 solo levantó los críticos (C6–C10) y C30/C31/C32 solo rescataron H5, H7, H8 y M2. Los 8 restantes fueron verificados como STILL-PRESENT contra el código actual el 2026-06-30. Son defectos de robustez y de contrato — no feature nueva — que dejan la plataforma con fallos silenciosos: reglas que nunca llegan a los agentes si Valkey está caído, lockouts permanentes de login, un campo `email` falso, agentes que nunca transicionan a `dead`, audit logs con JSON inválido, races en el contador de versiones, un flag de contrato faltante en reject, y un health check de n8n que reporta OK ante un 500.

## What Changes

- **H6 (ALTO)** — `rules/service.py`: `publish_rule_sync` commitea `Rule` + `RulesetVersion` a Postgres ANTES de publicar a Valkey; si Valkey está caído la versión avanza pero los agentes nunca reciben las reglas. Implementar un patrón outbox: persistir el comando pendiente en la misma transacción y publicarlo desde un background task con retry, de modo que la entrega sobreviva a una caída de Valkey.
- **M1 (MEDIO)** — `core/rate_limit.py`: el `EXPIRE` solo se aplica cuando `count == 1`; si `INCR` tiene éxito pero `EXPIRE` falla, la key queda sin TTL → lockout permanente del `(user+IP)`. Setear el TTL de forma idempotente en cada incremento. Corregir el docstring que dice "sliding-window" siendo fixed-window.
- **M3 (MEDIO)** — modelo `User` (`auth/models.py`) + `users/schemas.py` + `users/router.py` + seed admin (`auth/service.py`): agregar el campo `email` **NOT NULL + UNIQUE**, validado con `EmailStr`. Hoy `UserItem` devuelve `username` en el campo email y `CreateUserRequest.email` acepta cualquier string. Migración SQL idempotente en `backend/db/migrations/` (D3, sin Alembic) y seed admin con email vía env `ADMIN_EMAIL` (default `admin@fim.local`). Decisión D29.
- **M4 (MEDIO)** — `agents/heartbeat_consumer.py` `_sweep_offline`: `Agent.last_heartbeat < threshold` excluye las filas `NULL` (`NULL < x` es `NULL` en SQL) → agentes que nunca latieron nunca transicionan a `offline`/`dead`. Incluir explícitamente `last_heartbeat IS NULL` en el barrido. **Ver Open Question sobre la referencia temporal — el modelo `Agent` no tiene `created_at`/`registered_at`.**
- **M5 (MEDIO)** — `agents/service.py` `update_agent_config`: el `detail` del audit log se arma con f-string sobre `str(list)` → JSON inválido (comillas simples) que rompe si un path contiene `"` o `\`. Serializar con `json.dumps(...)`.
- **M6 (MEDIO)** — `rules/service.py` + `actions/service.py`: el incremento de `RulesetVersion` hace `SELECT` + `version += 1` + `flush` sin `SELECT FOR UPDATE`, en dos implementaciones duplicadas → race entre requests concurrentes. Unificar en un único `UPDATE ruleset_versions SET version = version + 1 RETURNING version` atómico.
- **M8 (MEDIO)** — `actions/service.py` `_reject_single`: el no-op sobre baseline `absent` es correcto por RN-74 (no publica `restore_file` ni `quarantine_file`), pero la respuesta no devuelve `baseline_absent: true`, dejando al admin sin señal. Retornar el flag en la respuesta. **No cambia el comportamiento de no-op.**
- **M9 (MEDIO)** — `core/health.py` `_check_n8n`: `client.head()` sin `raise_for_status()` → el `except httpx.HTTPStatusError` es dead code (un 500 de n8n se reporta como OK). Chequear el status code e implementar el fallback GET documentado.

## Capabilities

### New Capabilities

_(ninguna — este change es de remediación: corrige comportamiento incorrecto y completa contratos pendientes, no introduce capacidades nuevas)_

### Modified Capabilities

- `backend-rules`: el fan-out de `rule_sync` MUST sobrevivir a una caída de Valkey vía outbox con retry (H6); el incremento de `ruleset_version` MUST ser atómico bajo concurrencia (M6).
- `backend-auth`: el rate limit de login MUST fijar el TTL de forma idempotente en cada incremento, evitando lockouts permanentes por `EXPIRE` fallido (M1).
- `backend-user-management`: `User` MUST tener un campo `email` real (NOT NULL, UNIQUE, validado con `EmailStr`); las respuestas y el seed admin MUST usar ese campo (M3, D29).
- `backend-agent-management`: el barrido de heartbeat MUST considerar los agentes con `last_heartbeat IS NULL` en las transiciones de estado (M4); el `detail` del audit log de `update_config` MUST ser JSON válido (M5).
- `backend-approve-reject`: el reject sobre un evento con baseline `absent` MUST retornar `baseline_absent: true` en la respuesta (M8).
- `backend-health`: el check de n8n MUST reportar `down` ante un status HTTP de error y MUST implementar el fallback GET documentado (M9).

## Impact

- **Archivos afectados**: `backend/app/modules/rules/service.py`, `backend/app/modules/actions/service.py`, `backend/app/core/rate_limit.py`, `backend/app/modules/auth/models.py`, `backend/app/modules/auth/service.py`, `backend/app/modules/users/schemas.py`, `backend/app/modules/users/router.py`, `backend/app/modules/agents/heartbeat_consumer.py`, `backend/app/modules/agents/service.py`, `backend/app/core/health.py`.
- **Migración de BD**: nueva columna `email` (NOT NULL + UNIQUE) en la tabla `users` — requiere script SQL idempotente `backend/db/migrations/002_add_user_email.sql` (D3, sin Alembic; el próximo prefijo tras `001_add_agent_status_revoked.sql`).
- **Nueva env var**: `ADMIN_EMAIL` (default `admin@fim.local`) para el seed admin.
- **Cambio de contrato API**: `UserItem.email` pasa a ser un email real (antes devolvía `username`); `POST /actions/reject` y su variante bulk agregan `baseline_absent` a la respuesta. Ningún endpoint nuevo ni renombrado.
- **Sin cambio de protocolo Valkey**: el formato de mensajes en streams no cambia; el outbox (H6) solo cambia el *momento* y la *resiliencia* de la publicación, no el payload.
- **Tests**: se agregan tests de regresión por cada fix. El harness de aislamiento C33 permanece sin cambios.
- **Reglas cubiertas**: RN-44, RN-45, RN-74, RN-75, RN-79, RN-92, RN-94, RN-123.
- **Decisiones aplicadas**: D3, D29.
- **Dependencias satisfechas**: C32 (`backend-sse-security-fixes`) archivado el 2026-07-01.
- **Suposición abierta (M4)**: el modelo `Agent` no tiene `created_at`/`registered_at`; la referencia temporal para transicionar a `dead` a un agente que nunca latió requiere una decisión no cerrada en los appendices (ver `design.md` → Open Questions).
