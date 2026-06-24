## MODIFIED Requirements

### Requirement: Persistent state with atomic writes
El agente SHALL persistir `ruleset_version: int`, `last_stream_command_id: str` y `rules: list` en `/var/lib/fim-agent/state.json`. Al iniciar, si el archivo no existe, MUST usarse `ruleset_version: 0`, `last_stream_command_id: "0-0"` y `rules: []` como defaults. Toda escritura de `state.json` MUST pasar por un único punto de serialización que preserva los tres campos de forma no destructiva: actualizar un campo MUST NOT borrar los demás (F2). Cuando `RulesCache` persiste reglas, MUST delegar la escritura a ese punto único (vía `AgentState`) en lugar de escribir `state.json` por su cuenta. Las escrituras MUST ser atómicas: escribir a `.tmp` y luego `os.replace()` al path final. El archivo MUST tener permisos `0600` y owner `fim-agent`.

#### Scenario: Primera inicialización sin state.json
- **WHEN** el agente arranca y `/var/lib/fim-agent/state.json` no existe
- **THEN** el estado en memoria tiene `ruleset_version = 0`, `last_stream_command_id = "0-0"` y `rules = []`, y no se crea el archivo hasta la primera escritura

#### Scenario: Lectura de state existente
- **WHEN** `/var/lib/fim-agent/state.json` contiene `{"ruleset_version": 5, "last_stream_command_id": "100-0", "rules": [...]}`
- **THEN** el agente carga `ruleset_version = 5`, `last_stream_command_id = "100-0"` y las reglas al iniciar

#### Scenario: Persistir el cursor de comandos no borra las reglas
- **WHEN** el publisher procesa un comando y persiste un nuevo `last_stream_command_id`
- **THEN** `state.json` conserva el `rules` y el `ruleset_version` previos intactos

#### Scenario: Persistir reglas no borra el cursor de comandos
- **WHEN** `RulesCache` recibe un `rule_sync` y persiste nuevas reglas con un nuevo `ruleset_version`
- **THEN** `state.json` conserva el `last_stream_command_id` previo intacto

#### Scenario: Escritura atómica
- **WHEN** se actualiza cualquier campo del estado
- **THEN** el agente escribe a `state.json.tmp` y luego llama `os.replace("state.json.tmp", "state.json")`

#### Scenario: Permisos del archivo de estado
- **WHEN** `state.json` es creado por el agente
- **THEN** el archivo tiene permisos `0600` y owner `fim-agent`

## ADDED Requirements

### Requirement: El handler de shutdown propaga el flag al heartbeat

El handler de señal `SIGTERM`/`SIGINT` del agente SHALL llamar `publisher.set_shutdown(True)` antes de iniciar el drenaje de la cola y antes de activar el `stop_event`. Durante el drenaje el heartbeat MUST publicar `shutdown=true` en el stream `agent_heartbeat` para que el backend refleje que el agente está drenando (RN-93, G4).

#### Scenario: SIGTERM marca el publisher en shutdown

- **WHEN** el agente recibe `SIGTERM`
- **THEN** el handler llama `publisher.set_shutdown(True)` antes de drenar la cola y de activar `stop_event`

#### Scenario: Heartbeat publica shutdown durante el drenaje

- **WHEN** el agente está drenando la cola tras recibir `SIGTERM`
- **THEN** los heartbeats publicados durante el drenaje contienen `shutdown=true`

### Requirement: Configuración del intervalo de chequeo de renovación de certificado

`AgentConfig` SHALL exponer el campo `cert_renewal_check_interval_h: float` con default `24.0`, que define cada cuántas horas la tarea de renovación de certificado verifica la vigencia del certificado de cliente (RN-111, D13). Un valor ausente en el `config.yaml` MUST resolverse al default `24.0`.

#### Scenario: Default cuando no se especifica

- **WHEN** el `config.yaml` no define `cert_renewal_check_interval_h`
- **THEN** la configuración resuelve `cert_renewal_check_interval_h = 24.0`

#### Scenario: Valor explícito respetado

- **WHEN** el `config.yaml` define `cert_renewal_check_interval_h: 12.0`
- **THEN** la configuración resuelve `cert_renewal_check_interval_h = 12.0`

### Requirement: El loop principal arranca la tarea de renovación de certificado

El loop principal del agente SHALL registrar la tarea `_cert_renewal_loop` entre sus corrutinas cuando el agente ya está bootstrapped, pasándole el `stop_event` para permitir su terminación durante el shutdown. La tarea MUST coexistir con el publisher, el heartbeat y el detector sin bloquearlos (RN-111, D13, G3).

#### Scenario: Tarea registrada en el loop principal

- **WHEN** el agente arranca con certificados bootstrapped
- **THEN** `_cert_renewal_loop` se incluye entre las corrutinas pasadas a `asyncio.gather`

#### Scenario: La tarea termina al hacer shutdown

- **WHEN** el agente recibe `SIGTERM` y se activa el `stop_event`
- **THEN** la tarea de renovación de certificado termina sin bloquear el cierre del agente
