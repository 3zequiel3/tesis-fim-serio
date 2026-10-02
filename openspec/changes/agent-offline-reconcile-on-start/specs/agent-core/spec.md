## MODIFIED Requirements

### Requirement: Persistent state with atomic writes
El agente SHALL persistir `ruleset_version: int`, `last_stream_command_id: str`, `rules: list` e `initialized_roots: list[str]` en `/var/lib/fim-agent/state.json`. Al iniciar, si el archivo no existe, MUST usarse `ruleset_version: 0`, `last_stream_command_id: "0-0"`, `rules: []` e `initialized_roots: []` como defaults; un `state.json` previo sin la clave `initialized_roots` MUST cargarse con la lista vacía. `initialized_roots` SHALL contener, con el mismo string que figura en la configuración, cada `watch_path` que completó un primer escaneo (D80 / RN-174), y MUST serializarse ordenada. Toda escritura de `state.json` MUST pasar por un único punto de serialización que preserva los cuatro campos de forma no destructiva: actualizar un campo MUST NOT borrar los demás (F2). Cuando `RulesCache` persiste reglas, MUST delegar la escritura a ese punto único (vía `AgentState`) en lugar de escribir `state.json` por su cuenta. Las escrituras MUST ser atómicas: escribir a `.tmp` y luego `os.replace()` al path final. El archivo MUST tener permisos `0600` y owner `fim-agent`.

#### Scenario: Primera inicialización sin state.json
- **WHEN** el agente arranca y `/var/lib/fim-agent/state.json` no existe
- **THEN** el estado en memoria tiene `ruleset_version = 0`, `last_stream_command_id = "0-0"`, `rules = []` e `initialized_roots = []`, y no se crea el archivo hasta la primera escritura

#### Scenario: Lectura de state existente
- **WHEN** `/var/lib/fim-agent/state.json` contiene `{"ruleset_version": 5, "last_stream_command_id": "100-0", "rules": [...], "initialized_roots": ["/etc"]}`
- **THEN** el agente carga `ruleset_version = 5`, `last_stream_command_id = "100-0"`, las reglas e `initialized_roots = ["/etc"]` al iniciar

#### Scenario: state.json anterior sin initialized_roots
- **WHEN** `state.json` contiene sólo `ruleset_version`, `last_stream_command_id` y `rules`
- **THEN** el agente carga esos valores e `initialized_roots = []`, sin tratar el archivo como corrupto

#### Scenario: Persistir el cursor de comandos no borra las reglas
- **WHEN** el publisher procesa un comando y persiste un nuevo `last_stream_command_id`
- **THEN** `state.json` conserva el `rules`, el `ruleset_version` y el `initialized_roots` previos intactos

#### Scenario: Persistir reglas no borra el cursor de comandos
- **WHEN** `RulesCache` recibe un `rule_sync` y persiste nuevas reglas con un nuevo `ruleset_version`
- **THEN** `state.json` conserva el `last_stream_command_id` y el `initialized_roots` previos intactos

#### Scenario: Escritura atómica
- **WHEN** se actualiza cualquier campo del estado
- **THEN** el agente escribe a `state.json.tmp` y luego llama `os.replace("state.json.tmp", "state.json")`

#### Scenario: Permisos del archivo de estado
- **WHEN** `state.json` es creado por el agente
- **THEN** el archivo tiene permisos `0600` y owner `fim-agent`

## ADDED Requirements

### Requirement: El arranque reconcilia el baseline antes de arrancar el detector

Al arrancar, el agente SHALL, en este orden: podar `initialized_roots` a los `watch_paths` configurados; ejecutar el escaneo inicial y agregar a `initialized_roots` las raíces que completó, persistiendo `state.json`; construir publisher, motor de decisión y detector; rehidratar el journal (RN-83); ejecutar la reconciliación al arrancar y emitir cada hallazgo por el camino normal del detector; y recién entonces arrancar el detector y las demás corrutinas. Al terminar la reconciliación el agente SHALL registrar `baseline.reconcile.complete` con los conteos `deleted`, `modified`, `created`, `suppressed_already_reported`, `unchanged`, `errors` y `duration_ms`. Una excepción inesperada de la reconciliación MUST registrarse como `baseline.reconcile.failed` y MUST NOT abortar el arranque. Sin detector disponible la reconciliación MUST NOT ejecutarse y el agente SHALL registrar `baseline.reconcile.skipped`. Al agregar o retirar `watch_paths` en runtime (`update_config`), el agente SHALL actualizar `initialized_roots` en la misma escritura de `state.json`. (D80 / RN-174, RN-83)

#### Scenario: El reconcile corre después de la rehidratación y antes del detector
- **WHEN** el agente arranca con journal pendiente y cambios offline
- **THEN** la rehidratación termina antes de la primera emisión del reconcile, y la última emisión del reconcile ocurre antes de que el detector instale sus marcas

#### Scenario: Log de cierre con conteos
- **WHEN** el reconcile termina con una eliminación, una modificación y una creación
- **THEN** se registra `baseline.reconcile.complete` con `deleted=1`, `modified=1`, `created=1`

#### Scenario: Una falla del reconcile no impide el arranque
- **WHEN** `reconcile_on_start` lanza una excepción inesperada
- **THEN** se registra `baseline.reconcile.failed` y el detector arranca igual

#### Scenario: Raíz retirada de la configuración
- **WHEN** `state.json` tiene una raíz en `initialized_roots` que ya no figura en `watch_paths`
- **THEN** la raíz se quita de `initialized_roots` antes del escaneo inicial

#### Scenario: Raíz agregada por update_config
- **WHEN** un comando `update_config` agrega un `watch_path` y el agente lo escanea con `run_scan`
- **THEN** la raíz queda en `initialized_roots` en el `state.json` persistido
