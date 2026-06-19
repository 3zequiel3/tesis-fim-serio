# Spec: agent-config-commands

Capability: Handlers del agente FIM para los comandos de configuración entrantes desde el backend — `update_config` (recarga de watch_paths en fanotify + baseline scan de paths nuevos) y `rescan_baseline` (scan completo de baseline + event_ack), integrados en el dispatch de `agent/commands.py` (C13).

---

## ADDED Requirements

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
