## ADDED Requirements

### Requirement: Cola offline atómica con límite y política drop-oldest

El agente SHALL persistir cada evento a publicar como archivo JSON en `/var/lib/fim-agent/queue/` con nombre `{detected_at_epoch_ms}_{event_id}.json`, usando escritura atómica: escribir a un archivo `.tmp` y luego `os.replace()` al nombre final (RN-38, RN-41). El módulo `agent/queue.py` SHALL imponer un límite total de 100 MB sobre el directorio con política drop-oldest: antes de encolar, si la operación excedería el límite, MUST borrar los archivos más antiguos (por prefijo de timestamp del nombre) hasta liberar espacio (RN-84). El agente SHALL exponer `queue_size` (cantidad de archivos) y `queue_pressure` (ratio `used_bytes / 100MB`, float entre 0 y 1).

#### Scenario: Escritura atómica de un evento encolado
- **WHEN** el agente encola un evento con `event_id` `e1` y `detected_at` `t1`
- **THEN** primero escribe `{t1_ms}_e1.json.tmp` y luego ejecuta `os.replace()` al nombre `{t1_ms}_e1.json`
- **AND** nunca queda un archivo `.json` (sin sufijo `.tmp`) parcialmente escrito

#### Scenario: Drop-oldest al superar 100 MB
- **WHEN** el directorio de cola está en 100 MB y se intenta encolar un evento nuevo
- **THEN** el agente borra los archivos JSON más antiguos (menor prefijo de timestamp) hasta que el evento nuevo entre dentro del límite
- **AND** el evento nuevo queda persistido

#### Scenario: queue_pressure refleja el uso
- **WHEN** la cola usa 85 MB de los 100 MB permitidos
- **THEN** `queue_pressure` reporta aproximadamente `0.85`

#### Scenario: Limpieza de .tmp huérfanos al arrancar
- **WHEN** el agente arranca y existe un archivo `.tmp` residual de un crash previo
- **THEN** el agente borra los `.tmp` huérfanos antes de procesar la cola

### Requirement: Publisher de eventos firmados al stream events

El agente SHALL publicar cada evento encolado en el stream Valkey `events` mediante `agent/publisher.py`. El payload publicado MUST incluir `event_id` (UUID v4), `detected_at`, `schema_version` (int) y los datos del cambio (path, hash, contexto de proceso), y MUST llevar un campo `signature` = `HMAC-SHA256(shared_secret, canonical_json(payload))` donde `canonical_json` serializa el payload sin el campo `signature` con `sort_keys=True` y separadores compactos (RN-56, RN-79, RN-91). El `shared_secret` SHALL leerse de `/var/lib/fim-agent/secrets/shared_secret`. El envío de la cola al reconectar MUST ser en orden FIFO por prefijo de timestamp del nombre (RN-39).

#### Scenario: Evento publicado con firma HMAC válida
- **WHEN** el agente publica un evento `e1`
- **THEN** la entrada del stream `events` contiene `event_id`, `detected_at`, `schema_version` y `signature`
- **AND** `signature` == `HMAC-SHA256(shared_secret, canonical_json(payload_sin_signature))`

#### Scenario: Envío FIFO al reconectar
- **WHEN** la cola tiene eventos `e1` (t1) y `e2` (t2) con `t1 < t2` y se restablece la conexión con Valkey
- **THEN** el agente publica `e1` antes que `e2`

#### Scenario: Encolar cuando Valkey no está disponible
- **WHEN** el agente genera un evento y Valkey no responde
- **THEN** el evento queda persistido en la cola local y no se pierde

### Requirement: Borrado de cola solo tras event_ack bidireccional

El agente SHALL escuchar el stream `commands` filtrando por `target_agent_id IN (self.agent_id, null)` (D5, RN-106) y, al recibir un `event_ack` para un `event_id`, MUST borrar el archivo JSON correspondiente de la cola local (RN-40, RN-73). Si no recibe `event_ack` para un evento publicado dentro de 60 s, el agente MUST reintentar la publicación de ese evento (RN-40, RN-73); el backend deduplica por `event_id`.

#### Scenario: Archivo borrado al recibir event_ack
- **WHEN** el agente recibe un `event_ack` con `event_id` `e1`
- **THEN** el agente borra el archivo `{t1_ms}_e1.json` de la cola local

#### Scenario: Reintento si no llega ack en 60 s
- **WHEN** el agente publicó `e1` y no recibe `event_ack` para `e1` dentro de 60 s
- **THEN** el agente re-publica `e1` en el stream `events`
- **AND** el archivo de cola de `e1` permanece hasta recibir el ack

#### Scenario: Ack para otro agente es ignorado
- **WHEN** el agente recibe un mensaje en `commands` con `target_agent_id` distinto de su `agent_id` y distinto de null
- **THEN** el agente ignora el mensaje y no borra ningún archivo de cola

### Requirement: Heartbeat periódico al stream agent_heartbeat

El agente SHALL publicar en el stream `agent_heartbeat` cada 10 segundos vía `agent/heartbeat.py` un mensaje `{agent_id, timestamp, queue_size, ruleset_version, queue_pressure, shutdown, schema_version}` (RN-92). El campo `ruleset_version` SHALL leerse de `/var/lib/fim-agent/state.json`. Durante el shutdown graceful (SIGTERM) el agente MUST publicar heartbeats con `shutdown: true` mientras drena la cola (RN-93).

#### Scenario: Heartbeat cada 10 segundos
- **WHEN** el agente está operativo
- **THEN** publica un mensaje en `agent_heartbeat` aproximadamente cada 10 segundos con `agent_id`, `timestamp`, `queue_size`, `ruleset_version`, `queue_pressure` y `shutdown`

#### Scenario: queue_pressure flag bajo presión
- **WHEN** el `queue_pressure` ratio supera 0.8
- **THEN** el heartbeat refleja la presión de cola para que el backend/UI la muestre como alerta

#### Scenario: Heartbeat con shutdown durante drenaje
- **WHEN** el agente recibe SIGTERM y comienza a drenar la cola
- **THEN** los heartbeats publicados durante el drenaje llevan `shutdown: true`

### Requirement: Sin servidor HTTP en el agente

El agente NO SHALL exponer servidor HTTP, gRPC ni ningún listener TCP para el transporte (D8, RN-108). Toda comunicación con el backend MUST viajar por los streams Valkey `events`, `agent_heartbeat` y `commands`.

#### Scenario: El agente no abre puertos de escucha
- **WHEN** el agente está corriendo el loop de transporte
- **THEN** no hay ningún socket TCP en estado LISTEN abierto por el proceso del agente
