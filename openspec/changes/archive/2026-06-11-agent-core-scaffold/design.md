## Context

El agente FIM no corre en Docker: `fanotify` requiere `CAP_SYS_ADMIN`, incompatible con el aislamiento estándar de contenedores (ver arquitectura_stack.md §Despliegue del agente). Se despliega como servicio nativo `systemd` en cada anfitrión monitoreado. Antes de implementar cualquier funcionalidad (mTLS, baseline, detector fanotify), se necesita la estructura base: layout de módulos, lectura de configuración, logging, persistencia de estado y hardening systemd.

Este change no implementa nada funcional que el usuario final vea. Es la base sobre la que todos los changes M2 anclan.

## Goals / Non-Goals

**Goals:**
- Layout `agent/` con módulos por responsabilidad (uno por archivo, mirrors backend structure)
- `config.py`: lectura y validación de `/etc/fim-agent/config.yaml` con pydantic + PyYAML
- `logging.py`: structlog JSON sanitizado (mirrors `backend/core/logging.py`)
- `state.py`: lectura/escritura atómica de `state.json` (guarda `ruleset_version`)
- `__main__.py`: entry point limpio que inicializa config, logging y event loop
- `fim-agent.service`: unidad systemd con hardening completo de capabilities y namespaces
- `install.sh`: idempotente — crea usuario `fim-agent`, directorios con permisos auditados, venv, habilita servicio
- `requirements.txt` con versiones fijadas (pyfanotify 0.3.0, structlog, valkey-py, cryptography, pyyaml, pydantic-settings)
- `deploy/config.yaml.example` con todos los campos documentados

**Non-Goals:**
- No fanotify (Change 09)
- No Valkey Streams (Change 08)
- No mTLS/bootstrap (Change 06)
- No baseline engine (Change 07)
- No reglas ni decision engine (Change 10)
- No heartbeat ni publisher (changes posteriores)
- No pruebas de integración con el backend (depende de Change 06+)

## Decisions

### D-AGENT-01: Config con pydantic-settings + PyYAML

pydantic-settings soporta `settings_customise_sources`: se provee una fuente custom que carga el YAML con PyYAML y lo retorna como dict. Pydantic valida y tipea todos los campos. Error al arrancar si el YAML tiene campos faltantes o tipos incorrectos — falla temprana, mensaje claro.

Alternativa descartada: `dataclasses` + parsing manual → sin validación de tipos, más boilerplate, errores en runtime en lugar de en arranque.

### D-AGENT-02: State.json con escritura atómica

`state.json` guarda solo `ruleset_version: int` (default `0`). Escritura: `json.dumps` → archivo `.tmp` → `os.replace()` → path original. `os.replace()` es atómica en POSIX. Previene estado corrupto si el agente muere mid-write.

Alternativa descartada: SQLite → dependencia extra innecesaria para un solo entero. Redis/Valkey → no disponible offline (precisamente el estado que se protege).

### D-AGENT-03: structlog con procesador sanitize_logs

Pipeline de procesadores structlog:
1. `add_log_level` → campo `level`
2. `TimeStamper(fmt="iso")` → campo `timestamp`
3. `sanitize_logs` → filtra valores de claves `password|token|secret|key|credential` (regex case-insensitive)
4. `JSONRenderer` (producción) / `ConsoleRenderer` (dev, `LOG_FORMAT=console`)

Mirrors exacto de `backend/core/logging.py`. Consistencia de formato entre agente y backend facilita pipelines de log centralizado.

### D-AGENT-04: Entry point como módulo Python (`__main__.py`)

El servicio systemd ejecuta `/opt/fim-agent/venv/bin/python -m agent`. Esto permite instalar el agente como módulo Python en un venv aislado sin necesidad de scripts wrapper. `__main__.py` parsea `--config`, inicializa logging, carga config, inicializa state, y arranca el event loop asyncio (vacío en este change, expandido en changes posteriores).

### D-AGENT-05: install.sh idempotente

El script usa `id fim-agent || useradd` (no falla si el usuario existe), `mkdir -p` (no falla si el dir existe), `chown -R` y `chmod` explícitos al final. Permite re-ejecutarlo en upgrades sin romper instalaciones existentes.

Directorios creados con `0700 fim-agent`:
- `/var/lib/fim-agent/{baseline,quarantine,queue,journal,certs}/`
- `/var/lib/fim-agent/secrets/` (archivos individuales quedarán en `0400` cuando se creen)
- `/var/log/fim-agent/`
- `/etc/fim-agent/`

Venv en `/opt/fim-agent/venv/` — `pip install -r agent/requirements.txt`.

## Risks / Trade-offs

[El servicio falla en contenedores] → Esperado y documentado. El agente es explícitamente incompatible con Docker. La unidad systemd fallará con error de capabilities — falla ruidosa, no silenciosa.

[Permisos de `/var/lib/fim-agent/` pueden romperse en upgrades] → `install.sh` aplica `chown -R` al final de cada ejecución. Smoke test verifica permisos explícitamente con `stat`.

[State.json es modificado por otro proceso] → El agente es monoproceso (asyncio single-thread). No hay escritores concurrentes posibles. La atomicidad de `os.replace()` protege contra crashes propios, no contra intervención externa (que sería una violación de seguridad ya cubierta por los permisos `0600`).

[pyfanotify 0.3.0 no está en PyPI oficial] → Se instala desde wheel local o Git tag. `requirements.txt` pineará la versión exacta con hash para integridad.
