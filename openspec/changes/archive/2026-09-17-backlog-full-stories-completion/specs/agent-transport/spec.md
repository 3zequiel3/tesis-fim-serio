## MODIFIED Requirements

### Requirement: Heartbeat periódico al stream agent_heartbeat

El agente SHALL publicar en el stream `agent_heartbeat` cada 10 segundos vía `agent/heartbeat.py` un mensaje `{agent_id, timestamp, queue_size, ruleset_version, queue_pressure, queue_pressure_high, shutdown, schema_version, discarded_events}` (RN-92). El campo `ruleset_version` SHALL leerse de `/var/lib/fim-agent/state.json`. El campo `discarded_events` SHALL ser el contador acumulativo de eventos que el agente descartó localmente desde el arranque del proceso, siguiendo el patrón del contador de drops del detector (D37 / RN-131). Durante el shutdown graceful (SIGTERM) el agente MUST publicar heartbeats con `shutdown: true` mientras drena la cola (RN-93).

El campo `queue_pressure` SHALL conservarse como ratio float entre 0 y 1. El campo `queue_pressure_high` SHALL ser un booleano calculado por el agente: `true` cuando `queue_pressure` supera 0,8 (más del 80 % del límite de 100 MB de la cola offline, W3, RN-84) y `false` en caso contrario. Los dos campos SHALL derivarse de **una misma lectura** del ratio dentro de cada publicación, de modo que un heartbeat nunca lleve un flag incoherente con su propio ratio. El umbral SHALL definirse una sola vez en el agente y no repetirse como literal (D72/RN-166).

#### Scenario: Heartbeat cada 10 segundos
- **WHEN** el agente está operativo
- **THEN** publica un mensaje en `agent_heartbeat` aproximadamente cada 10 segundos con `agent_id`, `timestamp`, `queue_size`, `ruleset_version`, `queue_pressure`, `queue_pressure_high`, `shutdown` y `discarded_events`

#### Scenario: queue_pressure flag bajo presión
- **WHEN** el `queue_pressure` ratio supera 0.8
- **THEN** el heartbeat lleva `queue_pressure_high: true` y conserva el ratio en `queue_pressure`

#### Scenario: Sin presión el flag es falso
- **WHEN** el `queue_pressure` ratio es 0.8 o menor
- **THEN** el heartbeat lleva `queue_pressure_high: false`

#### Scenario: El umbral es estricto
- **WHEN** el `queue_pressure` ratio es exactamente 0.8
- **THEN** el heartbeat lleva `queue_pressure_high: false`

#### Scenario: El flag es un booleano del payload firmado
- **WHEN** el agente publica un heartbeat con `shared_secret` configurado
- **THEN** `queue_pressure_high` es de tipo booleano JSON y forma parte del payload sobre el que se calcula la firma HMAC

#### Scenario: discarded_events refleja los descartes locales
- **WHEN** el agente descartó tres eventos desde el arranque del proceso
- **THEN** el heartbeat lleva `discarded_events` igual a 3

#### Scenario: Heartbeat con shutdown durante drenaje
- **WHEN** el agente recibe SIGTERM y comienza a drenar la cola
- **THEN** los heartbeats publicados durante el drenaje llevan `shutdown: true`
