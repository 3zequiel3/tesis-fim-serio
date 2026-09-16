## MODIFIED Requirements

### Requirement: Fan-out de rule_sync firmado por agente

En cada escritura exitosa (crear, actualizar, eliminar) el sistema SHALL publicar el comando `rule_sync` al stream Valkey `commands` mediante fan-out: un mensaje físico por cada agente registrado con `shared_secret_hex` no nulo (D9, RN-58, RN-79). Cada mensaje MUST llevar `target_agent_id = agent.agent_id`, el `ruleset_version` recién incrementado, `schema_version`, y MUST estar firmado HMAC-SHA256 con el `shared_secret_hex` específico de ese agente. El léxico del payload MUST ser snake_case (RN-71). El `target_agent_id` MUST llevar siempre el id explícito del agente (nunca null para `rule_sync`).

La publicación MUST ser resiliente a una caída de Valkey mediante un patrón outbox: el comando (o los comandos de fan-out) MUST persistirse de forma durable en la misma transacción de DB que avanza el `ruleset_version`, ANTES de intentar la publicación al stream. La publicación efectiva al stream MUST ejecutarse de forma diferida (background task) con reintentos, de modo que si Valkey está caído en el momento de la escritura la versión avanza pero el comando queda pendiente y se entrega cuando Valkey se recupera. Un fallo de publicación a Valkey MUST NOT perder el comando ni dejar la versión avanzada sin comando entregable (RN-79, RN-123).

#### Scenario: Fan-out a varios agentes
- **WHEN** hay dos agentes registrados con secret y un admin crea una regla
- **THEN** el sistema publica dos mensajes `rule_sync` en el stream `commands`, uno por agente
- **AND** cada mensaje lleva `target_agent_id` del agente correspondiente y firma válida con su `shared_secret_hex`
- **AND** ambos mensajes llevan el mismo `ruleset_version`

#### Scenario: Firma verificable por el agente
- **WHEN** se publica un `rule_sync` para un agente
- **THEN** la firma `signature` del payload es válida bajo `verify_payload` con el `shared_secret_hex` de ese agente

#### Scenario: Sin agentes registrados
- **WHEN** no hay agentes con `shared_secret_hex` y un admin crea una regla
- **THEN** el sistema incrementa el counter pero no publica ningún mensaje ni inserta comando pendiente
- **AND** la operación retorna éxito

#### Scenario: Valkey caído al crear la regla — comando reentregado al recuperarse
- **WHEN** un admin crea una regla mientras Valkey está caído
- **THEN** la transacción de DB commitea la `Rule` y el `ruleset_version` incrementado junto con el comando pendiente persistido
- **AND** la respuesta HTTP no falla por la indisponibilidad de Valkey
- **AND** cuando Valkey se recupera, el background task publica el/los mensaje(s) `rule_sync` pendientes al stream `commands` sin intervención manual

#### Scenario: Fallo transitorio de publicación reintentado
- **WHEN** la primera publicación al stream falla por un error transitorio de Valkey
- **THEN** el comando pendiente permanece durable y se reintenta hasta que la publicación tiene éxito, sin duplicar la fila de comando persistida

## ADDED Requirements

### Requirement: Incremento atómico de ruleset_version bajo concurrencia

El incremento del contador global `ruleset_version` (D5) MUST ser atómico frente a requests concurrentes. El sistema MUST usar una única sentencia atómica del tipo `UPDATE ruleset_versions SET version = version + 1 RETURNING version` (o `SELECT ... FOR UPDATE` equivalente) en lugar de un patrón lee-modifica-escribe (`SELECT` + `version += 1` + `flush`) sin bloqueo. No MUST existir más de una implementación del incremento en el código: la lógica MUST estar unificada en una única función reutilizada por `rules/service.py` y `actions/service.py`.

#### Scenario: Dos incrementos concurrentes no se pisan
- **WHEN** dos requests incrementan `ruleset_version` de forma concurrente partiendo de la versión N
- **THEN** una obtiene N+1 y la otra obtiene N+2
- **AND** ningún incremento se pierde (la versión final es N+2, nunca N+1)

#### Scenario: Implementación única compartida
- **WHEN** tanto el flujo de reglas como el de acciones necesitan avanzar la versión
- **THEN** ambos invocan la misma función de incremento atómico, sin duplicar la lógica de lee-modifica-escribe
