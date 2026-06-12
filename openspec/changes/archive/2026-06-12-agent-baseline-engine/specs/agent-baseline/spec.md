## ADDED Requirements

### Requirement: Baseline key derivation via HKDF-SHA256

El motor de baseline SHALL derivar su clave de cifrado de 256 bits con `HKDF-SHA256(ikm=master_secret, salt=agent_id, info="baseline-v1", length=32)`, donde `master_secret` son los 32 bytes raw leídos desde `/var/lib/fim-agent/secrets/master_secret` y `agent_id` es el identificador del agente codificado en UTF-8. La clave derivada MUST mantenerse únicamente en memoria y MUST NOT escribirse a disco ni emitirse en logs.

#### Scenario: Derivación determinística

- **WHEN** el motor deriva la clave dos veces con el mismo `master_secret` y el mismo `agent_id`
- **THEN** obtiene exactamente la misma clave de 32 bytes en ambas invocaciones

#### Scenario: Agentes distintos derivan claves distintas

- **WHEN** dos motores comparten el mismo `master_secret` pero tienen `agent_id` diferentes
- **THEN** las claves derivadas son distintas entre sí

#### Scenario: master_secret ausente

- **WHEN** el motor arranca y `/var/lib/fim-agent/secrets/master_secret` no existe o no tiene 32 bytes
- **THEN** el motor falla con un error claro y no continúa la inicialización del baseline

### Requirement: AES-256-GCM authenticated encryption per entry

Cada entrada de baseline SHALL persistirse cifrada con AES-256-GCM usando la clave derivada (HKDF). Cada escritura MUST generar un nonce GCM de 96 bits (12 bytes) único por archivo. El blob en disco MUST tener el layout `[1 byte version][12 bytes nonce][ciphertext con tag GCM de 16 bytes]`. El `path` del archivo MUST formar parte del plaintext autenticado por GCM.

#### Scenario: Cada escritura usa un nonce distinto

- **WHEN** la misma entrada se escribe dos veces
- **THEN** el nonce de 96 bits del segundo blob es distinto al del primero

#### Scenario: Round-trip de cifrado preserva el contenido

- **WHEN** se cifra el contenido de un archivo y luego se descifra con la misma clave
- **THEN** el contenido descifrado es idéntico al original byte a byte y su SHA-256 coincide con el hash registrado

#### Scenario: GCM autentica path y contenido

- **WHEN** un blob cifrado se mueve para suplantar la entrada de otro `path`
- **THEN** el descifrado falla la verificación de la etiqueta GCM y se trata como incidente de integridad

### Requirement: Initial baseline scan

El motor SHALL ejecutar un escaneo inicial en el primer arranque del agente, recorriendo todos los `watch_paths` configurados. Para cada archivo regular encontrado el motor MUST calcular el SHA-256 de su contenido claro, persistir una entrada de baseline cifrada con `status: present`, y registrar la metadata (path, hash, size, mode, uid, gid, mtime). Si un `watch_path` se agrega en runtime sin baseline previo, el motor MUST escanearlo de la misma forma.

#### Scenario: Primer arranque genera baseline cifrado

- **WHEN** el agente arranca por primera vez con `watch_paths` que contienen archivos regulares
- **THEN** existe un archivo de baseline cifrado por cada archivo escaneado, cada uno con permisos `0600`, y cada entrada tiene `status: present` y un hash SHA-256 no nulo

#### Scenario: No re-escanea si ya hay baseline

- **WHEN** el agente reinicia y ya existe baseline para todos los `watch_paths`
- **THEN** el motor no regenera las entradas existentes y conserva sus snapshots

#### Scenario: Path nuevo sin baseline previo

- **WHEN** se agrega un `watch_path` nuevo que no tiene entradas de baseline
- **THEN** el motor escanea solo ese path y genera sus entradas cifradas

### Requirement: Baseline present and absent states

Una entrada de baseline SHALL tener `status` con valor `present` o `absent` (minúsculas, snake_case). Cuando `status` es `present`, `hash` MUST ser el SHA-256 hex del contenido. Cuando `status` es `absent`, `hash` MUST ser `null` y la entrada MUST NOT contener contenido de archivo.

#### Scenario: Entrada present con hash

- **WHEN** el motor registra un archivo existente
- **THEN** la entrada tiene `status: present` y `hash` con el SHA-256 del contenido

#### Scenario: Marcar un path como absent

- **WHEN** el motor marca un path como ausente (un archivo que no debe existir)
- **THEN** la entrada tiene `status: absent`, `hash: null`, y no almacena contenido cifrado del archivo

### Requirement: Versioned snapshots with FIFO, gzip and deduplication

El motor SHALL mantener un máximo de 3 snapshots por archivo. Al agregar un snapshot cuyo hash sea idéntico al del último snapshot almacenado, el motor MUST NOT crear un nuevo snapshot (deduplicación). Cuando ya existen 3 snapshots, el más antiguo MUST eliminarse antes de almacenar el nuevo (FIFO). El snapshot activo (más reciente) MUST almacenarse sin comprimir; los snapshots no-activos MUST comprimirse con gzip antes del cifrado.

#### Scenario: Deduplicación por hash

- **WHEN** se intenta agregar un snapshot con el mismo hash que el último almacenado
- **THEN** el motor no agrega un nuevo snapshot y el conteo de snapshots no cambia

#### Scenario: Límite FIFO de 3 snapshots

- **WHEN** ya existen 3 snapshots para un archivo y se agrega uno nuevo con hash distinto
- **THEN** el snapshot más antiguo se elimina y quedan 3 snapshots, siendo el nuevo el activo

#### Scenario: Compresión de snapshots no-activos

- **WHEN** un snapshot deja de ser el activo porque se agregó uno más nuevo
- **THEN** el snapshot anterior queda comprimido con gzip y el snapshot activo permanece sin comprimir

### Requirement: Integrity verification on read

Al leer o verificar una entrada de baseline, el motor SHALL intentar descifrarla con AES-256-GCM. Si la verificación de la etiqueta GCM falla (el blob cifrado fue alterado en disco), el motor MUST NOT devolver datos descifrados; en su lugar MUST registrar un log de seguridad y señalar un incidente de integridad al caller (sin publicarlo por sí mismo, ya que el agente no tiene servidor HTTP ni transporte propio en este módulo).

#### Scenario: Lectura de entrada íntegra

- **WHEN** el motor lee una entrada de baseline no alterada
- **THEN** el descifrado tiene éxito y devuelve la metadata y el contenido correctos

#### Scenario: Lectura de entrada alterada

- **WHEN** el blob cifrado de una entrada fue modificado en disco (un byte cambiado en nonce, ciphertext o tag)
- **THEN** el descifrado falla la verificación GCM, no se devuelven datos, y el motor señala un incidente de integridad con el path afectado

### Requirement: Restricted filesystem permissions for baseline

Los archivos cifrados de baseline SHALL tener permisos `0600`. El directorio `/var/lib/fim-agent/baseline/` MUST tener permisos `0700`. Las escrituras MUST ser atómicas: crear el archivo temporal con `0600` desde su creación, escribir, sincronizar y luego `os.replace()` al path final, dentro del mismo directorio. El motor MUST verificar y asegurar `0700` en el directorio de baseline al iniciar.

#### Scenario: Permisos de archivo de baseline

- **WHEN** el motor escribe una entrada de baseline
- **THEN** el archivo resultante tiene permisos `0600` y el directorio `baseline/` tiene `0700`

#### Scenario: Escritura atómica sin ventana de permisos laxos

- **WHEN** el motor persiste una entrada
- **THEN** el archivo temporal se crea directamente con `0600` y se promueve con `os.replace()`, sin que el archivo exista en ningún momento con permisos más laxos
