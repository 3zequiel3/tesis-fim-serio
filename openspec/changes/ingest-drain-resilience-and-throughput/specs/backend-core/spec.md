## ADDED Requirements

### Requirement: El cliente Valkey fija timeouts de socket y chequeo de salud de conexión

Los clientes Valkey del backend SHALL construirse —el sync de `init_valkey` y el async de
`build_async_valkey_client` (`backend/app/core/valkey.py`)— con
`socket_timeout`, `socket_connect_timeout` y `health_check_interval` explícitos (D87/RN-181). Los
tres valores SHALL salir de `Settings` con defaults, y el cliente MUST NOT construirse sin ellos.
`socket_timeout` MUST ser estrictamente mayor que el mayor `BLOCK` de las lecturas bloqueantes
(`XREADGROUP`/`XREAD`) que comparten el cliente async —hoy 2.000 ms en los consumers de eventos, de
heartbeat y de `command_ack`—, para que una espera normal sin mensajes no se convierta en un
timeout. Los timeouts SHALL aplicarse por igual a los esquemas en texto plano y TLS, sin alterar
los parámetros `ssl_*` de D17/RN-115.

#### Scenario: El cliente async se construye con los tres parámetros
- **WHEN** se invoca `build_async_valkey_client` con una URL `valkey://`
- **THEN** el cliente resultante tiene `socket_timeout`, `socket_connect_timeout` y `health_check_interval` iguales a los valores de `Settings`

#### Scenario: El cliente TLS conserva sus parámetros de mTLS
- **WHEN** se construye el cliente con una URL `valkeys://` y los certificados configurados
- **THEN** el cliente tiene los tres timeouts y además conserva `ssl_certfile`, `ssl_keyfile`, `ssl_ca_certs` y `ssl_check_hostname=True`

#### Scenario: Una lectura bloqueante sin mensajes no dispara timeout
- **WHEN** un consumer ejecuta `XREADGROUP` con `BLOCK` de 2.000 ms sobre un stream sin entradas nuevas
- **THEN** la llamada retorna vacía sin lanzar un error de timeout de socket

#### Scenario: Una conexión a un Valkey inalcanzable falla acotada en el tiempo
- **WHEN** el cliente intenta conectarse a un Valkey que no acepta conexiones
- **THEN** el intento falla en un tiempo no mayor que `socket_connect_timeout` más un margen de planificación
