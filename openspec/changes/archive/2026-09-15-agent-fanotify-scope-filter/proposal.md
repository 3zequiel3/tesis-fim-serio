## Why

El detector fanotify marca el filesystem completo (`FAN_MARK_FILESYSTEM`, limitación del kernel — tradeoff arquitectónico intencional, no es el bug) pero nunca filtra por `watch_paths`. En un host de un solo mount, el agente hashea, diffea y publica TODOS los cambios del host, no solo los de los paths configurados, violando RN-04 ("Solo los paths incluidos en la configuración generan eventos. Todo lo demás se ignora. Excepciones: Ninguna"). Además, un symlink dentro de un `watch_path` que apunta afuera (p. ej. a `/root/.ssh`) se cifra en el baseline como si fuera contenido en alcance. Esta change corrige la implementación para cumplir RN-04; cierra el hallazgo #6 de la auditoría dual-judge 2026-07-02, diferido en C35 hasta cerrar D31/RN-125 (cerrada el 2026-07-02).

## What Changes

- **Filtro de containment en `agent/detector.py::_read_loop`**: se descarta (sin encolar en `_raw_queue`) todo evento cuyo `os.path.realpath()` no esté contenido (`is_relative_to`) en ningún `watch_path` canonicalizado, ANTES de construir el `FanotifyEvent`. El filtro se ubica en el punto de lectura (`_read_loop`), no solo en la clasificación (`_process_event`), para que la cola acotada (`maxsize=1000`) no absorba el ruido irrelevante generado por el mark a nivel filesystem.
- **Canonicalización una sola vez**: los `watch_paths` se resuelven a `realpath` en `start()`, `reload_paths()` y `reload_watch_paths()` y se cachean — no se recalculan por evento.
- **Fix de symlinks fuera de scope en `agent/baseline.py::init_scan` (y `run_scan`)**: si el `realpath` de un archivo descubierto vía `rglob` escapa del `watch_path` canonicalizado, se omite con log warning en vez de cifrarse.
- **Contador `out_of_scope_drops`**: nuevo contador acumulado en el detector, surfaceado en el heartbeat del agente, análogo al contador `event_drops` ya existente. Es la única visibilidad operativa de cuánto tráfico fuera de alcance descarta `FAN_MARK_FILESYSTEM`.
- Se reutiliza el patrón de containment por `realpath` ya validado en D18/RN-116 (`agent/commands.py`) para consistencia entre módulos.

No hay cambios de contrato con el backend: el consumer de heartbeat (`backend/app/modules/agents/heartbeat_consumer.py`) lee solo `queue_pressure` y `shutdown` del payload e ignora los campos restantes (incluido `event_drops`); `out_of_scope_drops` viaja en el payload sin requerir columna ni migración.

## Capabilities

### New Capabilities
<!-- Ninguna. Esta change corrige la implementación de una política ya vigente (RN-04), no introduce una capability nueva. -->

### Modified Capabilities
- `agent-fanotify-detector`: se agrega la garantía observable de que los eventos cuyo `realpath` cae fuera de todos los `watch_paths` canonicalizados se descartan antes de encolarse, y se expone el contador `out_of_scope_drops` en el heartbeat (comportamiento nuevo; las requirements existentes no cambian).
- `agent-baseline`: se agrega la garantía de que los symlinks/archivos descubiertos por el scan cuyo `realpath` escapa del `watch_path` canonicalizado se omiten del baseline con warning en vez de cifrarse.

## Impact

- **Agente** (única capa con cambios de código):
  - `agent/detector.py`: `_read_loop` (filtro de containment), `start()`, `reload_paths()`, `reload_watch_paths()` (cache de `watch_paths` canonicalizados), contador `out_of_scope_drops` + propiedad pública.
  - `agent/baseline.py`: `init_scan` y `run_scan` (skip de archivos cuyo `realpath` escapa del scope).
  - `agent/heartbeat.py`: campo `out_of_scope_drops` en el payload del heartbeat.
  - `agent/tests/`: cobertura de filtro de scope, canonicalización, skip de symlinks y contador.
- **Backend**: sin cambios. El consumer de heartbeat ya tolera campos desconocidos del payload (lee solo claves específicas vía `.get()`).
- **Reglas cubiertas**: RN-04, RN-125. **Decisiones aplicadas**: D31 (reutiliza el patrón de D18/RN-116).
- **Dependencias del DAG**: C34, C35, C36 aplicadas en local (rama `devel`). D31/RN-125 cerrada.
