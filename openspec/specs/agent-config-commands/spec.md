# agent-config-commands Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

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

### Requirement: FanotifyDetector expone reload_watch_paths

El `FanotifyDetector` en `agent/detector.py` SHALL exponer un método público `reload_watch_paths(new_paths: list[str])` que: desmarca del grupo fanotify los paths que estaban en el set anterior y ya no están en `new_paths`; marca los paths nuevos que no estaban antes; actualiza el atributo interno `watch_paths`. Este método MUST ser thread-safe o async-safe para poder ser llamado desde el handler de commands.

#### Scenario: Nuevos paths marcados en fanotify
- **WHEN** se llama `detector.reload_watch_paths(["/etc", "/usr/bin"])` sobre un detector que monitoreaba `["/etc"]`
- **THEN** `/usr/bin` queda marcado en fanotify
- **AND** `/etc` permanece marcado (no se desmarca y remarca innecesariamente)

#### Scenario: Paths eliminados desmarcados en fanotify
- **WHEN** se llama `detector.reload_watch_paths(["/etc"])` sobre un detector que monitoreaba `["/etc", "/tmp"]`
- **THEN** `/tmp` queda desmarcado de fanotify

### Requirement: BaselineEngine expone run_scan(paths)

El `BaselineEngine` en `agent/baseline.py` SHALL exponer un método público `run_scan(paths: list[str])` que ejecuta el scan inicial sobre la lista de paths dada — idéntico al scan del primer arranque pero limitado a los paths especificados. Para cada archivo regular encontrado MUST calcular SHA-256, cifrar con AES-256-GCM y persistir en el baseline. Si ya existe una entrada para un path, MUST sobrescribirla (upsert).

#### Scenario: run_scan crea entradas de baseline para paths dados
- **WHEN** se llama `run_scan(["/tmp/test"])` y `/tmp/test` contiene archivos regulares
- **THEN** existen entradas de baseline cifradas para cada archivo encontrado

#### Scenario: run_scan no modifica entradas de otros paths
- **WHEN** ya existe baseline para `/etc/passwd` y se llama `run_scan(["/tmp"])`
- **THEN** la entrada de baseline de `/etc/passwd` permanece sin cambios

### Requirement: Handler rescan_baseline — scan completo y event_ack

El agente SHALL implementar `handle_rescan_baseline(command, baseline_engine, state)` en `agent/commands.py`. MUST: verificar firma HMAC y `target_agent_id`; obtener los `watch_paths` actuales de `config.yaml`; llamar `baseline_engine.run_scan(watch_paths)` para escanear todos los paths monitoreados; publicar `event_ack` con el resultado.

#### Scenario: rescan_baseline escanea todos los watch_paths actuales
- **WHEN** el agente recibe `{"type": "rescan_baseline", ...}` y monitorea `["/etc", "/usr/bin"]`
- **THEN** se ejecuta baseline scan sobre `/etc` y `/usr/bin`
- **AND** se publicó `event_ack` con `status="ok"`

#### Scenario: rescan_baseline publica event_ack de error si scan falla
- **WHEN** el scan falla por error de IO
- **THEN** se publica `event_ack` con `status="error"` describiendo la causa

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

### Requirement: update_config persists to the actual loaded config path

`AgentConfig` SHALL carry the filesystem path it was loaded from. `load_config(path)` MUST set `config_path` (a `PrivateAttr[Path | None]`) to `Path(path)` after `model_validate`. `handle_update_config` MUST resolve the write target as `config.config_path or Path("/etc/fim-agent/config.yaml")` rather than reading a non-existent attribute that always falls back to the default. This guarantees that an agent started with a non-default config file persists `update_config` changes back to that same file. (FA6, RN-68)

#### Scenario: update_config writes back to the loaded non-default path
- **WHEN** the agent was started with `load_config("/opt/fim/custom.yaml")` and later handles an `update_config` command
- **THEN** the updated configuration is written atomically to `/opt/fim/custom.yaml`, not to `/etc/fim-agent/config.yaml`

#### Scenario: Default path is used only when no load path is known
- **WHEN** `config.config_path` is `None`
- **THEN** `handle_update_config` falls back to `Path("/etc/fim-agent/config.yaml")`
