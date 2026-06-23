# Spec: backend-event-consumer

## Purpose

Consumers del backend para los streams `events` y `agent_heartbeat` — validación (schema, HMAC, clock skew), persistencia, protocolo ACK end-to-end y transiciones de estado de agente por heartbeat.
## Requirements
### Requirement: Consumer group fim-backend sobre el stream events

El backend SHALL consumir el stream `events` mediante un consumer group llamado `fim-backend` (RN-56), implementado en `backend/app/modules/events/consumer.py` y arrancado como tarea asyncio en el lifespan de `backend/app/main.py`. El consumer MUST crear el group si no existe (`MKSTREAM`) y, al arrancar, MUST reprocesar sus propias entradas pendientes (`XREADGROUP` con id `0`) antes de leer entradas nuevas (id `>`), garantizando recuperación idempotente ante reinicio (RN-76).

#### Scenario: Consumer group creado al arrancar
- **WHEN** el backend arranca y el group `fim-backend` no existe sobre `events`
- **THEN** el backend crea el group con `MKSTREAM` y comienza a consumir

#### Scenario: Reprocesa pendientes al reiniciar
- **WHEN** el backend reinicia y había entradas pendientes sin `XACK` en el group
- **THEN** el consumer las relee con `XREADGROUP ... 0` y las reprocesa antes de leer entradas nuevas

### Requirement: Validación de evento en orden barato a caro con rechazo tipado

El consumer SHALL validar cada evento entrante en este orden, rechazando al primer fallo y persistiendo el rechazo en `rejected_events_audit` con `RejectionReason` tipado y `payload_dump` truncado a 4 KB (D4, RN-105): (1) `schema_version` parseable y menor o igual al soportado, si no `invalid_schema` (RN-91); (2) `agent_id` existe en la tabla `agents`, si no `unknown_agent`; (3) firma `HMAC-SHA256(shared_secret, canonical_json(payload))` válida, si no `invalid_signature` (RN-79); (4) `abs(received_at - detected_at) <= 5 min`, si no `clock_skew` (RN-90). El backend SHALL agregar `received_at` con su propio reloj al consumir (RN-90). Un evento rechazado MUST recibir `XACK` (no se reintenta indefinidamente) y NO genera `event_ack`.

#### Scenario: Rechazo por clock skew
- **WHEN** llega un evento con `abs(received_at - detected_at)` mayor a 5 minutos
- **THEN** el backend NO persiste el `Event`
- **AND** inserta una fila en `rejected_events_audit` con `reason = clock_skew` y `payload_dump` truncado a 4 KB
- **AND** ejecuta `XACK` sobre la entrada

#### Scenario: Rechazo por schema_version no soportado
- **WHEN** llega un evento con `schema_version` mayor que el soportado por el backend
- **THEN** se inserta `rejected_events_audit` con `reason = invalid_schema`

#### Scenario: Rechazo por firma HMAC inválida
- **WHEN** llega un evento cuya `signature` no coincide con `HMAC-SHA256(shared_secret, canonical_json(payload))`
- **THEN** se inserta `rejected_events_audit` con `reason = invalid_signature`

#### Scenario: Rechazo por agente desconocido
- **WHEN** llega un evento con un `agent_id` que no existe en la tabla `agents`
- **THEN** se inserta `rejected_events_audit` con `reason = unknown_agent`

### Requirement: Protocolo ACK end-to-end con persistencia y dedup idempotente

Tras pasar todas las validaciones, el consumer SHALL clasificar el resultado del procesamiento de cada mensaje del stream `events` mediante una taxonomía explícita y ejecutar `XACK` de forma **condicional** según el resultado (C8):

- **Éxito** (la ingesta retorna un `Event`): persistir el `Event` en PostgreSQL, ejecutar `XACK`, y publicar un mensaje `event_ack` en el stream `commands` con el `event_id` y `target_agent_id` igual al `agent_id` del evento (D5, RN-73, RN-106). El `event_ack` MUST ir firmado con `HMAC-SHA256(shared_secret, canonical_json(payload))` (RN-79).
- **Skip legítimo** (re-entrega de un `event_id` ya persistido, o carrera de `mark_superseded` que aborta la creación): NO re-insertar el `Event`, ejecutar `XACK` (la entrada ya fue procesada), y para la re-entrega publicar `event_ack`.
- **Error de datos** (`InvalidTransitionError`): ejecutar `XACK` (el mensaje es inválido y no reintentable) y auditar el rechazo. No reintentar.
- **Error transitorio de base de datos** (`SQLAlchemyError`): NO ejecutar `XACK`. El mensaje MUST permanecer en la Pending Entries List (PEL) del consumer group para reintento automático. El consumer MUST loguear el error con `exc_info=True`.

El consumer MUST deduplicar por `event_id`: si el `event_id` ya está persistido, NO re-inserta el `Event` ni audita un rechazo, pero igualmente ejecuta `XACK` y publica `event_ack` (re-entrega legítima at-least-once, RN-73).

#### Scenario: Evento válido persistido y confirmado
- **WHEN** llega un evento válido `e1` del agente `a1` que no existe en la base
- **THEN** el backend inserta el `Event`, ejecuta `XACK`, y publica `event_ack` en `commands` con `event_id = e1` y `target_agent_id = a1`
- **AND** el `event_ack` lleva una `signature` HMAC válida

#### Scenario: Re-entrega de un evento ya persistido
- **WHEN** llega de nuevo el evento `e1` cuyo `event_id` ya está persistido
- **THEN** el backend NO inserta un segundo `Event` ni una fila en `rejected_events_audit`
- **AND** ejecuta `XACK` y vuelve a publicar `event_ack` para `e1`

#### Scenario: Error de datos no reintentable hace XACK
- **WHEN** la ingesta de un evento lanza `InvalidTransitionError`
- **THEN** el consumer ejecuta `XACK` sobre la entrada
- **AND** audita el rechazo
- **AND** no reintenta el mensaje

#### Scenario: Error transitorio de DB NO hace XACK y queda en PEL
- **WHEN** la ingesta de un evento válido lanza `SQLAlchemyError` (fallo transitorio de base de datos)
- **THEN** el consumer NO ejecuta `XACK`
- **AND** el mensaje permanece en la Pending Entries List del consumer group
- **AND** el consumer loguea el error con `exc_info=True`
- **AND** el evento de integridad no se pierde silenciosamente (queda disponible para reintento)

### Requirement: Heartbeat consumer actualiza estado y transiciona online/offline

El backend SHALL consumir el stream `agent_heartbeat` en `backend/app/modules/agents/heartbeat_consumer.py` (arrancado en el lifespan). Por cada heartbeat MUST actualizar `Agent.last_heartbeat`, `Agent.queue_pressure` y poner `Agent.status = online`; si el heartbeat trae `shutdown: true` MUST poner `status = draining` (RN-92, RN-93). Una tarea de barrido periódica SHALL marcar `status = offline` a los agentes cuyo `last_heartbeat` sea más antiguo que 30 segundos (RN-92). La transición `offline → dead` (5 min) y el webhook n8n quedan fuera de este change.

#### Scenario: Heartbeat marca al agente online
- **WHEN** el backend consume un heartbeat del agente `a1` con `queue_pressure = 0.4` y `shutdown = false`
- **THEN** `Agent(a1).last_heartbeat` se actualiza, `queue_pressure = 0.4` y `status = online`

#### Scenario: Sin heartbeat 30s marca offline
- **WHEN** el `last_heartbeat` del agente `a1` tiene más de 30 segundos de antigüedad
- **THEN** la tarea de barrido pone `Agent(a1).status = offline`

#### Scenario: Heartbeat con shutdown marca draining
- **WHEN** el backend consume un heartbeat de `a1` con `shutdown = true`
- **THEN** `Agent(a1).status = draining`

### Requirement: Contrato de firma y schema_version compartido para streams

El backend SHALL exponer helpers reutilizables de mensajes de stream (p. ej. en `backend/app/core/streams.py`): `canonical_json(payload)` que serializa con `sort_keys=True` y separadores compactos excluyendo el campo `signature`, `sign_payload(secret, payload)` y `verify_payload(secret, payload)` basados en `HMAC-SHA256` (RN-79). Todo mensaje publicado o consumido en `events`, `commands` o `agent_heartbeat` SHALL incluir `schema_version`; el receptor MUST rechazar `schema_version` mayor al soportado e ignorar campos desconocidos (forward compat, RN-91). Estos helpers son el cross-cutting que viaja con este change y los reutilizan los comandos de negocio de changes posteriores (D7).

#### Scenario: canonical_json determinístico
- **WHEN** se serializan dos payloads con las mismas claves en distinto orden de inserción
- **THEN** `canonical_json` produce exactamente el mismo string para ambos

#### Scenario: verify_payload rechaza firma alterada
- **WHEN** se altera un byte del payload tras firmarlo
- **THEN** `verify_payload` retorna falso

#### Scenario: schema_version desconocido a futuro es ignorado por campo
- **WHEN** un mensaje trae un campo desconocido pero `schema_version` soportado
- **THEN** el receptor procesa el mensaje ignorando el campo desconocido

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

Inmediatamente después de marcar un evento como `superseded` y crear el nuevo evento, el sistema SHALL contar los eventos `superseded` para el mismo path. Si el conteo supera 10, SHALL eliminar los `superseded` más antiguos hasta que la cadena tenga exactamente 10, excluyendo del borrado los que tengan `id` referenciado en `audit_log.target_id` con `target_type='event'`. El borrado SHALL ejecutarse ordenando los candidatos por `created_at` descendente (más nuevos primero), de modo que un evento hijo se elimine antes que el padre al que referencia y nunca quede una referencia colgante; combinado con la FK `ON DELETE SET NULL` sobre `parent_event_id`, la operación MUST completar sin `IntegrityError` incluso en cadenas largas (C9). La eliminación SHALL ocurrir en la misma transacción de base de datos que la creación del nuevo evento (RN-98).

#### Scenario: Cadena bajo 10 no desencadena compactación
- **WHEN** existen 8 eventos `superseded` para un path y se marca el 9no
- **THEN** no se elimina ningún evento

#### Scenario: Cadena llega a 11 — se compacta a 10
- **WHEN** existen 10 eventos `superseded` para un path y se marca el 11mo
- **THEN** se elimina el `superseded` sobrante que no esté referenciado en `audit_log`
- **AND** la cadena queda con exactamente 10 eventos `superseded`

#### Scenario: Compactación de cadena larga no viola la FK
- **WHEN** se compacta una cadena donde los eventos a borrar son `parent_event_id` de otros eventos de la cadena
- **THEN** el borrado completa sin `IntegrityError`
- **AND** `ingest_event` no aborta su transacción ni pierde el nuevo evento

#### Scenario: Compactación respeta referencias en audit_log
- **WHEN** el `superseded` candidato a borrar tiene su `id` en `audit_log.target_id`
- **THEN** no se elimina ese evento
- **AND** se elimina el siguiente candidato que no esté referenciado

### Requirement: Rate limiting 100 eventos/min por agent_id en el consumer

El consumer SHALL mantener un contador en memoria `dict[str, deque[float]]` (clave `agent_id`, valores timestamps UNIX) con ventana deslizante de 60 segundos. Antes de procesar cada evento, el consumer SHALL verificar si `agent_id` tiene más de 100 entradas en la ventana actual. Si supera el límite: ejecutar `XACK`, insertar en `rejected_events_audit` con `reason=rate_limited`, y NO procesar el evento. El contador SHALL reiniciarse al reiniciar el backend (no persiste en Valkey). El módulo SHALL exponer `reset_rate_limiter()` para facilitar tests (RN-88, D7).

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

