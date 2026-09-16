## MODIFIED Requirements

### Requirement: Publisher de eventos firmados al stream events

El agente SHALL publicar cada evento encolado en el stream Valkey `events` mediante `agent/publisher.py`. El payload publicado MUST incluir `event_id` (UUID v4), `detected_at`, **`sent_at`**, `schema_version` (int) y los datos del cambio (path, hash, contexto de proceso), y MUST llevar un campo `signature` = `HMAC-SHA256(shared_secret, canonical_json(payload))` donde `canonical_json` serializa el payload sin el campo `signature` con `sort_keys=True` y separadores compactos (RN-56, RN-79, RN-91). El `shared_secret` SHALL leerse de `/var/lib/fim-agent/secrets/shared_secret`. El envío de la cola al reconectar MUST ser en orden FIFO por prefijo de timestamp del nombre (RN-39).

**`sent_at` y la firma se producen por transmisión, no por evento (D37 / RN-131).** El agente SHALL sellar `sent_at` con la hora UTC actual y firmar el payload **inmediatamente antes de cada `XADD`** — en la primera publicación, en cada reintento y en cada republicación durante el drenaje de cola. `sent_at` MUST quedar cubierto por la firma: un campo fuera del canonical JSON firmado podría ser re-sellado por un tercero que capture el mensaje, que es exactamente el replay que la ventana de skew existe para detectar. En consecuencia, el payload persistido en la cola NO lleva `signature` ni `sent_at`: ambos se calculan al transmitir. `detected_at` permanece en el payload persistido, sin alterar, como el timestamp forense del cambio observado.

#### Scenario: Evento publicado con firma HMAC válida
- **WHEN** el agente publica un evento `e1`
- **THEN** la entrada del stream `events` contiene `event_id`, `detected_at`, `sent_at`, `schema_version` y `signature`
- **AND** `signature` == `HMAC-SHA256(shared_secret, canonical_json(payload_sin_signature))`

#### Scenario: Dos transmisiones del mismo evento llevan sent_at distinto y ambas firmas válidas
- **WHEN** el agente publica `e1` y, sin recibir respuesta, lo republica más tarde
- **THEN** las dos entradas del stream llevan `sent_at` distinto
- **AND** cada una verifica con su propia firma contra el `shared_secret` del agente

#### Scenario: detected_at sobrevive intacto a la republicación
- **WHEN** un evento detectado durante un corte se drena horas después
- **THEN** su `detected_at` es el de la detección original y su `sent_at` es el del drenaje

#### Scenario: El payload en cola no lleva firma ni sent_at
- **WHEN** un evento se encola
- **THEN** el payload persistido contiene `event_id`, `detected_at`, `schema_version` y los datos del cambio, y no contiene `signature` ni `sent_at`

#### Scenario: Una rotación del shared_secret no invalida la cola existente
- **WHEN** se rota el `shared_secret` con eventos sin enviar en la cola
- **THEN** esos eventos se publican correctamente, firmados con el secreto nuevo

#### Scenario: Envío FIFO al reconectar
- **WHEN** la cola tiene eventos `e1` (t1) y `e2` (t2) con `t1 < t2` y se restablece la conexión con Valkey
- **THEN** el agente publica `e1` antes que `e2`

#### Scenario: Encolar cuando Valkey no está disponible
- **WHEN** el agente genera un evento y Valkey no responde
- **THEN** el evento queda persistido en la cola local y no se pierde

### Requirement: Borrado de cola solo tras event_ack bidireccional

El agente SHALL escuchar el stream `commands` filtrando por `target_agent_id IN (self.agent_id, null)` (D5, RN-106) y SHALL tratar la respuesta tipada del backend como la única autoridad sobre el destino de un evento encolado (D37 / RN-131):

- Al recibir un `event_ack` para un `event_id`, MUST borrar el archivo JSON correspondiente de la cola local (RN-40, RN-73).
- Al recibir un `event_nack` **sin** `retry_after` (terminal — motivos `invalid_schema` y `clock_skew`), MUST borrar el archivo de la cola, dejar de publicar el evento y registrarlo en el directorio local de descarte con el motivo del nack.
- Al recibir un `event_nack` **con** `retry_after` (motivo `rate_limited`), MUST **conservar** el evento en la cola, NO contar el intento y aplicar backpressure.

Si no recibe ninguna respuesta para un evento publicado dentro de 60 s, el agente MUST reintentar la publicación de ese evento (RN-40, RN-73); el backend deduplica por `event_id`. El reintento MUST estar acotado por el techo de intentos por evento: un evento sin respuesta de ningún tipo no puede reintentarse indefinidamente.

El agente MUST ignorar todo `event_ack` y `event_nack` cuyo `event_id` no corresponda a un evento presente en su cola local, logueando el hecho y sin ejecutar ninguna operación de archivo. Un `invalid_schema` se evalúa en el backend antes de verificar la firma del evento, de modo que un tercero puede inducir un nack firmado con un `event_id` de su elección; esta cláusula lo reduce a un log.

#### Scenario: Archivo borrado al recibir event_ack
- **WHEN** el agente recibe un `event_ack` con `event_id` `e1`
- **THEN** el agente borra el archivo `{t1_ms}_e1.json` de la cola local

#### Scenario: Nack terminal borra de la cola y archiva el descarte
- **WHEN** el agente recibe un `event_nack` para `e1` con motivo `clock_skew` y sin `retry_after`
- **THEN** el archivo de cola de `e1` se borra, `e1` deja de publicarse y existe un registro de descarte de `e1` con motivo `clock_skew`

#### Scenario: Nack de rate limit conserva el evento
- **WHEN** el agente recibe un `event_nack` para `e1` con motivo `rate_limited` y un `retry_after`
- **THEN** el archivo de cola de `e1` sigue existiendo y su contador de intentos no cambió

#### Scenario: Reintento si no llega respuesta en 60 s
- **WHEN** el agente publicó `e1` y no recibe ninguna respuesta para `e1` dentro de 60 s
- **THEN** el agente re-publica `e1` en el stream `events` con `sent_at` re-sellado
- **AND** el archivo de cola de `e1` permanece hasta recibir ack, nack terminal o agotar el techo de intentos

#### Scenario: Respuesta para un evento que el agente no tiene se ignora
- **WHEN** el agente recibe un `event_nack` con firma correcta para un `event_id` que no está en su cola local
- **THEN** no se borra ningún archivo, no se escribe ningún descarte y el backpressure no se altera

#### Scenario: Ack para otro agente es ignorado
- **WHEN** el agente recibe un mensaje en `commands` con `target_agent_id` distinto de su `agent_id` y distinto de null
- **THEN** el agente ignora el mensaje y no borra ningún archivo de cola

#### Scenario: Un tipo de mensaje desconocido no produce efecto
- **WHEN** el agente recibe un mensaje verificado en `commands` con un `type` que no reconoce
- **THEN** el agente no ejecuta ninguna operación sobre la cola ni sobre el estado del publicador

### Requirement: Heartbeat periódico al stream agent_heartbeat

El agente SHALL publicar en el stream `agent_heartbeat` cada 10 segundos vía `agent/heartbeat.py` un mensaje `{agent_id, timestamp, queue_size, ruleset_version, queue_pressure, shutdown, schema_version, discarded_events}` (RN-92). El campo `ruleset_version` SHALL leerse de `/var/lib/fim-agent/state.json`. El campo `discarded_events` SHALL ser el contador acumulativo de eventos que el agente descartó localmente desde el arranque del proceso, siguiendo el patrón del contador de drops del detector (D37 / RN-131). Durante el shutdown graceful (SIGTERM) el agente MUST publicar heartbeats con `shutdown: true` mientras drena la cola (RN-93).

#### Scenario: Heartbeat cada 10 segundos
- **WHEN** el agente está operativo
- **THEN** publica un mensaje en `agent_heartbeat` aproximadamente cada 10 segundos con `agent_id`, `timestamp`, `queue_size`, `ruleset_version`, `queue_pressure`, `shutdown` y `discarded_events`

#### Scenario: queue_pressure flag bajo presión
- **WHEN** el `queue_pressure` ratio supera 0.8
- **THEN** el heartbeat refleja la presión de cola para que el backend/UI la muestre como alerta

#### Scenario: discarded_events refleja los descartes locales
- **WHEN** el agente descartó tres eventos desde el arranque del proceso
- **THEN** el heartbeat lleva `discarded_events` igual a 3

#### Scenario: Heartbeat con shutdown durante drenaje
- **WHEN** el agente recibe SIGTERM y comienza a drenar la cola
- **THEN** los heartbeats publicados durante el drenaje llevan `shutdown: true`
