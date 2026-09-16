# agent-fanotify-detector Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: Marcado FAN_MARK_FILESYSTEM sobre watch_paths con exclusión de /var/lib/fim-agent

El detector SHALL inicializar un grupo fanotify con el backend propio de `agent/_fanotify.py` (`ctypes` sobre syscalls crudas) usando `FAN_CLASS_NOTIF | FAN_REPORT_DFID_NAME` — **modo FID** — y marcar cada filesystem que contiene un `watch_path` con `FAN_MARK_FILESYSTEM | FAN_MARK_ADD` y la máscara combinada `FAN_CLOSE_WRITE | FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE` (RN-01, RN-02, RN-110, D46/RN-140).

El modo FID es **obligatorio, no preferido**: el modo fd clásico (`FAN_CLASS_NOTIF` sin FID) no admite `FAN_CREATE`, `FAN_DELETE` ni `FAN_MOVED_*` sobre una marca de filesystem — el kernel responde `EINVAL` —, de modo que exigir esas máscaras y prohibir el reporte FID a la vez es irrealizable. La resolución de path usa `open_by_handle_at(2)` sobre el handle del directorio padre más el nombre, lo que además permite resolver el path de un archivo **ya borrado**. Eso exige `CAP_DAC_READ_SEARCH` además de `CAP_SYS_ADMIN`. El módulo `agent/detector.py` MUST excluir con `FAN_MARK_FILESYSTEM | FAN_MARK_IGNORED_MASK` el path `/var/lib/fim-agent/**` para prevenir ciclos de auto-detección (RN-04). El marcado MUST ocurrir antes de que el detector empiece a leer eventos.

#### Scenario: Archivo monitoreado modificado genera evento

- **WHEN** un proceso escribe y cierra un archivo bajo un `watch_path` configurado
- **THEN** el detector recibe el evento fanotify con el path, PID, UID y path del ejecutable causante

#### Scenario: Archivo monitoreado borrado genera evento

- **WHEN** un proceso elimina un archivo bajo un `watch_path` configurado
- **THEN** el detector recibe un evento de borrado y produce un cambio con `operation_type="file_deleted"`

#### Scenario: Archivo creado bajo watch_path genera evento

- **WHEN** un proceso crea un archivo nuevo bajo un `watch_path` configurado
- **THEN** el detector recibe un evento de creación y produce un cambio con `operation_type="file_created"`

#### Scenario: Archivo bajo /var/lib/fim-agent no genera evento

- **WHEN** el agente escribe un archivo en `/var/lib/fim-agent/queue/`
- **THEN** el detector no recibe ningún evento fanotify para ese path

#### Scenario: Path fuera de watch_paths no genera evento

- **WHEN** un proceso escribe un archivo en un directorio no configurado en `watch_paths`
- **THEN** el detector no produce ningún evento de cambio

### Requirement: Captura de contexto del proceso causante (PID, UID, exe)

El detector SHALL extraer de cada evento fanotify el `pid` del proceso causante, su `uid` y el path del ejecutable (`/proc/<pid>/exe` → symlink resolution), almacenándolos como `process_pid`, `process_uid` y `process_exe` en el payload del evento (RN-01). Si `/proc/<pid>/exe` no es accesible (proceso ya terminó), el detector MUST usar `None` para `process_exe` sin fallar.

#### Scenario: Contexto de proceso capturado correctamente

- **WHEN** el proceso con PID 1234, UID 0 y ejecutable `/usr/bin/vim` modifica un archivo monitoreado
- **THEN** el evento generado contiene `process_pid=1234`, `process_uid=0`, `process_exe="/usr/bin/vim"`

#### Scenario: Proceso ya terminado al capturar exe

- **WHEN** el proceso causante termina antes de que el detector lea `/proc/<pid>/exe`
- **THEN** el evento generado contiene `process_pid=<pid>`, `process_uid=<uid>`, `process_exe=None`

### Requirement: Comparación SHA-256 contra baseline y descarte de no-cambios

Tras recibir un evento fanotify de tipo modificación (`FAN_CLOSE_WRITE`), el detector SHALL calcular el SHA-256 del contenido actual del archivo y compararlo con el hash almacenado en el baseline cifrado (vía `agent/baseline.py`). Si el hash es idéntico, el detector MUST descartar el evento sin encolarlo ni emitir log de nivel warn o superior (RN-01). Si el hash difiere o el archivo no existe en baseline, el detector MUST proceder con la generación del evento. Para eventos de borrado o de movimiento de origen (`FAN_DELETE`, `FAN_MOVED_FROM`) el detector MUST NOT hashear el archivo (ya no existe) y MUST emitir el cambio con `hash` nulo. Para eventos de creación o de movimiento de destino (`FAN_CREATE`, `FAN_MOVED_TO`) el detector MUST hashear el archivo nuevo y crear/actualizar la entrada de baseline.

#### Scenario: Mismo hash que baseline — evento descartado

- **WHEN** un proceso abre y cierra un archivo monitoreado sin modificar su contenido (hash idéntico al baseline)
- **THEN** el detector no encola ningún evento y no emite ninguna alerta

#### Scenario: Hash diferente al baseline — evento generado

- **WHEN** un proceso modifica el contenido de un archivo monitoreado (hash nuevo ≠ baseline)
- **THEN** el detector encola un evento con `operation_type="file_modified"`, el hash anterior y el hash actual

#### Scenario: Archivo sin entrada en baseline

- **WHEN** el detector recibe un evento de modificación para un archivo que no tiene entrada en el baseline
- **THEN** el detector encola el evento con `operation_type="file_modified"` usando `previous_hash=None`

### Requirement: Generación de diff unificado para archivos de texto

Para eventos donde el hash difiere, el detector SHALL detectar si el archivo es texto (ausencia de byte nulo `\x00` en los primeros 8 KB) y, si es texto y su tamaño no supera 1 MB, generar un diff unificado con `difflib.unified_diff` entre el contenido del baseline (snapshot cifrado más reciente) y el contenido actual (RN-03). El diff SHALL incluirse en el payload del evento como `diff_text: str | None`. Para archivos binarios o mayores de 1 MB, `diff_text` MUST ser `None`.

#### Scenario: Diff textual generado para archivo de texto

- **WHEN** un archivo de texto de 50 KB cambia de contenido
- **THEN** el evento contiene `diff_text` con el diff unificado en formato `unified_diff`

#### Scenario: Sin diff para archivo binario

- **WHEN** un archivo binario (contiene byte nulo) es modificado
- **THEN** el evento contiene `diff_text=None`

#### Scenario: Sin diff para archivo mayor a 1 MB

- **WHEN** un archivo de texto de 2 MB es modificado
- **THEN** el evento contiene `diff_text=None`

### Requirement: Deduplicación en memoria por path con encadenamiento parent_event_id

El detector SHALL mantener un `pending_paths: dict[str, str]` en memoria que mapea path → `event_id` del último evento encolado para ese path aún sin `event_ack`. Si llega un nuevo evento fanotify para un path ya en `pending_paths`, el detector MUST encolar el nuevo evento con `parent_event_id` igual al `event_id` del evento pendiente anterior y actualizar el mapa (RN-01). Al recibir `event_ack` para un `event_id`, el detector MUST eliminar la entrada correspondiente de `pending_paths` si el `event_id` coincide con el valor almacenado.

#### Scenario: Primer cambio en un path — sin parent_event_id

- **WHEN** se detecta el primer cambio en el path `/etc/hosts` (no hay entrada en pending_paths)
- **THEN** el evento encolado tiene `parent_event_id=None` y se agrega `/etc/hosts → event_id` a pending_paths

#### Scenario: Segundo cambio en el mismo path — encadenado

- **WHEN** se detecta un segundo cambio en `/etc/hosts` mientras el primer evento aún no recibió ack
- **THEN** el segundo evento tiene `parent_event_id` igual al `event_id` del primer evento

#### Scenario: event_ack limpia el pending_paths

- **WHEN** el command consumer recibe `event_ack` para el `event_id` de `/etc/hosts`
- **THEN** la entrada `/etc/hosts` se elimina de pending_paths

### Requirement: Recarga en caliente de watch_paths al recibir update_config

Al recibir un comando `update_config` desde el stream `commands`, el detector SHALL actualizar `watch_paths` sin reiniciar el proceso: desmarcar los filesystems anteriores con `FAN_MARK_FLUSH`, marcar los nuevos con `FAN_MARK_FILESYSTEM`, y disparar un scan de baseline inicial en `agent/baseline.py` para cada path nuevo que no tenga baseline (RN-04). Los paths removidos dejan de generar eventos inmediatamente tras el flush.

#### Scenario: Path nuevo añadido en caliente

- **WHEN** el comando `update_config` incluye un nuevo `watch_path` `/opt/app`
- **THEN** el detector empieza a monitorear `/opt/app` sin reiniciar el proceso ni perder eventos de otros paths

#### Scenario: Path eliminado deja de generar eventos

- **WHEN** el comando `update_config` elimina `/etc` de los `watch_paths`
- **THEN** cambios posteriores bajo `/etc` no generan eventos

#### Scenario: Baseline scan automático para path nuevo sin baseline

- **WHEN** se añade `/opt/app` via update_config y no tiene baseline previo
- **THEN** el detector invoca `baseline.scan_path("/opt/app")` antes de iniciar el monitoreo activo

### Requirement: Graceful shutdown SIGTERM con drenaje de cola y heartbeat shutdown

Al recibir SIGTERM, el detector SHALL dejar de aceptar nuevos eventos fanotify (stop_event.set()), esperar hasta 30 segundos a que la cola local drene (todos los archivos en `queue/` reciban `event_ack`), publicar heartbeats con `shutdown: true` durante el drenaje, y terminar con exit code 0 (RN-93). Si la cola no drena en 30 s, el agente termina igualmente con exit 0 (forzado).

#### Scenario: Shutdown limpio con cola vacía

- **WHEN** el agente recibe SIGTERM y la cola local está vacía
- **THEN** el agente publica un heartbeat con `shutdown=true`, deja de marcar fanotify y termina con exit 0 en menos de 5 segundos

#### Scenario: Shutdown con cola pendiente — drenaje de 30 s

- **WHEN** el agente recibe SIGTERM y hay 3 eventos en cola sin ack
- **THEN** el agente sigue publicando heartbeats con `shutdown=true`, espera los acks hasta 30 s y luego termina con exit 0

#### Scenario: Timeout de drenaje fuerza exit

- **WHEN** el agente recibe SIGTERM, tiene eventos en cola, y pasan 30 s sin acks
- **THEN** el agente termina con exit 0 sin importar el estado de la cola

### Requirement: Dispatch por tipo de evento y campo operation_type en el payload

El detector SHALL despachar cada evento fanotify según su tipo y emitir el campo `operation_type` (str, snake_case) en el payload del cambio, con el léxico canónico (RN-71, RN-110):

| `operation_type` | Condición |
|------------------|-----------|
| `file_modified`  | `FAN_CLOSE_WRITE` y el hash difiere del baseline |
| `file_absent`    | `FAN_CLOSE_WRITE` y el archivo no existe al momento de hashear (race) |
| `file_deleted`   | `FAN_DELETE` o `FAN_MOVED_FROM` |
| `file_created`   | `FAN_CREATE` o `FAN_MOVED_TO` |

Para `file_deleted` el detector MUST actualizar el baseline con `mark_absent(path)` y MUST emitir `hash` nulo. Para `file_created` el detector MUST hashear el archivo y persistir la entrada con `write_entry(path)`. El valor de `operation_type` MUST estar siempre en minúsculas snake_case.

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

### Requirement: Eventos con path nulo se descartan

Si `ev.path` es `None` (caso de borde bajo carga extrema del kernel), el detector SHALL descartar el evento con un `log.warning` y MUST NOT generar ningún cambio ni tocar el baseline (RN-110, D12).

#### Scenario: Evento sin path resoluble se descarta

- **WHEN** el backend fanotify entrega un evento cuyo path no puede resolverse vía `open_by_handle_at(2)`
- **THEN** el detector registra un warning y no produce ningún cambio

### Requirement: Detector exposes close() for deterministic teardown

`FanotifyDetector` SHALL expose a `close()` method that closes the fanotify file descriptor and joins the internal `fan-reader` thread with a bounded timeout (5 seconds). Closing the fd MUST unblock the reader thread parked in the blocking `read()` syscall so the join completes promptly. `close()` MUST be idempotent: calling it when already closed is a safe no-op. (FA4)

#### Scenario: close() unblocks the reader thread and joins it
- **WHEN** `close()` is called while the reader thread is blocked in `read()`
- **THEN** the fanotify fd is closed, the syscall returns, and the thread is joined within 5 seconds

#### Scenario: close() is idempotent
- **WHEN** `close()` is called a second time after the detector is already closed
- **THEN** it returns without raising and without attempting to close an invalid fd

### Requirement: Raw event queue is bounded with a drop counter surfaced via heartbeat

The detector's in-memory raw event queue SHALL be bounded (`asyncio.Queue(maxsize=1000)`) to prevent unbounded memory growth under event storms. Because the producer runs on the `fan-reader` thread via `loop.call_soon_threadsafe`, the enqueue MUST go through a wrapper that catches `asyncio.QueueFull`, increments a monotonic `event_drops` counter, and emits a `warning` log instead of letting the exception be lost. The current `event_drops` count MUST be readable by the heartbeat publisher and included in the `agent_heartbeat` payload as the field `event_drops`. (FA5)

#### Scenario: Enqueue under saturation increments the drop counter
- **WHEN** the raw queue is full and a new fanotify event arrives from the reader thread
- **THEN** the wrapper catches `QueueFull`, increments `event_drops`, logs a warning, and does not propagate the exception

#### Scenario: Drop counter is exposed in the heartbeat
- **WHEN** the heartbeat publisher builds its periodic payload
- **THEN** the payload includes an `event_drops` field reflecting the detector's current cumulative drop count

#### Scenario: Normal enqueue under capacity does not drop
- **WHEN** the raw queue has free capacity and an event arrives
- **THEN** the event is enqueued and `event_drops` is unchanged

### Requirement: Detector discards events outside the configured watch_path scope

Because the detector marks the whole filesystem (`FAN_MARK_FILESYSTEM`), it MUST enforce RN-04 ("only configured paths generate events; everything else is ignored; exceptions: none") in software. Scope containment is evaluated **by the location of the path itself, not by its resolved target**: in `_read_loop`, before constructing the internal `FanotifyEvent`, the detector SHALL call a new `_path_location_in_scope(path, watch_paths)` that canonicalizes ONLY the parent directory (`os.path.realpath(os.path.dirname(path))`) and compares the literal `basename` against the canonicalized `watch_paths`, WITHOUT resolving (without following) the final path component even when it is a symlink. The detector SHALL discard the event when this location check is not satisfied. This replaces the previous full-`realpath` containment (D31), which dereferenced the final component and therefore hid an in-scope symlink whose target resolved out of scope. The previous full-`realpath` helper is renamed `_target_in_scope` and retained ONLY for metadata checks that need to know whether the resolved target falls in scope; it MUST NOT be used at the discard point. The check MUST run at the read stage (before enqueueing into the bounded `_raw_queue`), NOT only at the `_process_event` classification stage, so the bounded queue never absorbs out-of-scope noise. The `watch_paths` SHALL be canonicalized to `realpath` exactly once — in `start()`, `reload_paths()`, and `reload_watch_paths()` — and cached; canonicalization MUST NOT run per event. A `watch_path` that is itself a symlink is canonicalized once and that `realpath` defines its containment boundary (D31 behavior preserved). (D31 / RN-125, refined by D33 / RN-127)

#### Scenario: Event whose parent directory is inside a watch_path is processed
- **WHEN** a fanotify event arrives whose parent directory `os.path.realpath(os.path.dirname(path))` is relative to a canonicalized `watch_path`
- **THEN** the detector builds the `FanotifyEvent` and enqueues it for processing, regardless of whether the final component is a symlink pointing out of scope

#### Scenario: Escape symlink created inside a watch_path is no longer invisible
- **WHEN** a symlink `/etc/evil -> /root/.ssh/authorized_keys` is created inside a configured `watch_path` and its resolved target is out of scope
- **THEN** the detector treats the event as in-scope because the link's parent directory is in scope, and it does NOT discard the event

#### Scenario: Event whose parent directory is outside every watch_path is dropped at read time
- **WHEN** a fanotify event arrives whose parent directory realpath is not relative to any canonicalized `watch_path`
- **THEN** the detector discards it in `_read_loop` without constructing a `FanotifyEvent` and without enqueueing it into `_raw_queue`

#### Scenario: Deleting a regular file inside scope is still published
- **WHEN** a regular file inside a `watch_path` is deleted (its final component no longer exists, but its parent directory does)
- **THEN** `_path_location_in_scope` resolves the still-existing parent directory, the event is kept, and the `file_deleted` event is published (no regression of the C35 legitimate-delete trap)

#### Scenario: watch_paths are canonicalized once, not per event
- **WHEN** the detector starts or reloads its watch paths via `start()`, `reload_paths()`, or `reload_watch_paths()`
- **THEN** each `watch_path` is resolved to `realpath` a single time and the cached values are used for every subsequent scope check

#### Scenario: A watch_path that is itself a symlink defines its boundary by realpath
- **WHEN** a configured `watch_path` is a symlink and an event occurs under its resolved target
- **THEN** the event is treated as in-scope because containment is evaluated against the canonicalized `watch_path`

### Requirement: Out-of-scope drop counter is surfaced via heartbeat

The detector SHALL maintain a monotonic `out_of_scope_drops` counter that increments each time an event is discarded for falling outside the configured `watch_paths`, analogous to the existing `event_drops` counter. The current count MUST be readable by the heartbeat publisher and included in the `agent_heartbeat` payload as the field `out_of_scope_drops`. This is the only operational visibility into how much filesystem-wide traffic `FAN_MARK_FILESYSTEM` is discarding. (D31 / RN-125)

#### Scenario: Dropping an out-of-scope event increments the counter
- **WHEN** the detector discards an event because its real path is outside every `watch_path`
- **THEN** `out_of_scope_drops` is incremented by one and a warning is logged

#### Scenario: Out-of-scope drop counter is exposed in the heartbeat
- **WHEN** the heartbeat publisher builds its periodic payload
- **THEN** the payload includes an `out_of_scope_drops` field reflecting the detector's current cumulative out-of-scope drop count

#### Scenario: In-scope traffic does not increment the counter
- **WHEN** all incoming events resolve inside the configured `watch_paths`
- **THEN** `out_of_scope_drops` remains unchanged

### Requirement: In-scope symlinks are reported as filesystem objects, never followed

For any path whose final component is a symlink and whose location is in scope (per `_path_location_in_scope`), the detector SHALL treat the symlink as a filesystem object in its own right and MUST NEVER follow it: it MUST NOT open, hash, or encrypt the content of the symlink target, whether that target is inside or outside scope. In `_process_event`, the symlink branch SHALL use `os.lstat`/`os.readlink` only. The event MUST be reported using the existing RN-71 canonical lexicon (`file_created` / `file_deleted` / `file_modified`) — NO new `event_type` is introduced. The reported `hash_detected` SHALL be `sha256(os.readlink(path))` (a hash of the target string, not of the target's content), and the content `diff` SHALL be `None`. Re-pointing an existing symlink to a different target SHALL be detected as `file_modified` because the `readlink` string changes. The event payload SHALL carry `is_symlink=true` and `symlink_target` (the `readlink` string); backend consumers that ignore unknown keys are unaffected. (D33 / RN-127)

#### Scenario: Creating an in-scope symlink reports file_created with target-string hash
- **WHEN** a symlink is created inside a `watch_path`
- **THEN** the detector reports `file_created`, sets `hash_detected = sha256(os.readlink(path))`, leaves the content diff as `None`, and never reads the target's bytes

#### Scenario: Re-pointing an existing symlink reports file_modified
- **WHEN** an existing in-scope symlink is changed to point at a different target
- **THEN** the detector reports `file_modified` because the `readlink` string (and therefore its hash) changed

#### Scenario: Symlink target content is never read regardless of target scope
- **WHEN** an in-scope symlink points at a target that is out of scope (e.g. `/root/.ssh/authorized_keys`) or in scope
- **THEN** the detector uses `os.lstat`/`os.readlink` only and never opens, hashes, or encrypts the target's content

#### Scenario: Symlink event payload carries symlink metadata
- **WHEN** the detector publishes an event for an in-scope symlink
- **THEN** the payload includes `is_symlink=true` and `symlink_target` set to the `readlink` string

#### Scenario: Deleting an in-scope symlink reports a real file_deleted, not a spurious one
- **WHEN** an in-scope symlink that was previously reported and baselined is deleted
- **THEN** the detector reports a real `file_deleted` (the baseline entry exists to distinguish it from a `file_absent`), resolving the LOW-1 spurious-delete finding as a consequence

### Requirement: Optional hardlink_suspected detective counter in heartbeat

Hardlinks are a known unresolved limitation: `os.path.realpath`/`os.lstat` cannot distinguish a hardlink from a regular file, and determining whether another name of the same inode falls out of scope would require a full-filesystem scan incompatible with the agent's bounded-queue reactive design. As a cheap detective signal with NO change of behavior, the detector MAY maintain a monotonic `hardlink_suspected` counter that increments when a regular file is created in scope with `st_nlink >= 2`, and expose it in the `agent_heartbeat` payload. This counter MUST NOT alter classification, hashing, encryption, or event publication. (D33 / RN-127)

#### Scenario: Creating an in-scope regular file with st_nlink >= 2 increments the counter
- **WHEN** a regular file is created inside a `watch_path` and its `st_nlink >= 2`
- **THEN** `hardlink_suspected` is incremented by one and the event is otherwise processed exactly as a normal regular-file create

#### Scenario: hardlink_suspected is surfaced in the heartbeat without changing behavior
- **WHEN** the heartbeat publisher builds its periodic payload
- **THEN** the payload MAY include a `hardlink_suspected` field reflecting the current count, and no detection, hashing, or publication behavior is altered by its presence

### Requirement: Any classification that yields a hash discards the event when neither the hash nor the object type changed

The detector SHALL treat "no real change, no event" as a property of the detector, not of one branch. For **every** event classification that produces a `current_hash` — `file_modified`, `file_absent`, and `file_created` (which covers both `FAN_CREATE` and `FAN_MOVED_TO`) — the detector MUST discard the event without publishing when both of the following hold:

- `current_hash is not None` and `current_hash` equals the hash recorded in the baseline entry for that path, **and**
- the object type did not change: the path is a symlink now if and only if the baseline entry records it as a symlink (`entry.symlink_target is not None`).

A `MOVED_TO` whose resulting hash equals the baseline hash is not an integrity violation. RN-32 requires a restore to be verified against the baseline hash and RN-33 states that after a successful restore the baseline "already contains the correct hash, which is the same as the restored file's" — so reporting that file as a change contradicts rules the agent already implements. This closes the second half of the mechanism D19 / RN-117 describes: the `.fim_restore_tmp` suffix filter suppresses the temporary file's own events, and this discard suppresses the `FAN_MOVED_TO` that `os.replace` delivers on the **final** path, which never carries the suffix.

The discard MUST happen after `current_hash` is computed and **before** the event reserves an `event_id` or mutates the pending/reverse indices, so that a discarded event leaves no trace in the supersession bookkeeping. A discarded event MUST NOT write a baseline entry, add a snapshot, or mark the path absent.

The `file_deleted` classification is explicitly outside this requirement: it produces no hash, and the absence of a file is never "no change".

Object-type identity is required in addition to hash equality because a type change is itself an integrity violation (D33 / RN-127, symlink-as-object). Requiring it can only make the discard stricter, never more permissive. The symlink hash remains `sha256(os.readlink(path))` — the hash of the target **string**, never of its content.

#### Scenario: A MOVED_TO landing baseline-identical content produces no event
- **WHEN** a rename delivers `FAN_MOVED_TO` on a monitored path whose baseline entry records hash `H`, and the file's content now hashes to `H`
- **THEN** no event is published, no `event_id` is reserved, and the baseline entry is left untouched

#### Scenario: A FAN_CREATE landing baseline-identical content produces no event
- **WHEN** `FAN_CREATE` arrives for a path whose baseline entry is `present` with hash `H`, and the file hashes to `H`
- **THEN** no event is published

#### Scenario: A MOVED_TO landing different content still produces exactly one file_created event
- **WHEN** a rename delivers `FAN_MOVED_TO` on a monitored path whose baseline entry records hash `H`, and the file now hashes to `H2 != H`
- **THEN** exactly one event with `event_type: "file_created"` is published

#### Scenario: A type change is not suppressed even when the hashes coincide
- **WHEN** `FAN_MOVED_TO` arrives for a path whose baseline entry records a `symlink_target`, the path is now a regular file, and its content hash equals the baseline hash
- **THEN** the event is published, because the object type changed

#### Scenario: Recreating a previously deleted path is never suppressed
- **WHEN** a path was marked absent (baseline `status: "absent"`, `hash: null`) and a file is then created at that path
- **THEN** the event is published, because a null baseline hash equals no real hash

#### Scenario: A discarded event does not supersede the pending event for that path
- **WHEN** a `file_modified` event `e1` is pending for path `p` and a subsequent `MOVED_TO` on `p` is discarded by this requirement
- **THEN** `e1` remains the pending event registered for `p`, and no new `event_id` is mapped to it

#### Scenario: The suffix filter keeps working for the temporary file itself
- **WHEN** any fanotify event arrives for a path ending in `.fim_restore_tmp`
- **THEN** it is discarded at the top of processing, before classification, exactly as D19 / RN-117 already requires

### Requirement: The discard invariant is verified against a real filesystem, never a mocked one

The tests that cover this invariant SHALL exercise a real `BaselineEngine` over a real temporary directory and a real `DecisionEngine` performing real `os.open` / `os.replace` calls. Mocking the filesystem or the baseline is what allowed the feedback loop to survive a 417-test agent suite: the loop is a property of the coupling between the detector and the decision engine, and every unit was individually green while the coupling was broken. Only the network publisher and the arrival of kernel events may be simulated.

A test asserting that no event is published MUST first assert that the restore actually took effect — the restored file's content on disk and a journal entry in its completed state. "No event was published" is also true when the restore **fails**, which is the state the system was in for its entire life before change 41 (`agent-deployment-caps`) granted the write capabilities and derived `ReadWritePaths`. A test that only counts events would have passed green throughout that period without executing a single line of the path under test.

Every suppression scenario MUST have a symmetric scenario that asserts an event **is** published, so that a filter which suppresses too much is distinguishable from a correct one.

#### Scenario: The restore is proven to have happened before suppression is asserted
- **WHEN** the integration test drives a tamper-then-restore cycle
- **THEN** it asserts the file's on-disk content matches the known-good baseline content and the journal entry reached `completed`, and only then asserts that the resulting `MOVED_TO` published nothing

#### Scenario: The event pump terminates under a hard ceiling
- **WHEN** the regression test re-injects the `MOVED_TO` the kernel would deliver after each restore the engine actually performs
- **THEN** the pump runs under a fixed iteration ceiling that fails the test if reached, so a reintroduced loop is a legible failure rather than a hung CI job

