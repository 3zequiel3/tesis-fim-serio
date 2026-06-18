## ADDED Requirements

### Requirement: Validación de transición de estado en service.py

El sistema SHALL definir en `backend/app/modules/events/service.py` la tabla de transiciones canónicas `VALID_TRANSITIONS: dict[EventStatus, set[EventStatus]]` alineada a RN-72: `pending → {approved, rejected, superseded}`; todos los demás estados son terminales (out-edges vacías). La función `validate_transition(from_status, to_status)` SHALL lanzar `InvalidTransitionError` si la transición no está en la tabla. `InvalidTransitionError` SHALL ser una excepción de dominio definida en el mismo módulo. El consumer SHALL capturar `InvalidTransitionError`, ejecutar `XACK`, loguear el intento y NO persistir el evento resultante. El HTTP handler de C13 (approve/reject) también SHALL capturarla y retornar `409 Conflict`.

#### Scenario: Transición válida pending → superseded no lanza error

- **WHEN** se llama `validate_transition(EventStatus.pending, EventStatus.superseded)`
- **THEN** la función retorna sin excepción

#### Scenario: Transición inválida desde estado terminal lanza InvalidTransitionError

- **WHEN** se llama `validate_transition(EventStatus.approved, EventStatus.pending)`
- **THEN** se lanza `InvalidTransitionError`

#### Scenario: Transición inválida pending → alert_only lanza InvalidTransitionError

- **WHEN** se llama `validate_transition(EventStatus.pending, EventStatus.alert_only)`
- **THEN** se lanza `InvalidTransitionError`

#### Scenario: Consumer recibe evento con transición inválida — hace XACK y no persiste

- **WHEN** llega un evento que intentaría transicionar un evento terminal a otro estado
- **THEN** el consumer ejecuta `XACK` sobre la entrada
- **AND** no modifica ni inserta ningún `Event`
- **AND** registra un log de warning con `from_status` y `to_status`

### Requirement: Cadena superseded en ingesta con optimistic locking

Cuando el consumer ingesta un evento válido para un path que ya tiene un evento con `status=pending`, el sistema SHALL: (1) marcar el evento pending anterior como `superseded` usando `UPDATE events SET status='superseded', version=version+1 WHERE id=? AND version=? AND status='pending'`; (2) si la UPDATE afecta 0 filas (carrera), logear warning y abortar la creación del nuevo evento sin error al agente; (3) crear el nuevo evento con `parent_event_id` apuntando al ID del anterior. Si no existe evento `pending` para el path, el nuevo evento se crea sin `parent_event_id` (RN-21–23, RN-77).

#### Scenario: Nuevo evento en path con pending existente genera cadena

- **WHEN** existe `event_A` con `path='/etc/hosts'` y `status=pending`
- **AND** llega un nuevo evento válido para `path='/etc/hosts'`
- **THEN** `event_A.status` pasa a `superseded` y `event_A.version` incrementa en 1
- **AND** se crea `event_B` con `parent_event_id = event_A.id`

#### Scenario: Nuevo evento en path sin pending — no genera cadena

- **WHEN** no existe evento `pending` para `path='/etc/passwd'`
- **AND** llega un nuevo evento válido para `path='/etc/passwd'`
- **THEN** se crea el evento con `parent_event_id = None`

#### Scenario: Carrera en superseded (UPDATE 0 filas) — consumer aborta sin error

- **WHEN** la UPDATE para marcar superseded afecta 0 filas
- **THEN** el consumer no crea el nuevo evento
- **AND** ejecuta `XACK` sobre la entrada
- **AND** emite un log de warning

### Requirement: Compactación de cadena a máximo 10 eventos por path

Inmediatamente después de marcar un evento como `superseded` y crear el nuevo evento, el sistema SHALL contar los eventos `superseded` para el mismo path. Si el conteo supera 10, SHALL eliminar los `superseded` más antiguos (ordenados por `created_at asc`) hasta que la cadena tenga exactamente 10, excluyendo del borrado los que tengan `id` referenciado en `audit_log.target_id` con `target_type='event'`. La eliminación SHALL ocurrir en la misma transacción de base de datos que la creación del nuevo evento (RN-98).

#### Scenario: Cadena bajo 10 no desencadena compactación

- **WHEN** existen 8 eventos `superseded` para un path y se marca el 9no
- **THEN** no se elimina ningún evento

#### Scenario: Cadena llega a 11 — se compacta a 10

- **WHEN** existen 10 eventos `superseded` para un path y se marca el 11mo
- **THEN** se elimina el `superseded` más antiguo que no esté referenciado en `audit_log`
- **AND** la cadena queda con exactamente 10 eventos `superseded`

#### Scenario: Compactación respeta referencias en audit_log

- **WHEN** el `superseded` más antiguo tiene su `id` en `audit_log.target_id`
- **THEN** no se elimina ese evento
- **AND** se elimina el siguiente más antiguo que no esté referenciado

### Requirement: Rate limiting 100 eventos/min por agent_id en el consumer

El consumer SHALL mantener un contador en memoria `dict[str, deque[float]]` (clave `agent_id`, valores timestamps UNIX) con ventana deslizante de 60 segundos, protegido con `asyncio.Lock`. Antes de procesar cada evento, el consumer SHALL verificar si `agent_id` tiene más de 100 entradas en la ventana actual. Si supera el límite: ejecutar `XACK`, insertar en `rejected_events_audit` con `reason=rate_limited`, y NO procesar el evento. El contador SHALL reiniciarse al reiniciar el backend (no persiste en Valkey). El módulo SHALL exponer `reset_rate_limiter()` para facilitar tests (RN-88, D7).

#### Scenario: Evento bajo límite pasa el rate check

- **WHEN** `agent_a1` envió 50 eventos en los últimos 60 segundos
- **AND** llega un nuevo evento de `agent_a1`
- **THEN** el evento pasa el rate check y continúa la validación normal

#### Scenario: Evento que supera límite es rechazado y auditado

- **WHEN** `agent_a1` envió 100 eventos en los últimos 60 segundos
- **AND** llega el evento 101 de `agent_a1`
- **THEN** el consumer ejecuta `XACK`
- **AND** inserta en `rejected_events_audit` con `reason=rate_limited` y `agent_id='a1'`
- **AND** NO persiste el `Event`

#### Scenario: Ventana deslizante expira conteos antiguos

- **WHEN** `agent_a1` envió 100 eventos hace más de 60 segundos
- **AND** llega un nuevo evento de `agent_a1`
- **THEN** el evento pasa el rate check (ventana expirada)

#### Scenario: reset_rate_limiter limpia el estado

- **WHEN** se llama `reset_rate_limiter()`
- **THEN** todos los contadores quedan en cero

### Requirement: Retención 30 días para eventos terminales

El backend SHALL ejecutar una tarea asyncio periódica (una vez por hora) que elimine eventos en estados terminales (`approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`) cuyo `created_at < NOW() - 30 days`, excluyendo los que tengan `id` referenciado en `audit_log.target_id` con `target_type='event'`. La tarea SHALL lanzarse en el lifespan de FastAPI junto con el consumer loop (RN-98).

#### Scenario: Evento terminal con más de 30 días es eliminado

- **WHEN** existe un evento `approved` con `created_at` de hace 31 días
- **AND** no está referenciado en `audit_log`
- **THEN** la tarea de retención lo elimina

#### Scenario: Evento terminal referenciado en audit_log NO se elimina

- **WHEN** existe un evento `approved` con `created_at` de hace 31 días
- **AND** su `id` aparece en `audit_log.target_id`
- **THEN** la tarea de retención NO lo elimina

#### Scenario: Evento terminal con menos de 30 días NO se elimina

- **WHEN** existe un evento `approved` con `created_at` de hace 20 días
- **THEN** la tarea de retención NO lo elimina
