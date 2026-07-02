## 1. Baseline

- [x] 1.1 Correr la suite completa (`pytest`) y confirmar verde antes de tocar nada — NOTA: baseline arrancó con 4 fallas preexistentes fuera de scope (`test_c31_backend_event_correctness.py::test_fix04_pagination_sql`, `::test_fix05_compact_chain_retains_newest`, `test_notifications.py::test_notify_event_retry_3x_then_log_only`, `::test_log_only_always_delivers`), no relacionadas a H6/M1/M3/M5/M6/M8/M9. No se tocan (fuera del alcance de C34); documentadas para seguimiento aparte.

## 2. M3 — Campo email real en User + seed (hacerlo primero: afecta migración de BD)

- [x] 2.1 Agregar el campo `email` (NOT NULL + UNIQUE) al modelo `User` en `backend/app/modules/auth/models.py`
- [x] 2.2 Crear `backend/db/migrations/002_add_user_email.sql` idempotente: agregar la columna, backfillear filas existentes (p. ej. el admin) antes de imponer `NOT NULL`, y crear el índice UNIQUE (`IF NOT EXISTS`)
- [x] 2.3 Verificar idempotencia ejecutando el script SQL dos veces en el contenedor de test
- [x] 2.4 En `backend/app/modules/users/schemas.py`: usar `EmailStr` en `CreateUserRequest.email`; que `UserItem`/`UserListResponse` expongan el `email` real del usuario (dejar de mapear `username` al campo email)
- [x] 2.5 En `backend/app/modules/users/router.py`: persistir/leer el `email` real en create y list; mapear la violación de UNIQUE a 409
- [x] 2.6 En `backend/app/modules/auth/service.py`: el seed admin toma `email` de la env `ADMIN_EMAIL` (default `admin@fim.local`); mantener el seed idempotente
- [x] 2.7 Correr la suite completa para confirmar regresión cero

## 3. M6 — Incremento atómico unificado de ruleset_version

- [x] 3.1 Reescribir `increment_ruleset_version` en `backend/app/modules/rules/service.py` como un único `UPDATE ruleset_versions SET version = version + 1 RETURNING version` atómico
- [x] 3.2 En `backend/app/modules/actions/service.py`: reemplazar el `SELECT` + `rv.version += 1` + `flush` (línea ~76) por una invocación a la función unificada; eliminar la implementación duplicada
- [x] 3.3 Correr la suite completa para confirmar regresión cero

## 4. H6 — Outbox para publish_rule_sync

- [x] 4.1 Inspeccionar el schema de `published_commands` (D10) y decidir si el outbox reutiliza esa tabla con estado `pending`/`published` o si se agrega una tabla `command_outbox` dedicada; si agrega tabla, crear migración idempotente con el próximo prefijo numérico — decisión: se reutiliza `published_commands` (+ `payload`, `status`; `published_at` ahora nullable), migración `003_add_published_commands_outbox.sql`
- [x] 4.2 En `backend/app/modules/rules/service.py`: persistir el/los comando(s) de fan-out como pendientes en la MISMA transacción que commitea `Rule` + `RulesetVersion` (antes de intentar el `XADD`)
- [x] 4.3 Implementar un background task / worker que tome los comandos pendientes y ejecute el `XADD` a Valkey con retry, marcándolos como publicados al confirmar
- [x] 4.4 Verificar que un fallo de publicación a Valkey no pierde el comando ni deja la versión huérfana, y que no se duplica la fila de comando persistida
- [x] 4.5 Correr la suite completa para confirmar regresión cero

## 5. M1 — TTL idempotente en rate limit

- [x] 5.1 En `backend/app/core/rate_limit.py`: setear el TTL en cada incremento (pipeline atómico `INCR` + `EXPIRE`, o equivalente idempotente), no solo cuando `count == 1` — implementado como `EXPIRE` incondicional tras cada `INCR` (idempotente y auto-reparador, ver design.md)
- [x] 5.2 Corregir el docstring que dice "sliding-window" → describirlo correctamente como fixed-window de 900 s
- [x] 5.3 Correr la suite completa para confirmar regresión cero

## 6. M5 — Audit detail como JSON válido

- [x] 6.1 En `backend/app/modules/agents/service.py` `update_agent_config`: reemplazar la interpolación f-string sobre `str(list)` por `json.dumps(...)` para el `detail` del audit log
- [x] 6.2 Correr la suite completa para confirmar regresión cero

## 7. M8 — Flag baseline_absent en la respuesta de reject

- [x] 7.1 En `backend/app/modules/actions/service.py` `_reject_single`: incluir `baseline_absent` (ya computado, línea ~275) en el objeto de respuesta; ajustar el schema de reject (y su variante bulk si aplica). NO cambiar la rama de no-op
- [x] 7.2 Correr la suite completa para confirmar regresión cero

## 8. M9 — Health check n8n

- [x] 8.1 En `backend/app/core/health.py` `_check_n8n`: chequear el status code (o `raise_for_status()`) para que un 5xx reporte `down`; implementar el fallback `GET` cuando `HEAD` falla o no está soportado
- [x] 8.2 Correr la suite completa para confirmar regresión cero

## 9. Tests de regresión

- [x] 9.1 M3: test de que crear usuario con email inválido → 422; email duplicado → 409; list/create devuelven el email real; seed usa `ADMIN_EMAIL` y su default
- [x] 9.2 M6: test de que dos incrementos concurrentes producen N+1 y N+2 sin pérdida
- [x] 9.3 H6: test de que con Valkey caído la regla se persiste con versión avanzada + comando pendiente, y que al recuperarse el background task lo publica (reentrega)
- [x] 9.4 M1: test de que la key de rate limit siempre tiene TTL > 0 tras incrementos con `count > 1` (no queda en `-1`)
- [x] 9.5 M5: test de que el `detail` del audit log de `update_config` es JSON parseable con un path que contiene comillas dobles / barra invertida
- [x] 9.6 M8: test de que reject sobre baseline `absent` retorna `baseline_absent: true` y no publica comando; reject normal retorna `baseline_absent: false`
- [x] 9.7 M9: test de que n8n respondiendo 500 reporta `down`; fallback GET cuando HEAD no está soportado
- [x] 9.8 Correr la suite completa con los nuevos tests; confirmar que todos pasan

## 10. M4 — BLOQUEADO: transición a dead de agentes que nunca latieron (requiere decisión D30)

- [ ] 10.1 PRE-REQUISITO: cerrar la decisión (candidata D30) en el appendix "Decisiones de implementación — Abril 2026" de `docs/arquitectura_stack.md` / `docs/reglas_de_negocio.md`: definir la referencia temporal para agentes con `last_heartbeat IS NULL` (opción A: NULL = inmediatamente elegible para `dead`; opción B: agregar `registered_at`/`created_at` a `Agent` + grace de 5 min). NO implementar M4 hasta cerrar esto (ver design → Open Questions) — # DIFERIDO — pendiente D32/RN-126 (candidata D30 en design.md; el equipo usó el número D32 al pedir este apply). NO implementado en este apply por decisión explícita del usuario.
- [ ] 10.2 (post-decisión) En `backend/app/modules/agents/heartbeat_consumer.py` `_sweep_offline`: incluir explícitamente `last_heartbeat IS NULL` en el barrido según la política elegida en 10.1 — # DIFERIDO — pendiente D32/RN-126
- [ ] 10.3 (post-decisión) Test de regresión: agente que nunca latió transiciona (o no) según D30 — # DIFERIDO — pendiente D32/RN-126

## 11. Commit y cierre

- [x] 11.1 Commit `fix(users): add real unique email field + ADMIN_EMAIL seed + migration 002` (M3) — 3ee0794
- [x] 11.2 Commit `fix(rules): atomic ruleset_version increment unified across rules/actions` (M6) — a42abb9
- [x] 11.3 Commit `fix(rules): outbox for rule_sync publish surviving Valkey outage` (H6) — 1a08230 (+ f6a5c6f fixup de test de regresión)
- [x] 11.4 Commit `fix(core): idempotent rate-limit TTL + fixed-window docstring` (M1) — 915f0b1
- [x] 11.5 Commit `fix(agents): valid JSON audit detail in update_config` (M5) — dc9c47f
- [x] 11.6 Commit `fix(actions): return baseline_absent flag on reject no-op` (M8) — 98eb018
- [x] 11.7 Commit `fix(health): n8n check reports down on error status + GET fallback` (M9) — 3d07a9d
- [x] 11.8 Correr la suite completa final y confirmar verde antes de marcar el change como completo — 298 passed, 4 fallas preexistentes fuera de scope (ver nota en 1.1), 0 regresiones nuevas
