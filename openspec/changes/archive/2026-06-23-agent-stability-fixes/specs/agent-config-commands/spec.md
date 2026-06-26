## ADDED Requirements

### Requirement: update_config persists to the actual loaded config path

`AgentConfig` SHALL carry the filesystem path it was loaded from. `load_config(path)` MUST set `config_path` (a `PrivateAttr[Path | None]`) to `Path(path)` after `model_validate`. `handle_update_config` MUST resolve the write target as `config.config_path or Path("/etc/fim-agent/config.yaml")` rather than reading a non-existent attribute that always falls back to the default. This guarantees that an agent started with a non-default config file persists `update_config` changes back to that same file. (FA6, RN-68)

#### Scenario: update_config writes back to the loaded non-default path
- **WHEN** the agent was started with `load_config("/opt/fim/custom.yaml")` and later handles an `update_config` command
- **THEN** the updated configuration is written atomically to `/opt/fim/custom.yaml`, not to `/etc/fim-agent/config.yaml`

#### Scenario: Default path is used only when no load path is known
- **WHEN** `config.config_path` is `None`
- **THEN** `handle_update_config` falls back to `Path("/etc/fim-agent/config.yaml")`
