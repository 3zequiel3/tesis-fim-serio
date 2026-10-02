## ADDED Requirements

### Requirement: Formato envuelto del secreto compartido del agente (D86/RN-180)

El valor persistido en `agents.shared_secret_hex` para todo agente bootstrapeado SHALL tener el formato
`v1:<payload>`, donde `<payload>` es la codificación base64url sin relleno de `nonce ‖ ciphertext ‖
tag`, producida con AES-256-GCM sobre los 32 bytes del secreto compartido. El `nonce` SHALL ser de
12 bytes, aleatorio y nuevo en cada envoltura. El dato asociado (AAD) SHALL ser el `agent_id` del
agente codificado en UTF-8, de modo que un valor envuelto para un agente MUST NOT descifrar bajo el
`agent_id` de otro. El backend MUST NOT persistir el secreto compartido en claro.

#### Scenario: El secreto no queda en claro en la base
- **WHEN** un agente completa el bootstrap y se lee `agents.shared_secret_hex` directamente de la base
- **THEN** el valor empieza con `v1:`
- **AND** no contiene el hex del secreto devuelto al agente en `AgentBootstrapResponse.shared_secret_hex`

#### Scenario: Dos envolturas del mismo secreto difieren
- **WHEN** se envuelve dos veces el mismo secreto para el mismo `agent_id`
- **THEN** los dos valores persistidos son distintos (nonce distinto)
- **AND** ambos se desenvuelven al mismo secreto

#### Scenario: Un AAD distinto falla la verificación
- **WHEN** un valor envuelto para `agent-a` se desenvuelve con `agent_id = agent-b`
- **THEN** el helper lanza su excepción de desenvoltura y no devuelve ningún byte

#### Scenario: Un valor alterado falla la verificación
- **WHEN** se modifica un solo carácter del payload de un valor `v1:`
- **THEN** el helper lanza su excepción de desenvoltura

### Requirement: Helper único de lectura del secreto compartido (D86/RN-180)

El backend SHALL exponer un único helper `unwrap_agent_secret(agent_id: str, stored: str) -> bytes` y
todo sitio que reconstruye el secreto compartido desde `Agent.shared_secret_hex` SHALL usarlo; ningún
módulo fuera del helper MUST invocar `bytes.fromhex` sobre esa columna. Los sitios cubiertos son:
`_get_agent_auth` (`events/consumer.py`), `_get_shared_secret` (`agents/command_ack_consumer.py`),
`_get_agent_secret` (`agents/streams.py`), `_get_agent_secret` (`actions/streams.py`), la verificación
HMAC de `heartbeat_consumer.py` y `publish_rule_sync` (`rules/service.py`).

Toda falla de desenvoltura (prefijo desconocido, base64 inválido, tag inválido, longitud distinta de
32 bytes, hex heredado inválido) SHALL lanzar una excepción que herede de `ValueError`, para que cada
sitio conserve su semántica de error actual: los que capturan `ValueError` siguen devolviendo `None` o
descartando el mensaje; los que lo propagan siguen revirtiendo la transacción (D37/RN-131). El mensaje
de la excepción y los logs MUST NOT contener material del secreto ni de la clave.

#### Scenario: Los seis sitios usan el helper
- **WHEN** se busca `bytes.fromhex` aplicado a `shared_secret_hex` en `backend/app/`
- **THEN** la única ocurrencia está dentro del helper

#### Scenario: Ingesta con secreto envuelto
- **WHEN** el consumer de eventos recibe un evento firmado por un agente cuyo secreto está envuelto
- **THEN** la firma HMAC verifica y el evento se ingesta como antes

#### Scenario: Falla de desenvoltura en un sitio que propaga
- **WHEN** `_get_agent_secret` de `actions/streams.py` recibe un valor que no desenvuelve
- **THEN** la excepción se propaga y la transacción del caller se revierte, igual que con un hex inválido hoy

#### Scenario: Falla de desenvoltura en un sitio que captura
- **WHEN** la verificación de heartbeat recibe un valor que no desenvuelve
- **THEN** el heartbeat se descarta con un log de error y el estado del agente no se actualiza

### Requirement: El hex heredado sigue siendo legible (D86/RN-180)

Un valor de `shared_secret_hex` sin el prefijo `v1:` SHALL interpretarse como el formato heredado:
hex en claro, decodificado con la misma regla que hoy. Un valor con un prefijo de versión distinto de
`v1:` (cualquier cadena que contenga `:`) MUST fallar cerrado con la excepción de desenvoltura, sin
intentar interpretarlo como hex.

#### Scenario: Valor heredado en hex
- **WHEN** `Agent.shared_secret_hex` contiene un hex de 64 caracteres sin prefijo
- **THEN** el helper devuelve los 32 bytes correspondientes
- **AND** la verificación HMAC de un mensaje firmado con ese secreto pasa

#### Scenario: Prefijo de versión desconocido
- **WHEN** `Agent.shared_secret_hex` contiene `v2:` seguido de cualquier payload
- **THEN** el helper lanza su excepción de desenvoltura

### Requirement: Migración de datos que envuelve los secretos existentes (D86/RN-180)

El lifespan SHALL envolver, en cada arranque, después de `create_all` y `seed_admin` y **antes** de
arrancar los consumers, toda fila de `agents` con `shared_secret_hex` no nulo y sin prefijo `v1:`,
usando el `agent_id` de esa fila como AAD, en una única transacción. La migración SHALL ser
idempotente: una fila ya envuelta MUST NOT reescribirse. SHALL emitir un log `info` con la cantidad de
filas envueltas, sin material de secreto. Una fila heredada cuyo valor no es hex válido —ya hoy
ilegible para los seis sitios de lectura— SHALL dejarse intacta y reportarse con un log `error` que
nombre el `agent_id`, sin abortar el arranque: una fila corrupta no debe dejar sin backend a todos los
agentes sanos.

#### Scenario: Envuelve los valores existentes
- **WHEN** la base contiene tres agentes con secreto en hex heredado y uno con secreto `NULL`
- **THEN** tras el arranque los tres valores empiezan con `v1:` y el cuarto sigue `NULL`
- **AND** cada uno se desenvuelve al mismo secreto que contenía antes

#### Scenario: Idempotente
- **WHEN** el backend arranca dos veces sobre la misma base
- **THEN** el segundo arranque reporta cero filas envueltas y ningún valor cambia

#### Scenario: Hex heredado inválido
- **WHEN** una fila contiene un `shared_secret_hex` sin prefijo que no es hex válido
- **THEN** el arranque continúa y esa fila queda sin modificar
- **AND** se emite un log de error que nombra su `agent_id`
- **AND** las demás filas heredadas quedan envueltas

### Requirement: Carga de la clave de envoltura y falla explícita del arranque (D86/RN-180)

La clave de envoltura SHALL leerse de la ruta indicada por el setting `agent_secret_wrap_key_path`
(variable `AGENT_SECRET_WRAP_KEY_PATH`) y SHALL tener exactamente 32 bytes. El lifespan SHALL cargarla
y validarla **antes** de cualquier acceso a la base. Si la ruta está vacía, el archivo no existe, no es
legible o su longitud no es 32 bytes, el arranque MUST abortar con una excepción y un log `error`
`backend.agent_secret_wrap_key.invalid` que nombren la ruta y la causa, sin el contenido del archivo.
La validación MUST NOT ejecutarse en la construcción de `Settings`, porque `certs-init` importa la
configuración antes de que la clave exista. Si el archivo tiene permisos más laxos que `0400`/`0600`
(cualquier bit de `0o177` encendido), el arranque MUST abortar con la causa `permissive_mode`.

El backend MUST NOT generar la clave por sí mismo: una clave nueva haría ilegibles todos los secretos
ya envueltos con la anterior.

#### Scenario: Archivo de clave ausente
- **WHEN** el backend arranca con `AGENT_SECRET_WRAP_KEY_PATH` apuntando a un archivo inexistente
- **THEN** el lifespan aborta antes de ejecutar `create_all`
- **AND** el log de error nombra la ruta y la causa `missing`

#### Scenario: Setting vacío
- **WHEN** el backend arranca sin `AGENT_SECRET_WRAP_KEY_PATH`
- **THEN** el lifespan aborta con un log de error de causa `not_configured`

#### Scenario: Longitud incorrecta
- **WHEN** el archivo de clave tiene 31 o 33 bytes
- **THEN** el lifespan aborta con un log de error de causa `invalid_length`

#### Scenario: Permisos laxos
- **WHEN** el archivo de clave tiene 32 bytes y modo `0640` o `0644`
- **THEN** el lifespan aborta antes de ejecutar `create_all` con un log de error de causa `permissive_mode`

#### Scenario: Permisos aceptados
- **WHEN** el archivo de clave tiene 32 bytes y modo `0400` o `0600`
- **THEN** el lifespan carga la clave y continúa

#### Scenario: Importar la configuración no exige la clave
- **WHEN** `certs-init` importa `app.core.config` sin que el archivo de clave exista
- **THEN** la importación no falla

### Requirement: Generación idempotente de la clave por `certs-init` (D86/RN-180)

`certs-init` SHALL asegurar la clave de envoltura en la ruta `AGENT_SECRET_WRAP_KEY_PATH`: si el
archivo no existe, SHALL crearlo de forma exclusiva (`O_CREAT | O_EXCL`) con 32 bytes de un generador
criptográfico, modo `0400` y dueño `10001:10001`; si existe y tiene 32 bytes, MUST NOT reescribirlo; si
existe con otra longitud, SHALL terminar con exit distinto de 0 nombrando la ruta, sin modificarlo.

#### Scenario: Primer arranque
- **WHEN** `certs-init` corre con el volumen de secretos vacío
- **THEN** existe el archivo de clave con 32 bytes, modo `0400` y dueño `10001`

#### Scenario: Segundo arranque
- **WHEN** `certs-init` corre por segunda vez
- **THEN** el archivo de clave queda byte a byte idéntico

#### Scenario: Clave existente corrupta
- **WHEN** el archivo de clave existe con una longitud distinta de 32 bytes
- **THEN** `certs-init` termina con exit distinto de 0 y el archivo no se modifica
