## ADDED Requirements

### Requirement: Modelo Event con EventStatus canónico y optimistic locking

El sistema SHALL definir `class Event(SQLModel, table=True)` en `backend/app/modules/events/models.py` con los campos: `id: int` (PK autoincrement), `path: str` (indexed), `hash_detected: str`, `status: EventStatus` (enum, indexed), `parent_event_id: int | None` (FK `events.id`), `version: int = 0` (optimistic locking, RN-77), `process_pid: int | None`, `process_uid: int | None`, `process_exe: str | None`, `detected_at: datetime`, `received_at: datetime`, `created_at: datetime`, `resolved_at: datetime | None`, `resolved_by: int | None` (FK `users.id`). El enum `EventStatus(str, Enum)` SHALL tener exactamente los 7 valores canónicos en minúsculas (RN-71): `pending`, `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`.

#### Scenario: Tabla events creada con columnas correctas
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `events` existe en PostgreSQL
- **AND** tiene columnas `id`, `path`, `hash_detected`, `status`, `parent_event_id`, `version`, `process_pid`, `process_uid`, `process_exe`, `detected_at`, `received_at`, `created_at`, `resolved_at`, `resolved_by`

#### Scenario: EventStatus rechaza valores fuera del léxico canónico
- **WHEN** se intenta asignar `EventStatus("PENDING")` (mayúsculas)
- **THEN** se lanza `ValueError`

#### Scenario: EventStatus acepta los 7 valores canónicos
- **WHEN** se crean instancias con cada uno de los valores `pending`, `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`
- **THEN** cada instancia se crea sin error

### Requirement: Modelos Rule y RulesetVersion con léxico canónico

El sistema SHALL definir `class Rule(SQLModel, table=True)` en `backend/app/modules/rules/models.py` con: `id: int` (PK), `pattern: str`, `severity: RuleSeverity`, `action: RuleAction`, `created_at: datetime`, `updated_at: datetime`. El enum `RuleAction(str, Enum)` SHALL tener exactamente los 4 valores: `auto_restore`, `quarantine`, `manual_review`, `alert_only` (RN-08). El enum `RuleSeverity(str, Enum)` SHALL tener los valores: `critical`, `high`, `medium`, `low`. El sistema SHALL definir `class RulesetVersion(SQLModel, table=True)` con: `id: int` (PK), `version: int = 0` (contador global monotónico, D5), `updated_at: datetime`. La tabla `ruleset_versions` SHALL tener como máximo 1 fila.

#### Scenario: Tabla rules creada
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `rules` existe con columnas `id`, `pattern`, `severity`, `action`, `created_at`, `updated_at`

#### Scenario: RuleAction rechaza valores fuera de los 4 canónicos
- **WHEN** se intenta construir `RuleAction("block")`
- **THEN** se lanza `ValueError`

#### Scenario: Tabla ruleset_versions creada
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `ruleset_versions` existe con columnas `id`, `version`, `updated_at`

### Requirement: Modelo Agent con AgentStatus y tabla revoked_certificates

El sistema SHALL definir `class Agent(SQLModel, table=True)` en `backend/app/modules/agents/models.py` con: `agent_id: str` (PK, UUID string), `status: AgentStatus`, `last_heartbeat: datetime | None`, `ruleset_version_applied: int = 0` (semántica D5: máximo version de comandos broadcast o targeted a este agente confirmados via event_ack), `queue_pressure: float | None`, `bootstrap_secret_hash: str | None`. El enum `AgentStatus(str, Enum)` SHALL tener los valores: `online`, `offline`, `draining`, `dead`. El sistema SHALL definir `class RevokedCertificate(SQLModel, table=True)` en el mismo módulo con: `id: int` (PK), `agent_id: str` (FK `agents.agent_id`), `serial_number: str`, `revoked_at: datetime`, `reason: str | None`.

#### Scenario: Tabla agents creada con PK string
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `agents` existe
- **AND** la columna `agent_id` es de tipo VARCHAR (no INTEGER)

#### Scenario: AgentStatus acepta los 4 valores canónicos
- **WHEN** se crean instancias con `online`, `offline`, `draining`, `dead`
- **THEN** cada instancia se crea sin error

#### Scenario: Tabla revoked_certificates creada con FK
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `revoked_certificates` existe con FK a `agents.agent_id`

### Requirement: Modelo BaselineEntry con status present/absent (D1, RN-66, RN-104)

El sistema SHALL definir `class BaselineEntry(SQLModel, table=True)` en `backend/app/modules/agents/models.py` con: `id: int` (PK), `path: str` (indexed), `agent_id: str` (FK `agents.agent_id`, indexed), `hash: str | None` (null cuando status=`absent`), `status: BaselineStatus`, `last_updated: datetime`, `ruleset_version: int`. El enum `BaselineStatus(str, Enum)` SHALL tener exactamente los valores `present` y `absent`. La tabla SHALL tener un índice unique compuesto sobre `(path, agent_id)`.

#### Scenario: Tabla baseline_entries creada con unique constraint
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `baseline_entries` existe
- **AND** tiene un unique constraint (o index) sobre `(path, agent_id)`

#### Scenario: BaselineStatus solo acepta present y absent
- **WHEN** se intenta construir `BaselineStatus("missing")`
- **THEN** se lanza `ValueError`

#### Scenario: hash puede ser null cuando status es absent
- **WHEN** se inserta una fila con `hash=None` y `status=BaselineStatus.absent`
- **THEN** la inserción tiene éxito sin violación de constraint

### Requirement: Modelo RejectedEventAudit con RejectionReason tipado (D4, RN-105)

El sistema SHALL definir `class RejectedEventAudit(SQLModel, table=True)` en `backend/app/modules/events/models.py` con: `id: int` (PK), `event_id: str | None` (UUID si pudo parsearse), `agent_id: str`, `reason: RejectionReason`, `received_at: datetime`, `detected_at: datetime | None`, `payload_dump: str` (JSON truncado a 4 KB). El enum `RejectionReason(str, Enum)` SHALL tener exactamente los valores: `clock_skew`, `invalid_schema`, `invalid_signature`, `unknown_agent`, `duplicate_event`.

#### Scenario: Tabla rejected_events_audit creada
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `rejected_events_audit` existe con columnas `id`, `event_id`, `agent_id`, `reason`, `received_at`, `detected_at`, `payload_dump`

#### Scenario: RejectionReason rechaza valores no canónicos
- **WHEN** se intenta construir `RejectionReason("expired")`
- **THEN** se lanza `ValueError`

#### Scenario: Los 5 valores canónicos son aceptados
- **WHEN** se crean instancias con `clock_skew`, `invalid_schema`, `invalid_signature`, `unknown_agent`, `duplicate_event`
- **THEN** cada instancia se crea sin error

### Requirement: Modelo Alert unificado con lifecycle completo (D6, RN-107)

El sistema SHALL definir `class Alert(SQLModel, table=True)` en `backend/app/modules/alerts/models.py` con: `id: int` (PK), `event_id: int` (FK `events.id`), `severity: AlertSeverity`, `channel: AlertChannel | None` (null mientras pending), `delivered_at: datetime | None`, `failed_at: datetime | None`, `last_error: str | None`, `retry_count: int = 0`, `created_at: datetime`. Los enums SHALL ser: `AlertSeverity(str, Enum)` con valores `critical`, `high`, `medium`, `low`; `AlertChannel(str, Enum)` con valores `n8n`, `smtp_fallback`, `webhook_fallback`, `log_only`. La tabla `failed_notifications` NO SHALL existir; el modelo `Alert` cubre su función (D6).

#### Scenario: Tabla alerts creada con columnas de lifecycle
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `alerts` existe
- **AND** tiene columnas `delivered_at`, `failed_at`, `retry_count`, `last_error`, `channel`
- **AND** NO existe la tabla `failed_notifications`

#### Scenario: Estados derivables por query SQL
- **WHEN** se consulta `SELECT * FROM alerts WHERE delivered_at IS NULL AND failed_at IS NOT NULL`
- **THEN** el resultado contiene solo alertas en estado "failed terminal" (D6)

#### Scenario: channel puede ser null en estado pending
- **WHEN** se inserta una alerta con `channel=None`, `delivered_at=None`, `failed_at=None`
- **THEN** la inserción tiene éxito

### Requirement: Modelo AuditLog sin FK a Event

El sistema SHALL definir `class AuditLog(SQLModel, table=True)` en `backend/app/modules/audit/models.py` con: `id: int` (PK), `user_id: int` (FK `users.id`), `action: str`, `target_type: str | None`, `target_id: int | None`, `detail: str | None` (JSON dump de contexto), `created_at: datetime`. El campo `target_id` SHALL ser nullable para cubrir acciones sin target específico (e.g., login).

#### Scenario: Tabla audit_log creada
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `audit_log` existe con columnas `id`, `user_id`, `action`, `target_type`, `target_id`, `detail`, `created_at`

#### Scenario: Registro sin target_id tiene éxito
- **WHEN** se inserta una fila con `target_type=None` y `target_id=None`
- **THEN** la inserción tiene éxito sin violación de constraint

### Requirement: main.py importa todos los módulos de modelos antes de create_all()

El sistema SHALL garantizar que `SQLModel.metadata` tenga todos los modelos registrados cuando se llama `create_all()` en el lifespan. Para ello, `backend/app/main.py` SHALL importar (directamente o vía `modules/__init__.py`) todos los archivos `modules/<domain>/models.py` antes de que el lifespan ejecute `create_all()`.

#### Scenario: create_all() crea todas las tablas del schema
- **WHEN** el backend arranca contra una base `fim` vacía (solo con el schema público)
- **THEN** `create_all()` crea las tablas: `events`, `rules`, `ruleset_versions`, `agents`, `revoked_certificates`, `baseline_entries`, `rejected_events_audit`, `alerts`, `audit_log`, `users`
- **AND** no lanza `NoSuchTableError` ni `ProgrammingError`

#### Scenario: create_all() es idempotente en segunda ejecución
- **WHEN** el backend se reinicia con las tablas ya existentes
- **THEN** `create_all()` completa sin error
- **AND** no elimina ni recrea datos existentes
