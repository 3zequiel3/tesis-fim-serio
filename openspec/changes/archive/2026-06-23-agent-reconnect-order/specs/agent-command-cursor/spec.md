## ADDED Requirements

### Requirement: Cursor del stream commands persistido en AgentState

El agente SHALL persistir el último `stream_id` procesado con éxito del stream `commands` en `AgentState`, campo `last_stream_command_id` (`str`, default `"0-0"`). El cursor SHALL serializarse en `state.json` junto con el resto del estado y cargarse al arrancar.

#### Scenario: Primer arranque sin state.json

- **WHEN** el agente arranca y no existe `state.json` (o el archivo no contiene `last_stream_command_id`)
- **THEN** `AgentState.last_stream_command_id` vale `"0-0"`
- **AND** el `XREAD` posterior arranca desde el origen del stream, entregando todos los mensajes existentes

#### Scenario: Cursor cargado desde estado previo

- **WHEN** el agente arranca y `state.json` contiene `last_stream_command_id: "1718000000000-0"`
- **THEN** `load_state` retorna un `AgentState` con `last_stream_command_id == "1718000000000-0"`
- **AND** el `XREAD` arranca desde ese cursor, no desde `"$"`

#### Scenario: Cursor actualizado en disco tras cada mensaje procesado

- **WHEN** el agente procesa con éxito un mensaje del stream `commands` con id `msg_id`
- **THEN** `AgentState.last_stream_command_id` pasa a valer `msg_id`
- **AND** el nuevo valor se persiste en `state.json` (escritura atómica vía archivo temporal + `os.replace`, permisos `0o600`)

#### Scenario: Recuperación de comandos emitidos durante downtime

- **WHEN** el backend emitió comandos al stream `commands` mientras el agente estaba caído
- **AND** el agente arranca con `last_stream_command_id` apuntando a un id previo a esos comandos
- **THEN** el agente lee y aplica esos comandos pendientes desde el cursor persistido (cierra el gap de RN-85)
