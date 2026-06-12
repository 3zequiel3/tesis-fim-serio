## ADDED Requirements

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
El agente SHALL persistir `ruleset_version: int` en `/var/lib/fim-agent/state.json`. Al iniciar, si el archivo no existe, MUST usarse `ruleset_version: 0` como default. Las escrituras MUST ser atómicas: escribir a `.tmp` y luego `os.replace()` al path final. El archivo MUST tener permisos `0600` y owner `fim-agent`.

#### Scenario: Primera inicialización sin state.json
- **WHEN** el agente arranca y `/var/lib/fim-agent/state.json` no existe
- **THEN** el estado en memoria tiene `ruleset_version = 0` y no se crea el archivo hasta la primera escritura

#### Scenario: Lectura de state existente
- **WHEN** `/var/lib/fim-agent/state.json` contiene `{"ruleset_version": 5}`
- **THEN** el agente carga `ruleset_version = 5` al iniciar

#### Scenario: Escritura atómica
- **WHEN** se actualiza `ruleset_version`
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
