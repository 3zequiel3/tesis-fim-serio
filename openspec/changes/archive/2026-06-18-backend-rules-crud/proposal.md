## Why

Las reglas de decisión (pattern + severity + action) son el corazón del motor de decisión del agente, pero hoy no existe forma de gestionarlas: el modelo `Rule` y el counter `RulesetVersion` ya están definidos (C03) pero no hay endpoints ni lógica de sincronización. Sin CRUD de reglas, un admin no puede definir qué hace el sistema cuando detecta un cambio, y el agente (C10) no tiene reglas que aplicar más allá del default `alert_only`. Este change cierra esa brecha y es prerequisito de C13 (approve/reject) y C19 (dashboard de reglas).

## What Changes

- **Nuevos endpoints REST `/rules`** (autenticados via JWT de C04):
  - `POST /rules` — crear regla (solo admin)
  - `GET /rules` — listar reglas (cualquier usuario autenticado), ordenadas por severity (critical→low) y luego por id
  - `GET /rules/{id}` — detalle de una regla (autenticado)
  - `PUT /rules/{id}` — actualizar regla (solo admin)
  - `DELETE /rules/{id}` — eliminar regla (solo admin)
- **Validación de reglas** (RN-08, RN-58): `pattern` debe ser un glob válido compatible con `fnmatch` de Python; `severity` debe estar en el enum `RuleSeverity`; `action` debe estar en el enum `RuleAction`.
- **Sincronización al agente en cada escritura** (RN-58, RN-75, RN-79, D5, D9): tras todo POST/PUT/DELETE se incrementa el counter global `RulesetVersion`, y se hace **fan-out** de un comando `rule_sync` firmado HMAC — un mensaje físico por agente registrado, cada uno con `target_agent_id = agent.agent_id` y firmado con el `shared_secret_hex` específico de ese agente.
- **Nueva tabla `published_commands`** (D10): registro histórico de todo comando versionado publicado al stream `commands`, base del check D5 "agente al día".
- **Auditoría** (RN-94): cada CRUD de regla escribe una fila en `audit_log` (user_id, action, target_type='rule', target_id).

## Capabilities

### New Capabilities
- `backend-rules`: gestión CRUD de reglas de decisión vía REST, validación de pattern/severity/action, incremento del counter `RulesetVersion`, fan-out de comandos `rule_sync` firmados HMAC por agente, registro en `published_commands` y auditoría.

### Modified Capabilities
- `domain-models`: se agrega el modelo `PublishedCommand` (tabla `published_commands`) — owner asignado a C12 por D10. No cambia la semántica de modelos existentes; solo agrega uno nuevo.

## Impact

- **Código nuevo**:
  - `backend/app/modules/rules/service.py` — lógica de negocio (create/update/delete, increment_ruleset_version, publish_rule_sync con fan-out, registro en published_commands + audit_log).
  - `backend/app/modules/rules/router.py` — router FastAPI con los 5 endpoints.
- **Código modificado**:
  - `backend/app/modules/rules/models.py` — agrega `class PublishedCommand(SQLModel, table=True)`.
  - `backend/app/main.py` — registra el `rules_router` y asegura que `PublishedCommand` quede en `SQLModel.metadata` para `create_all()`.
- **Reutiliza** (sin modificar): `app/core/streams.py` (`sign_payload`, `canonical_json`, `STREAM_COMMANDS`, `SCHEMA_VERSION`), `app/core/deps.py` (`get_current_user`, `require_admin`), `app/core/valkey.py` (`get_valkey_client`), `app/modules/agents/models.py` (`Agent.shared_secret_hex`), `app/modules/audit/models.py` (`AuditLog`).
- **APIs**: nuevos endpoints REST bajo `/rules` (OpenAPI auto-documentado).
- **Stream Valkey**: nuevos mensajes `rule_sync` en el stream `commands`, consumidos por el agente (C10 `commands_consumer`).
- **Dependencias DAG**: C04 (auth) y C08 (transport) — ambas archivadas. Satisfechas.
- **Reglas cubiertas**: RN-08, RN-09, RN-29, RN-57, RN-58, RN-75, RN-79, RN-94, RN-106. **Decisiones aplicadas**: D5, D9, D10.
