## ADDED Requirements

### Requirement: Retención de rejected_events_audit sin purga de audit_log (D65, RN-159, W18/RN-94)

El backend SHALL definir el setting `rejected_events_retention_days` (variable de entorno `REJECTED_EVENTS_RETENTION_DAYS`, entero, default `90`, mínimo `1`); un valor menor que 1 o no entero MUST abortar el arranque con `ValidationError`. El backend SHALL ejecutar una tarea asyncio periódica `rejected_events_retention_task()` (una vez por hora), lanzada en el lifespan de FastAPI junto a `retention_task()` y cancelada en el shutdown, que elimine las filas de `rejected_events_audit` cuyo `received_at < NOW() - rejected_events_retention_days días`. El borrado MUST ejecutarse en lotes de a lo sumo 1000 filas, cada lote en su propia transacción, repitiendo hasta que un lote elimine menos filas que el tamaño de lote. La columna de referencia MUST ser `received_at` (reloj del backend), no `detected_at`. `rejected_events_audit` SHALL tener un índice sobre `received_at` (migración manual idempotente `backend/db/migrations/017_add_rejected_events_audit_received_at_index.sql`, `CREATE INDEX IF NOT EXISTS`), del cual el filtro `WHERE received_at < :cutoff` de cada lote MUST beneficiarse. Un error de base de datos durante una corrida MUST registrarse en log sin terminar la tarea, que MUST reintentar en la siguiente iteración. Al terminar una corrida con borrados, la tarea SHALL emitir un log `info` con la cantidad eliminada, sin incluir `payload_dump`. La tarea MUST NOT eliminar ni modificar filas de `audit_log`, y ningún proceso del backend MUST purgar `audit_log` (retención ilimitada, W18/RN-94).

#### Scenario: Fila rechazada más antigua que el período se elimina
- **WHEN** existe una fila de `rejected_events_audit` con `received_at` de hace 91 días y `REJECTED_EVENTS_RETENTION_DAYS` no está definida
- **THEN** una corrida de la tarea de retención la elimina

#### Scenario: Fila rechazada reciente se conserva
- **WHEN** existe una fila de `rejected_events_audit` con `received_at` de hace 89 días y el período es 90
- **THEN** una corrida de la tarea de retención no la elimina

#### Scenario: Período configurable
- **WHEN** `REJECTED_EVENTS_RETENTION_DAYS=7` y existen filas con `received_at` de hace 8 y de hace 6 días
- **THEN** la corrida elimina la de 8 días y conserva la de 6 días

#### Scenario: Borrado en lotes
- **WHEN** existen 2500 filas vencidas en `rejected_events_audit`
- **THEN** una corrida las elimina todas en tres lotes (1000, 1000 y 500) confirmados por separado

#### Scenario: audit_log no pierde filas
- **WHEN** existen filas de `audit_log` con `created_at` de hace 400 días y filas vencidas en `rejected_events_audit`
- **THEN** tras la corrida la cantidad de filas de `audit_log` es idéntica a la previa

#### Scenario: Valor de retención inválido aborta el arranque
- **WHEN** el backend arranca con `REJECTED_EVENTS_RETENTION_DAYS=0`
- **THEN** la carga de `Settings` falla con `ValidationError`

#### Scenario: Error transitorio no mata la tarea
- **WHEN** una corrida falla por un error de base de datos
- **THEN** la tarea registra el error y vuelve a ejecutarse en la siguiente iteración

#### Scenario: La tarea se lanza y se cancela con el lifespan
- **WHEN** el backend arranca y luego se detiene
- **THEN** `rejected_events_retention_task()` se crea como task en el startup y se cancela en el shutdown junto con `retention_task()`

#### Scenario: Migración del índice es idempotente
- **WHEN** se ejecuta `backend/db/migrations/017_add_rejected_events_audit_received_at_index.sql` dos veces contra la misma base
- **THEN** la segunda ejecución no produce error y el índice sobre `received_at` existe una sola vez
