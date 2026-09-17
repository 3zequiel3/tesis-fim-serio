## MODIFIED Requirements

### Requirement: Structured JSON logging with sanitization

El agente SHALL emitir todos sus logs en formato JSON estructurado vía structlog. Cada entrada MUST incluir `timestamp` (ISO 8601), `level`, y `event` (mensaje). El agente MUST filtrar valores de claves que contengan `password`, `token`, `secret`, `key`, o `credential` (case-insensitive) en cualquier campo del log, reemplazándolos con `"[REDACTED]"`.

El agente SHALL filtrar su salida por el nivel configurado (`--log-level`, sobreescribible por la variable de entorno `LOG_LEVEL`; default `info`), con el mismo mecanismo que ya usa el backend (`structlog.make_filtering_bound_logger`, D73/RN-167). A nivel `info`, una entrada de nivel `debug` MUST NOT llegar a stdout. Un nombre de nivel desconocido o mal formado SHALL resolverse a `info` y MUST NOT impedir el arranque del agente.

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

#### Scenario: A nivel info, un log debug no llega a stdout
- **WHEN** el agente arranca con el nivel `info` (default, sin `LOG_LEVEL` ni `--log-level` a `debug`) y ejecuta `log.debug("detector.out_of_scope_drop", path=..., total_drops=...)`
- **THEN** esa línea no aparece en stdout

#### Scenario: A nivel debug, un log debug sí llega a stdout
- **WHEN** el agente arranca con `--log-level debug` o `LOG_LEVEL=debug` y ejecuta `log.debug(...)`
- **THEN** la línea se emite en stdout como cualquier otro nivel

#### Scenario: LOG_LEVEL sobreescribe el nivel por argumento
- **WHEN** el agente arranca con `--log-level info` pero `LOG_LEVEL=debug` está definida en el entorno
- **THEN** el nivel efectivo es `debug` y los logs `debug` se emiten

#### Scenario: Nivel desconocido cae a info sin romper el arranque
- **WHEN** `LOG_LEVEL` o `--log-level` traen un valor que no es un nivel válido de `logging`
- **THEN** el agente arranca igual, con el nivel efectivo `info`
