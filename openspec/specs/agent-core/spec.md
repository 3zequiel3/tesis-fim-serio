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
La unidad `fim-agent.service` SHALL arrancar el agente con `AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN` y el mismo conjunto en `CapabilityBoundingSet`. `CAP_DAC_READ_SEARCH` la exige `open_by_handle_at(2)` del modo FID (D46/RN-140); `CAP_DAC_OVERRIDE`, `CAP_FOWNER` y `CAP_CHOWN` las requieren las acciones de restauración y cuarentena sobre archivos de otros usuarios. MUST aplicarse `ProtectSystem=strict`, `NoNewPrivileges=true`, `PrivateTmp=true`. El servicio MUST correr como user `fim-agent` con `ReadWritePaths=/var/lib/fim-agent /var/log/fim-agent`. El servicio MUST configurarse con `Restart=on-failure` y `RestartSec=5s`.

#### Scenario: Servicio arranca con capabilities correctas
- **WHEN** `systemctl start fim-agent`
- **THEN** el proceso corre como `fim-agent` y `capsh --decode=$(cat /proc/$(pgrep -f fim-agent)/status | grep CapAmb | awk '{print $2}')` muestra `cap_sys_admin` y `cap_dac_read_search`

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
- **THEN** existe `/opt/fim-agent/venv/bin/python` y `pip freeze` dentro del venv coincide con las versiones fijadas en `agent/requirements.txt`
- **AND** `pyfanotify` NO está instalado: el detector usa el backend propio de `agent/_fanotify.py` (D46/RN-140)

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

### Requirement: Instalador parametrizable con prompts para valores faltantes (D56/RN-150)

`agent/install.sh` SHALL aceptar sus entradas por flags o por variables de entorno, con precedencia flag > variable de entorno > prompt interactivo:

| Entrada | Flag | Variable de entorno |
|---|---|---|
| Host del servidor (DNS o IP) | `--server-host` | `FIM_SERVER_HOST` |
| `agent_id` (default: hostname del equipo) | `--agent-id` | `FIM_AGENT_ID` |
| `watch_paths` (repetible / separadas por comas) | `--watch-path` | `FIM_WATCH_PATHS` |
| Ruta del `ca.pem` del servidor | `--ca-cert` | `FIM_CA_CERT` |
| Huella SHA-256 esperada de la CA | `--ca-fingerprint` | `FIM_CA_FINGERPRINT` |
| Archivo con el secreto de bootstrap | `--bootstrap-secret-file` | `FIM_BOOTSTRAP_SECRET_FILE` |

A partir del host SHALL derivar `backend_url=https://<host>:8444`, `mtls_backend_url=https://<host>:8443` y `valkey_url=valkeys://<host>:6380`, encerrando entre corchetes un literal IPv6. Cada `watch_path` SHALL ser absoluto, existir, y pasar la misma validación que el generador del drop-in (`agent.deployment`). Con `--non-interactive`, un valor faltante SHALL terminar la instalación con exit distinto de 0 nombrando la entrada, antes de modificar nada bajo `/etc/fim-agent`. `config.yaml` SHALL generarse a partir de `agent/deploy/config.yaml.example`, reemplazando sólo los campos derivados de las entradas y conservando los demás defaults.

*(Revisado el 2026-09-15 tras la aceptación en VPS — hallazgo 14.2)* `--ca-cert` y `--bootstrap-secret-file`, cuando se dan como rutas relativas, SHALL resolverse contra el directorio desde el que se invocó `install.sh`, en las tres fases (`plan`, `apply` y `check`) — incluidas `apply` y `check`, que cambian de directorio de trabajo internamente.

*(Revisado el 2026-09-15 — hallazgo 14.1)* `install.sh` SHALL aceptar además `--python <ruta>` para elegir el intérprete usado para crear el venv (precedencia sobre `FIM_AGENT_PYTHON`, default `python3`), y SHALL validar la versión de ese intérprete **antes** de crear el venv: exactamente Python 3.13. Con otra versión, o si el intérprete no existe, SHALL abortar con exit distinto de 0 sin crear el venv, nombrando la versión encontrada, la requerida y la alternativa (`uv python install 3.13`). Esta validación SHALL NOT repetirse al reinstalar sobre un venv ya creado.

#### Scenario: Instalación con flags completos
- **WHEN** se ejecuta `install.sh --non-interactive --server-host 203.0.113.10 --agent-id web-01 --watch-path /srv/app --ca-cert ./fim-ca.pem --ca-fingerprint <huella> --bootstrap-secret-file ./secret` en un host sin instalación previa
- **THEN** `/etc/fim-agent/config.yaml` contiene `agent_id: web-01`, `backend_url: https://203.0.113.10:8444`, `mtls_backend_url: https://203.0.113.10:8443`, `valkey_url: valkeys://203.0.113.10:6380` y `watch_paths: [/srv/app]`

#### Scenario: `agent_id` por defecto
- **WHEN** no se provee `agent_id` y se acepta el prompt vacío
- **THEN** `agent_id` es el hostname del equipo

#### Scenario: Ruta vigilada inválida
- **WHEN** un `watch_path` es relativo o no existe
- **THEN** la instalación termina con exit distinto de 0 nombrando la ruta y no se escribe nada bajo `/etc/fim-agent`

#### Scenario: Valor faltante en modo no interactivo
- **WHEN** se ejecuta con `--non-interactive` sin `--server-host` ni `FIM_SERVER_HOST`
- **THEN** termina con exit distinto de 0 nombrando la entrada faltante

#### Scenario: Rutas relativas de `--ca-cert` y `--bootstrap-secret-file` en `apply`/`check`
- **WHEN** se ejecuta `install.sh` desde `/srv/ops` con `--ca-cert ./fim-ca.pem --bootstrap-secret-file ./secret` (rutas relativas a `/srv/ops`)
- **THEN** las fases `plan`, `apply` y `check` leen ambos archivos correctamente, aunque `apply` y `check` cambien de directorio de trabajo a `/opt/fim-agent` internamente

#### Scenario: Intérprete con versión incorrecta
- **WHEN** el `python3` por defecto (o el que indica `--python`) no es la versión 3.13
- **THEN** la instalación termina con exit distinto de 0, nombra la versión encontrada y la requerida, sugiere `uv python install 3.13`, y no crea `/opt/fim-agent/venv`

#### Scenario: `--python` selecciona el intérprete del venv
- **WHEN** se ejecuta con `--python <ruta-a-python-3.13>` en un host sin instalación previa
- **THEN** el venv se crea con ese intérprete

### Requirement: El secreto de bootstrap nunca se acepta como argumento (D56/RN-150)

El instalador SHALL obtener el secreto de bootstrap únicamente por prompt oculto (sin eco en la terminal) o leyéndolo de un archivo. SHALL NOT existir flag, argumento posicional ni variable de entorno que transporte el valor del secreto; un flag no reconocido que lo intente (por ejemplo `--bootstrap-secret`) SHALL rechazarse sin escribir nada. El secreto SHALL validarse (al menos 16 caracteres) antes de escribirlo, SHALL escribirse sólo en `/etc/fim-agent/env` como `FIM_BOOTSTRAP_SECRET` (modo `0600`, `root:root`), y SHALL NOT aparecer en `config.yaml`, en la salida del instalador, en logs, ni en los argumentos de ningún proceso que el instalador lance.

*(Revisado el 2026-09-15 tras la aceptación en VPS — hallazgo 14.3)* El secreto es la única entrada de la tabla anterior cuya ausencia en modo no interactivo SHALL NOT terminar la instalación cuando el host ya tiene un certificado de agente propio vigente (el mismo chequeo que usa el propio agente para decidir si ya bootstrapeó, `agent.bootstrap.is_bootstrapped`) y no se pasó `--reconfigure`: reinstalar un agente ya enrolado no lo exige, porque la configuración autoritativa ya vive en el backend. En cualquier otro caso — primera instalación, o `--reconfigure` — el secreto sigue siendo obligatorio en modo no interactivo.

#### Scenario: Intento de pasar el secreto por argumento
- **WHEN** se ejecuta `install.sh --bootstrap-secret 0123456789abcdef`
- **THEN** termina con exit distinto de 0 indicando que el secreto se provee por prompt o archivo
- **AND** no se escribe ningún archivo bajo `/etc/fim-agent`

#### Scenario: Secreto desde archivo
- **WHEN** se provee `--bootstrap-secret-file` con un secreto válido
- **THEN** `/etc/fim-agent/env` contiene `FIM_BOOTSTRAP_SECRET=<secreto>` con modo `0600` y dueño `root:root`
- **AND** el valor no aparece en la salida del instalador ni en los argumentos de los subprocesos lanzados

#### Scenario: Secreto demasiado corto
- **WHEN** el secreto provisto tiene menos de 16 caracteres
- **THEN** la instalación termina con exit distinto de 0 sin escribir `/etc/fim-agent/env`

#### Scenario: Reinstalación de un agente ya enrolado sin secreto
- **WHEN** se ejecuta `install.sh --non-interactive` sin `--bootstrap-secret-file` ni `--reconfigure` sobre un host con un certificado de agente propio y vigente
- **THEN** la instalación continúa (exit 0 si el resto de las verificaciones pasa) sin exigir el secreto de bootstrap, y `/etc/fim-agent/env` queda sin modificar

#### Scenario: `--reconfigure` sigue exigiendo el secreto aunque el agente esté enrolado
- **WHEN** se ejecuta `install.sh --non-interactive --reconfigure` sin `--bootstrap-secret-file` sobre un host con un certificado de agente propio y vigente
- **THEN** la instalación termina con exit distinto de 0 nombrando el secreto de bootstrap como entrada faltante

### Requirement: Ancla de confianza verificada por huella SHA-256 (D56/RN-150, RN-114)

El instalador SHALL calcular la huella SHA-256 sobre la codificación DER del certificado provisto como `ca.pem` y SHALL compararla con la huella esperada, aceptando hexadecimal sin distinguir mayúsculas e ignorando `:` y espacios —el mismo formato que entrega el paso de registro del servidor—. Si no coinciden, si el archivo no es un certificado PEM válido o si no es un certificado de CA, SHALL abortar antes de escribir cualquier archivo bajo `/etc/fim-agent` y antes de habilitar el servicio, mostrando la huella esperada y la calculada. Si coinciden, SHALL copiar el certificado a `ca_cert_path` con modo `0644` y dueño `root`.

#### Scenario: Huella coincidente
- **WHEN** la huella calculada coincide con la esperada
- **THEN** el certificado queda en `ca_cert_path` y la instalación continúa

#### Scenario: Huella distinta
- **WHEN** la huella calculada no coincide con la esperada
- **THEN** la instalación termina con exit distinto de 0, muestra ambas huellas y no escribe nada bajo `/etc/fim-agent`

#### Scenario: Formatos equivalentes de huella
- **WHEN** la huella esperada se provee como `AB:CD:...` en mayúsculas y la calculada es `abcd...`
- **THEN** se consideran coincidentes

### Requirement: La configuración existente no se sobrescribe sin reconfiguración explícita (D56/RN-150)

Si `/etc/fim-agent/config.yaml` o `/etc/fim-agent/env` existen, el instalador SHALL NOT modificarlos salvo que se invoque con `--reconfigure`. Sin ese flag, si se proveyeron entradas que difieren de la configuración existente, SHALL advertir que se ignoran y cómo aplicarlas. Con `--reconfigure`, SHALL regenerarlos a partir de las entradas, conservando una copia del archivo anterior. Al finalizar toda ejecución SHALL informar que, tras el primer bootstrap, la configuración autoritativa vive en el backend y se modifica desde la consola, y que reconfigurar localmente sólo afecta los datos de conexión de un agente aún no enrolado.

#### Scenario: Re-ejecución sin reconfiguración
- **WHEN** se ejecuta `install.sh` sobre un host con `config.yaml` y `env` existentes, sin `--reconfigure`
- **THEN** ambos archivos quedan byte a byte idénticos

#### Scenario: Reconfiguración explícita
- **WHEN** se ejecuta con `--reconfigure` y un `--server-host` distinto
- **THEN** `config.yaml` refleja las URLs derivadas del nuevo host y existe una copia del archivo anterior

#### Scenario: Aviso de autoridad de la configuración
- **WHEN** termina cualquier ejecución del instalador
- **THEN** la salida informa que tras el primer bootstrap la configuración autoritativa vive en el backend

### Requirement: La reinstalación reemplaza el código instalado (D56/RN-150)

Re-ejecutar el instalador SHALL reemplazar el árbol de código instalado en `/opt/fim-agent/agent` por el de la fuente, en lugar de copiar la fuente dentro del destino existente. Tras la reinstalación, `/opt/fim-agent/agent/agent` SHALL NOT existir, los archivos eliminados de la fuente SHALL NOT permanecer en el destino, y la propiedad SHALL seguir siendo `root:root` (D36/RN-130). Si el servicio estaba activo, SHALL reiniciarse para ejecutar el código nuevo.

#### Scenario: Código actualizado
- **WHEN** se modifica un módulo en la fuente y se re-ejecuta el instalador
- **THEN** el archivo instalado es idéntico al de la fuente
- **AND** no existe `/opt/fim-agent/agent/agent`

#### Scenario: Archivo eliminado en la fuente
- **WHEN** un archivo existe en la instalación previa pero ya no en la fuente
- **THEN** tras la reinstalación el archivo no existe en `/opt/fim-agent/agent`

#### Scenario: Servicio activo reiniciado
- **WHEN** `fim-agent.service` está activo al re-ejecutar el instalador
- **THEN** el servicio se reinicia y el proceso resultante carga el código nuevo

### Requirement: Verificación de alcance antes de habilitar el servicio (D56/RN-150)

Antes de habilitar `fim-agent.service`, el instalador SHALL verificar, para el puerto 8444 y el puerto 6380 del host del servidor, la resolución del nombre, la conexión TCP y un handshake TLS que verifique el certificado del servidor contra la CA verificada y su SAN contra el host configurado, con un tiempo máximo acotado por intento. SHALL informar el resultado por puerto distinguiendo resolución, conexión rechazada o agotada, y verificación TLS (incluida la discrepancia de hostname). En el puerto 6380 el rechazo posterior por falta de certificado de cliente SHALL NOT contarse como falla, porque el agente todavía no se enroló. Si alguna verificación falla, el instalador SHALL completar la instalación sin habilitar ni arrancar el servicio y SHALL terminar con exit distinto de 0; si todas pasan, SHALL habilitar el servicio y arrancarlo cuando haya un secreto de bootstrap provisto para un host sin certificado propio.

#### Scenario: Servidor alcanzable
- **WHEN** 8444 y 6380 responden con certificados que encadenan a la CA y cubren el host
- **THEN** el instalador informa ambos puertos como alcanzables y habilita el servicio

#### Scenario: Puerto 6380 inalcanzable
- **WHEN** la conexión TCP a 6380 es rechazada
- **THEN** el instalador informa la falla nombrando el puerto 6380 y la causa, no habilita el servicio y termina con exit distinto de 0

#### Scenario: Hostname no cubierto por el SAN
- **WHEN** el certificado presentado en 8444 encadena a la CA pero no cubre el host configurado
- **THEN** el instalador informa una discrepancia de hostname y sugiere revisar `FIM_PUBLIC_HOSTS` del servidor

