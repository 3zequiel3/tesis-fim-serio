# Spec: backend-event-consumer

Capability: Consumers del backend para los streams `events` y `agent_heartbeat` — validación (schema, HMAC, clock skew), persistencia, protocolo ACK end-to-end y transiciones de estado de agente por heartbeat.

---

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

Tras pasar todas las validaciones, el consumer SHALL persistir el `Event` en PostgreSQL, ejecutar `XACK` sobre la entrada del stream `events`, y publicar un mensaje `event_ack` en el stream `commands` con el `event_id` y `target_agent_id` igual al `agent_id` del evento (D5, RN-73, RN-106). El `event_ack` MUST ir firmado con `HMAC-SHA256(shared_secret, canonical_json(payload))` (RN-79). El consumer MUST deduplicar por `event_id`: si el `event_id` ya está persistido, NO re-inserta el `Event` ni audita un rechazo, pero igualmente ejecuta `XACK` y publica `event_ack` (re-entrega legítima at-least-once, RN-73).

#### Scenario: Evento válido persistido y confirmado
- **WHEN** llega un evento válido `e1` del agente `a1` que no existe en la base
- **THEN** el backend inserta el `Event`, ejecuta `XACK`, y publica `event_ack` en `commands` con `event_id = e1` y `target_agent_id = a1`
- **AND** el `event_ack` lleva una `signature` HMAC válida

#### Scenario: Re-entrega de un evento ya persistido
- **WHEN** llega de nuevo el evento `e1` cuyo `event_id` ya está persistido
- **THEN** el backend NO inserta un segundo `Event` ni una fila en `rejected_events_audit`
- **AND** ejecuta `XACK` y vuelve a publicar `event_ack` para `e1`

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
