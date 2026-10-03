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

El sistema SHALL definir en `backend/app/modules/events/service.py` la tabla de transiciones canónicas `VALID_TRANSITIONS: dict[EventStatus, set[EventStatus]]` alineada a RN-72: `pending → {approved, rejected, superseded}`; todos los demás estados son terminales (out-edges vacías). La función `validate_transition(from_status, to_status)` SHALL lanzar `InvalidTransitionError` si la transición no está en la tabla. `InvalidTransitionError` SHALL ser una excepción de dominio definida en el mismo módulo. El consumer SHALL capturar `InvalidTransitionError`, ejecutar `XACK`, loguear el intento y NO persistir el evento resultante. El HTTP handler de C13 (approve/reject) también SHALL capturarla y retornar `409 Conflict`. La derivación del estado de un evento entrante (D35/RN-129) es una asignación en la **creación** de la fila y MUST NOT pasar por `validate_transition`: la tabla de transiciones y la máquina de estados de RN-72 quedan inalteradas por esa derivación. (RN-72; cláusula de creación por D35 / RN-129)

#### Scenario: Transición válida pending → superseded no lanza error
- **WHEN** se llama `validate_transition(EventStatus.pending, EventStatus.superseded)`
- **THEN** la llamada retorna sin lanzar excepción

#### Scenario: Transición inválida approved → pending lanza InvalidTransitionError
- **WHEN** se llama `validate_transition(EventStatus.approved, EventStatus.pending)`
- **THEN** se lanza `InvalidTransitionError`

#### Scenario: Transición inválida pending → alert_only lanza InvalidTransitionError
- **WHEN** se llama `validate_transition(EventStatus.pending, EventStatus.alert_only)`
- **THEN** se lanza `InvalidTransitionError`

#### Scenario: Crear un evento con estado terminal derivado no invoca validate_transition
- **WHEN** `ingest_event` deriva `alert_only` para un evento nuevo
- **THEN** la fila se crea directamente con `status=alert_only` sin consultar `VALID_TRANSITIONS`, porque no hay estado de origen del cual transicionar

### Requirement: Cadena superseded en ingesta con optimistic locking y re-consulta ante race

Cuando el consumer ingesta un evento válido para un path que ya tiene un evento con `status=pending`, el sistema SHALL: (1) marcar el evento pending anterior como `superseded` usando `UPDATE events SET status='superseded', version=version+1 WHERE id=? AND version=? AND status='pending'`; (2) si la UPDATE afecta 0 filas (carrera), re-consultar si todavía existe un pending activo para el mismo path (D25, RN-121): si hay pending → logear warning y abortar la creación del nuevo evento (skip legítimo); si NO hay pending → insertar el nuevo evento sin `parent_event_id`; (3) crear el nuevo evento con `parent_event_id` apuntando al ID del anterior. Si no existe evento `pending` para el path, el nuevo evento se crea sin `parent_event_id` (RN-21–23, RN-77). La supersesión SHALL evaluarse **antes** de derivar el estado del evento entrante y MUST NOT depender de él: un evento entrante terminal (`auto_restored`, `quarantined`, `alert_only`) supersede al `pending` activo del mismo path exactamente igual que un evento entrante `pending`. Recíprocamente, como la consulta de supersesión solo alcanza eventos `pending`, un evento terminal nunca es superseded a posteriori — es un hecho consumado, no un pendiente desplazable. (D35 / RN-129 refina la cláusula de estado; el resto es D25 / RN-121 sin cambios)

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
- **THEN** el consumer inserta el nuevo evento sin `parent_event_id`
- **AND** ejecuta `XACK` sobre la entrada

#### Scenario: Carrera en superseded — pending todavía existe — consumer aborta
- **WHEN** la UPDATE para marcar superseded afecta 0 filas
- **AND** la re-consulta de pending para el path retorna un evento pending activo
- **THEN** el consumer no crea el nuevo evento (skip legítimo)
- **AND** ejecuta `XACK` sobre la entrada
- **AND** emite un log de warning

#### Scenario: Evento entrante terminal supersede al pending del mismo path
- **WHEN** existe `event_A` con `path='/etc/hosts'` y `status=pending`
- **AND** llega un evento válido para `path='/etc/hosts'` cuyo estado derivado es `auto_restored`
- **THEN** `event_A` pasa a `superseded` y se crea `event_B` con `status=auto_restored` y `parent_event_id = event_A.id`

#### Scenario: Un evento terminal ya persistido no es superseded por uno posterior
- **WHEN** existe `event_A` con `path='/etc/hosts'` y `status=auto_restored`
- **AND** llega un nuevo evento válido para `path='/etc/hosts'`
- **THEN** `event_A` conserva su estado terminal y el nuevo evento se crea sin `parent_event_id`, porque la consulta de supersesión solo alcanza eventos `pending`

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

El consumer SHALL limitar la ingesta de eventos nuevos con un **token bucket por `agent_id`**, en
memoria (D85/RN-179). Cada `agent_id` tiene un balde de capacidad `burst` que se rellena de forma
continua a `rate_per_s` tokens por segundo, sin superar nunca la capacidad; un evento nuevo admitido
consume exactamente un token, y un evento sin token disponible excede el límite. Los defaults del
producto SHALL ser un régimen sostenido de 100 eventos por minuto (`rate_per_s = 100/60`) y una
ráfaga de 3.000 eventos (`burst = 3000`), elegida para cubrir el replay de 2.672 eventos de la
batería 5 con margen. Un `agent_id` sin estado previo SHALL comenzar con el balde lleno. El balde de
un agente MUST NOT verse afectado por los eventos de otro.

El check de rate limit se ejecuta DESPUÉS del dedup — re-entregas de eventos ya procesados NO
consumen tokens. Solo los eventos genuinamente nuevos (que superan el dedup) avanzan al check de
rate. Si excede el límite: ejecutar `XACK`, insertar en `rejected_events_audit` con
`reason=rate_limited`, **publicar un `event_nack` con `reason=rate_limited` y `retry_after`**
(D37/RN-131), y NO procesar el evento. El evento **NO se descarta**: el agente lo retiene y lo
reenvía cuando haya presupuesto — esta cláusula prevalece sobre la frase "se descartan con alerta"
de RN-88, que además nunca se implementó. El estado de los baldes SHALL reiniciarse al reiniciar el
backend (no persiste en Valkey). El limiter SHALL exponer `reset_rate_limiter()` para facilitar tests
y un método explícito que devuelva los segundos restantes hasta que haya un token disponible para un
`agent_id`, usado para derivar `retry_after` (RN-88, D7, D37, D85).

#### Scenario: Evento con tokens disponibles pasa el rate check
- **WHEN** el balde de `agent_a1` tiene al menos un token
- **AND** llega un nuevo evento de `agent_a1` que no existe en DB (no es re-entrega)
- **THEN** el evento pasa el rate check, consume un token y continúa la validación normal

#### Scenario: Una ráfaga de hasta 3.000 eventos se admite con el balde lleno
- **WHEN** `agent_a1` no tiene estado previo en el limiter
- **AND** llegan 3.000 eventos nuevos de `agent_a1` sin que transcurra tiempo entre ellos
- **THEN** los 3.000 eventos pasan el rate check
- **AND** el evento 3.001, en el mismo instante, excede el límite

#### Scenario: El régimen sostenido se limita a 100 eventos por minuto
- **WHEN** el balde de `agent_a1` está vacío
- **AND** `agent_a1` ofrece eventos nuevos de forma continua durante 10 minutos
- **THEN** se admiten 1.000 eventos en esos 10 minutos, con una tolerancia de un evento
- **AND** el resto excede el límite

#### Scenario: El relleno nunca supera la capacidad del balde
- **WHEN** `agent_a1` vació su balde y luego permanece inactivo durante 2 horas
- **THEN** su balde vuelve a tener exactamente 3.000 tokens, no más

#### Scenario: Los baldes de agentes distintos son independientes
- **WHEN** `agent_a1` vació su balde
- **AND** llega un evento nuevo de `agent_a2` sin estado previo
- **THEN** el evento de `agent_a2` pasa el rate check
- **AND** `agent_a2` conserva 2.999 tokens

#### Scenario: Evento que excede el límite es auditado y nackeado con retry_after
- **WHEN** el balde de `agent_a1` no tiene un token disponible
- **AND** llega un evento de `agent_a1` con un `event_id` nuevo (no re-entrega)
- **THEN** el consumer ejecuta `XACK`
- **AND** inserta en `rejected_events_audit` con `reason=rate_limited` y `agent_id='a1'`
- **AND** publica un `event_nack` con `reason=rate_limited` y un `retry_after` numérico positivo
- **AND** NO persiste el `Event`

#### Scenario: Re-entrega no consume tokens
- **WHEN** al balde de `agent_a1` le queda exactamente un token
- **AND** llega de nuevo el evento `e1` que ya existe en DB (re-entrega legítima)
- **THEN** el balde de `agent_a1` conserva ese token
- **AND** el evento `e1` es procesado como dedup (XACK + event_ack)

#### Scenario: Un evento rate-limited reenviado más tarde se ingesta
- **WHEN** un evento fue rechazado por rate limit y el agente lo reenvía una vez que hay un token
- **THEN** el evento se persiste normalmente y recibe `event_ack`

#### Scenario: reset_rate_limiter limpia el estado
- **WHEN** se llama `reset_rate_limiter()`
- **THEN** todos los agentes vuelven a no tener estado y su próximo evento encuentra el balde lleno

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

El consumer SHALL derivar el `retry_after` del `event_nack` de `rate_limited` del estado vivo del
token bucket del agente, no de una constante: el tiempo hasta que el balde acumule el token que le
falta, `(1 − tokens) / rate_per_s` (D85/RN-179). Con los defaults del producto ese valor no supera
0,6 s. El valor SHALL tener un piso positivo pequeño (0,5 s) para que un resultado cero o negativo
por una carrera no induzca un busy-loop en el agente. Si el agente tiene al menos un token, o no tiene
estado, el método SHALL devolver `0.0`.

El limiter SHALL exponer esto como un método explícito. El consumer MUST NOT leer el estado interno
del limiter. (D37 / RN-131, RN-88, D85 / RN-179)

#### Scenario: Un agente que acaba de vaciar el balde espera el intervalo de un token
- **WHEN** el balde de un agente tiene 0 tokens con el régimen de 100 eventos por minuto
- **THEN** el `retry_after` del nack es de 0,6 segundos

#### Scenario: Un agente con un token casi completo espera el piso
- **WHEN** el balde de un agente tiene 0,9 tokens con el régimen de 100 eventos por minuto
- **THEN** el `retry_after` del nack es el piso de 0,5 segundos

#### Scenario: El retry_after acompaña la tasa configurada
- **WHEN** la tasa configurada es de 0,1 tokens por segundo y el balde del agente tiene 0 tokens
- **THEN** el `retry_after` del nack es de 10 segundos

#### Scenario: retry_after is never zero or negative
- **WHEN** el remanente calculado es cero o negativo
- **THEN** el `retry_after` emitido es el mínimo positivo configurado

#### Scenario: Sin déficit no hay espera
- **WHEN** el agente tiene al menos un token, o no tiene estado en el limiter
- **THEN** el método devuelve `0.0`

### Requirement: ingest_event derives the event status from action and action_failed

`ingest_event` (`backend/app/modules/events/service.py`) SHALL derive `Event.status` from the `action` and `action_failed` keys of the incoming stream payload, via a pure function `derive_event_status(action, action_failed) -> EventStatus` defined in the same module. The payload keys MUST be read tolerantly — `.get("action")` and `bool(.get("action_failed", False))` — because the agent writes `action_failed` only on the failure path (`agent/decision.py:80`). The derivation table is exactly: `auto_restore` + not failed → `auto_restored`; `quarantine` + not failed → `quarantined`; `alert_only` → `alert_only` regardless of `action_failed`; `manual_review` → `pending`; `auto_restore` or `quarantine` with `action_failed` true → `pending`; absent or unrecognized `action` → `pending`. A failed automatic action MUST NOT produce a terminal status, because the file remains tampered on disk and the incident must return to the operator queue with approve and reject available — terminal statuses have no out-edges in `VALID_TRANSITIONS` and would leave a compromised file with no actor able to intervene. An absent or unrecognized `action` MUST NOT reject the event; it ingests as `pending` (forward tolerance, the same criterion D33 applied to `is_symlink`). (D35 / RN-129, RN-13, RN-06)

#### Scenario: auto_restore action produces a terminal auto_restored event
- **WHEN** the consumer ingests a payload with `action = "auto_restore"` and no `action_failed` key
- **THEN** the persisted event has `status = auto_restored`

#### Scenario: quarantine action produces a terminal quarantined event
- **WHEN** the consumer ingests a payload with `action = "quarantine"` and no `action_failed` key
- **THEN** the persisted event has `status = quarantined`

#### Scenario: alert_only action produces a terminal alert_only event regardless of action_failed
- **WHEN** the consumer ingests a payload with `action = "alert_only"`, with or without `action_failed` set to true
- **THEN** the persisted event has `status = alert_only`, because `alert_only` performs no physical action and has nothing to fail

#### Scenario: manual_review action leaves the event pending
- **WHEN** the consumer ingests a payload with `action = "manual_review"`
- **THEN** the persisted event has `status = pending` and is available for operator approve/reject

#### Scenario: Failed auto_restore returns the event to the operator queue as pending
- **WHEN** the consumer ingests a payload with `action = "auto_restore"` and `action_failed = true`
- **THEN** the persisted event has `status = pending`, NOT `auto_restored`, so that approve and reject remain available on a file that is still tampered

#### Scenario: Failed quarantine returns the event to the operator queue as pending
- **WHEN** the consumer ingests a payload with `action = "quarantine"` and `action_failed = true`
- **THEN** the persisted event has `status = pending`, NOT `quarantined`

#### Scenario: Payload from an older agent without an action key ingests as pending
- **WHEN** the consumer ingests a payload published by an agent version that emits no `action` key
- **THEN** the event ingests without error with `status = pending`, preserving the pre-change behavior

#### Scenario: Unrecognized action value ingests as pending instead of being rejected
- **WHEN** the consumer ingests a payload whose `action` is a value outside `auto_restore | quarantine | manual_review | alert_only`
- **THEN** the event ingests without error with `status = pending`, and is NOT rejected as an invalid schema

### Requirement: The backend is the sole authority over EventStatus and ignores any agent-supplied status

`ingest_event` MUST NOT read a `status` key from the stream payload. The existing `event_data.get("status", "pending")` read and its `ValueError` fallback SHALL be removed; the enum fallback is subsumed by `derive_event_status`. This is a security boundary, not a stylistic choice: `action` is a closed four-value vocabulary produced by the agent rule engine, whereas a free-form `status` field would let a compromised agent inject events already marked `approved` or `rejected`, bypassing the human decision cycle (RN-25 / RN-26) and its audit trail. The statuses `approved`, `rejected` and `superseded` SHALL NOT be derivable from an agent payload under any circumstance: they are backend-exclusive transitions originating from an operator decision or from automatic supersession (RN-77). (D35 / RN-129)

#### Scenario: A payload carrying an explicit status field has it ignored
- **WHEN** the consumer ingests a payload that contains a `status` key
- **THEN** the key is ignored entirely and the persisted status is the one derived from `action` and `action_failed`

#### Scenario: An agent payload cannot induce an approved event
- **WHEN** a payload attempts to set `status = "approved"`, whether directly or via an `action` value naming it
- **THEN** the persisted event is `pending` (or the status derived from a recognized `action`), never `approved`

#### Scenario: An agent payload cannot induce a rejected or superseded event
- **WHEN** a payload attempts to induce `rejected` or `superseded`
- **THEN** the persisted event is `pending` (or the status derived from a recognized `action`), because those statuses are reachable only through backend-originated transitions

### Requirement: Agent-originated terminal events record an automatic resolution

When `ingest_event` derives a terminal status (`auto_restored`, `quarantined`, `alert_only`), it SHALL persist `resolved_at = received_at` and leave `resolved_by = NULL`. `received_at` is the timestamp already passed into `ingest_event` by the consumer, which keeps the function deterministic and free of wall-clock reads. The combination `resolved_by IS NULL AND resolved_at IS NOT NULL` identifies an automatic agent resolution with no human operator, distinguishable from an approve/reject, which always sets `resolved_by`. Events that derive `pending` — including those whose automatic action failed — MUST NOT set `resolved_at` or `resolved_by`: they remain open. (D35 / RN-129)

#### Scenario: Terminal event records resolved_at and a null resolved_by
- **WHEN** an event is ingested with a derived status of `auto_restored`, `quarantined` or `alert_only`
- **THEN** the row has `resolved_at` equal to its `received_at` and `resolved_by` null

#### Scenario: Pending event leaves the resolution fields empty
- **WHEN** an event is ingested with a derived status of `pending`
- **THEN** `resolved_at` and `resolved_by` are both null

#### Scenario: Failed remediation stays unresolved
- **WHEN** an event with `action = "auto_restore"` and `action_failed = true` is ingested
- **THEN** it is `pending` with `resolved_at` null, because the file remains tampered and the incident is not resolved

### Requirement: ingest_event persists the action_failed flag

`ingest_event` SHALL persist `Event.action_failed` on every ingested event, with the value read from the payload (defaulting to `false`), independently of the derived status. Without this column a `pending` produced by a failed `auto_restore` would be indistinguishable from a `pending` produced by `manual_review`, and the fact that the system attempted remediation and could not complete it would be lost — it is not recorded anywhere else on the backend side. A `pending` with `action_failed = true` means the file is still tampered AND automatic remediation already failed, which carries operational priority over an ordinary `pending`. (D35 / RN-129)

#### Scenario: Failed action persists the flag alongside the pending status
- **WHEN** an event with `action_failed = true` is ingested
- **THEN** the row has `action_failed = true` and `status = pending`

#### Scenario: Successful action persists the flag as false
- **WHEN** an event with a successful action is ingested (no `action_failed` key in the payload)
- **THEN** the row has `action_failed = false`

### Requirement: Ingestion persists the action failure cause with forward tolerance

`ingest_event` SHALL read the action failure cause from the event payload and persist it on the event row, truncating it to the column's length. The cause composes with the existing `action_failed` flag introduced by D35 / RN-129 and does not alter the status derivation in any way: an event whose action failed is still ingested as `pending`, and the cause only explains why.

The value SHALL NOT be validated against an enumeration, neither in the database nor at ingestion. The vocabulary evolves on the agent side, and a database-level constraint would turn an agent newer than the backend into lost integrity events — the very asset the system exists not to lose. An unrecognized value SHALL be stored as received; an absent value SHALL be stored as null. This is the same forward-tolerance criterion already applied to an unknown `action` and to the symlink metadata.

The cause SHALL NOT be derivable into any event status and SHALL NOT influence supersession. (D36 / RN-130, D35 / RN-129, RN-71)

#### Scenario: A known cause is persisted alongside the failure flag

- **WHEN** an event payload carries `action_failed` true and a cause of `read_only_mount`
- **THEN** the persisted row has status `pending`, the failure flag set, and the cause `read_only_mount`

#### Scenario: An unknown cause is stored rather than rejected

- **WHEN** an event payload carries a cause literal the backend does not recognize
- **THEN** the event is ingested normally and the cause is stored as received

#### Scenario: An absent cause is null

- **WHEN** an event payload from an older agent carries no cause key
- **THEN** the persisted cause is null and the rest of the ingestion is unchanged

#### Scenario: A successful action stores no cause

- **WHEN** an event payload reports a successful automatic action
- **THEN** the persisted cause is null and the derived status is the terminal one

#### Scenario: The cause does not affect status derivation or supersession

- **WHEN** two events for the same path arrive, the second carrying a failure cause
- **THEN** the derived statuses and the supersession of the active pending event are exactly what they would be without the cause

### Requirement: La ingesta persiste detected_offline con tolerancia hacia adelante

`ingest_event` SHALL leer `detected_offline` del payload y persistirlo en `Event.detected_offline`: un booleano se guarda tal cual; una clave ausente se guarda como `NULL`; cualquier otro valor se guarda como `NULL` y se registra `consumer.detected_offline_invalid`, sin rechazar el evento. El campo MUST NOT alterar la validación de `schema_version`, la verificación HMAC, la derivación del status, la severidad ni la supersesión. (D80 / RN-174)

#### Scenario: Evento offline
- **WHEN** se ingiere un payload con `detected_offline: true`
- **THEN** la fila persistida tiene `detected_offline = true` y el mismo status que tendría el evento sin el campo

#### Scenario: Evento en línea
- **WHEN** se ingiere un payload con `detected_offline: false`
- **THEN** la fila persistida tiene `detected_offline = false`

#### Scenario: Agente anterior sin el campo
- **WHEN** se ingiere un payload sin la clave `detected_offline`
- **THEN** la fila persistida tiene `detected_offline IS NULL`

#### Scenario: Valor no booleano
- **WHEN** se ingiere un payload con `detected_offline: "yes"`
- **THEN** el evento se persiste con `detected_offline IS NULL` y se registra `consumer.detected_offline_invalid`

### Requirement: Configuración del límite de ingesta y advertencia por settings heredados

El backend SHALL leer el límite de ingesta de dos settings (D85/RN-179):
`rate_limit_ingest_rate_per_s` (variable `RATE_LIMIT_INGEST_RATE_PER_S`, número real estrictamente
positivo, default `100/60`) y `rate_limit_ingest_burst` (variable `RATE_LIMIT_INGEST_BURST`, entero
mayor o igual a 1, default `3000`). Un valor fuera de rango MUST hacer fallar el arranque con un
error de validación. El limiter construido sin argumentos SHALL tomar ambos valores de la
configuración.

Los settings `rate_limit_ingest_events` y `rate_limit_ingest_window_seconds` SHALL NOT existir. Si
`RATE_LIMIT_INGEST_EVENTS` o `RATE_LIMIT_INGEST_WINDOW_SECONDS` tienen un valor no vacío en el
entorno del proceso o en el archivo `.env` que lee la configuración, el arranque del backend SHALL
registrar una única advertencia que nombre las variables ignoradas y sus reemplazos, y SHALL
continuar. Esos valores MUST NOT influir en el límite efectivo.

#### Scenario: Los defaults del producto son 100 eventos por minuto y ráfaga de 3.000
- **WHEN** el backend arranca sin `RATE_LIMIT_INGEST_RATE_PER_S` ni `RATE_LIMIT_INGEST_BURST`
- **THEN** el limiter usa una tasa de 100/60 tokens por segundo y una capacidad de 3.000 tokens

#### Scenario: El limiter respeta la configuración
- **WHEN** `RATE_LIMIT_INGEST_BURST=3` y `RATE_LIMIT_INGEST_RATE_PER_S=0.5`
- **THEN** un agente sin estado puede enviar 3 eventos nuevos en el mismo instante y el cuarto excede el límite
- **AND** el `retry_after` de ese cuarto evento es de 2 segundos

#### Scenario: Un valor fuera de rango impide arrancar
- **WHEN** `RATE_LIMIT_INGEST_RATE_PER_S=0` o `RATE_LIMIT_INGEST_BURST=0`
- **THEN** la carga de la configuración falla con un error de validación

#### Scenario: Una variable heredada produce una advertencia y no tiene efecto
- **WHEN** el entorno del backend define `RATE_LIMIT_INGEST_EVENTS=100000`
- **THEN** el arranque registra una advertencia que nombra `RATE_LIMIT_INGEST_EVENTS` y los reemplazos `RATE_LIMIT_INGEST_RATE_PER_S` y `RATE_LIMIT_INGEST_BURST`
- **AND** el backend arranca
- **AND** el limiter usa los valores de `rate_limit_ingest_rate_per_s` y `rate_limit_ingest_burst`

#### Scenario: Una variable heredada vacía no produce advertencia
- **WHEN** el entorno define `RATE_LIMIT_INGEST_EVENTS` con valor vacío y no define `RATE_LIMIT_INGEST_WINDOW_SECONDS`
- **THEN** el arranque no registra la advertencia

### Requirement: El bucle principal del consumer recrea el group ante NOGROUP

El consumer SHALL invocar, cuando una lectura del bucle principal de `run_consumer` (`XREADGROUP` con
id `>`) falla con un error cuyo mensaje contiene `NOGROUP`, `_ensure_group` dentro del mismo
bucle, SHALL releer su PEL (`XREADGROUP` con id `0`) y SHALL volver a leer entradas nuevas, sin
requerir un reinicio del proceso del backend (D87/RN-181). El consumer MUST loguear la recreación
con un evento propio (`consumer.group_recreated`), distinto de `consumer.loop_error`. Si
`_ensure_group` falla (por ejemplo, Valkey todavía no responde), el consumer MUST conservar el
comportamiento actual: loguear, esperar 1 segundo y reintentar en la siguiente iteración. El group
SHALL recrearse con el mismo id inicial que en el arranque (`0`) y con `MKSTREAM`, de modo que
ninguna entrada presente en el stream quede sin leer.

#### Scenario: Valkey vuelve sin el group y el consumer lo recrea sin reiniciar
- **WHEN** el consumer está en su bucle principal
- **AND** Valkey se reinicia sin conservar el consumer group `fim-backend`
- **AND** la siguiente lectura `XREADGROUP` falla con `NOGROUP`
- **THEN** el consumer invoca `_ensure_group` y el group `fim-backend` vuelve a existir
- **AND** el consumer registra `consumer.group_recreated`
- **AND** un evento publicado después de la recreación se ingesta y recibe `event_ack` sin reiniciar el backend

#### Scenario: Un error distinto de NOGROUP conserva el tratamiento actual
- **WHEN** la lectura del bucle principal falla con un error que no contiene `NOGROUP`
- **THEN** el consumer loguea `consumer.loop_error`, espera 1 segundo y reintenta
- **AND** no invoca `_ensure_group`

#### Scenario: La recreación falla mientras Valkey no responde
- **WHEN** la lectura falla con `NOGROUP` y la llamada a `_ensure_group` lanza un error de conexión
- **THEN** el consumer no termina
- **AND** reintenta en la siguiente iteración del bucle, después de esperar 1 segundo

### Requirement: La autenticación del agente se cachea en memoria con TTL de 5 segundos

El consumer SHALL cachear en memoria el resultado de `_get_agent_auth` por `agent_id` con un TTL de
5 segundos medido con reloj monótono (D87/RN-181). El caché SHALL invalidarse **sólo** por TTL,
porque no existe revocación de agente (`AgentStatus.revoked` nunca se asigna, D86/RN-180). Sólo se
SHALL cachear un resultado con secreto resuelto: un `agent_id` desconocido o sin secreto MUST NOT
quedar en el caché, de modo que el tamaño del caché queda acotado por la cantidad de agentes
registrados y un agente recién enrolado no se rechaza por un resultado negativo previo. El secreto
MUST obtenerse a través del helper único de lectura de D86/RN-180; el caché MUST NOT almacenar el
valor envuelto ni volver a leer `shared_secret_hex` por su cuenta. Un acierto del caché MUST NOT
abrir una `Session` ni pasar por el executor; un fallo SHALL resolver la consulta en el executor,
como exige D75/RN-169. El camino de rechazo (`_reject`, cuando necesita el secreto para firmar un
`event_nack`) SHALL usar el mismo caché.

#### Scenario: Eventos consecutivos del mismo agente dentro del TTL consultan la base una sola vez
- **WHEN** llegan dos eventos válidos del agente `a1` separados por menos de 5 segundos
- **THEN** la base se consulta para resolver la autenticación de `a1` una única vez
- **AND** ambos eventos se validan con el mismo secreto

#### Scenario: Vencido el TTL se vuelve a consultar la base
- **WHEN** transcurren más de 5 segundos desde que se cacheó la autenticación de `a1`
- **AND** llega un nuevo evento de `a1`
- **THEN** la autenticación de `a1` se vuelve a resolver contra la base

#### Scenario: Un agent_id desconocido no queda cacheado
- **WHEN** llega un evento de un `agent_id` que no existe en la base
- **THEN** el evento se rechaza como `unknown_agent`
- **AND** el caché no contiene una entrada para ese `agent_id`
- **AND** un evento posterior del mismo `agent_id`, enviado después de que el agente se registre y enrole, se resuelve contra la base

### Requirement: XACK y event_ack se emiten por lote y sólo después del commit de cada evento

Dentro de `_process_batch`, el consumer SHALL acumular la respuesta `event_ack` y el `XACK` de cada
evento que se resuelve con `event_ack` (ingesta persistida, re-entrega detectada en dedup —en la
base o dentro del mismo lote— y skip por carrera de supersesión) y SHALL emitirlos juntos, en un
único pipeline transaccional, al terminar el lote (D87/RN-181). Como los eventos del lote se
persisten en una única transacción (ampliación del 2026-10-03 de D87/RN-181), ninguna entrada MUST
agregarse al acumulado antes de que el `COMMIT` de esa transacción haya retornado con éxito. Si la
transacción del lote lanza `SQLAlchemyError`, ninguna entrada que dependa de ella MUST agregarse al
acumulado ni recibir `XACK`, y todas MUST permanecer en la PEL, tal como exige el requisito
«Protocolo ACK end-to-end con persistencia y dedup idempotente»; la re-ejecución evento por evento
ante `IntegrityError`/`DataError` sigue el requisito «Los eventos validados de un lote se persisten
en una única transacción». Los rechazos de validación (`_reject`) SHALL conservar su `XACK` y su
`event_nack` inmediatos; el rechazo `rate_limited` y el camino de `InvalidTransitionError` SHALL
emitir su `XACK` y su `event_nack` después del `COMMIT` del lote. El despacho de mensajes del lote
MUST seguir siendo secuencial (D75/RN-169). Si el acumulado no puede emitirse (por ejemplo, Valkey
se cae al final del lote), las entradas MUST quedar en la PEL, y ninguna re-entrega posterior
—desde la PEL o por republicación del agente— MUST producir una segunda fila en `events`. Invocado
fuera de un lote, `_handle_message` SHALL conservar la emisión inmediata de `XACK` y `event_ack`.

#### Scenario: Un lote de eventos válidos se confirma con un único pipeline
- **WHEN** `_process_batch` recibe un lote de N eventos válidos y nuevos
- **THEN** los N eventos quedan persistidos
- **AND** los N `event_ack` y los N `XACK` se emiten en un único pipeline al final del lote

#### Scenario: El acumulado nunca precede al commit
- **WHEN** se procesa un lote de eventos válidos
- **THEN** para cada evento, el instante en que su `XACK` se agrega al acumulado es posterior al retorno del `COMMIT` de la transacción del lote

#### Scenario: Un error transitorio de base de datos en el lote no confirma ninguno de sus eventos
- **WHEN** un lote contiene los eventos `e1`, `e2` y `e3`
- **AND** la transacción del lote lanza un `SQLAlchemyError` transitorio
- **THEN** ni `e1`, ni `e2`, ni `e3` reciben `XACK` ni respuesta
- **AND** los tres permanecen en la PEL

#### Scenario: Valkey falla al emitir el acumulado
- **WHEN** el pipeline del final del lote falla
- **THEN** los eventos del lote quedan persistidos y sus entradas siguen en la PEL
- **AND** una re-entrega posterior de cualquiera de ellos no produce una segunda fila en `events`

#### Scenario: El orden FIFO y la ausencia de duplicados se preservan
- **WHEN** se drena un lote de eventos del mismo agente generados en orden
- **THEN** el orden de inserción en `events` reproduce el orden del stream
- **AND** ningún `event_id` aparece dos veces, incluida la re-entrega desde la PEL

### Requirement: Perfilado opcional de la ingesta por etapa

El consumer SHALL registrar, cuando el setting `fim_profile_ingest` está activo (variable de entorno
`FIM_PROFILE_INGEST` en `1`), un log estructurado `consumer.timing` por evento procesado con la duración
en milisegundos de cada etapa —resolución de autenticación (indicando si fue acierto del caché),
validación, ingesta transaccional y total— y un log `consumer.timing` por lote con la duración de la
emisión del acumulado de ACK y el tamaño del lote (D87/RN-181). Cuando los eventos del lote se
persisten en una única transacción (ampliación del 2026-10-03 de D87/RN-181), el `ingest_ms` por
evento SHALL ser la porción de tiempo de las operaciones de ese evento dentro de la transacción del
lote, el log por evento SHALL emitirse después del `COMMIT` del lote, y el log por lote SHALL
incluir además la cantidad de candidatos persistidos en la transacción (`candidates`), la duración
de la transacción sin el `COMMIT` (`ingest_db_ms`) y la duración del `COMMIT` (`commit_ms`). Con el
setting inactivo, que es el default, el consumer MUST NOT emitir `consumer.timing`. Los logs de
perfilado MUST NOT incluir el payload, el secreto ni la firma, y SHALL respetar la sanitización de
logs existente (RN-89).

#### Scenario: Perfilado activo emite tiempos por etapa
- **WHEN** el backend corre con `FIM_PROFILE_INGEST=1`
- **AND** se ingesta un lote de eventos válidos
- **THEN** se registra un `consumer.timing` por evento con las duraciones de autenticación, validación, ingesta y total
- **AND** se registra un `consumer.timing` por lote con la duración de la emisión del ACK, el tamaño del lote, `candidates`, `ingest_db_ms` y `commit_ms`

#### Scenario: Perfilado inactivo por defecto
- **WHEN** el backend corre sin `FIM_PROFILE_INGEST`
- **THEN** no se registra ningún `consumer.timing`

### Requirement: Piso de rendimiento de la ingesta y INSERT por lote condicional

El carril de ingesta SHALL sostener al menos 95 eventos por segundo, con objetivo de 150 (D87/RN-181).
Con el caché de autenticación y el ACK por lote, el laboratorio midió 76,6 ev/s sobre `v5.0-tesis`
(diagnóstico del 2026-10-03). La ampliación del 2026-10-03 de D87/RN-181, revisada tras medir,
atribuye la caída a la construcción de un cliente HTTP con su contexto SSL por cada entrega de
notificación. Por eso las optimizaciones SHALL adoptarse en este orden:

- **Fase A, obligatoria.** El cliente HTTP de larga vida del carril de notificación (requisito «Las
  entregas HTTP del carril de notificación reutilizan un cliente de larga vida» de
  `backend-notifications`).
- **Fase B, condicional.** Sólo si con la fase A el banco de desarrollo no alcanza el umbral de
  abajo: la persistencia de los eventos validados de un lote en una única transacción por lote. Debe
  preservar:
  - el orden FIFO de inserción;
  - la cadena `superseded`, incluido el caso en que dos eventos del mismo lote afectan la misma ruta;
  - el dedup idempotente por `event_id`, en la base y dentro del lote;
  - que un error transitorio deje todo el lote en la PEL.

  MUST NOT introducir concurrencia entre eventos del lote (D75/RN-169).
- **Dentro de la fase B, y sólo si tampoco alcanza el umbral,** la creación de la fila `Alert` en
  esa transacción (enmienda condicional de D76/RN-170).

Antes de etiquetar `v5.1-tesis`, el banco de desarrollo `lab/bench_ingest_consumer.py` SHALL medir,
con la cadena de notificación **sin stub**, al menos 1,5 veces su línea base sin stub en el mismo
host. Sin stub significa:

- reglas que hacen alertar a cada evento;
- un sumidero HTTP local que persiste una fila por pedido en otra base de la misma instancia de
  PostgreSQL;
- rutas repetidas como el generador de carga.

La línea base registrada es 62,0 ev/s, así que el umbral es ≥93 ev/s.

Si la fase A alcanza el umbral, la fase B MUST NOT implementarse y SHALL registrarse como no
necesaria, con su medición. Si la fase B se adopta, su delta de requisitos SHALL escribirse en la
change antes del código.

El piso de laboratorio SHALL medirse en la Batería 5 del arnés unificado sobre `v5.1-tesis`, como
ventana de consumo entre el primer y el último `received_at` de los eventos drenados. Las
mediciones de desarrollo, antes y después de cada fase, y las decisiones sobre la fase B y su paso
condicional SHALL quedar registradas en la change. El resultado del laboratorio SHALL registrarse
tal como se mida, sin declarar una mejora antes de medirla.

#### Scenario: La fase A alcanza el umbral de desarrollo
- **WHEN** el banco de desarrollo sin stub mide con la fase A al menos 1,5 veces su línea base sin stub en el mismo host
- **THEN** la persistencia por lote no se implementa
- **AND** la change registra ambas mediciones y la decisión

#### Scenario: La fase A no alcanza el umbral de desarrollo
- **WHEN** el banco de desarrollo sin stub mide con la fase A menos de 1,5 veces su línea base sin stub
- **THEN** se adopta la persistencia de los eventos validados de un lote en una única transacción, con su delta de requisitos escrito antes del código
- **AND** dos eventos válidos consecutivos de la misma ruta en un lote, sin pending previo, dejan al primero `superseded` y al segundo `pending` con `parent_event_id` igual al id del primero

#### Scenario: La ventana de consumo de la Batería 5 se registra
- **WHEN** la Batería 5 drena el stream tras restaurar Valkey
- **THEN** registra el ritmo como la cantidad de eventos drenados dividida por la diferencia entre el último y el primer `received_at`

### Requirement: Los eventos validados de un lote se persisten en una única transacción

Dentro de `_process_batch`, el consumer SHALL persistir los eventos del lote que superan la
validación (schema, agente, firma HMAC, clock skew y `event_id` no vacío) en **una única
transacción de base de datos por lote**, ejecutada en una única salida al executor de ingesta y en
el orden en que las entradas aparecen en el stream (ampliación del 2026-10-03 de D87/RN-181). El
despacho de mensajes MUST seguir siendo secuencial (D75/RN-169) y MUST NOT existir concurrencia
entre eventos del lote. Dentro de esa transacción, el sistema SHALL conservar la semántica por
evento de la ingesta:

- **Dedup**: un `event_id` ya presente en la base, o ya visto antes en el mismo lote, SHALL
  resolverse como re-entrega, sin una segunda fila en `events` y sin consumir rate limit.
- **Rate limit**: la decisión SHALL tomarse por evento nuevo, después del dedup y en el orden del
  lote. Si la transacción del lote se revierte, los tokens que sus candidatos consumieron SHALL
  devolverse al balde de su agente, sin superar su capacidad.
- **Cadena `superseded`**: el `pending` vigente de cada ruta SHALL incluir los eventos insertados
  antes en el mismo lote, de modo que un evento posterior de la misma ruta lo supersede con el
  `UPDATE` optimista y la re-consulta ante carrera de D25/RN-121. La máquina de estados (RN-11,
  RN-12, RN-72) y la compactación por evento en la misma transacción (RN-98) MUST NOT cambiar.
- **Severidad**: las reglas SHALL leerse una vez por lote; una regla modificada durante un lote
  rige desde el lote siguiente.
- **Orden**: el orden de inserción en `events` SHALL reproducir el orden del stream.

Un `InvalidTransitionError`, un descarte por carrera de supersesión o una decisión `rate_limited`
de un candidato MUST NOT abortar la transacción del lote. Los efectos que dependen del resultado de
la ingesta —`event_ack` y `XACK`, el rechazo `rate_limited`, el `XACK` + auditoría + `event_nack`
de `InvalidTransitionError` y el agendado de la notificación del evento persistido— SHALL aplicarse
**después** de que el `COMMIT` del lote retorne con éxito, en el orden del stream. El agendado de
la notificación MUST omitirse para un evento del lote que la compactación del mismo lote eliminó
antes del `COMMIT`. Los rechazos de la validación SHALL conservar su `XACK` y su `event_nack`
inmediatos.

Si cualquier operación de la transacción del lote o su `COMMIT` lanza `SQLAlchemyError`, el sistema
SHALL revertir la transacción y ningún candidato del lote MUST recibir `XACK` ni respuesta: todos
MUST permanecer en la PEL, y el consumer MUST loguear el error con `exc_info=True`. Si el error es
`IntegrityError` o `DataError`, el sistema SHALL además re-ejecutar los candidatos del lote uno por
uno por el camino de ingesta por evento, de modo que sólo el evento que vuelve a fallar quede en la
PEL. Invocado fuera de un lote, `_handle_message` SHALL conservar el camino de ingesta por evento,
con su propia transacción.

Los efectos posteriores al `COMMIT` SHALL ser independientes entre candidatos: si el efecto de uno
falla, el consumer MUST loguear el error y dejar sin `XACK` sólo ese mensaje, sin impedir los
efectos de los demás. En particular, el agendado de la notificación de un evento persistido MUST
ocurrir aunque falle cualquier efecto de ese evento o de otro del lote. Si el consumer se cancela
mientras el lote se persiste (apagado del backend), SHALL completar la persistencia y sus efectos,
con una espera acotada, antes de propagar la cancelación. Un payload firmado cuyo `path` o
`event_id` no sea una cadena SHALL rechazarse en la validación con el motivo `invalid_schema`,
aislado de su lote; y cualquier excepción de la transacción del lote que no sea un `SQLAlchemyError`
SHALL tratarse como `IntegrityError`: revertir, devolver los tokens y re-ejecutar los candidatos
uno por uno.

#### Scenario: Un lote de eventos válidos se confirma con un único COMMIT
- **WHEN** `_process_batch` recibe un lote de N eventos válidos y nuevos de rutas distintas
- **THEN** los N eventos quedan persistidos mediante una sola transacción con un único `COMMIT`
- **AND** el orden de inserción en `events` reproduce el orden del stream

#### Scenario: Dos eventos de la misma ruta en un lote forman cadena
- **WHEN** un lote contiene dos eventos válidos consecutivos para la misma ruta, ambos con estado derivado `pending` y sin `pending` previo en la base
- **THEN** el primero queda `superseded` con su `version` incrementada en 1
- **AND** el segundo queda `pending` con `parent_event_id` igual al id del primero

#### Scenario: Un evento terminal del lote supersede al pending insertado antes en el mismo lote
- **WHEN** un lote contiene un evento `pending` para `/etc/hosts` seguido de un evento para `/etc/hosts` cuyo estado derivado es `alert_only`
- **THEN** el primero queda `superseded`
- **AND** el segundo queda `alert_only` con `parent_event_id` igual al id del primero

#### Scenario: Un event_id repetido dentro del lote se resuelve como re-entrega
- **WHEN** un lote contiene dos entradas con el mismo `event_id`
- **THEN** se persiste una sola fila en `events`
- **AND** ambas entradas reciben `XACK` y `event_ack` después del `COMMIT` del lote
- **AND** la segunda entrada no consume rate limit

#### Scenario: Un error transitorio deja todo el lote en la PEL
- **WHEN** un lote contiene los eventos válidos `e1`, `e2` y `e3`
- **AND** la transacción del lote lanza un `SQLAlchemyError` que no es `IntegrityError` ni `DataError`
- **THEN** ninguna fila de `e1`, `e2` ni `e3` queda en `events`
- **AND** ninguno recibe `XACK` ni respuesta en `commands`, y los tres permanecen en la PEL
- **AND** los tokens de rate limit que consumieron se devuelven al balde del agente
- **AND** una re-entrega posterior de los tres los persiste una sola vez cada uno

#### Scenario: Un evento envenenado no bloquea a sus vecinos
- **WHEN** la transacción de un lote con `e1`, `e2` y `e3` lanza `IntegrityError` por causa de `e2`
- **THEN** el sistema revierte la transacción y re-ejecuta `e1`, `e2` y `e3` uno por uno
- **AND** `e1` y `e3` quedan persistidos y reciben `XACK` y `event_ack`
- **AND** `e2` no recibe `XACK` ni respuesta y permanece en la PEL

#### Scenario: Los efectos de la ingesta esperan al COMMIT del lote
- **WHEN** un lote contiene un evento persistido, un evento `rate_limited` y un evento cuya ingesta lanza `InvalidTransitionError`
- **THEN** el `event_ack`, el `event_nack` de `rate_limited`, el `XACK` + auditoría + `event_nack` de la transición inválida y el agendado de la notificación ocurren después del retorno del `COMMIT` del lote
- **AND** se aplican en el orden del stream

#### Scenario: El fallo de un efecto no impide la notificación de los eventos persistidos
- **WHEN** un lote contiene un evento `rate_limited` cuyo rechazo falla y un evento nuevo persistido después
- **THEN** el evento nuevo recibe `XACK`, `event_ack` y su notificación se agenda
- **AND** el evento `rate_limited` permanece en la PEL

#### Scenario: Un path que no es cadena se rechaza sin afectar al lote
- **WHEN** un lote contiene un evento con firma válida cuyo `path` es un entero o una lista
- **THEN** ese evento recibe `XACK` y un rechazo `invalid_schema` inmediatos
- **AND** sus vecinos válidos se persisten

#### Scenario: La cancelación a mitad de un lote no pierde sus efectos
- **WHEN** el consumer se cancela mientras el executor confirma el lote
- **THEN** los `event_ack` y `XACK` de los eventos confirmados se emiten
- **AND** la cancelación se propaga después

#### Scenario: Un rechazo de validación sigue siendo inmediato dentro del lote
- **WHEN** un lote contiene una entrada con firma HMAC inválida antes de eventos válidos
- **THEN** esa entrada recibe su `XACK` inmediato, antes del `COMMIT` del lote
- **AND** no forma parte de la transacción del lote

#### Scenario: Fuera de un lote se conserva el camino por evento
- **WHEN** `_handle_message` se invoca directamente, sin un lote en curso
- **THEN** el evento se ingesta en su propia transacción y se confirma de inmediato, como antes de esta change

