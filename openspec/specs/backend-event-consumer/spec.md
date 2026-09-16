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

El consumer SHALL validar cada evento entrante en este orden, rechazando al primer fallo y persistiendo el rechazo en `rejected_events_audit` con `RejectionReason` tipado y `payload_dump` truncado a 4 KB (D4, RN-105): (1) `schema_version` parseable y menor o igual al soportado, si no `invalid_schema` (RN-91); (2) `agent_id` existe en la tabla `agents`, si no `unknown_agent`; (3) firma `HMAC-SHA256(shared_secret, canonical_json(payload))` válida, si no `invalid_signature` (RN-79); (4) **ventana de skew sobre `sent_at`** según la cláusula de abajo, si no `clock_skew` (RN-90, enmendada por D37/RN-131); (5) **`event_id` no-vacío**, si no `invalid_schema`; (6) **dedup por `event_id`** — si ya existe en DB, XACK + event_ack, sin consumir rate budget; (7) **rate limit** 100 eventos/min por `agent_id`, si supera: `XACK` + `rejected_events_audit` con `reason=rate_limited` (RN-88). El orden dedup-antes-que-rate-limit garantiza que re-entregas legítimas no consuman presupuesto de rate (FIX-06). El backend SHALL agregar `received_at` con su propio reloj al consumir (RN-90). Un evento rechazado MUST recibir `XACK` (no se reintenta indefinidamente) y MUST recibir la respuesta tipada que le corresponda según la matriz de D37/RN-131 — que para dos de los seis motivos es ninguna respuesta.

**Ventana de skew (D37 / RN-131, prevalece sobre RN-90).** El paso (4) SHALL evaluarse así:

- `detected_at` MUST seguir siendo parseable y normalizable a UTC-aware. Si no lo es → rechazar con `clock_skew` (`clock_skew.unparseable` en el log). `detected_at` **NO tiene ventana**: un evento legítimamente encolado durante un corte de horas llega con `detected_at` antiguo y MUST ser aceptado por este criterio. `detected_at` permanece como verdad forense.
- Si el payload trae `sent_at`: MUST ser parseable y normalizable a UTC-aware (si no → `clock_skew`, `clock_skew.unparseable_sent_at` en el log), y MUST cumplir `abs(received_at - sent_at) <= 5 min` (si no → `clock_skew`, `clock_skew.out_of_range` en el log). La ventana es bidireccional: un `sent_at` en el futuro es tan sospechoso como uno viejo.
- Si el payload **no** trae `sent_at` (agente anterior a D37): la ventana SHALL evaluarse sobre `detected_at`, con el comportamiento previo íntegro. La ausencia del campo significa el comportamiento anterior, no un rechazo (tolerancia hacia adelante, D33/D35/D36).

`detected_at` y `sent_at` MUST normalizarse a UTC-aware antes de cualquier cálculo. Si tienen tzinfo, se usa `astimezone(timezone.utc)`. Si no lo tienen (naive), se asume UTC y se asigna `tzinfo=timezone.utc`.

`event_id` MUST ser una cadena no-vacía. Si es `None` o `""` → rechazar con `invalid_schema`.

#### Scenario: Rechazo por sent_at fuera de rango
- **WHEN** llega un evento con `sent_at` cuya diferencia con `received_at` supera 5 minutos
- **THEN** el backend NO persiste el `Event`
- **AND** inserta una fila en `rejected_events_audit` con `reason = clock_skew` y `payload_dump` truncado a 4 KB
- **AND** ejecuta `XACK` sobre la entrada
- **AND** el log emite `clock_skew.out_of_range`

#### Scenario: Evento con detected_at antiguo y sent_at reciente se acepta
- **WHEN** llega un evento cuyo `detected_at` es de hace seis horas y cuyo `sent_at` es de hace dos segundos, con firma válida
- **THEN** el evento se persiste normalmente
- **AND** el `detected_at` persistido es el original de hace seis horas

#### Scenario: Evento sin sent_at cae al criterio anterior sobre detected_at
- **WHEN** llega un evento de un agente que no envía `sent_at`, con `detected_at` dentro de los 5 minutos
- **THEN** el evento se acepta

#### Scenario: Evento sin sent_at y con detected_at viejo se rechaza como antes
- **WHEN** llega un evento sin `sent_at` cuyo `detected_at` es de hace seis horas
- **THEN** se inserta `rejected_events_audit` con `reason = clock_skew`

#### Scenario: Rechazo por sent_at no parseable
- **WHEN** llega un evento cuyo campo `sent_at` no es un ISO8601 válido
- **THEN** se inserta `rejected_events_audit` con `reason = clock_skew`
- **AND** el log emite `clock_skew.unparseable_sent_at`

#### Scenario: Rechazo por detected_at no parseable
- **WHEN** llega un evento cuyo campo `detected_at` no es un ISO8601 válido
- **THEN** se inserta `rejected_events_audit` con `reason = clock_skew`
- **AND** el log emite `clock_skew.unparseable`
- **AND** ejecuta `XACK`

#### Scenario: sent_at en el futuro se rechaza
- **WHEN** llega un evento cuyo `sent_at` está 10 minutos en el futuro respecto de `received_at`
- **THEN** se inserta `rejected_events_audit` con `reason = clock_skew`

#### Scenario: sent_at naive se interpreta como UTC
- **WHEN** llega un evento con `sent_at` como datetime naive (sin tzinfo) dentro del rango de 5 minutos
- **THEN** el evento se acepta (no hay TypeError al calcular el skew)

#### Scenario: Rechazo por event_id vacío
- **WHEN** llega un evento con `event_id = ""` o `event_id` ausente en el payload
- **THEN** se inserta `rejected_events_audit` con `reason = invalid_schema`
- **AND** ejecuta `XACK`

#### Scenario: Rechazo por schema_version no soportado
- **WHEN** llega un evento con `schema_version` mayor que el soportado por el backend
- **THEN** se inserta `rejected_events_audit` con `reason = invalid_schema`

#### Scenario: Rechazo por firma HMAC inválida
- **WHEN** llega un evento cuya `signature` no coincide con `HMAC-SHA256(shared_secret, canonical_json(payload))`
- **THEN** se inserta `rejected_events_audit` con `reason = invalid_signature`

#### Scenario: La firma cubre sent_at
- **WHEN** llega un evento cuyo `sent_at` fue alterado después de firmarse
- **THEN** se inserta `rejected_events_audit` con `reason = invalid_signature` y no se evalúa la ventana de skew

#### Scenario: Rechazo por agente desconocido
- **WHEN** llega un evento con un `agent_id` que no existe en la tabla `agents`
- **THEN** se inserta `rejected_events_audit` con `reason = unknown_agent`

### Requirement: Protocolo ACK end-to-end con persistencia y dedup idempotente

Tras pasar todas las validaciones, el consumer SHALL clasificar el resultado del procesamiento de cada mensaje del stream `events` mediante una taxonomía explícita y ejecutar `XACK` de forma **condicional** según el resultado (C8):

- **Éxito** (la ingesta retorna un `Event`): persistir el `Event` en PostgreSQL, ejecutar `XACK`, y publicar un mensaje `event_ack` en el stream `commands` con el `event_id` y `target_agent_id` igual al `agent_id` del evento (D5, RN-73, RN-106). El `event_ack` MUST ir firmado con `HMAC-SHA256(shared_secret, canonical_json(payload))` (RN-79).
- **Skip legítimo — re-entrega**: si `event_id` ya existe en DB (detectado en el paso de dedup, ANTES del rate limit), NO re-insertar el `Event`, ejecutar `XACK` y publicar `event_ack`. El presupuesto de rate limit NO se consume para re-entregas.
- **Skip legítimo — carrera en superseded sin pending activo**: cuando `mark_superseded` devuelve False y la re-consulta muestra que sigue habiendo un pending activo, el consumer ejecuta `XACK` sin insertar el evento. Como el evento entrante no se persiste y el agente lo tiene retenido en cola, el consumer SHALL publicar `event_ack` también en este caso: el evento ya está representado en la base por el pending activo, y no hacerlo lo dejaría reintentando indefinidamente.
- **Error de datos** (`InvalidTransitionError`): ejecutar `XACK` (el mensaje es inválido y no reintentable), auditar el rechazo y publicar un `event_nack` terminal con `reason=invalid_schema`. No reintentar. Sin la respuesta, el agente republica para siempre un evento que nunca va a entrar.
- **Error transitorio de base de datos** (`SQLAlchemyError`): NO ejecutar `XACK` y NO publicar ninguna respuesta. El mensaje MUST permanecer en la Pending Entries List (PEL) del consumer group para reintento automático. El consumer MUST loguear el error con `exc_info=True`.

#### Scenario: Evento válido persistido y confirmado
- **WHEN** llega un evento válido `e1` del agente `a1` que no existe en la base
- **THEN** el backend inserta el `Event`, ejecuta `XACK`, y publica `event_ack` en `commands` con `event_id = e1` y `target_agent_id = a1`
- **AND** el `event_ack` lleva una `signature` HMAC válida

#### Scenario: Re-entrega detectada en dedup no consume rate budget
- **WHEN** llega de nuevo el evento `e1` cuyo `event_id` ya está persistido en DB
- **THEN** el backend NO incrementa el contador de rate limit para el agente
- **AND** el backend NO inserta un segundo `Event` ni una fila en `rejected_events_audit`
- **AND** ejecuta `XACK` y vuelve a publicar `event_ack` para `e1`

#### Scenario: Error de datos no reintentable hace XACK y responde nack terminal
- **WHEN** la ingesta de un evento lanza `InvalidTransitionError`
- **THEN** el consumer ejecuta `XACK` sobre la entrada
- **AND** audita el rechazo
- **AND** publica un `event_nack` terminal con `reason = invalid_schema` para ese `event_id`
- **AND** no reintenta el mensaje

#### Scenario: Skip por carrera en superseded también responde ack
- **WHEN** la ingesta se salta legítimamente el evento por una carrera de supersesión con un pending activo
- **THEN** el consumer ejecuta `XACK` y publica `event_ack` para ese `event_id`

#### Scenario: Error transitorio de DB NO hace XACK, NO responde y queda en PEL
- **WHEN** la ingesta de un evento válido lanza `SQLAlchemyError` (fallo transitorio de base de datos)
- **THEN** el consumer NO ejecuta `XACK`
- **AND** no publica ninguna respuesta en el stream `commands`
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

### Requirement: Cadena superseded en ingesta con optimistic locking y re-consulta ante race

Cuando el consumer ingesta un evento válido para un path que ya tiene un evento con `status=pending`, el sistema SHALL: (1) marcar el evento pending anterior como `superseded` usando `UPDATE events SET status='superseded', version=version+1 WHERE id=? AND version=? AND status='pending'`; (2) si la UPDATE afecta 0 filas (carrera), re-consultar si todavía existe un pending activo para el mismo path (D25, RN-121): si hay pending → logear warning y abortar la creación del nuevo evento (skip legítimo); si NO hay pending → insertar el nuevo evento como pending independiente sin `parent_event_id`; (3) crear el nuevo evento con `parent_event_id` apuntando al ID del anterior. Si no existe evento `pending` para el path, el nuevo evento se crea sin `parent_event_id` (RN-21–23, RN-77).

#### Scenario: Nuevo evento en path con pending existente genera cadena
- **WHEN** existe `event_A` con `path='/etc/hosts'` y `status=pending`
- **AND** llega un nuevo evento válido para `path='/etc/hosts'`
- **THEN** `event_A.status` pasa a `superseded` y `event_A.version` incrementa en 1
- **AND** se crea `event_B` con `parent_event_id = event_A.id`

#### Scenario: Nuevo evento en path sin pending — no genera cadena
- **WHEN** no existe evento `pending` para `path='/etc/passwd'`
- **AND** llega un nuevo evento válido para `path='/etc/passwd'`
- **THEN** se crea el evento con `parent_event_id = None`

#### Scenario: Carrera en superseded — pending resuelto concurrentemente — nuevo evento insertado
- **WHEN** la UPDATE para marcar superseded afecta 0 filas
- **AND** la re-consulta de pending para el path retorna None (el pending fue resuelto concurrentemente por un approve/reject)
- **THEN** el consumer inserta el nuevo evento como pending independiente (sin `parent_event_id`)
- **AND** ejecuta `XACK` sobre la entrada

#### Scenario: Carrera en superseded — pending todavía existe — consumer aborta
- **WHEN** la UPDATE para marcar superseded afecta 0 filas
- **AND** la re-consulta de pending para el path retorna un evento pending activo
- **THEN** el consumer no crea el nuevo evento (skip legítimo)
- **AND** ejecuta `XACK` sobre la entrada
- **AND** emite un log de warning

### Requirement: Compactación de cadena — retiene los más recientes

Inmediatamente después de marcar un evento como `superseded` y crear el nuevo evento, el sistema SHALL contar los eventos `superseded` para el mismo path. Si el conteo supera 10, SHALL eliminar los `superseded` más **antiguos** hasta que la cadena tenga exactamente 10, excluyendo del borrado los que tengan `id` referenciado en `audit_log.target_id` con `target_type='event'`. El borrado SHALL ejecutarse ordenando los candidatos por `created_at` **ascendente** (más antiguos primero), de modo que se descarten los eventos más viejos y se retengan los más recientes. Combinado con la FK `ON DELETE SET NULL` sobre `parent_event_id`, la operación MUST completar sin `IntegrityError` incluso en cadenas largas (C9). La eliminación SHALL ocurrir en la misma transacción de base de datos que la creación del nuevo evento (RN-98).

#### Scenario: Cadena bajo 10 no desencadena compactación
- **WHEN** existen 8 eventos `superseded` para un path y se marca el 9no
- **THEN** no se elimina ningún evento

#### Scenario: Cadena llega a 11 — se compacta a 10 eliminando el más antiguo
- **WHEN** existen 10 eventos `superseded` para un path y se marca el 11mo
- **THEN** se elimina el `superseded` más antiguo (menor `created_at`) que no esté referenciado en `audit_log`
- **AND** la cadena queda con exactamente 10 eventos `superseded`

#### Scenario: Compactación de cadena larga no viola la FK
- **WHEN** se compacta una cadena donde los eventos a borrar son `parent_event_id` de otros eventos de la cadena
- **THEN** el borrado completa sin `IntegrityError`
- **AND** `ingest_event` no aborta su transacción ni pierde el nuevo evento

#### Scenario: Compactación respeta referencias en audit_log
- **WHEN** el `superseded` candidato a borrar tiene su `id` en `audit_log.target_id`
- **THEN** no se elimina ese evento
- **AND** se elimina el siguiente candidato más antiguo que no esté referenciado

### Requirement: Rate limiting 100 eventos/min por agent_id en el consumer

El consumer SHALL mantener un contador en memoria `dict[str, deque[float]]` (clave `agent_id`, valores timestamps UNIX) con ventana deslizante de 60 segundos. El check de rate limit se ejecuta DESPUÉS del dedup — re-entregas de eventos ya procesados NO consumen presupuesto de rate. Solo los eventos genuinamente nuevos (que superan el dedup) avanzan al check de rate. Si supera el límite: ejecutar `XACK`, insertar en `rejected_events_audit` con `reason=rate_limited`, **publicar un `event_nack` con `reason=rate_limited` y `retry_after`** (D37/RN-131), y NO procesar el evento. El evento **NO se descarta**: el agente lo retiene y lo reenvía cuando haya presupuesto — esta cláusula prevalece sobre la frase "se descartan con alerta" de RN-88, que además nunca se implementó. El contador SHALL reiniciarse al reiniciar el backend (no persiste en Valkey). El limiter SHALL exponer `reset_rate_limiter()` para facilitar tests y un método explícito que devuelva los segundos restantes hasta que se libere cupo para un `agent_id`, usado para derivar `retry_after` (RN-88, D7, D37).

#### Scenario: Evento bajo límite pasa el rate check
- **WHEN** `agent_a1` envió 50 eventos en los últimos 60 segundos
- **AND** llega un nuevo evento de `agent_a1` que no existe en DB (no es re-entrega)
- **THEN** el evento pasa el rate check y continúa la validación normal

#### Scenario: Evento que supera límite es auditado y nackeado con retry_after
- **WHEN** `agent_a1` envió 100 eventos en los últimos 60 segundos
- **AND** llega el evento 101 de `agent_a1` con un `event_id` nuevo (no re-entrega)
- **THEN** el consumer ejecuta `XACK`
- **AND** inserta en `rejected_events_audit` con `reason=rate_limited` y `agent_id='a1'`
- **AND** publica un `event_nack` con `reason=rate_limited` y un `retry_after` numérico positivo
- **AND** NO persiste el `Event`

#### Scenario: Re-entrega no consume rate budget
- **WHEN** `agent_a1` envió 99 eventos en los últimos 60 segundos
- **AND** llega de nuevo el evento `e1` que ya existe en DB (re-entrega legítima)
- **THEN** el rate counter de `agent_a1` permanece en 99 (no se incrementa)
- **AND** el evento `e1` es procesado como dedup (XACK + event_ack)

#### Scenario: Ventana deslizante expira conteos antiguos
- **WHEN** `agent_a1` envió 100 eventos hace más de 60 segundos
- **AND** llega un nuevo evento de `agent_a1`
- **THEN** el evento pasa el rate check (ventana expirada)

#### Scenario: Un evento rate-limited reenviado más tarde se ingesta
- **WHEN** un evento fue rechazado por rate limit y el agente lo reenvía una vez liberado el presupuesto
- **THEN** el evento se persiste normalmente y recibe `event_ack`

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

### Requirement: Consumer resiliente en startup ante Valkey no disponible

El consumer de eventos MUST envolver las llamadas de inicialización (`_ensure_group`, `_process_batch("0")`) en un bloque try/except antes del loop principal. Si Valkey no está disponible al arrancar, el consumer MUST loguear el error con nivel ERROR, esperar 1 segundo, y reintentar hasta conectarse. No MUST morir permanentemente por fallo en la inicialización.

#### Scenario: Valkey no disponible al arrancar — consumer reintenta

- **WHEN** el backend arranca y Valkey no responde durante `_ensure_group`
- **THEN** el consumer loguea el error y reintenta cada 1 segundo
- **AND** el consumer NO muere permanentemente ni deja de procesar eventos cuando Valkey se recupera

#### Scenario: Procesamiento de pendientes falla al arrancar — consumer entra al loop de todas formas

- **WHEN** `_process_batch("0")` falla por un error transitorio de Valkey o DB al arrancar
- **THEN** el consumer loguea el error y continúa al loop principal de mensajes nuevos
- **AND** los mensajes pendientes serán reprocesados en el próximo reinicio

### Requirement: Notificaciones post-ingesta con referencia fuerte a la task asyncio

El consumer de eventos MUST guardar una referencia fuerte a cualquier `asyncio.Task` creada para `notify_if_applicable`. La referencia SHALL mantenerse en un `set` module-level hasta que la task complete, previniendo cancelación silenciosa por el GC. La task MUST removerse del set al completar (callback `discard`).

#### Scenario: Task de notificación no es cancelada por GC

- **WHEN** el consumer crea una task de notificación para un evento crítico
- **THEN** la task mantiene una referencia fuerte hasta que `notify_if_applicable` complete
- **AND** el GC no puede cancelar la task mientras está en vuelo

### Requirement: ingest_event persists symlink metadata from the payload

`ingest_event` (`backend/app/modules/events/service.py`) SHALL read `is_symlink` and `symlink_target` from the incoming stream payload using tolerant `.get()` access (defaulting to `False` and `None` respectively) and persist them onto the `Event` row. Because the reader is tolerant, events published by older agents that omit these keys MUST ingest without error. The existing cheap-to-expensive validation order and the superseded-chain / optimistic-locking behavior MUST remain unchanged. (D33 / RN-127)

#### Scenario: Symlink event payload is persisted with its metadata
- **WHEN** the consumer ingests a payload with `is_symlink=true` and `symlink_target` set
- **THEN** `ingest_event` persists both values onto the `Event` row

#### Scenario: Payload without symlink keys ingests with defaults
- **WHEN** the consumer ingests a payload from an older agent that omits `is_symlink`/`symlink_target`
- **THEN** `ingest_event` defaults them to `false`/`null` via `.get()` and ingests the event without error

#### Scenario: Symlink metadata extraction does not alter validation or supersede behavior
- **WHEN** a symlink event participates in a superseded chain or optimistic-locking race
- **THEN** the existing validation order and supersede/locking behavior are unchanged by the added metadata extraction

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

### Requirement: The consumer answers every event with exactly one typed response, or with none where responding would be unsafe

The consumer SHALL produce, for every message it takes off the `events` stream, exactly one of three outcomes, determined solely by the rejection reason (D37 / RN-131):

| Reason | Response | Meaning to the agent |
|---|---|---|
| successful ingestion, `duplicate_event` | `event_ack` | delete the event from the queue |
| `invalid_schema`, `clock_skew` | terminal `event_nack` | delete the event from the queue and record it locally |
| `rate_limited` | `event_nack` carrying `retry_after` | retain the event and apply backpressure |
| `invalid_signature`, `unknown_agent` | no response at all | the event expires by the agent's own retry ceiling |

The `event_nack` message SHALL be published to the `commands` stream with the same shape and signing as `event_ack`: `type` (`"event_nack"`), `event_id`, `target_agent_id`, `reason`, `schema_version`, `timestamp`, and `signature` = HMAC-SHA256 over the canonical JSON with the target agent's shared secret (RN-79). The key `retry_after` (seconds, numeric) SHALL be present **only** when `reason` is `rate_limited`; its absence is what makes a nack terminal.

`reason` SHALL use the literals of the existing `RejectionReason` vocabulary, lowercase snake_case (RN-71). No parallel vocabulary is introduced.

No response SHALL be emitted for `invalid_signature` or `unknown_agent`. Neither case permits signing a verifiable response nor identifying the recipient, and answering would turn the backend into an oracle confirming which `agent_id` values exist. The same silence SHALL apply to the existing discard of a revoked agent.

A rejection SHALL continue to be persisted in `rejected_events_audit` and to receive `XACK` in every case, exactly as before. The typed response is added to that behaviour; it does not replace it. This amends the clause of D4 / RN-105 and the module docstring stating that a rejection produces no `event_ack`.

#### Scenario: A clock skew rejection emits a terminal nack

- **WHEN** an event is rejected with reason `clock_skew`
- **THEN** the `commands` stream receives an `event_nack` for that `event_id` with `reason` `clock_skew`, no `retry_after`, and a valid signature
- **AND** the rejection row is still written to `rejected_events_audit` and the entry still receives `XACK`

#### Scenario: A rate-limited event gets a nack with retry_after

- **WHEN** an event is rejected with reason `rate_limited`
- **THEN** the `commands` stream receives an `event_nack` with `reason` `rate_limited` and a numeric `retry_after`

#### Scenario: An invalid signature produces silence

- **WHEN** an event is rejected with reason `invalid_signature`
- **THEN** no message whatsoever is added to the `commands` stream for that event

#### Scenario: An unknown agent produces silence

- **WHEN** an event is rejected with reason `unknown_agent`
- **THEN** no message whatsoever is added to the `commands` stream for that event

#### Scenario: A revoked agent's event produces silence

- **WHEN** an event from a revoked agent is discarded
- **THEN** no message whatsoever is added to the `commands` stream for that event

#### Scenario: A schema rejection for a known agent is signed with that agent's secret

- **WHEN** an event with an unsupported `schema_version` arrives carrying an `agent_id` that exists and has a shared secret
- **THEN** an `event_nack` with `reason` `invalid_schema` is published, signed with that agent's shared secret

#### Scenario: A schema rejection for an unknown agent produces silence

- **WHEN** an event with an unsupported `schema_version` arrives carrying an `agent_id` that does not exist
- **THEN** no message is added to the `commands` stream, because no verifiable response can be signed

#### Scenario: A rejection with no usable event_id produces silence

- **WHEN** an event is rejected with reason `invalid_schema` because its `event_id` is absent or empty
- **THEN** no message is added to the `commands` stream, because there is no event to address the response to

### Requirement: retry_after is derived from the live rate limiter state

The consumer SHALL derive the `retry_after` value from the rate limiter's own sliding window rather than from a fixed constant: the time remaining until the oldest timestamp in the agent's window falls out of the 60-second window. The value SHALL be floored at a small positive minimum so that a zero or negative result from a race cannot induce a busy loop in the agent.

The rate limiter SHALL expose this as an explicit method. The consumer MUST NOT reach into the limiter's internal deque. (D37 / RN-131, RN-88)

#### Scenario: An agent that just filled its budget waits close to the full window

- **WHEN** an agent's 100 events were all recorded moments ago and event 101 arrives
- **THEN** the `retry_after` in the nack is close to 60 seconds

#### Scenario: An agent whose window is almost expired waits briefly

- **WHEN** an agent's oldest recorded event is 58 seconds old and its budget is full
- **THEN** the `retry_after` in the nack is approximately 2 seconds

#### Scenario: retry_after is never zero or negative

- **WHEN** the computed remainder is zero or negative
- **THEN** the emitted `retry_after` is the configured positive minimum

