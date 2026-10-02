## ADDED Requirements

### Requirement: Valkey persiste con AOF en el compose base y en el override TLS

El servicio `valkey` SHALL arrancar con `--appendonly yes --appendfsync everysec` tanto en
`docker-compose.yml` como en `docker-compose.tls.yml` (D87/RN-181). Como el override TLS reemplaza
el `command` completo del servicio, los dos flags MUST repetirse ahí junto con los flags de TLS de
D53/RN-147. El archivo AOF SHALL residir en el volumen nombrado `valkey_data` montado en `/data`,
de modo que el stream `events`, sus consumer groups y sus PEL sobrevivan a un reinicio o a una
recreación del contenedor.

#### Scenario: El stream y el group sobreviven a un reinicio de Valkey
- **WHEN** el stream `events` tiene entradas y el group `fim-backend` existe
- **AND** se reinicia el contenedor `valkey` con `docker compose restart valkey`
- **THEN** después del reinicio `XLEN events` devuelve la misma cantidad de entradas
- **AND** `XINFO GROUPS events` sigue listando `fim-backend`

#### Scenario: El override TLS conserva AOF
- **WHEN** se levanta el stack con `docker-compose.yml` y `docker-compose.tls.yml`
- **THEN** `CONFIG GET appendonly` sobre Valkey devuelve `yes`
- **AND** `CONFIG GET appendfsync` devuelve `everysec`
- **AND** Valkey sigue escuchando sólo TLS en `6380`
