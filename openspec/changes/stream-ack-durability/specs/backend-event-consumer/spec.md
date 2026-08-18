## ADDED Requirements

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

## MODIFIED Requirements

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
