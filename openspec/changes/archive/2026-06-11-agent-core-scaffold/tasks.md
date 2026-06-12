## 1. Estructura del proyecto

- [x] 1.1 Crear `agent/` con `__init__.py` vacío y `agent/py.typed` (marker de tipado)
- [x] 1.2 Crear `agent/requirements.txt` con versiones fijadas: `pyfanotify==0.3.0`, `structlog`, `valkey`, `cryptography`, `pyyaml`, `pydantic-settings`, `pydantic`

## 2. Módulo config

- [x] 2.1 Crear `agent/config.py` con clase `AgentConfig(BaseSettings)` que carga `/etc/fim-agent/config.yaml` vía fuente custom (PyYAML → dict → pydantic)
- [x] 2.2 Definir campos: `agent_id: str`, `valkey_url: str`, `ca_cert_path: str`, `watch_paths: list[str]`, `storage: StorageConfig` (nested: `baseline_dir`, `queue_dir`, `journal_dir`)
- [x] 2.3 Agregar validadores: `agent_id` no vacío, `watch_paths` no vacío, paths en `storage` son strings no vacíos
- [x] 2.4 Exponer función `load_config(path: str | Path) -> AgentConfig` — lanza `SystemExit(1)` con mensaje claro si el archivo no existe o la validación falla

## 3. Módulo logging

- [x] 3.1 Crear `agent/logging.py` con función `configure_logging(level: str = "info", fmt: str = "json") -> None`
- [x] 3.2 Implementar procesador `sanitize_logs(logger, method, event_dict)`: regex case-insensitive sobre claves que contengan `password|token|secret|key|credential` → reemplazar valor con `"[REDACTED]"`
- [x] 3.3 Configurar cadena structlog: `add_log_level` → `TimeStamper(fmt="iso")` → `sanitize_logs` → `JSONRenderer` (si `fmt="json"`) o `ConsoleRenderer` (si `fmt="console"`)
- [x] 3.4 Leer `LOG_LEVEL` y `LOG_FORMAT` de variables de entorno como defaults override-ables por parámetro

## 4. Módulo state

- [x] 4.1 Crear `agent/state.py` con dataclass `AgentState(ruleset_version: int = 0)` y `state_path: Path`
- [x] 4.2 Implementar `load_state(path: Path) -> AgentState`: lee JSON si el archivo existe, retorna default si no existe; lanza `SystemExit(1)` si el archivo existe pero es JSON inválido
- [x] 4.3 Implementar `save_state(state: AgentState, path: Path) -> None`: escribe JSON a `path.with_suffix(".tmp")` → `os.replace()` al path final
- [x] 4.4 Asegurar que al crear `state.json` se aplican permisos `0600` (`os.open` con `O_CREAT | O_WRONLY`, `mode=0o600` antes de la escritura)

## 5. Entry point

- [x] 5.1 Crear `agent/__main__.py` con `argparse`: `--config` (default `/etc/fim-agent/config.yaml`), `--log-level` (default `info`), `--log-format` (default `json`)
- [x] 5.2 Inicializar logging primero (antes de cargar config) para que los errores de config sean visibles
- [x] 5.3 Cargar config con `load_config()` y state con `load_state()`
- [x] 5.4 Arrancar `asyncio.run(main())` donde `main()` es una coroutine que loguea `"agent started"` con `agent_id` y `ruleset_version`, y queda en `asyncio.Event().wait()` (placeholder hasta Change 06+)
- [x] 5.5 Registrar handlers `SIGTERM` y `SIGINT` que loguean `"shutting down"` y cancelan el loop limpiamente

## 6. Unidad systemd

- [x] 6.1 Crear `agent/deploy/fim-agent.service` con sección `[Unit]`: `Description`, `After=network.target`
- [x] 6.2 Sección `[Service]`: `User=fim-agent`, `Group=fim-agent`, `WorkingDirectory=/opt/fim-agent`, `ExecStart=/opt/fim-agent/venv/bin/python -m agent --config /etc/fim-agent/config.yaml`
- [x] 6.3 Capabilities: `AmbientCapabilities=CAP_SYS_ADMIN`, `CapabilityBoundingSet=CAP_SYS_ADMIN`
- [x] 6.4 Hardening: `ProtectSystem=strict`, `NoNewPrivileges=true`, `PrivateTmp=true`, `ReadWritePaths=/var/lib/fim-agent /var/log/fim-agent`
- [x] 6.5 Restart policy: `Restart=on-failure`, `RestartSec=5s`, `StandardOutput=journal`, `StandardError=journal`
- [x] 6.6 Sección `[Install]`: `WantedBy=multi-user.target`

## 7. Template de configuración

- [x] 7.1 Crear `agent/deploy/config.yaml.example` con todos los campos y comentarios inline explicando su rol
- [x] 7.2 Incluir sección `storage` con los 3 paths estándar y el path de `secrets_dir` y `certs_dir` para uso posterior (Changes 06+)

## 8. Script de instalación

- [x] 8.1 Crear `agent/install.sh` (bash, `set -euo pipefail`) que crea el usuario `fim-agent` si no existe
- [x] 8.2 Crear árbol de directorios `/var/lib/fim-agent/{baseline,quarantine,queue,journal,secrets,certs}/` con `chmod 0700` y `chown fim-agent:fim-agent`
- [x] 8.3 Crear `/var/log/fim-agent/` (`chmod 0750`) y `/etc/fim-agent/` (`chmod 0750`) con owner `fim-agent`
- [x] 8.4 Crear `/opt/fim-agent/venv/` con `python3 -m venv` e instalar `agent/requirements.txt`
- [x] 8.5 Copiar `deploy/fim-agent.service` a `/etc/systemd/system/`; ejecutar `systemctl daemon-reload`; `systemctl enable fim-agent`
- [x] 8.6 Copiar `deploy/config.yaml.example` a `/etc/fim-agent/config.yaml` **solo si no existe** (no sobreescribir config existente)
- [x] 8.7 Aplicar `chown -R fim-agent:fim-agent /var/lib/fim-agent /var/log/fim-agent /etc/fim-agent /opt/fim-agent` al final para garantizar permisos correctos

## 9. Smoke test

- [x] 9.1 Crear `agent/deploy/config.yaml.test` con `agent_id: test-agent`, paths locales, y ejecutar `python -m agent --config agent/deploy/config.yaml.test` — verificar que arranca sin error y loguea `"agent started"`
- [x] 9.2 Verificar que `state.json` no es creado hasta la primera escritura explícita de estado
- [x] 9.3 Verificar sanitización: loguear un campo `test_secret=valor_real` y confirmar que la salida JSON muestra `"[REDACTED]"` en lugar del valor
- [ ] 9.4 Ejecutar `install.sh` en un host/VM Linux y verificar: `systemctl start fim-agent` OK, `systemctl status fim-agent` muestra `active (running)`
- [ ] 9.5 Verificar que el proceso corre como `fim-agent`: `ps aux | grep python.*agent` muestra el usuario correcto
- [ ] 9.6 Verificar capabilities: `cat /proc/$(pgrep -f "python.*-m agent")/status | grep CapAmb` muestra el bit de `CAP_SYS_ADMIN`
- [ ] 9.7 Verificar permisos del layout: `stat /var/lib/fim-agent` muestra `0700`, owner `fim-agent`; lo mismo para cada subdirectorio
