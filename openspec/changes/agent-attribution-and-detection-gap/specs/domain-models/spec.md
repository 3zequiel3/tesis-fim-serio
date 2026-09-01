## MODIFIED Requirements

### Requirement: Modelo Event con EventStatus canónico y optimistic locking

El sistema SHALL definir `class Event(SQLModel, table=True)` en
`backend/app/modules/events/models.py` con los campos: `id: int` (PK autoincrement),
`event_type: str` (default `file_modified`), `path: str | None` (indexed), `hash_detected: str`,
`status: EventStatus` (enum, indexed), `parent_event_id: int | None` (FK `events.id`),
`version: int = 0` (optimistic locking, RN-77), `process_pid: int | None`, `process_uid: int | None`,
`process_exe: str | None`, `detected_at: datetime`, `received_at: datetime`, `created_at: datetime`,
`resolved_at: datetime | None`, `resolved_by: int | None` (FK `users.id`). El enum
`EventStatus(str, Enum)` SHALL tener exactamente los 7 valores canónicos en minúsculas (RN-71):
`pending`, `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`.

`event_type` SHALL persistir el vocabulario que el agente ya emite —`file_created`, `file_modified`,
`file_deleted`, `file_absent`, `detection_gap`— en minúsculas snake_case (RN-71, D51/RN-145). El
campo SHALL declararse como `str` **sin validación contra enum ni restricción `CHECK` en la base**,
con el mismo criterio de tolerancia hacia adelante que `action` y `action_error` (D33, D36/RN-130):
un valor desconocido emitido por un agente más nuevo se guarda tal cual en vez de rechazar el evento.

`path` SHALL admitir nulo: un evento puede no hablar de ningún archivo concreto, como el
`detection_gap` que reporta una brecha de cobertura del kernel (D50/RN-144). El nulo MUST llegar
nulo hasta la columna; el modelo MUST NOT declarar cadena vacía como default.

`process_pid`, `process_uid` y `process_exe` SHALL seguir siendo nullables, y un nulo SHALL
significar **atribución no resuelta** (D49/RN-143). El valor `0` en `process_uid` SHALL significar
exclusivamente que el proceso causante corría como root.

#### Scenario: Tabla events creada con columnas correctas
- **WHEN** el backend arranca y ejecuta `create_all()`
- **THEN** la tabla `events` existe en PostgreSQL
- **AND** tiene columnas `id`, `event_type`, `path`, `hash_detected`, `status`, `parent_event_id`, `version`, `process_pid`, `process_uid`, `process_exe`, `detected_at`, `received_at`, `created_at`, `resolved_at`, `resolved_by`

#### Scenario: EventStatus rechaza valores fuera del léxico canónico
- **WHEN** se intenta asignar `EventStatus("PENDING")` (mayúsculas)
- **THEN** se lanza `ValueError`

#### Scenario: EventStatus acepta los 7 valores canónicos
- **WHEN** se crean instancias con cada uno de los valores `pending`, `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`
- **THEN** cada instancia se crea sin error

#### Scenario: La columna path acepta NULL
- **WHEN** se inserta un `Event` con `path=None`
- **THEN** la inserción completa sin `IntegrityError`
- **AND** la fila resultante tiene `path IS NULL`

#### Scenario: event_type acepta un valor fuera del vocabulario conocido
- **WHEN** se inserta un `Event` con `event_type="some_future_type"`
- **THEN** la inserción completa sin error y el valor se persiste literal

## ADDED Requirements

### Requirement: Migración 012 agrega event_type y relaja path a nullable

El sistema SHALL proveer `backend/db/migrations/012_add_event_type_and_nullable_path.sql`, siguiendo
la misma convención que las migraciones 005–011: SQL manual versionado, sin Alembic (D3), aplicable
con `psql $DATABASE_URL -f 012_add_event_type_and_nullable_path.sql`, con un encabezado de
comentario que explique la decisión que lo motiva y sus consecuencias.

La migración SHALL: (1) agregar la columna `event_type` como `VARCHAR` NOT NULL con default
`'file_modified'` para las filas preexistentes; (2) ejecutar `ALTER TABLE events ALTER COLUMN path
DROP NOT NULL`. El script SHALL ser idempotente: `ADD COLUMN IF NOT EXISTS` para la primera
operación, y la segunda es un no-op sin error sobre una columna ya nullable.

La migración SHALL viajar **en esta misma change**, no en una separada: el modelo SQLModel declara
`event_type` y `create_all` no altera tablas existentes, de modo que un backend desplegado sin la
migración fallaría en la primera ingesta con `UndefinedColumn`.

El default `file_modified` para filas preexistentes SHALL documentarse como **irrecuperable, no
adivinado**: hasta esta change el backend nunca persistió `event_type`, así que el valor real de los
eventos históricos no existe en ningún lado. `file_modified` es el caso mayoritario y el valor que
D51/RN-145 fija como default.

La migración SHALL NOT crear índice sobre `event_type`: no hay endpoint ni filtro que consulte por
ese campo en el alcance de esta change, e indexar una columna de baja cardinalidad sin consulta que
lo justifique no aporta nada — mismo criterio que la migración 008 con `action_error`.

#### Scenario: La migración agrega la columna con el default correcto
- **WHEN** se ejecuta la migración sobre una base con filas preexistentes en `events`
- **THEN** la columna `event_type` existe, es NOT NULL, y todas las filas previas tienen `'file_modified'`

#### Scenario: La migración relaja path a nullable
- **WHEN** se ejecuta la migración
- **THEN** `events.path` admite NULL

#### Scenario: La migración es idempotente
- **WHEN** se ejecuta la migración dos veces consecutivas
- **THEN** la segunda ejecución completa sin error y sin alterar los datos
