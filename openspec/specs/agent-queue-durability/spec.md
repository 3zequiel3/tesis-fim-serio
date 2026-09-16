# agent-queue-durability Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: FIFO ordering survives variable-length timestamps

The offline event queue SHALL order its files chronologically regardless of the number of digits in the epoch-millisecond timestamp. The file name MUST encode the timestamp zero-padded to a fixed width of 16 digits (`{detected_at_ms:016d}_{event_id}.json`) so that a lexicographic sort of file names is equivalent to a chronological sort. This enforces FIFO drain order (RN-39).

#### Scenario: Timestamps of different digit length sort chronologically
- **WHEN** the queue contains one event with a 12-digit timestamp and one with a 13-digit timestamp
- **THEN** the file whose timestamp is chronologically older sorts first in `_json_files`, independent of digit count

#### Scenario: FIFO drain returns oldest first
- **WHEN** events are enqueued out of timestamp order and then drained
- **THEN** they are returned oldest-timestamp-first

### Requirement: drop-oldest removes the chronologically oldest event

When enqueuing an event would exceed the 100 MB queue limit, the queue SHALL delete the chronologically oldest event(s) until the new event fits (RN-84). The deletion MUST target the file with the smallest timestamp, never the newest.

#### Scenario: Eviction under pressure deletes the oldest event
- **WHEN** the queue is at capacity and a new event is enqueued
- **THEN** the event with the smallest (oldest) timestamp is unlinked, and the newest events are retained

#### Scenario: Eviction with mixed-length legacy and padded names
- **WHEN** the queue holds both legacy (non-padded) and new (16-digit padded) file names and eviction runs
- **THEN** the chronologically oldest event is deleted, not a newer one mis-ordered by lexicographic comparison

### Requirement: Legacy queue file names are tolerated

The queue SHALL continue to operate correctly on file names written by a previous version without the zero-pad. Removal by `event_id` MUST keep working because `event_id` (UUID v4) contains no underscore and the name is split on the first underscore only.

#### Scenario: Remove by event_id works for padded and legacy names
- **WHEN** `remove(event_id)` is called and a matching file exists under either the padded or the legacy naming scheme
- **THEN** the file is unlinked and the call returns `true`

### Requirement: Queue files carry retry metadata in an envelope and tolerate the previous bare-payload format

Each queue file SHALL hold an envelope containing the event payload plus the durable retry metadata: the payload under a `payload` key, an integer attempt count, and the timestamp of the first publication attempt.

Reading SHALL detect the format: a loaded object that does not carry a `payload` key is a file written by an earlier agent version and SHALL be wrapped as an envelope with an attempt count of zero. No migration script, no manual step, and no loss of an existing queue. This is the same tolerance criterion already applied to legacy queue file names.

The file naming scheme (`{detected_at_epoch_ms:016d}_{event_id}.json`), the FIFO ordering by name prefix, the atomic write via temporary file plus rename, the removal by `event_id`, the 100 MB budget and the drop-oldest policy SHALL all remain unchanged (RN-38 to RN-41, RN-84).

Incrementing the attempt count SHALL rewrite the envelope with the same atomic write used for enqueueing. (D37 / RN-131)

#### Scenario: An enqueued event starts at zero attempts

- **WHEN** a newly detected event is enqueued
- **THEN** its queue file holds an envelope whose attempt count is zero and whose `payload` key carries the event payload

#### Scenario: A queue file written by an earlier version is read as zero attempts

- **WHEN** the queue directory contains a file holding a bare payload object with no `payload` key
- **THEN** it is read as an event with an attempt count of zero and is published normally

#### Scenario: A mixed queue directory drains in FIFO order

- **WHEN** the queue holds both envelope files and bare-payload files from an earlier version
- **THEN** all of them are drained in timestamp-prefix order and none is skipped

#### Scenario: The attempt count is durable across a restart

- **WHEN** an event's attempt count is incremented and the agent restarts
- **THEN** the count read from disk is the incremented value

#### Scenario: The envelope rewrite is atomic

- **WHEN** the process is interrupted while rewriting an envelope
- **THEN** the queue directory holds either the previous complete file or the new complete file, and any orphaned temporary file is swept on the next startup

#### Scenario: Removal by event_id still works on the envelope format

- **WHEN** an `event_ack` arrives for an event stored as an envelope
- **THEN** its queue file is removed by `event_id` exactly as before

### Requirement: Discarded events are archived in a bounded local directory separate from the queue

The agent SHALL maintain a discard directory, configurable and defaulting to a sibling of the queue directory, holding events that will never be published again. Each discard record SHALL carry the event payload, the discard reason, the attempt count and the discard timestamp, and SHALL use the same name scheme as the queue so that chronological ordering is preserved.

The discard reason SHALL come from a closed lowercase snake_case vocabulary (RN-71): `max_attempts_exceeded`, `invalid_schema`, `clock_skew`.

The discard directory SHALL NOT count toward the queue's 100 MB budget and SHALL NOT contribute to `queue_pressure`. Mixing the two budgets would let a discard evict a live event through drop-oldest.

The discard directory SHALL be bounded by a configurable file count with its own drop-oldest policy, so that a host with a persistent problem cannot fill its disk. (D37 / RN-131, RN-71, RN-84)

#### Scenario: A discarded event leaves the queue and enters the discard directory

- **WHEN** an event reaches its attempt ceiling
- **THEN** its queue file no longer exists and a discard record for it exists carrying reason `max_attempts_exceeded` and its final attempt count

#### Scenario: A terminal nack files the event with the nack's reason

- **WHEN** an event is removed because of a terminal `event_nack` with reason `invalid_schema`
- **THEN** the discard record carries reason `invalid_schema`

#### Scenario: Discards do not consume the queue budget

- **WHEN** the discard directory holds several records
- **THEN** `queue_pressure` and the 100 MB accounting reflect only the queue files

#### Scenario: The discard directory drops the oldest records past its bound

- **WHEN** the number of discard records exceeds the configured bound
- **THEN** the chronologically oldest records are removed until the bound is met

#### Scenario: The discard directory is created on demand with restrictive permissions

- **WHEN** the first event is discarded and the directory does not exist
- **THEN** it is created before the record is written, following the same permission conventions as the queue directory

### Requirement: Queue and discard files are encrypted at rest with a queue-scoped key

Todo archivo que el agente escribe en la cola offline y en el directorio de descarte SHALL persistirse cifrado con AES-256-GCM. La clave SHALL derivarse con `HKDF-SHA256(ikm=master_secret, salt=agent_id, info="queue-v1", length=32)`, separada por dominio de las claves de baseline (`baseline-v1`) y cuarentena (`quarantine-v1`). La clave derivada MUST mantenerse únicamente en memoria y MUST NOT escribirse a disco ni emitirse en logs.

Cada escritura —encolado, reescritura del contador de intentos, migración y registro de descarte— MUST usar un nonce aleatorio de 12 bytes nuevo. El blob MUST tener el layout `[magic y versión b"FIMQE\x01"][nonce 12 bytes][ciphertext con tag GCM de 16 bytes]`, y los datos asociados de GCM MUST incluir el magic y el nombre base del archivo, de modo que el contenido quede ligado a su `event_id` y a su posición FIFO.

El plaintext cifrado SHALL ser el mismo sobre JSON que define la durabilidad del transporte (D37/RN-131). Ningún camino de escritura de la cola o del descarte MUST producir un archivo en claro, y la cola MUST NOT poder construirse sin `master_secret` y `agent_id`.

El esquema de nombres (`{detected_at_epoch_ms:016d}_{event_id}.json`), el orden FIFO, la escritura atómica por archivo temporal y renombrado, el borrado por `event_id`, el presupuesto de 100 MB medido sobre bytes en disco, el drop-oldest y la cota del descarte SHALL permanecer sin cambios. (D63 / RN-157, RN-50, RN-82, RN-84)

#### Scenario: Un archivo de cola no contiene diff_text legible

- **WHEN** se encola un evento cuyo payload incluye `diff_text`, una ruta y contexto de proceso
- **THEN** el archivo de cola no contiene esos valores ni ninguna clave del sobre en claro, empieza con `b"FIMQE\x01"` y la cola devuelve el payload original al leerlo

#### Scenario: Un registro de descarte no contiene diff_text legible

- **WHEN** un evento con `diff_text` se mueve al directorio de descarte
- **THEN** el registro de descarte no contiene `diff_text`, el payload ni el motivo en claro, y al descifrarlo con la clave de cola contiene el payload, el motivo y la marca de descarte

#### Scenario: Cada escritura usa un nonce distinto

- **WHEN** el contador de intentos de un evento se incrementa dos veces
- **THEN** el nonce de cada blob reescrito es distinto del anterior

#### Scenario: La clave de cola está separada de las otras claves del agente

- **WHEN** se derivan las claves de cola, baseline y cuarentena con el mismo `master_secret` y el mismo `agent_id`
- **THEN** las tres claves son distintas entre sí, y agentes con distinto `agent_id` derivan claves de cola distintas

#### Scenario: Un archivo renombrado no se autentica

- **WHEN** el blob cifrado de un evento se copia bajo el nombre de archivo de otro evento
- **THEN** su lectura falla la verificación GCM y el contenido no se entrega como el evento suplantado

#### Scenario: El presupuesto de 100 MB sigue midiendo bytes en disco

- **WHEN** se encolan eventos hasta superar el presupuesto
- **THEN** el drop-oldest se aplica sobre el tamaño de los blobs cifrados y `queue_pressure` refleja ese tamaño

### Requirement: Legacy plaintext queue and discard files are re-encrypted in place

Al abrir la cola, el agente SHALL recorrer una única vez el directorio de cola y el directorio de descarte, y todo archivo en claro escrito por una versión anterior —sobre o payload desnudo— SHALL leerse y reescribirse cifrado con el mismo nombre mediante escritura atómica, antes de construir los índices de nombre y tamaño. Un payload desnudo SHALL reescribirse envuelto con un contador de intentos en cero, igual que como se lee.

La clasificación de formato MUST depender del magic inicial y no de un intento fallido de descifrado: un archivo que empieza con el magic y no se autentica MUST NOT reinterpretarse como JSON en claro.

Si la reescritura de un archivo falla, el archivo SHALL permanecer en claro y legible, y cualquier lectura posterior o el arranque siguiente SHALL volver a intentar la migración. No SHALL existir un script de migración separado ni un paso manual, y ningún evento pendiente MUST perderse por la migración. La migración SHALL registrar sólo conteos agregados, sin nombres de archivo ni contenido. (D63 / RN-157, D37 / RN-131)

#### Scenario: Una cola en claro preexistente queda cifrada y se drena

- **WHEN** el agente arranca con archivos de cola en claro en formato sobre y en formato payload desnudo
- **THEN** después de abrir la cola ninguno de esos archivos contiene JSON en claro, conservan su nombre, y el drenaje publica todos los eventos en orden FIFO con los contadores de intentos que tenían

#### Scenario: Un descarte en claro preexistente queda cifrado

- **WHEN** el agente arranca con registros de descarte en claro que nadie vuelve a leer
- **THEN** después de abrir la cola esos registros están cifrados, conservan su nombre y la cota del descarte no cambia

#### Scenario: Una reescritura fallida no pierde el evento

- **WHEN** la reescritura cifrada de un archivo legacy falla por un error de E/S
- **THEN** el archivo queda en claro y legible, el evento sigue en la cola y la migración se reintenta en la siguiente lectura o arranque

#### Scenario: Un segundo arranque no reescribe archivos ya cifrados

- **WHEN** el agente arranca con una cola que ya está completamente cifrada
- **THEN** ningún archivo se reescribe y los nonces de los blobs no cambian

### Requirement: A queue file that fails authentication is handled as unreadable without stopping the agent

Un archivo de cola que no supera la verificación GCM —byte alterado, archivo truncado, clave distinta o nombre cambiado— o cuyo contenido no es un blob cifrado ni un JSON legacy válido SHALL tratarse por el mismo camino que la cola aplica a un archivo ilegible: MUST NOT publicarse, MUST NOT interrumpir la lectura ni el drenaje de los demás archivos, MUST NOT detener el agente, su contador de intentos SHALL leerse como cero sin reescribir el archivo, y SHALL seguir contando para el presupuesto de 100 MB hasta que el drop-oldest lo elimine.

Cada archivo en esa condición SHALL registrarse con un evento de log que incluya el `event_id` tomado del nombre y un motivo en snake_case minúsculas (`authentication_failed` o `malformed`), y MUST NOT incluir contenido del archivo. (D63 / RN-157, D37 / RN-131, RN-71)

#### Scenario: Un byte alterado impide publicar ese evento y no los demás

- **WHEN** la cola contiene tres eventos cifrados y se altera un byte del ciphertext del segundo
- **THEN** el drenaje publica el primero y el tercero, el segundo no se publica, se registra `queue.unreadable_file` con motivo `authentication_failed`, y el agente sigue en ejecución

#### Scenario: Un archivo truncado se trata como ilegible

- **WHEN** un archivo de cola tiene menos bytes que el magic, el nonce y el tag
- **THEN** se saltea con motivo `malformed` y la cola sigue operando

#### Scenario: Una clave distinta no expone ni publica la cola

- **WHEN** la cola se abre con un `master_secret` distinto del que cifró sus archivos
- **THEN** ningún archivo se publica, ninguno se reinterpreta como JSON en claro, y cada uno se registra como ilegible sin contenido

#### Scenario: El contador de un archivo ilegible no se reescribe

- **WHEN** se incrementa el contador de intentos de un evento cuyo archivo no se autentica
- **THEN** la operación devuelve cero y el archivo queda byte a byte igual

### Requirement: A root-only CLI can inspect queue and discard files for forensic use

El agente SHALL proveer un comando de solo lectura, invocable con `python -m agent.queue_inspect`, para que un operador inspeccione con fines forenses el contenido de los archivos de la cola offline y del directorio de descarte. El comando SHALL requerir privilegios de root y MUST rechazar la ejecución antes de leer configuración, `master_secret` o cualquier archivo de cola o descarte cuando el proceso no corre como root.

El comando SHALL derivar la clave de cola a partir del `master_secret` y del `agent_id` leídos del mismo estado del agente que usa el proceso principal (configuración y directorio de secretos), sin credenciales ni rutas nuevas. En su modo por defecto SHALL listar, por archivo, el nombre, el tamaño en disco y su estado (`ok`, `authentication_failed`, `malformed`, `legacy_plaintext`), sin descifrar ni imprimir contenido. El comando SHALL imprimir el contenido descifrado de un archivo únicamente cuando se invoca con un flag explícito que identifique ese archivo.

El comando MUST NOT escribir, crear, modificar ni eliminar ningún archivo de `queue_dir` ni de `discard_dir` en ningún modo, y MUST NOT ejecutar la pasada de migración en el lugar de D63. Un archivo que no se autentica o que está mal formado SHALL reportarse por stderr con su motivo (`authentication_failed` | `malformed`), sin contenido y sin una excepción no controlada, terminando con un código de salida distinto de cero. (D63 / RN-157, D37 / RN-131, RN-108)

#### Scenario: Un usuario sin privilegios de root es rechazado

- **WHEN** se invoca `python -m agent.queue_inspect` como un usuario que no es root
- **THEN** el comando termina con un mensaje claro y un código de salida distinto de cero, sin leer `master_secret`, configuración ni ningún archivo de cola o descarte

#### Scenario: El contenido descifrado coincide con el sobre original

- **WHEN** un operador root invoca el comando con el flag de impresión sobre un archivo cifrado con la clave de cola vigente
- **THEN** el comando imprime el sobre JSON descifrado y su contenido es idéntico al payload, los intentos y las marcas de tiempo que se habían encolado originalmente

#### Scenario: Clave incorrecta o archivo manipulado se reportan sin interrumpir el comando

- **WHEN** un operador root invoca el comando con el flag de impresión sobre un archivo cifrado con un `master_secret` distinto, o sobre un archivo cuyo ciphertext fue alterado
- **THEN** el comando reporta por stderr el motivo (`authentication_failed`) sin imprimir contenido, sin lanzar una excepción no controlada, y termina con un código de salida distinto de cero

#### Scenario: El comando nunca escribe

- **WHEN** se ejecuta el comando en modo lista o en modo impresión, incluso sobre archivos en claro heredados o archivos que no se autentican
- **THEN** ningún archivo de `queue_dir` ni de `discard_dir` cambia de tamaño, contenido o fecha de modificación, y no se crea ningún archivo nuevo

