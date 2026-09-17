## ADDED Requirements

### Requirement: El consumer de heartbeat persiste el contador de descartes fuera de scope

El consumer de heartbeat SHALL leer del payload el contador acumulativo de eventos descartados por
caer fuera de los `watch_paths` y SHALL persistirlo en el modelo `Agent` en una columna entera
**nullable**, agregada por una migración aditiva e idempotente bajo la convención D3 (SQL plano en
`backend/db/migrations/`, sin Alembic, aplicada a mano). La migración MUST ser estrictamente aditiva:
no hay backfill posible —no existe forma de reconstruir cuántos descartes acumuló un agente antes de
la columna— y `NULL` es la respuesta correcta para las filas existentes (D69/RN-163).

El valor SHALL tratarse con tolerancia hacia adelante, con el mismo criterio ya aplicado a
`queue_pressure`, `watch_path_status` y `discarded_events`: una clave ausente SHALL dejar el valor
guardado sin tocar en vez de resetearlo a cero, y un valor no numérico SHALL ignorarse con un log en
vez de rechazar el heartbeat. Un booleano SHALL rechazarse explícitamente como no numérico. Un
contador malformado MUST NOT impedir que el resto del heartbeat se procese.

`GET /agents` y `GET /agents/{id}` SHALL exponer el valor. `None` SHALL significar "el agente nunca
reportó la clave" y SHALL ser distinguible de `0`, que significa "reportó y no descartó nada": el
agente ya publica la clave en cada heartbeat, así que un nulo es información sobre el agente, no
sobre el filtro de scope (D69/RN-163, RN-04, RN-92).

#### Scenario: El contador se persiste desde el heartbeat

- **WHEN** llega un heartbeat de `agent-01` con un contador de descartes fuera de scope de 2748492
- **THEN** el valor guardado para `agent-01` es 2748492 y los dos endpoints de agentes lo exponen

#### Scenario: Una clave ausente no resetea el valor guardado

- **WHEN** llega un heartbeat sin la clave, de un agente que antes había reportado 2748492
- **THEN** el valor guardado sigue siendo 2748492

#### Scenario: Un valor no numérico se ignora sin romper el heartbeat

- **WHEN** llega un heartbeat cuyo contador de descartes fuera de scope no es numérico
- **THEN** el valor guardado queda sin cambios
- **AND** el resto del heartbeat se procesa normalmente y el agente queda `online`

#### Scenario: Un booleano se rechaza como no numérico

- **WHEN** llega un heartbeat cuyo contador de descartes fuera de scope es un booleano
- **THEN** el valor guardado queda sin cambios y se registra un log de valor inválido

#### Scenario: Un agente que nunca reportó se lee como nulo

- **WHEN** un agente nunca envió la clave
- **THEN** los endpoints exponen un valor nulo en vez de cero, distinguiendo "nunca reportó" de
  "reportó cero"
