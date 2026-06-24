# Spec: agent-config-commands

Capability: Handlers del agente FIM para los comandos de configuración entrantes desde el backend — `update_config` (recarga de watch_paths en fanotify + baseline scan de paths nuevos) y `rescan_baseline` (scan completo de baseline + event_ack), integrados en el dispatch de `agent/commands.py` (C13).

---

## ADDED Requirements

### Requirement: Destructive command handlers are registered at startup

The agent SHALL register the command-handler dependencies (baseline engine, agent state, journal, quarantine directory, detector) on the publisher before the command listener starts processing the `commands` stream, so that `baseline_update`, `restore_file`, `quarantine_file`, and `rescan_baseline` are dispatched to their real handlers instead of being silently ignored. (RN-79, RN-83)

#### Scenario: Handlers registered during agent startup

- **WHEN** the agent process starts on Linux and finishes constructing the detector
- **THEN** `publisher.register_command_handlers(engine, state, journal, quarantine_dir, detector)` is called before `publisher.run` begins consuming the `commands` stream
- **AND** the publisher's `_baseline_engine`, `_agent_state`, `_journal`, `_quarantine_dir`, and `_detector` references are all non-null.

#### Scenario: restore_file is executed, not dropped

- **WHEN** the backend publishes a valid `restore_file` command targeted at this agent
- **THEN** the agent dispatches it through `commands.dispatch` and performs the restore
- **AND** the agent does NOT log `publisher.command_handler_not_registered`.

#### Scenario: quarantine_file is executed, not dropped

- **WHEN** the backend publishes a valid `quarantine_file` command targeted at this agent
- **THEN** the agent dispatches it through `commands.dispatch` and quarantines the file.

### Requirement: All inbound commands are HMAC-verified at a single entry point

The agent SHALL verify the HMAC-SHA256 signature of every message read from the `commands` stream through a single entry point before any side effect occurs, rejecting messages whose signature is missing or invalid. No command type — present or future, including `event_ack`, `update_config`, and `rule_sync` — SHALL be acted upon without passing this verification. (RN-79)

#### Scenario: Valid signature is accepted

- **WHEN** a command message arrives with `signature == HMAC-SHA256(shared_secret, canonical_json(payload))`
- **THEN** the single entry point returns the parsed payload
- **AND** the command is processed normally.

#### Scenario: Invalid signature is rejected

- **WHEN** a command message arrives whose `signature` does not match the expected HMAC over its canonical payload
- **THEN** the single entry point returns `None`
- **AND** no handler runs, the offline queue is not modified, fanotify watchers are not reconfigured, and no rules are injected.

#### Scenario: Missing signature is rejected

- **WHEN** a command message arrives with no `signature` field
- **THEN** the single entry point returns `None` and the message is dropped without side effects.

#### Scenario: event_ack without valid signature does not purge the queue

- **WHEN** an `event_ack` message with an invalid signature is written to the `commands` stream
- **THEN** the agent does NOT remove the referenced event from the offline queue and does NOT clear the corresponding pending entry.

#### Scenario: Malformed JSON is rejected

- **WHEN** a message payload is not valid JSON
- **THEN** the entry point returns `None` and the message is dropped without raising.

### Requirement: target_agent_id filtering is preserved after verification

The agent SHALL ignore commands whose `target_agent_id` is set to a value other than this agent's `agent_id`, while still accepting broadcast commands where `target_agent_id` is null or absent. This filtering SHALL apply to every command type. (D5, RN-106)

#### Scenario: Command for another agent is ignored

- **WHEN** a validly signed command arrives with `target_agent_id` not equal to this agent's `agent_id`
- **THEN** the command is ignored with no side effects.

#### Scenario: Broadcast command is accepted

- **WHEN** a validly signed command arrives with `target_agent_id` null or absent
- **THEN** the command is processed normally.

### Requirement: update_config is dispatched only through the versioned handler

The agent SHALL route `update_config` exclusively through `commands.dispatch` → `handle_update_config`, which enforces `ruleset_version` monotonicity and persists the new state. The agent SHALL NOT contain any direct `update_config` branch that reconfigures fanotify watchers while bypassing the version check. (RN-75)

#### Scenario: No duplicated direct update_config branch exists

- **WHEN** the command listener processes an `update_config` command
- **THEN** it reaches `handle_update_config` (which checks `ruleset_version` and persists state)
- **AND** there is no earlier code path that applies `watch_paths` without the version check.

#### Scenario: Stale update_config is rejected by version monotonicity

- **WHEN** a validly signed `update_config` command arrives with a `ruleset_version` less than or equal to the locally persisted `ruleset_version`
- **THEN** the watchers are not reconfigured and the stale command is rejected.

### Requirement: restore_file cae a snapshots cuando el contenido activo es nulo

Al procesar el comando `restore_file`, si la entrada de baseline tiene `content_b64` nulo (típicamente porque el archivo está en estado `absent`), el handler SHALL buscar el snapshot más reciente cuyo `content_b64` no sea nulo, descomprimirlo si `gzip=True`, y usar ese contenido para restaurar el archivo. El handler MUST verificar el SHA-256 del contenido restaurado contra el hash del snapshot usado, journalizar la acción transaccionalmente (pending/completed/failed) y publicar el `event_ack`. Si no existe ningún snapshot utilizable, el handler MUST fallar con el error `no_restorable_content` y journalizar el fallo (RN-30–33, F3).

#### Scenario: Restauración por comando desde snapshot cuando el contenido activo es nulo

- **WHEN** llega un comando `restore_file` para un path cuya entrada de baseline tiene `content_b64=None` pero existe un snapshot con contenido
- **THEN** el handler restaura el archivo desde el snapshot más reciente con contenido, verifica el hash y publica `event_ack`

#### Scenario: Snapshot comprimido se descomprime en el handler

- **WHEN** el snapshot seleccionado para el `restore_file` tiene `gzip=True`
- **THEN** el handler descomprime el contenido antes de escribirlo y verificar el hash

#### Scenario: Comando sin contenido restaurable falla con error claro

- **WHEN** llega un comando `restore_file` y ni el contenido activo ni ningún snapshot tienen contenido
- **THEN** el handler journaliza el fallo con el error `no_restorable_content` y no escribe el archivo

#### Scenario: Contenido activo presente conserva el comportamiento previo

- **WHEN** llega un comando `restore_file` y la entrada de baseline tiene `content_b64` no nulo
- **THEN** el handler restaura desde el contenido activo sin consultar snapshots

## Previous Requirements

### Requirement: Handler update_config — recarga watch_paths y escanea paths nuevos

El agente SHALL implementar un handler `handle_update_config(command, detector, baseline_engine, state)` en `agent/commands.py`. Al recibirlo, MUST: verificar firma HMAC y `target_agent_id` (mecanismo ya implementado en dispatch de C13); comparar `command["watch_paths"]` con los paths actualmente configurados; llamar `detector.reload_watch_paths(new_paths)` para que fanotify deje de marcar los paths eliminados y empiece a marcar los nuevos; llamar `baseline_engine.run_scan(added_paths)` solo para los paths que no tenían baseline previo; actualizar `config.yaml` local con los nuevos paths; actualizar `state.ruleset_version = command["ruleset_version"]`; publicar `event_ack`.

#### Scenario: update_config recarga fanotify con nuevos paths
- **WHEN** el agente recibe `{"type": "update_config", "watch_paths": ["/etc", "/usr/bin"], ...}`
- **THEN** el detector pasa a monitorear `/etc` y `/usr/bin`
- **AND** se publicó `event_ack` con `status="ok"`

#### Scenario: update_config escanea solo paths nuevos
- **WHEN** el agente ya monitorea `/etc` y recibe `update_config` con `watch_paths=["/etc", "/usr/bin"]`
- **THEN** se ejecuta baseline scan solo para `/usr/bin` (path nuevo)
- **AND** `/etc` no es re-escaneado

#### Scenario: update_config elimina paths ya no monitoreados
- **WHEN** el agente monitorea `/etc` y `/tmp` y recibe `update_config` con `watch_paths=["/etc"]`
- **THEN** `/tmp` deja de ser monitoreado por fanotify
- **AND** el baseline de `/tmp` no se borra (persiste para referencia histórica)

#### Scenario: config.yaml actualizado tras update_config
- **WHEN** el handler ejecuta exitosamente
- **THEN** `config.yaml` del agente refleja los nuevos `watch_paths`

---

### Requirement: FanotifyDetector expone reload_watch_paths

El `FanotifyDetector` en `agent/detector.py` SHALL exponer un método público `reload_watch_paths(new_paths: list[str])` que: desmarca del grupo fanotify los paths que estaban en el set anterior y ya no están en `new_paths`; marca los paths nuevos que no estaban antes; actualiza el atributo interno `watch_paths`. Este método MUST ser thread-safe o async-safe para poder ser llamado desde el handler de commands.

#### Scenario: Nuevos paths marcados en fanotify
- **WHEN** se llama `detector.reload_watch_paths(["/etc", "/usr/bin"])` sobre un detector que monitoreaba `["/etc"]`
- **THEN** `/usr/bin` queda marcado en fanotify
- **AND** `/etc` permanece marcado (no se desmarca y remarca innecesariamente)

#### Scenario: Paths eliminados desmarcados en fanotify
- **WHEN** se llama `detector.reload_watch_paths(["/etc"])` sobre un detector que monitoreaba `["/etc", "/tmp"]`
- **THEN** `/tmp` queda desmarcado de fanotify

---

### Requirement: BaselineEngine expone run_scan(paths)

El `BaselineEngine` en `agent/baseline.py` SHALL exponer un método público `run_scan(paths: list[str])` que ejecuta el scan inicial sobre la lista de paths dada — idéntico al scan del primer arranque pero limitado a los paths especificados. Para cada archivo regular encontrado MUST calcular SHA-256, cifrar con AES-256-GCM y persistir en el baseline. Si ya existe una entrada para un path, MUST sobrescribirla (upsert).

#### Scenario: run_scan crea entradas de baseline para paths dados
- **WHEN** se llama `run_scan(["/tmp/test"])` y `/tmp/test` contiene archivos regulares
- **THEN** existen entradas de baseline cifradas para cada archivo encontrado

#### Scenario: run_scan no modifica entradas de otros paths
- **WHEN** ya existe baseline para `/etc/passwd` y se llama `run_scan(["/tmp"])`
- **THEN** la entrada de baseline de `/etc/passwd` permanece sin cambios

---

### Requirement: Handler rescan_baseline — scan completo y event_ack

El agente SHALL implementar `handle_rescan_baseline(command, baseline_engine, state)` en `agent/commands.py`. MUST: verificar firma HMAC y `target_agent_id`; obtener los `watch_paths` actuales de `config.yaml`; llamar `baseline_engine.run_scan(watch_paths)` para escanear todos los paths monitoreados; publicar `event_ack` con el resultado.

#### Scenario: rescan_baseline escanea todos los watch_paths actuales
- **WHEN** el agente recibe `{"type": "rescan_baseline", ...}` y monitorea `["/etc", "/usr/bin"]`
- **THEN** se ejecuta baseline scan sobre `/etc` y `/usr/bin`
- **AND** se publicó `event_ack` con `status="ok"`

#### Scenario: rescan_baseline publica event_ack de error si scan falla
- **WHEN** el scan falla por error de IO
- **THEN** se publica `event_ack` con `status="error"` describiendo la causa
