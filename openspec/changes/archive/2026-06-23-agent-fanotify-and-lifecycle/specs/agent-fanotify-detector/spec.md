## MODIFIED Requirements

### Requirement: Marcado FAN_MARK_FILESYSTEM sobre watch_paths con exclusión de /var/lib/fim-agent

El detector SHALL inicializar un grupo fanotify con `pyfanotify 0.3.0` y marcar cada filesystem que contiene un `watch_path` usando `FAN_MARK_FILESYSTEM | FAN_MARK_ADD` con la máscara combinada `FAN_CLOSE_WRITE | FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE` (RN-01, RN-02, RN-110). El detector MUST NOT usar `FAN_REPORT_DFID_NAME` ni `FAN_REPORT_FID`: la resolución de path se realiza vía `ev.path` que pyfanotify resuelve internamente. El módulo `agent/detector.py` MUST excluir con `FAN_MARK_FILESYSTEM | FAN_MARK_IGNORED_MASK` el path `/var/lib/fim-agent/**` para prevenir ciclos de auto-detección (RN-04). El marcado MUST ocurrir antes de que el detector empiece a leer eventos.

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

## ADDED Requirements

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

- **WHEN** pyfanotify entrega un evento con `ev.path is None`
- **THEN** el detector registra un warning y no produce ningún cambio
