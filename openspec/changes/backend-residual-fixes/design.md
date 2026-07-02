## Context

La auditoría del 2026-06-23 ([docs/audit_bugs.md](docs/audit_bugs.md)) catalogó bugs backend por severidad. Los críticos entraron en C22; H5/H7/H8/M2 fueron rescatados por C30/C31/C32. Quedaron 8 sin change: 1 ALTO (H6) y 7 MEDIOS (M1, M3, M4, M5, M6, M8, M9). Revalidados como STILL-PRESENT contra el código actual el 2026-06-30. Este change los remedia; no introduce features.

Restricciones vigentes: backend Python 3.13 + FastAPI async, SQLModel sobre PostgreSQL 18.3, Valkey 9.0.3 para el transporte agent↔backend vía Streams, migraciones SQL idempotentes sin Alembic (D3, prefijo numérico secuencial en `backend/db/migrations/` — el próximo es `002_`), seed admin en el lifespan de FastAPI (D3). Decisión D29 (User.email) cerrada el 2026-07-01.

Hallazgos de ubicación (verificados en código, corrigen supuestos de la entrada de CHANGES.md):
- El modelo `User` vive en `backend/app/modules/auth/models.py` (tabla `users`), **no** en `users/models.py` (ese archivo no existe; el módulo `users/` solo tiene `router.py` y `schemas.py`). El seed admin está en `backend/app/modules/auth/service.py` (invocado desde `main.py`).
- El incremento de versión está duplicado: `rules/service.py:67 increment_ruleset_version()` y `actions/service.py:76 rv.version += 1`.
- `_reject_single` (`actions/service.py:228`) ya computa `baseline_absent` (línea 275) pero no lo retorna.
- `_check_n8n` (`core/health.py:71`) usa `client.head()` sin `raise_for_status()`.
- `_sweep_offline` (`agents/heartbeat_consumer.py:128`) filtra por `Agent.last_heartbeat < threshold` en dos pasadas (offline y dead).
- **El modelo `Agent` (`agents/models.py:17`) NO tiene `created_at` ni `registered_at`** — solo `agent_id`, `status` (default `offline`), `last_heartbeat` (nullable). Esto bloquea parte de M4 (ver Open Questions).

## Goals / Non-Goals

**Goals:**
- H6: hacer que la entrega de `rule_sync` sobreviva a una caída de Valkey vía outbox con retry, sin perder el comando ni dejar la versión huérfana.
- M1: TTL idempotente en el rate limit de login; corregir el docstring fixed-window.
- M3: campo `email` real (NOT NULL + UNIQUE + EmailStr) en `User`, migración `002_`, seed vía `ADMIN_EMAIL`.
- M4 (parte decidible): incluir explícitamente `last_heartbeat IS NULL` en el barrido para no excluir silenciosamente esas filas. **La transición a `dead` de agentes que nunca latieron queda pendiente de decisión (Open Questions).**
- M5: `detail` del audit log de `update_config` como JSON válido vía `json.dumps`.
- M6: incremento de `ruleset_version` atómico y unificado en una sola función.
- M8: `_reject_single` retorna `baseline_absent` en la respuesta, sin cambiar el no-op.
- M9: `_check_n8n` chequea el status code + fallback GET; un 5xx reporta `down`.
- Tests de regresión por cada fix aplicado.

**Non-Goals:**
- Cambios en el protocolo de mensajes Valkey (formato de payloads).
- Endpoints HTTP nuevos o renombrados.
- Agregar `created_at`/`registered_at` al modelo `Agent` (requiere decisión — fuera de scope de este change hasta cerrarla).
- Cambios en el frontend o en el agente FIM.
- Key wrapping / KMS para `shared_secret_hex` (D27, ya documentado como futuro).

## Decisions

### H6 — Outbox para `publish_rule_sync`

**Elección**: persistir el/los comando(s) de fan-out en una tabla outbox (o reutilizar `published_commands` con un estado `pending`/`published`) dentro de la MISMA transacción que commitea `Rule` + `RulesetVersion`. Un background task (o worker de reintento) toma los pendientes y ejecuta el `XADD` a Valkey con retry exponencial; marca cada fila como publicada al confirmar. Si Valkey está caído, la versión avanza pero los comandos quedan `pending` y se entregan al recuperarse.

**Alternativa considerada**: publicar de forma síncrona con retry en el request. Descartada: bloquea el request HTTP durante la caída de Valkey y no garantiza entrega si el proceso muere. El outbox desacopla durabilidad de disponibilidad.

**Nota de implementación**: hoy `publish_rule_sync` corre post-commit (docstring `rules/service.py:13`, "D-F trade-off"). El outbox invierte el orden: primero durabilidad en la misma transacción, luego publicación diferida. Definir en apply si se agrega una tabla `command_outbox` o se extiende `published_commands` con estado — decidirlo mirando el schema real de `published_commands` (D10) para no duplicar concepto.

### M1 — TTL idempotente en rate limit

**Elección**: setear el TTL en cada incremento, no solo cuando `count == 1`. Opción preferida: pipeline atómico `INCR` + `EXPIRE` (o `SET ... EX` idempotente / script Lua) de modo que un `INCR` exitoso nunca deje la key sin TTL. Corregir el docstring que dice "sliding-window": es fixed-window de 900 s.

**Alternativa considerada**: `EXPIRE ... NX` (solo si no tiene TTL). Descartada como única defensa: no repara una key que YA quedó sin TTL por el bug previo; setear el TTL en cada incremento es idempotente y auto-reparador.

### M3 — Campo email real + seed

**Elección**: agregar `email: EmailStr` (o `str` con validación EmailStr en el schema) al modelo `User` en `auth/models.py`, `NOT NULL + UNIQUE`. `CreateUserRequest.email` usa `EmailStr`. `UserItem`/`UserListResponse` devuelven el `email` real. Migración `002_add_user_email.sql` idempotente. Seed admin en `auth/service.py` toma `ADMIN_EMAIL` (default `admin@fim.local`).

**Trade-off de la columna NOT NULL sobre tabla existente**: si hay filas previas (p. ej. el admin sembrado sin email), la migración debe backfillear un valor antes de imponer `NOT NULL` (o agregar la columna con default y luego endurecer). Definir el orden exacto en la migración idempotente durante apply, siguiendo el estilo de `001_add_agent_status_revoked.sql`.

### M5 — Audit detail como JSON válido

**Elección**: reemplazar la interpolación f-string sobre `str(list)` por `json.dumps(...)` en `update_agent_config` (`agents/service.py`). Garantiza comillas dobles y escape correcto de `"`/`\` en paths.

### M6 — Incremento atómico unificado

**Elección**: reemplazar el patrón `SELECT` + `version += 1` + `flush` por un único `UPDATE ruleset_versions SET version = version + 1 RETURNING version`. Unificar las dos implementaciones (`rules/service.py:67` y `actions/service.py:76`) en la función existente `increment_ruleset_version` (o una compartida en `rules/service.py`), y que `actions/service.py` la invoque en lugar de duplicar la lógica.

**Alternativa considerada**: `SELECT ... FOR UPDATE` + incremento en Python. Equivalente en correctitud pero más verboso y con un round-trip extra; el `UPDATE ... RETURNING` es atómico en una sola sentencia.

### M8 — Flag baseline_absent en la respuesta

**Elección**: `_reject_single` ya calcula `baseline_absent` (línea 275); agregarlo al objeto de respuesta (schema de reject y su variante bulk). No se toca la rama de no-op. El frontend consumirá el flag para avisar al admin (consumo del flag fuera de scope de este change backend).

### M9 — Health check n8n

**Elección**: en `_check_n8n`, chequear el status code de la respuesta (o `raise_for_status()`) para que un 5xx reporte `down`. Implementar el fallback GET documentado: si `HEAD` falla o no está soportado, reintentar con `GET`. El `except httpx.HTTPStatusError` deja de ser dead code.

## Risks / Trade-offs

- **[H6] Complejidad del outbox** → mantenerlo mínimo: una tabla/estado + un poller con retry. Riesgo de doble publicación si el proceso muere entre `XADD` y marcar `published`; mitigación: idempotencia del consumer de comandos del agente (ya verifica versión) tolera un reenvío ocasional.
- **[H6] Latencia de entrega** → con Valkey sano la publicación diferida agrega latencia despreciable; con Valkey caído la entrega se demora hasta la recuperación (comportamiento deseado, no un fallo).
- **[M1] Reparación de keys ya rotas** → keys que quedaron sin TTL por el bug previo se auto-reparan en el próximo `INCR`; no requiere migración de datos.
- **[M3] NOT NULL sobre tabla poblada** → backfill obligatorio en la migración antes de endurecer el constraint; validar idempotencia ejecutando el script dos veces.
- **[M6] UPDATE ... RETURNING** → soportado por PostgreSQL 18.3; confirmar que la sesión SQLModel/SQLAlchemy propaga el valor retornado.
- **[M8] Contrato de respuesta** → agregar un campo es aditivo; clientes viejos lo ignoran. Sin ruptura.
- **[M9] Fallback GET** → un `GET` a un webhook n8n podría disparar el workflow. Mitigación: preferir `HEAD` y usar `GET` solo como fallback cuando `HEAD` no está soportado; documentar el comportamiento.

## Migration Plan

1. Correr la suite completa en verde antes de tocar nada.
2. M3 primero (afecta migración de BD): modelo + `002_add_user_email.sql` + seed `ADMIN_EMAIL` + schemas/router; validar migración idempotente ejecutándola dos veces.
3. M6 (unificar incremento atómico) — base para H6.
4. H6 (outbox) apoyándose en el incremento atómico.
5. M1, M5, M8, M9 (fixes localizados, independientes entre sí).
6. M4 (parte decidible: `last_heartbeat IS NULL` en el barrido) **solo si se cierra la decisión de Open Questions**; caso contrario queda BLOQUEADO y fuera de este apply.
7. Tests de regresión por fix; suite completa final en verde.
8. Rollback: revertir el commit del fix afectado. La migración `002_` es aditiva; el rollback de la columna requiere un `DROP COLUMN` manual si fuese necesario.

## Open Questions

- **[M4 — BLOQUEANTE, suposición NO cerrada]** El modelo `Agent` no tiene `created_at`/`registered_at`. La entrada de CHANGES.md asumía usar `created_at` como referencia temporal, pero ese campo no existe. Sin una referencia temporal no se puede decidir *cuándo* un agente que nunca latió (`last_heartbeat IS NULL`, `status=offline` por default) debe transicionar a `dead`: RN-92 dice "sin heartbeat 5 min → dead", pero no hay marca de "desde cuándo". Hay dos comportamientos posibles y elegir cualquiera ES una decisión de producto:
  1. **NULL = inmediatamente elegible para `dead`** (nunca probó estar vivo). Riesgo: un agente recién pre-registrado por el admin flipea a `dead` en <10 s antes de instalarse (self-healing al primer heartbeat, pero falso positivo transitorio).
  2. **Agregar `registered_at`/`created_at` a `Agent`** (+ migración) y aplicar la grace de 5 min desde el registro. Cambio de modelo de datos + decisión.

  Por la regla del proyecto (CLAUDE.md: no avanzar con suposiciones tácitas), la transición-a-dead de agentes NULL queda **fuera de scope** hasta cerrar esta decisión en el appendix "Decisiones de implementación — Abril 2026" (candidata **D30**). La parte puramente decidible (no excluir silenciosamente filas NULL del barrido) se documenta pero su implementación depende de qué política se elija. Recomendación: cerrar D30 antes de `/opsx:apply`.
- El resto de los fixes (H6, M1, M3, M5, M6, M8, M9) no tiene decisiones abiertas: D3 y D29 están cerradas.
