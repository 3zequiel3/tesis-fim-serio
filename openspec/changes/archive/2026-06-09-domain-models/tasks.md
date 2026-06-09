## 1. Estructura de módulos

- [x] 1.1 Crear `backend/app/modules/events/__init__.py` (vacío)
- [x] 1.2 Crear `backend/app/modules/rules/__init__.py` (vacío)
- [x] 1.3 Crear `backend/app/modules/agents/__init__.py` (vacío)
- [x] 1.4 Crear `backend/app/modules/alerts/__init__.py` (vacío)
- [x] 1.5 Crear `backend/app/modules/auth/__init__.py` (vacío)
- [x] 1.6 Crear `backend/app/modules/audit/__init__.py` (vacío)

## 2. Modelo User (modules/auth)

- [x] 2.1 Crear `backend/app/modules/auth/models.py` con `class User(SQLModel, table=True)`: `id: int` (PK), `username: str` (unique), `password_hash: str`, `role: str = "admin"`, `must_change_password: bool = True`, `created_at: datetime`
- [x] 2.2 Agregar índice único sobre `users.username`

## 3. Modelos Event y RejectedEventAudit (modules/events)

- [x] 3.1 Crear `backend/app/modules/events/models.py`
- [x] 3.2 Definir `class EventStatus(str, Enum)` con los 7 valores canónicos: `pending`, `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`
- [x] 3.3 Definir `class Event(SQLModel, table=True)` con todos los campos según spec: `id`, `path` (indexed), `hash_detected`, `status`, `parent_event_id` (FK self), `version`, `process_pid`, `process_uid`, `process_exe`, `detected_at`, `received_at`, `created_at`, `resolved_at`, `resolved_by` (FK users.id)
- [x] 3.4 Definir `class RejectionReason(str, Enum)` con 5 valores: `clock_skew`, `invalid_schema`, `invalid_signature`, `unknown_agent`, `duplicate_event`
- [x] 3.5 Definir `class RejectedEventAudit(SQLModel, table=True)` con: `id`, `event_id` (nullable string), `agent_id`, `reason`, `received_at`, `detected_at`, `payload_dump`

## 4. Modelos Rule y RulesetVersion (modules/rules)

- [x] 4.1 Crear `backend/app/modules/rules/models.py`
- [x] 4.2 Definir `class RuleAction(str, Enum)` con 4 valores: `auto_restore`, `quarantine`, `manual_review`, `alert_only`
- [x] 4.3 Definir `class RuleSeverity(str, Enum)` con 4 valores: `critical`, `high`, `medium`, `low`
- [x] 4.4 Definir `class Rule(SQLModel, table=True)` con: `id`, `pattern`, `severity`, `action`, `created_at`, `updated_at`
- [x] 4.5 Definir `class RulesetVersion(SQLModel, table=True)` con: `id`, `version: int = 0`, `updated_at`

## 5. Modelos Agent, RevokedCertificate y BaselineEntry (modules/agents)

- [x] 5.1 Crear `backend/app/modules/agents/models.py`
- [x] 5.2 Definir `class AgentStatus(str, Enum)` con 4 valores: `online`, `offline`, `draining`, `dead`
- [x] 5.3 Definir `class Agent(SQLModel, table=True)` con PK string `agent_id`: `agent_id: str` (PK), `status: AgentStatus`, `last_heartbeat: datetime | None`, `ruleset_version_applied: int = 0`, `queue_pressure: float | None`, `bootstrap_secret_hash: str | None`
- [x] 5.4 Definir `class RevokedCertificate(SQLModel, table=True)` con FK a `agents.agent_id`
- [x] 5.5 Definir `class BaselineStatus(str, Enum)` con valores `present`, `absent`
- [x] 5.6 Definir `class BaselineEntry(SQLModel, table=True)` con unique constraint sobre `(path, agent_id)`: `id`, `path` (indexed), `agent_id` (FK agents, indexed), `hash: str | None`, `status: BaselineStatus`, `last_updated`, `ruleset_version`

## 6. Modelo Alert (modules/alerts)

- [x] 6.1 Crear `backend/app/modules/alerts/models.py`
- [x] 6.2 Definir `class AlertSeverity(str, Enum)` con 4 valores: `critical`, `high`, `medium`, `low`
- [x] 6.3 Definir `class AlertChannel(str, Enum)` con 4 valores: `n8n`, `smtp_fallback`, `webhook_fallback`, `log_only`
- [x] 6.4 Definir `class Alert(SQLModel, table=True)` con: `id`, `event_id` (FK events.id), `severity`, `channel: AlertChannel | None`, `delivered_at: datetime | None`, `failed_at: datetime | None`, `last_error: str | None`, `retry_count: int = 0`, `created_at`

## 7. Modelo AuditLog (modules/audit)

- [x] 7.1 Crear `backend/app/modules/audit/models.py`
- [x] 7.2 Definir `class AuditLog(SQLModel, table=True)` con: `id`, `user_id` (FK users.id), `action: str`, `target_type: str | None`, `target_id: int | None`, `detail: str | None`, `created_at`

## 8. Registro de modelos y seed_admin

- [x] 8.1 Importar todos los `modules/<domain>/models.py` en `backend/app/modules/__init__.py` para asegurar registro en `SQLModel.metadata`
- [x] 8.2 Importar `backend/app/modules` en `backend/app/main.py` (antes del lifespan) para que `create_all()` vea todos los modelos
- [x] 8.3 Mover `seed_admin()` de `main.py` a `backend/app/modules/auth/service.py` con la lógica completa: verificar si existe admin, si no existe crearlo con Argon2id + `must_change_password=True`, si tabla no existe retornar con log `event=seed_admin.skipped`
- [x] 8.4 Actualizar `main.py` para importar `seed_admin` desde `modules/auth/service.py`

## 9. Smoke test

- [x] 9.1 Agregar test `backend/tests/test_domain_models.py` que verifica: (a) enums rechazan valores fuera del léxico canónico, (b) `EventStatus`, `RuleAction`, `AgentStatus`, `BaselineStatus`, `RejectionReason`, `AlertSeverity`, `AlertChannel` aceptan todos sus valores canónicos
- [x] 9.2 Levantar `docker compose up -d db valkey backend` y verificar que `create_all()` crea las 10 tablas esperadas: `users`, `events`, `rejected_events_audit`, `rules`, `ruleset_versions`, `agents`, `revoked_certificates`, `baseline_entries`, `alerts`, `audit_log`
- [x] 9.3 Verificar que `baseline_entries` y `alerts` existen con el shape definido en los appendices de docs (`arquitectura_stack.md §D1, D6`)
- [x] 9.4 Verificar que NO existe la tabla `failed_notifications`
- [x] 9.5 Reiniciar el backend y confirmar que `create_all()` es idempotente (no errores, no pérdida de datos)
