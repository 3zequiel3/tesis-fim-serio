# domain-models Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
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

El sistema SHALL definir `class RejectedEventAudit(SQLModel, table=True)` en `backend/app/modules/events/models.py` con: `id: int` (PK), `event_id: str | None` (UUID si pudo parsearse), `agent_id: str`, `reason: RejectionReason`, `received_at: datetime`, `detected_at: datetime | None`, `payload_dump: str` (JSON truncado a 4 KB). El enum `RejectionReason(str, Enum)` SHALL tener exactamente los valores: `clock_skew`, `invalid_schema`, `invalid_signature`, `unknown_agent`, `duplicate_event`, `rate_limited`.

#### Scenario: Tabla rejected_events_audit creada
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `rejected_events_audit` existe con columnas `id`, `event_id`, `agent_id`, `reason`, `received_at`, `detected_at`, `payload_dump`

#### Scenario: RejectionReason rechaza valores no canónicos
- **WHEN** se intenta construir `RejectionReason("expired")`
- **THEN** se lanza `ValueError`

#### Scenario: Los 6 valores canónicos son aceptados
- **WHEN** se crean instancias con `clock_skew`, `invalid_schema`, `invalid_signature`, `unknown_agent`, `duplicate_event`, `rate_limited`
- **THEN** cada instancia se crea sin error

#### Scenario: Rechazo por rate limit registrado con reason=rate_limited
- **WHEN** el consumer supera el rate limit para un `agent_id`
- **THEN** se inserta en `rejected_events_audit` con `reason=rate_limited`
- **AND** el `payload_dump` es el JSON del evento truncado a 4 KB

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

### Requirement: Modelo PublishedCommand

El sistema SHALL definir un modelo `PublishedCommand` (tabla `published_commands`) en `backend/app/modules/rules/models.py` (owner C12 por D10). El modelo MUST tener las columnas: `id: int` (PK autoincrement), `command_type: str`, `target_agent_id: str | None`, `ruleset_version: int`, `published_at: datetime`. La tabla MUST quedar registrada en `SQLModel.metadata` para que `create_all()` la incluya. Esta tabla es el registro histórico de todo comando versionado publicado al stream `commands` y la base del check D5 de "agente al día".

#### Scenario: Tabla creada en create_all
- **WHEN** el backend arranca y ejecuta `SQLModel.metadata.create_all(engine)`
- **THEN** la tabla `published_commands` existe con las columnas id, command_type, target_agent_id, ruleset_version, published_at

#### Scenario: Inserción de un comando publicado
- **WHEN** se inserta un `PublishedCommand` con `command_type='rule_sync'`, `target_agent_id='agent-1'`, `ruleset_version=5`
- **THEN** la fila persiste con un `id` autoincrement y un `published_at` no nulo

#### Scenario: target_agent_id nullable
- **WHEN** se define el modelo `PublishedCommand`
- **THEN** `target_agent_id` admite `None` para soportar el check D5 (`... OR target_agent_id IS NULL`), aunque `rule_sync` siempre lo escribe con id explícito

### Requirement: Every persisted instant is stored in a column that declares its time zone

Every column that holds a point in time SHALL be `timestamp with time zone` (`timestamptz`). The instant a row records MUST be determined by the stored value and its type alone, and MUST NOT depend on the `TimeZone` setting of the session that reads or writes it.

This covers exactly the 19 columns that exist today, across 11 tables:

| Table | Columns |
|---|---|
| `agents` | `last_heartbeat` |
| `alerts` | `created_at`, `delivered_at`, `failed_at` |
| `audit_log` | `created_at` |
| `baseline_entries` | `last_updated` |
| `events` | `created_at`, `detected_at`, `received_at`, `resolved_at` |
| `published_commands` | `acked_at`, `published_at` |
| `rejected_events_audit` | `detected_at`, `received_at` |
| `revoked_certificates` | `revoked_at` |
| `rules` | `created_at`, `updated_at` |
| `ruleset_versions` | `updated_at` |
| `users` | `created_at` |

The requirement is stated as a property of **every** instant-valued column, not as a list. A column added later that holds a point in time MUST satisfy it too; the table above is the inventory at the time of writing, not the definition.

The migration MUST preserve every stored instant unchanged. The values already hold UTC by convention, so the conversion changes the declared type and not the instant.

#### Scenario: The 19 columns report as time-zone aware
- **WHEN** `information_schema.columns` is queried for the schema the backend uses
- **THEN** each of the 19 columns above reports `data_type` of `timestamp with time zone`

#### Scenario: No instant-valued column is left without a zone
- **WHEN** `information_schema.columns` is queried for every column whose `data_type` starts with `timestamp`
- **THEN** the result contains no column of type `timestamp without time zone`

#### Scenario: The stored instant survives the migration
- **WHEN** a row written before the migration is read after it
- **THEN** the value denotes the same instant it denoted before, now carrying a `+00` offset

#### Scenario: The migration is idempotent
- **WHEN** the migration script is applied a second time against an already-migrated database
- **THEN** it completes without error and changes nothing

#### Scenario: The migration refuses to run under a non-UTC session
- **WHEN** the migration script is applied by a session whose effective time zone is not UTC
- **THEN** it aborts with an explicit error before altering any column, because interpreting the naive values under another zone would silently shift every instant

### Requirement: Model definitions produce time-zone-aware columns and time-zone-aware defaults

The SQLModel definitions SHALL declare instant-valued fields as time-zone aware, so that a schema built from the models — as the test harness does with `SQLModel.metadata.create_all` — produces the same column type as the schema built by the migrations. Declaring the type in the migration alone is insufficient: it would leave the entire test suite validating a schema that does not exist in production.

Every default that produces a timestamp SHALL use `datetime.now(timezone.utc)`. `datetime.utcnow` SHALL NOT be used in any form — neither called nor passed as a factory. It returns a naive value that resembles UTC without declaring it, it is the origin of the naive/aware mixture, and it is deprecated as of Python 3.12.

#### Scenario: A schema built from the models is time-zone aware
- **WHEN** the schema is created from the model metadata rather than from the migrations
- **THEN** every instant-valued column reports `timestamp with time zone`

#### Scenario: Default-generated timestamps are aware
- **WHEN** a row is created without supplying a value for a timestamp field that has a default
- **THEN** the value stored is time-zone aware and denotes the current instant in UTC

#### Scenario: utcnow is absent from production modules in every form
- **WHEN** the production sources under `backend/app/` are scanned for `datetime.utcnow`
- **THEN** no occurrence is found, whether written as a call `datetime.utcnow()` or as a bare reference such as `default_factory=datetime.utcnow`

#### Scenario: The guard against utcnow is proven to fail on its own negative case
- **WHEN** the guard that scans for `datetime.utcnow` is given a source fragment containing `default_factory=datetime.utcnow`
- **THEN** the guard reports it as a violation

### Requirement: Existing temporal comparisons keep their meaning

The change SHALL NOT alter the semantics of any comparison over instants. The anti-replay skew window (RN-90, RN-131), the 30-day retention of terminal events (RN-98), the agent offline/dead sweep and the command sweep MUST continue to select the same rows for the same data.

These comparisons are evaluated by PostgreSQL, with an aware Python datetime compared against the column. Before the change PostgreSQL coerces the aware value using the session's zone and reaches the right answer because that zone happens to be UTC; after the change it compares instants directly. The outcome is unchanged; what is removed is the dependency on the session.

#### Scenario: The retention cutoff selects the same events
- **WHEN** the retention task runs against a fixed set of events with known ages
- **THEN** it selects exactly the terminal events older than the retention window, as it did before the migration

#### Scenario: The agent sweep transitions the same agents
- **WHEN** the offline/dead sweep runs against agents with known last-heartbeat instants
- **THEN** it transitions exactly the agents whose last heartbeat falls outside the corresponding threshold

#### Scenario: The skew window accepts and rejects the same events
- **WHEN** an event carrying a `sent_at` inside the skew window is ingested, and another carrying one outside it
- **THEN** the first is accepted and the second is rejected with `clock_skew`, unchanged from before the migration

