## ADDED Requirements

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
