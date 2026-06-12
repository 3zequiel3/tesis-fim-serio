## Why

El agente FIM no puede vivir en Docker porque `fanotify` requiere `CAP_SYS_ADMIN`, incompatible con el aislamiento estándar de contenedores. Este change sienta la base estructural del agente como servicio nativo: estructura de módulos, configuración por archivo local, logging estructurado, estado persistente, hardening systemd y layout de directorios con permisos auditados. Sin este scaffold, ningún módulo funcional del agente (mTLS, baseline, detector) tiene dónde anclar.

## What Changes

- Nuevo directorio `agent/` con módulos base: `config.py`, `logging.py`, `state.py`, `__main__.py`
- Unidad systemd `fim-agent.service` con `AmbientCapabilities=CAP_SYS_ADMIN`, `ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`
- Script `install.sh`: crea usuario `fim-agent`, layout de directorios con permisos auditados, habilita e inicia el servicio
- `requirements.txt` del agente con versiones fijadas (pyfanotify 0.3.0, structlog, valkey-py, cryptography, pyyaml)
- Template `/etc/fim-agent/config.yaml` con todos los campos de bootstrap documentados

## Capabilities

### New Capabilities

- `agent-core`: Scaffold completo del agente FIM — módulos base (`config`, `logging`, `state`), arranque como servicio systemd con hardening de capabilities, layout de directorios con permisos `0700`/`0400`, y script de instalación idempotente.

### Modified Capabilities

*(ninguna — este change no altera specs existentes)*

## Impact

- **Nuevo directorio**: `agent/` (raíz del proyecto)
- **Nuevos archivos**: `agent/__main__.py`, `agent/config.py`, `agent/logging.py`, `agent/state.py`, `agent/requirements.txt`
- **Archivos de despliegue**: `agent/deploy/fim-agent.service`, `agent/deploy/config.yaml.example`, `agent/install.sh`
- **Sin impacto** en backend, frontend ni Docker Compose existentes
- **Reglas cubiertas**: RN-51 (permisos restringidos), RN-68 (configuración bootstrap), RN-89 (cola offline — layout de directorio `queue/`)
- **Dependencias del DAG**: ninguna (paralelizable con M1, que ya está completo)
