## MODIFIED Requirements

### Requirement: Validación de evento en orden barato a caro con rechazo tipado

El consumer SHALL validar cada evento entrante en este orden, rechazando al primer fallo y persistiendo el rechazo en `rejected_events_audit` con `RejectionReason` tipado y `payload_dump` truncado a 4 KB (D4, RN-105): (1) `schema_version` parseable y menor o igual al soportado, si no `invalid_schema` (RN-91); (2) `agent_id` existe en la tabla `agents`, si no `unknown_agent`; (3) firma `HMAC-SHA256(shared_secret, canonical_json(payload))` válida, si no `invalid_signature` (RN-79); (4) `detected_at` UTC-aware y `abs(received_at - detected_at) <= 5 min`, si no `clock_skew` (RN-90); (5) **`event_id` no-vacío**, si no `invalid_schema`; (6) **dedup por `event_id`** — si ya existe en DB, XACK + event_ack, sin consumir rate budget; (7) **rate limit** 100 eventos/min por `agent_id`, si supera: `XACK` + `rejected_events_audit` con `reason=rate_limited` (RN-88). El orden dedup-antes-que-rate-limit garantiza que re-entregas legítimas no consuman presupuesto de rate (FIX-06). El backend SHALL agregar `received_at` con su propio reloj al consumir (RN-90). Un evento rechazado MUST recibir `XACK` (no se reintenta indefinidamente) y NO genera `event_ack`.

`detected_at` MUST normalizarse a UTC-aware antes del cálculo de clock skew. Si `detected_at` no es parseable → rechazar con `clock_skew` (`clock_skew.unparseable` en el log). Si es parseable pero fuera de rango → rechazar con `clock_skew` (`clock_skew.out_of_range` en el log). Si tiene tzinfo, se usa `astimezone(timezone.utc)`. Si no tiene tzinfo (naive), se asume UTC y se asigna `tzinfo=timezone.utc`.

`event_id` MUST ser una cadena no-vacía. Si es `None` o `""` → rechazar con `invalid_schema`.

#### Scenario: Rechazo por clock skew (out of range)
- **WHEN** llega un evento con `abs(received_at - detected_at)` mayor a 5 minutos
- **THEN** el backend NO persiste el `Event`
- **AND** inserta una fila en `rejected_events_audit` con `reason = clock_skew` y `payload_dump` truncado a 4 KB
- **AND** ejecuta `XACK` sobre la entrada

#### Scenario: Rechazo por detected_at no parseable
- **WHEN** llega un evento cuyo campo `detected_at` no es un ISO8601 válido
- **THEN** se inserta `rejected_events_audit` con `reason = clock_skew`
- **AND** el log emite `clock_skew.unparseable`
- **AND** ejecuta `XACK`

#### Scenario: detected_at naive se interpreta como UTC
- **WHEN** llega un evento con `detected_at` como datetime naive (sin tzinfo) dentro del rango de 5 minutos
- **THEN** el event se acepta (no hay TypeError al calcular el clock skew)

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

#### Scenario: Rechazo por agente desconocido
- **WHEN** llega un evento con un `agent_id` que no existe en la tabla `agents`
- **THEN** se inserta `rejected_events_audit` con `reason = unknown_agent`

---

### Requirement: Protocolo ACK end-to-end con persistencia y dedup idempotente

Tras pasar todas las validaciones, el consumer SHALL clasificar el resultado del procesamiento de cada mensaje del stream `events` mediante una taxonomía explícita y ejecutar `XACK` de forma **condicional** según el resultado (C8):

- **Éxito** (la ingesta retorna un `Event`): persistir el `Event` en PostgreSQL, ejecutar `XACK`, y publicar un mensaje `event_ack` en el stream `commands` con el `event_id` y `target_agent_id` igual al `agent_id` del evento (D5, RN-73, RN-106). El `event_ack` MUST ir firmado con `HMAC-SHA256(shared_secret, canonical_json(payload))` (RN-79).
- **Skip legítimo — re-entrega**: si `event_id` ya existe en DB (detectado en el paso de dedup, ANTES del rate limit), NO re-insertar el `Event`, ejecutar `XACK` y publicar `event_ack`. El presupuesto de rate limit NO se consume para re-entregas.
- **Skip legítimo — carrera en superseded sin pending activo**: cuando `mark_superseded` devuelve False y la re-consulta muestra que sigue habiendo un pending activo, el consumer ejecuta `XACK` sin insertar el evento.
- **Error de datos** (`InvalidTransitionError`): ejecutar `XACK` (el mensaje es inválido y no reintentable) y auditar el rechazo. No reintentar.
- **Error transitorio de base de datos** (`SQLAlchemyError`): NO ejecutar `XACK`. El mensaje MUST permanecer en la Pending Entries List (PEL) del consumer group para reintento automático. El consumer MUST loguear el error con `exc_info=True`.

#### Scenario: Evento válido persistido y confirmado
- **WHEN** llega un evento válido `e1` del agente `a1` que no existe en la base
- **THEN** el backend inserta el `Event`, ejecuta `XACK`, y publica `event_ack` en `commands` con `event_id = e1` y `target_agent_id = a1`
- **AND** el `event_ack` lleva una `signature` HMAC válida

#### Scenario: Re-entrega detectada en dedup no consume rate budget
- **WHEN** llega de nuevo el evento `e1` cuyo `event_id` ya está persistido en DB
- **THEN** el backend NO incrementa el contador de rate limit para el agente
- **AND** el backend NO inserta un segundo `Event` ni una fila en `rejected_events_audit`
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

---

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

---

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

---

### Requirement: Rate limiting 100 eventos/min por agent_id en el consumer

El consumer SHALL mantener un contador en memoria `dict[str, deque[float]]` (clave `agent_id`, valores timestamps UNIX) con ventana deslizante de 60 segundos. El check de rate limit se ejecuta DESPUÉS del dedup — re-entregas de eventos ya procesados NO consumen presupuesto de rate. Solo los eventos genuinamente nuevos (que superan el dedup) avanzan al check de rate. Si supera el límite: ejecutar `XACK`, insertar en `rejected_events_audit` con `reason=rate_limited`, y NO procesar el evento. El contador SHALL reiniciarse al reiniciar el backend (no persiste en Valkey). El módulo SHALL exponer `reset_rate_limiter()` para facilitar tests (RN-88, D7).

#### Scenario: Evento bajo límite pasa el rate check
- **WHEN** `agent_a1` envió 50 eventos en los últimos 60 segundos
- **AND** llega un nuevo evento de `agent_a1` que no existe en DB (no es re-entrega)
- **THEN** el evento pasa el rate check y continúa la validación normal

#### Scenario: Evento que supera límite es rechazado y auditado
- **WHEN** `agent_a1` envió 100 eventos en los últimos 60 segundos
- **AND** llega el evento 101 de `agent_a1` con un `event_id` nuevo (no re-entrega)
- **THEN** el consumer ejecuta `XACK`
- **AND** inserta en `rejected_events_audit` con `reason=rate_limited` y `agent_id='a1'`
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

#### Scenario: reset_rate_limiter limpia el estado
- **WHEN** se llama `reset_rate_limiter()`
- **THEN** todos los contadores quedan en cero
