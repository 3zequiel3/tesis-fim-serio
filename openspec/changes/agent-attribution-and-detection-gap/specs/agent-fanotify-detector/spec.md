## MODIFIED Requirements

### Requirement: Captura de contexto del proceso causante (PID, UID, exe)

El detector SHALL extraer de cada evento fanotify el `pid` del proceso causante —el único dato de
proceso que `struct fanotify_event_metadata` entrega, en cualquier modo de operación— y SHALL
resolver **fuera de banda** su `uid` desde `/proc/<pid>/status` y el path de su ejecutable desde
`/proc/<pid>/exe`, almacenándolos como `process_pid`, `process_uid` y `process_exe` en el payload del
evento (RN-01, RN-03).

Ambas resoluciones son *best-effort*. `/proc/<pid>` desaparece en cuanto el proceso termina, y entre
la notificación del kernel y el armado del evento hay hasta 150 ms de reintentos de hash, de modo
que un proceso corto ya no existe cuando se lo consulta. Si `/proc/<pid>/exe` no es accesible, el
detector MUST usar `None` para `process_exe` sin fallar. Si `/proc/<pid>/status` no es accesible, el
detector MUST usar `None` para `process_uid` sin fallar: `_get_uid` SHALL tener tipo de retorno
`int | None` y `FanotifyEvent.uid` y `DetectedChange.process_uid` SHALL ser `int | None`.

El valor `0` en `process_uid` SHALL significar **exclusivamente** que el proceso causante corría como
root. El detector MUST NOT usar `0`, ni ningún otro entero, como valor de relleno para una
atribución que no pudo resolver (D49/RN-143): cualquier entero que se elija colisiona con un uid
real, y `0` colisiona con el peor posible, porque contamina toda búsqueda de cambios privilegiados
con los cambios cuyo autor el sistema no supo identificar.

#### Scenario: Contexto de proceso capturado correctamente

- **WHEN** el proceso con PID 1234, UID 0 y ejecutable `/usr/bin/vim` modifica un archivo monitoreado
- **THEN** el evento generado contiene `process_pid=1234`, `process_uid=0`, `process_exe="/usr/bin/vim"`

#### Scenario: Proceso ya terminado al capturar exe

- **WHEN** el proceso causante termina antes de que el detector lea `/proc/<pid>/exe`
- **THEN** el evento generado contiene `process_pid=<pid>`, `process_uid=<uid>`, `process_exe=None`

#### Scenario: Proceso ya terminado al resolver el uid — atribución no resuelta

- **WHEN** el proceso causante termina antes de que el detector lea `/proc/<pid>/status`, de modo que
  la lectura levanta `OSError`
- **THEN** `_get_uid` retorna `None` sin propagar la excepción
- **AND** el evento generado contiene `process_uid=None`, nunca `0`

#### Scenario: uid 0 se reserva para root real

- **WHEN** el proceso causante existe al momento de la consulta y `/proc/<pid>/status` reporta
  `Uid:\t0\t0\t0\t0`
- **THEN** el evento generado contiene `process_uid=0`, distinguible de una atribución no resuelta

### Requirement: Dispatch por tipo de evento y campo operation_type en el payload

El detector SHALL despachar cada evento fanotify según su tipo y emitir el campo `operation_type`
(str, snake_case) en el payload del cambio, con el léxico canónico (RN-71, RN-110):

| `operation_type` | Condición |
|------------------|-----------|
| `file_modified`  | `FAN_CLOSE_WRITE` y el hash difiere del baseline |
| `file_absent`    | `FAN_CLOSE_WRITE` y el archivo no existe al momento de hashear (race) |
| `file_deleted`   | `FAN_DELETE` o `FAN_MOVED_FROM` |
| `file_created`   | `FAN_CREATE` o `FAN_MOVED_TO` |
| `detection_gap`  | `FAN_Q_OVERFLOW` — el kernel desbordó su cola y descartó eventos (D50/RN-144) |

Para `file_deleted` el detector MUST actualizar el baseline con `mark_absent(path)` y MUST emitir
`hash` nulo. Para `file_created` el detector MUST hashear el archivo y persistir la entrada con
`write_entry(path)`. Para `detection_gap` el detector MUST NOT tocar el baseline: el evento no habla
de ningún archivo. El valor de `operation_type` MUST estar siempre en minúsculas snake_case, y el
campo `event_type` del payload MUST llevar el mismo valor.

#### Scenario: Borrado emite file_deleted y marca baseline absent

- **WHEN** un archivo monitoreado es borrado (`FAN_DELETE`)
- **THEN** el detector emite un cambio con `operation_type="file_deleted"`, `hash` nulo, y el baseline del path queda en estado `absent`

#### Scenario: Movimiento de origen emite file_deleted

- **WHEN** un archivo monitoreado es movido fuera del path vigilado (`FAN_MOVED_FROM`)
- **THEN** el detector emite un cambio con `operation_type="file_deleted"` y `hash` nulo

#### Scenario: Creación emite file_created con hash y baseline

- **WHEN** un archivo nuevo es creado bajo un `watch_path` (`FAN_CREATE`)
- **THEN** el detector emite un cambio con `operation_type="file_created"` con el hash del archivo y persiste la entrada de baseline

#### Scenario: Movimiento de destino emite file_created

- **WHEN** un archivo es movido hacia un path vigilado (`FAN_MOVED_TO`)
- **THEN** el detector emite un cambio con `operation_type="file_created"` con el hash del archivo

#### Scenario: Desbordamiento emite detection_gap sin tocar el baseline

- **WHEN** el kernel reporta `FAN_Q_OVERFLOW`
- **THEN** el detector emite un cambio con `operation_type="detection_gap"` y `event_type="detection_gap"`
- **AND** no se escribe, ni se marca ausente, ninguna entrada de baseline

### Requirement: Eventos con path nulo se descartan

Si `ev.path` es `None` **y el evento no es un desbordamiento de la cola del kernel**, el detector SHALL descartar el evento con un `log.warning` y MUST NOT generar ningún cambio ni tocar el baseline (RN-110, D12): un evento de archivo cuyo path no pudo reconstruirse vía `open_by_handle_at(2)` no aporta información accionable.

Esta regla MUST NOT alcanzar al evento de desbordamiento (`FAN_Q_OVERFLOW`), que por construcción no
tiene path porque no habla de ningún archivo. El chequeo del bit de desbordamiento SHALL ocurrir
**antes** del descarte por path nulo en el hilo lector, de modo que la brecha de detección no se
pierda con un warning genérico (D50/RN-144).

#### Scenario: Evento sin path resoluble se descarta

- **WHEN** el backend fanotify entrega un evento cuyo path no puede resolverse vía `open_by_handle_at(2)`
- **THEN** el detector registra un warning y no produce ningún cambio

#### Scenario: El desbordamiento no cae en el descarte por path nulo

- **WHEN** el backend fanotify entrega un evento con `FAN_Q_OVERFLOW` y `path=None`
- **THEN** el detector NO lo descarta por la regla de path nulo
- **AND** emite un evento `detection_gap`

## ADDED Requirements

### Requirement: Detección de FAN_Q_OVERFLOW y emisión de detection_gap

`agent/_fanotify.py` SHALL definir la constante `FAN_Q_OVERFLOW = 0x00004000` y `_parse_events` SHALL
propagar el `mask` de cada registro sin filtrarlo, de modo que el bit de desbordamiento llegue al
consumidor. El reconocimiento del bit SHALL ocurrir en el hilo lector del detector (`_read_loop`),
antes del filtro de scope y antes del descarte por path nulo.

Al reconocerlo, el detector SHALL emitir un evento sintético con:

- `event_type` y `operation_type` iguales a `"detection_gap"`
- `path` **nulo** — el evento no habla de ningún archivo
- `process_pid`, `process_uid` y `process_exe` **nulos** — no hay proceso causante que atribuir
- causa `fan_q_overflow` en su metadato
- `action: "alert_only"` ya resuelto en el payload
- `hash_detected` como cadena vacía, conforme al contrato D-C13-04 con el backend

El evento SHALL publicarse por el mismo `Publisher` que el resto de los eventos, heredando cola
offline, firma HMAC, `schema_version` y reintentos. El detector MUST NOT invocar
`DecisionEngine.evaluate_and_act` para este evento ni escribir una entrada de journal: el motor
evalúa reglas contra la ruta y sus acciones físicas operan sobre el filesystem, y un evento sin ruta
no tiene nada que matchear ni nada sobre qué actuar.

El detector MUST NOT encolar el evento sintético en la `asyncio.Queue` interna: bajo saturación esa
cola es justamente lo que está lleno, y perder el aviso de pérdida por `QueueFull` anularía el
propósito de la regla.

En plataformas sin `fanotify` funcional el detector ya degrada y no emite eventos de ningún tipo;
tampoco emite `detection_gap`.

#### Scenario: Un desbordamiento produce un evento detection_gap publicado

- **WHEN** el hilo lector recibe del kernel un evento cuyo `mask` tiene el bit `FAN_Q_OVERFLOW`
- **THEN** se publica un evento con `event_type="detection_gap"`, `path=None`, `process_pid=None`,
  `process_uid=None`, `process_exe=None`, causa `fan_q_overflow` y `action="alert_only"`

#### Scenario: El detection_gap no atraviesa el motor de decisión

- **WHEN** el detector emite un `detection_gap` con un `DecisionEngine` configurado
- **THEN** `evaluate_and_act` no se invoca para ese evento
- **AND** no se escribe ninguna entrada de journal para ese evento

#### Scenario: El detection_gap no consume la cola interna

- **WHEN** la `asyncio.Queue` interna del detector está llena y llega un `FAN_Q_OVERFLOW`
- **THEN** el `detection_gap` se publica igual
- **AND** el contador `event_drops` no se incrementa por causa de este evento

#### Scenario: Un evento normal con mask sin el bit de desbordamiento sigue su curso

- **WHEN** el hilo lector recibe un evento con `FAN_CLOSE_WRITE` y path resoluble
- **THEN** el evento sigue el pipeline habitual y no se emite ningún `detection_gap`

### Requirement: Deduplicación de detection_gap por ventana de 60 segundos

Bajo saturación sostenida el kernel emite `FAN_Q_OVERFLOW` repetidamente. El detector SHALL emitir a
lo sumo **un** `detection_gap` por ventana de **60 segundos**, contando los desbordamientos
suprimidos y reportando esa cuenta en el evento emitido (campo `suppressed_count`) (D50/RN-144).

La deduplicación SHALL ser **por ventana de tiempo**, no por desbordamiento: emitir uno por cada
`FAN_Q_OVERFLOW` inundaría la tabla de eventos justo cuando menos capacidad hay para procesarla, de
modo que el evento diagnóstico se convertiría en una segunda falla.

El primer desbordamiento de una ventana nueva SHALL emitirse con la cuenta de supresiones acumulada
desde la emisión anterior, y esa cuenta SHALL reiniciarse tras emitir. El estado de la ventana vive
en memoria del hilo lector: tras un reinicio del agente, el primer desbordamiento SHALL emitirse
siempre.

#### Scenario: Desbordamientos sucesivos dentro de la ventana se suprimen

- **WHEN** llegan cinco `FAN_Q_OVERFLOW` dentro de una misma ventana de 60 segundos
- **THEN** se publica exactamente un evento `detection_gap`
- **AND** las cuatro supresiones quedan contadas

#### Scenario: El primer desbordamiento de la ventana siguiente reporta las supresiones

- **WHEN** tras suprimir cuatro desbordamientos transcurren más de 60 segundos y llega uno nuevo
- **THEN** se publica un segundo `detection_gap` con `suppressed_count=4`
- **AND** el contador de supresiones vuelve a cero

#### Scenario: Un desbordamiento aislado reporta cero supresiones

- **WHEN** llega un `FAN_Q_OVERFLOW` sin desbordamientos previos en la ventana anterior
- **THEN** se publica un `detection_gap` con `suppressed_count=0`

#### Scenario: El estado de ventana no sobrevive al reinicio

- **WHEN** el agente reinicia y recibe un `FAN_Q_OVERFLOW` antes de que transcurran 60 segundos
  desde el último `detection_gap` de la ejecución anterior
- **THEN** el evento se emite igual, sin suprimirse
