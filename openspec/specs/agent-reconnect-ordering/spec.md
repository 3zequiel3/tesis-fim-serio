## ADDED Requirements

### Requirement: Orden de arranque del Publisher — flush de comandos antes del drain de eventos

Al arrancar, el Publisher SHALL procesar los comandos pendientes del stream `commands` ANTES de drenar la cola de eventos encolados. El orden de arranque obligatorio es:

1. Leer `last_stream_command_id` del estado persistido (`"0-0"` si no existe).
2. Ejecutar el flush de comandos pendientes desde ese cursor.
3. Ejecutar `_drain_queue()` (publicar eventos encolados).
4. Arrancar el `_ack_listener` en background para comandos futuros.

`_drain_queue()` SHALL NOT iniciar hasta que el flush de comandos haya terminado. Este orden cierra el requisito de la Tabla 14 de la tesis y hace ejecutable RN-85.

#### Scenario: Drain no inicia hasta que el flush de comandos termina

- **WHEN** el Publisher arranca con comandos pendientes en el stream `commands` y eventos en la cola local
- **THEN** todos los comandos pendientes se aplican primero
- **AND** `_drain_queue()` no publica ningún evento encolado hasta que el flush de comandos haya retornado

#### Scenario: Comandos del flush verificados y filtrados como en operación normal

- **WHEN** el flush lee un mensaje del stream `commands`
- **THEN** el mensaje pasa por la verificación HMAC-SHA256 (RN-79) antes de cualquier side effect
- **AND** se filtra por `target_agent_id == agent_id` (D5, RN-106) antes de aplicarse
- **AND** un mensaje con firma inválida o destinado a otro agente no se aplica, pero el cursor avanza

### Requirement: Flush loop con timeout configurable

El flush de comandos pendientes SHALL ejecutar un loop `XREAD COUNT 100 BLOCK 0` desde el cursor guardado, aplicando cada comando, hasta que una ronda retorne vacío o hasta superar `command_flush_timeout_s` (configurable, default `2.0`). Si se supera el timeout, el agente SHALL continuar con el drain emitiendo una advertencia de log; el cursor queda apuntando al último mensaje procesado antes del timeout.

#### Scenario: Flush termina al vaciarse el stream

- **WHEN** el flush procesa todos los comandos pendientes y la siguiente ronda de `XREAD` retorna vacío
- **THEN** el flush termina y el control pasa a `_drain_queue()`
- **AND** `last_stream_command_id` apunta al último comando procesado

#### Scenario: Flush interrumpido por timeout

- **WHEN** el flush no logra alcanzar una ronda vacía antes de superar `command_flush_timeout_s`
- **THEN** el flush se interrumpe y el control pasa a `_drain_queue()`
- **AND** se emite una advertencia de log indicando el flush incompleto
- **AND** `last_stream_command_id` apunta al último mensaje procesado antes del timeout

#### Scenario: Stream sin comandos pendientes al arrancar

- **WHEN** el Publisher arranca y no hay comandos pendientes desde el cursor
- **THEN** la primera ronda de `XREAD` retorna vacío y el flush termina de inmediato
- **AND** el control pasa a `_drain_queue()` sin demora adicional
