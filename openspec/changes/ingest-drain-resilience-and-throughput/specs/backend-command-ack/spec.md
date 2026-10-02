## ADDED Requirements

### Requirement: El lector de command_ack recrea su group ante NOGROUP

El consumidor de `command_ack` SHALL invocar su `_ensure_group`, cuando una lectura del bucle
principal de `_reader_loop` (`XREADGROUP` con id `>` sobre el stream `event_ack`) falla con un
error cuyo mensaje contiene `NOGROUP`, dentro del mismo bucle; SHALL releer su PEL (`XREADGROUP`
con id `0`) y SHALL volver a leer entradas nuevas, sin requerir un reinicio del backend
(ampliación de D87/RN-181). El group `fim-command-ack` SHALL recrearse desde el id `0` y con
`MKSTREAM`, igual que al arrancar. El consumidor MUST loguear la recreación con un evento propio
(`command_ack_consumer.group_recreated`), distinto de `command_ack_consumer.loop_error`. Si la
recreación falla, MUST conservar el tratamiento actual: loguear, esperar 1 segundo y reintentar. El
barrido de timeout (`_sweep_loop`) MUST NOT verse afectado.

#### Scenario: Valkey vuelve sin el group de command_ack y el lector lo recrea
- **WHEN** el lector de `command_ack` está en su bucle principal
- **AND** la siguiente lectura `XREADGROUP` falla con `NOGROUP`
- **THEN** el lector recrea el group `fim-command-ack` desde `0`
- **AND** registra `command_ack_consumer.group_recreated`
- **AND** un `command_ack` publicado después de la recreación actualiza el `PublishedCommand` correspondiente sin reiniciar el backend

#### Scenario: Un error distinto de NOGROUP conserva el tratamiento actual
- **WHEN** la lectura del lector de `command_ack` falla con un error que no contiene `NOGROUP`
- **THEN** el lector loguea `command_ack_consumer.loop_error`, espera 1 segundo y reintenta
- **AND** no intenta recrear el group
