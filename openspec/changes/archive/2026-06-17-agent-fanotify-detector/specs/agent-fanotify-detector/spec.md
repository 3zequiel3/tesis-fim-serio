## ADDED Requirements

### Requirement: Marcado FAN_MARK_FILESYSTEM sobre watch_paths con exclusión de /var/lib/fim-agent

El detector SHALL inicializar un grupo fanotify con `pyfanotify 0.3.0` y marcar cada filesystem que contiene un `watch_path` usando `FAN_MARK_FILESYSTEM | FAN_MARK_ADD` con máscara `FAN_CLOSE_WRITE` (RN-01, RN-02). El módulo `agent/detector.py` MUST excluir con `FAN_MARK_FILESYSTEM | FAN_MARK_IGNORED_MASK` el path `/var/lib/fim-agent/**` para prevenir ciclos de auto-detección (RN-04). El marcado MUST ocurrir antes de que el detector empiece a leer eventos.

#### Scenario: Archivo monitoreado genera evento

- **WHEN** un proceso escribe y cierra un archivo bajo un `watch_path` configurado
- **THEN** el detector recibe el evento fanotify con el path, PID, UID y path del ejecutable causante

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

Tras recibir un evento fanotify, el detector SHALL calcular el SHA-256 del contenido actual del archivo y compararlo con el hash almacenado en el baseline cifrado (vía `agent/baseline.py`). Si el hash es idéntico, el detector MUST descartar el evento sin encolarlo ni emitir log de nivel warn o superior (RN-01). Si el hash difiere o el archivo no existe en baseline, el detector MUST proceder con la generación del evento.

#### Scenario: Mismo hash que baseline — evento descartado

- **WHEN** un proceso abre y cierra un archivo monitoreado sin modificar su contenido (hash idéntico al baseline)
- **THEN** el detector no encola ningún evento y no emite ninguna alerta

#### Scenario: Hash diferente al baseline — evento generado

- **WHEN** un proceso modifica el contenido de un archivo monitoreado (hash nuevo ≠ baseline)
- **THEN** el detector encola un evento con `event_type="file_modified"`, el hash anterior y el hash actual

#### Scenario: Archivo sin entrada en baseline

- **WHEN** el detector recibe un evento para un archivo que no tiene entrada en el baseline
- **THEN** el detector encola el evento con `event_type="file_modified"` usando `previous_hash=None`

#### Scenario: Archivo borrado entre evento y lectura

- **WHEN** el archivo es borrado entre la notificación fanotify y la lectura del detector
- **THEN** el detector encola un evento con `event_type="file_absent"` y actualiza el baseline a `status=absent`

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
