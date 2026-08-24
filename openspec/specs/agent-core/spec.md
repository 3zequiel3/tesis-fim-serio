# agent-core Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

### Requirement: Bootstrap config loading from YAML
El agente SHALL leer su configuración inicial desde `/etc/fim-agent/config.yaml` al arrancar. El archivo MUST contener los campos: `agent_id` (string), `valkey_url` (string), `ca_cert_path` (string), `watch_paths` (lista de strings), y sección `storage` con `baseline_dir`, `queue_dir`, `journal_dir` (strings). El agente MUST fallar con mensaje de error claro si el archivo no existe o tiene campos obligatorios faltantes.

#### Scenario: Arranque con config válida
- **WHEN** el servicio arranca y `/etc/fim-agent/config.yaml` existe con todos los campos requeridos
- **THEN** el agente carga la configuración sin errores y continúa la inicialización

#### Scenario: Arranque sin config
- **WHEN** el servicio arranca y `/etc/fim-agent/config.yaml` no existe
- **THEN** el agente termina con exit code 1 y loguea `"Config file not found: /etc/fim-agent/config.yaml"`

#### Scenario: Config con campo faltante
- **WHEN** el archivo existe pero le falta el campo `agent_id`
- **THEN** el agente termina con exit code 1 y loguea un mensaje indicando qué campo falta

### Requirement: Structured JSON logging with sanitization
El agente SHALL emitir todos sus logs en formato JSON estructurado vía structlog. Cada entrada MUST incluir `timestamp` (ISO 8601), `level`, y `event` (mensaje). El agente MUST filtrar valores de claves que contengan `password`, `token`, `secret`, `key`, o `credential` (case-insensitive) en cualquier campo del log, reemplazándolos con `"[REDACTED]"`.

#### Scenario: Log de evento normal
- **WHEN** el agente loguea `log.info("agent started", agent_id="host-01")`
- **THEN** la salida es una línea JSON con `timestamp`, `level: "info"`, `event: "agent started"`, `agent_id: "host-01"`

#### Scenario: Log con campo sensible
- **WHEN** el agente loguea un evento que incluye una clave `bootstrap_secret`
- **THEN** la salida JSON muestra `bootstrap_secret: "[REDACTED]"` en lugar del valor real

#### Scenario: Formato JSON en producción
- **WHEN** la variable de entorno `LOG_FORMAT` no está definida o es `json`
- **THEN** cada línea de log es un objeto JSON válido parseable

#### Scenario: Formato console en desarrollo
- **WHEN** `LOG_FORMAT=console`
- **THEN** los logs se emiten en formato humano-legible (ConsoleRenderer de structlog)

### Requirement: Persistent state with atomic writes
El agente SHALL persistir `ruleset_version: int`, `last_stream_command_id: str` y `rules: list` en `/var/lib/fim-agent/state.json`. Al iniciar, si el archivo no existe, MUST usarse `ruleset_version: 0`, `last_stream_command_id: "0-0"` y `rules: []` como defaults. Toda escritura de `state.json` MUST pasar por un único punto de serialización que preserva los tres campos de forma no destructiva: actualizar un campo MUST NOT borrar los demás (F2). Cuando `RulesCache` persiste reglas, MUST delegar la escritura a ese punto único (vía `AgentState`) en lugar de escribir `state.json` por su cuenta. Las escrituras MUST ser atómicas: escribir a `.tmp` y luego `os.replace()` al path final. El archivo MUST tener permisos `0600` y owner `fim-agent`.

#### Scenario: Primera inicialización sin state.json
- **WHEN** el agente arranca y `/var/lib/fim-agent/state.json` no existe
- **THEN** el estado en memoria tiene `ruleset_version = 0`, `last_stream_command_id = "0-0"` y `rules = []`, y no se crea el archivo hasta la primera escritura

#### Scenario: Lectura de state existente
- **WHEN** `/var/lib/fim-agent/state.json` contiene `{"ruleset_version": 5, "last_stream_command_id": "100-0", "rules": [...]}`
- **THEN** el agente carga `ruleset_version = 5`, `last_stream_command_id = "100-0"` y las reglas al iniciar

#### Scenario: Persistir el cursor de comandos no borra las reglas
- **WHEN** el publisher procesa un comando y persiste un nuevo `last_stream_command_id`
- **THEN** `state.json` conserva el `rules` y el `ruleset_version` previos intactos

#### Scenario: Persistir reglas no borra el cursor de comandos
- **WHEN** `RulesCache` recibe un `rule_sync` y persiste nuevas reglas con un nuevo `ruleset_version`
- **THEN** `state.json` conserva el `last_stream_command_id` previo intacto

#### Scenario: Escritura atómica
- **WHEN** se actualiza cualquier campo del estado
- **THEN** el agente escribe a `state.json.tmp` y luego llama `os.replace("state.json.tmp", "state.json")`

#### Scenario: Permisos del archivo de estado
- **WHEN** `state.json` es creado por el agente
- **THEN** el archivo tiene permisos `0600` y owner `fim-agent`

### Requirement: Directory layout with restricted permissions
El script `install.sh` SHALL crear los directorios de trabajo del agente con los permisos correctos. Los directorios MUST existir antes de que el servicio arranque. El directorio `/var/lib/fim-agent/` y todos sus subdirectorios directos (`baseline`, `quarantine`, `queue`, `journal`, `secrets`, `certs`) MUST tener permisos `0700` y owner `fim-agent`. El directorio `/var/log/fim-agent/` MUST tener permisos `0750` y owner `fim-agent`. El directorio `/etc/fim-agent/` MUST tener permisos `0750` y owner `fim-agent`.

#### Scenario: Permisos de /var/lib/fim-agent/
- **WHEN** `install.sh` se ejecuta en un sistema limpio
- **THEN** `stat /var/lib/fim-agent` muestra `0700` y owner `fim-agent`

#### Scenario: Subdirectorios creados correctamente
- **WHEN** `install.sh` se ejecuta
- **THEN** existen `/var/lib/fim-agent/{baseline,quarantine,queue,journal,secrets,certs}/` con permisos `0700`

#### Scenario: Idempotencia de install.sh
- **WHEN** `install.sh` se ejecuta dos veces consecutivas
- **THEN** la segunda ejecución termina sin errores y los permisos son los mismos

### Requirement: Systemd service unit with capability hardening
La unidad `fim-agent.service` SHALL arrancar el agente con `AmbientCapabilities=CAP_SYS_ADMIN` y `CapabilityBoundingSet=CAP_SYS_ADMIN`. MUST aplicarse `ProtectSystem=strict`, `NoNewPrivileges=true`, `PrivateTmp=true`. El servicio MUST correr como user `fim-agent` con `ReadWritePaths=/var/lib/fim-agent /var/log/fim-agent`. El servicio MUST configurarse con `Restart=on-failure` y `RestartSec=5s`.

#### Scenario: Servicio arranca con capabilities correctas
- **WHEN** `systemctl start fim-agent`
- **THEN** el proceso corre como `fim-agent` y `capsh --decode=$(cat /proc/$(pgrep -f fim-agent)/status | grep CapAmb | awk '{print $2}')` muestra `cap_sys_admin`

#### Scenario: Hardening de namespaces activo
- **WHEN** el servicio está corriendo
- **THEN** `systemctl show fim-agent | grep ProtectSystem` muestra `strict` y `NoNewPrivileges=yes`

#### Scenario: Restart automático en fallo
- **WHEN** el proceso del agente muere inesperadamente
- **THEN** systemd lo reinicia después de 5 segundos

### Requirement: Install script creates isolated Python environment
`install.sh` SHALL crear un virtual environment Python en `/opt/fim-agent/venv/` e instalar las dependencias del agente desde `agent/requirements.txt` con versiones fijadas. El script MUST ser idempotente.

#### Scenario: Instalación limpia
- **WHEN** `install.sh` se ejecuta en un sistema sin instalación previa
- **THEN** existe `/opt/fim-agent/venv/bin/python` y `pip show pyfanotify` dentro del venv muestra `0.3.0`

#### Scenario: Reinstalación idempotente
- **WHEN** `install.sh` se ejecuta en un sistema con instalación previa
- **THEN** el script termina sin errores y las versiones de paquetes no cambian

### Requirement: El handler de shutdown propaga el flag al heartbeat

El handler de señal `SIGTERM`/`SIGINT` del agente SHALL llamar `publisher.set_shutdown(True)` antes de iniciar el drenaje de la cola y antes de activar el `stop_event`. Durante el drenaje el heartbeat MUST publicar `shutdown=true` en el stream `agent_heartbeat` para que el backend refleje que el agente está drenando (RN-93, G4).

#### Scenario: SIGTERM marca el publisher en shutdown

- **WHEN** el agente recibe `SIGTERM`
- **THEN** el handler llama `publisher.set_shutdown(True)` antes de drenar la cola y de activar `stop_event`

#### Scenario: Heartbeat publica shutdown durante el drenaje

- **WHEN** el agente está drenando la cola tras recibir `SIGTERM`
- **THEN** los heartbeats publicados durante el drenaje contienen `shutdown=true`

### Requirement: Configuración del intervalo de chequeo de renovación de certificado

`AgentConfig` SHALL exponer el campo `cert_renewal_check_interval_h: float` con default `24.0`, que define cada cuántas horas la tarea de renovación de certificado verifica la vigencia del certificado de cliente (RN-111, D13). Un valor ausente en el `config.yaml` MUST resolverse al default `24.0`.

#### Scenario: Default cuando no se especifica

- **WHEN** el `config.yaml` no define `cert_renewal_check_interval_h`
- **THEN** la configuración resuelve `cert_renewal_check_interval_h = 24.0`

#### Scenario: Valor explícito respetado

- **WHEN** el `config.yaml` define `cert_renewal_check_interval_h: 12.0`
- **THEN** la configuración resuelve `cert_renewal_check_interval_h = 12.0`

### Requirement: El loop principal arranca la tarea de renovación de certificado

El loop principal del agente SHALL registrar la tarea `_cert_renewal_loop` entre sus corrutinas cuando el agente ya está bootstrapped, pasándole el `stop_event` para permitir su terminación durante el shutdown. La tarea MUST coexistir con el publisher, el heartbeat y el detector sin bloquearlos (RN-111, D13, G3).

#### Scenario: Tarea registrada en el loop principal

- **WHEN** el agente arranca con certificados bootstrapped
- **THEN** `_cert_renewal_loop` se incluye entre las corrutinas pasadas a `asyncio.gather`

#### Scenario: La tarea termina al hacer shutdown

- **WHEN** el agente recibe `SIGTERM` y se activa el `stop_event`
- **THEN** la tarea de renovación de certificado termina sin bloquear el cierre del agente

### Requirement: Signal handlers are registered only after queue and publisher exist

The agent main entrypoint SHALL initialize `queue` and `publisher` to `None`, construct them, and only THEN register the `SIGTERM`/`SIGINT` handlers via `loop.add_signal_handler`. The `_shutdown` callback MUST early-return when `queue` or `publisher` is still `None`, so a signal delivered during startup is a safe no-op rather than a `NoneType` access. (FA1)

#### Scenario: Signal during startup before publisher exists is a safe no-op
- **WHEN** a `SIGTERM` is delivered after handlers are registered but `publisher` is still `None`
- **THEN** `_shutdown` early-returns without raising, leaving the process to finish startup or exit cleanly

#### Scenario: Handlers are registered after queue and publisher construction
- **WHEN** the agent main coroutine sets up signal handling
- **THEN** `loop.add_signal_handler(SIGTERM/SIGINT, ...)` is invoked only after `queue = EventQueue(...)` and `publisher = Publisher(...)` have been assigned

### Requirement: Shutdown closes the fanotify fd and joins the reader thread

On shutdown the agent SHALL, in its `finally` block, call `detector.close()` before the process exits. `detector.close()` MUST close the fanotify file descriptor — which unblocks the `fan-reader` thread parked in the blocking `read()` syscall — and then `join()` that thread with a 5-second timeout. The agent MUST NOT leak the fanotify fd or leave an orphaned reader thread on exit. (FA4)

#### Scenario: Clean shutdown unblocks and joins the reader thread
- **WHEN** the agent receives `SIGTERM` while the `fan-reader` thread is blocked in `read()`
- **THEN** `detector.close()` closes the fanotify fd, the `read()` syscall returns/raises, and the thread is joined within the 5-second timeout

#### Scenario: No fanotify fd leak on exit
- **WHEN** the agent process terminates through its normal shutdown path
- **THEN** the fanotify fd has been explicitly closed by `detector.close()` and is not relying on process teardown
