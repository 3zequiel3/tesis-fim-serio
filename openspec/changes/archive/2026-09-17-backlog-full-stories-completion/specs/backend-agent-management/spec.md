## ADDED Requirements

### Requirement: El consumer de heartbeat persiste el flag de presión de cola

El consumer de heartbeat SHALL leer del payload el booleano `queue_pressure_high` y SHALL persistirlo en
el modelo `Agent` en una columna booleana **nullable**, agregada por la migración aditiva e idempotente
`021_add_agent_queue_pressure_high.sql` bajo la convención D3 (SQL plano en `backend/db/migrations/`, sin
Alembic, aplicada a mano). La migración MUST ser estrictamente aditiva: sin backfill, sin `DEFAULT` y sin
`NOT NULL`, porque no hay forma de reconstruir el flag de un heartbeat pasado y `NULL` es la respuesta
correcta para las filas existentes (D72/RN-166). El número `020` pertenece al change
`agent-scope-drop-observability`.

El valor SHALL tratarse con tolerancia hacia adelante, con el mismo criterio ya aplicado a
`discarded_events` (D37/RN-131) y a `out_of_scope_drops` (D69/RN-163): una clave ausente SHALL dejar el
valor guardado sin tocar, y un valor que no sea un booleano JSON SHALL ignorarse con un log en vez de
rechazar el heartbeat. En particular, los enteros `0` y `1` y las cadenas `"true"` y `"false"` SHALL
rechazarse: sólo `true` y `false` son valores válidos. Un flag malformado MUST NOT impedir que el resto
del heartbeat se procese.

La columna existente `queue_pressure` y su ingesta SHALL permanecer sin cambios.

`GET /agents` y `GET /agents/{id}` SHALL exponer el valor como `queue_pressure_high`. `null` SHALL
significar "el agente nunca reportó la clave" y SHALL ser distinguible de `false` (W3, RN-84, RN-92).

#### Scenario: El flag se persiste desde el heartbeat

- **WHEN** llega un heartbeat de `agent-01` con `queue_pressure: 0.85` y `queue_pressure_high: true`
- **THEN** el agente queda con `queue_pressure_high = true` y `queue_pressure = 0.85`, y los dos endpoints de agentes exponen ambos valores

#### Scenario: El flag en falso se persiste como falso

- **WHEN** llega un heartbeat de `agent-01` con `queue_pressure_high: false`, posterior a uno que reportó `true`
- **THEN** el valor guardado es `false`

#### Scenario: Una clave ausente no resetea el valor guardado

- **WHEN** llega un heartbeat sin la clave, de un agente que antes había reportado `true`
- **THEN** el valor guardado sigue siendo `true`

#### Scenario: Un valor que no es booleano se ignora sin romper el heartbeat

- **WHEN** llega un heartbeat cuyo `queue_pressure_high` es `1`, `"true"` o `null`
- **THEN** el valor guardado queda sin cambios y se registra un log de valor inválido para los dos primeros casos
- **AND** el resto del heartbeat se procesa normalmente y el agente queda `online`

#### Scenario: Un agente anterior a la clave se lee como nulo

- **WHEN** un agente nunca envió `queue_pressure_high`
- **THEN** los endpoints exponen `null`, distinto de `false`

#### Scenario: La migración es idempotente

- **WHEN** `021_add_agent_queue_pressure_high.sql` se aplica dos veces sobre la misma base
- **THEN** la segunda ejecución no produce error y la columna sigue siendo booleana y nullable
