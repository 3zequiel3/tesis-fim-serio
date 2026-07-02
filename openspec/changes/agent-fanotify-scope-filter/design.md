## Context

El detector fanotify (`agent/detector.py`) usa `FAN_MARK_FILESYSTEM` para marcar el filesystem completo. Esto es una limitación del kernel ya documentada como tradeoff arquitectónico (marcar path por path no captura movimientos entre subárboles ni creación de archivos nuevos de forma confiable), NO es el bug a corregir. El bug es que ni `_read_loop` ni `_process_event` filtran por `watch_paths`: en un host de un solo mount, todo cambio del host se hashea, diffea y publica, violando RN-04.

Estado actual relevante (verificado en código):
- `_read_loop` (hilo `fan-reader`) construye un `FanotifyEvent` por cada evento crudo y lo entrega al event loop vía `call_soon_threadsafe(self._try_enqueue, ...)` → `_raw_queue` (`asyncio.Queue(maxsize=1000)`). No hay filtro de scope en ningún punto.
- `_try_enqueue` ya incrementa `_event_drops` y expone la propiedad `event_drops`; `agent/heartbeat.py::_publish` ya publica `event_drops` en el payload.
- `backend/.../heartbeat_consumer.py::_handle_heartbeat` lee SOLO `queue_pressure` y `shutdown` del payload; ignora `event_drops` y cualquier otro campo. El modelo `Agent` NO tiene columna `event_drops`.
- `agent/baseline.py::init_scan` y `run_scan` iteran `p.rglob("*")` y filtran con `if not file_path.is_file(): continue`. `is_file()` sigue symlinks, así que un symlink a un archivo externo pasa el filtro y se cifra vía `write_entry`.
- `agent/commands.py` (D18/RN-116) ya usa `os.path.realpath(path)` + check de containment (`startswith`) para `quarantine_file`/`restore_file`.

Decisión de negocio: D31 / RN-125, cerrada el 2026-07-02 en los appendices canónicos. Esta change es una corrección de implementación de RN-04, no una regla nueva.

## Goals / Non-Goals

**Goals:**
- Cumplir RN-04 en software: descartar todo evento cuyo `realpath` caiga fuera de los `watch_paths` canonicalizados, en el punto de lectura (`_read_loop`), antes de encolar.
- Canonicalizar los `watch_paths` a `realpath` una sola vez (en `start()`, `reload_paths()`, `reload_watch_paths()`) y cachear el resultado; no recalcular por evento.
- Omitir del baseline (con warning) los archivos/symlinks descubiertos por el scan cuyo `realpath` escapa del `watch_path` canonicalizado.
- Exponer un contador `out_of_scope_drops` en el heartbeat, análogo a `event_drops`.
- Reutilizar el patrón de containment por `realpath` de D18/RN-116 para consistencia entre módulos.

**Non-Goals:**
- NO cambiar el uso de `FAN_MARK_FILESYSTEM` (tradeoff del kernel, fuera de alcance por D31).
- NO agregar columna ni migración en el backend: `out_of_scope_drops` viaja en el payload del heartbeat y el consumer lo ignora, igual que hoy con `event_drops` (ver Decisiones).
- NO refactorizar el check `startswith` de `agent/commands.py` a `is_relative_to` (pertenece a D18/RN-116, un decision cerrado distinto; ver Risks / Trade-offs).
- NO tocar backend ni frontend.

## Decisions

### D1 — Filtro de containment en `_read_loop`, antes de construir el evento

Se agrega el check de scope en `_read_loop`, dentro del `for ev in raw_events`, justo después del guard `if ev.path is None` y ANTES de construir `FanotifyEvent`. Un evento fuera de scope se descarta e incrementa `out_of_scope_drops`; no se construye el objeto ni se llama `call_soon_threadsafe`.

Rationale: D31 lo exige explícitamente en el punto de lectura, no solo en clasificación, para que la cola acotada (`maxsize=1000`) no se sature con ruido irrelevante generado por el mark a nivel filesystem. Ubicarlo en `_process_event` dejaría entrar el ruido a la cola y competir con eventos legítimos por los 1000 slots.

Alternativa descartada: filtrar en `_process_event`. Rechazada porque la cola acotada absorbería el ruido (el problema exacto que D31 busca evitar).

### D2 — Helper de containment compartido con `is_relative_to`

Se introduce un helper puro (p. ej. `_realpath_in_scope(path: str, canonical_roots: list[str]) -> bool`) que canonicaliza `path` con `os.path.realpath` y verifica `Path(real).is_relative_to(root)` contra cada root canonicalizado. Lo usan el filtro del detector y el skip del baseline scan.

Rationale: `is_relative_to` (Python 3.9+) es el check de containment correcto y robusto frente al prefix-matching. D31 lo nombra explícitamente (`is_relative_to()`). Un helper único garantiza semántica idéntica entre `detector.py` y `baseline.py`.

Alternativa descartada: `real.startswith(root)` como en `commands.py`. Rechazada porque `startswith` es vulnerable a prefijos (`/etc/app` matchea `/etc/apple`). D31 manda `is_relative_to`; ver el trade-off sobre `commands.py` más abajo.

### D3 — Cache de `watch_paths` canonicalizados

Se agrega `self._watch_paths_real: list[str]`, recomputado desde `self._watch_paths` en `start()`, `reload_paths()` y `reload_watch_paths()` (incluida la rama `noop_no_fan` de `reload_watch_paths`, para que tests/plataformas sin fanotify también actualicen el cache). El filtro lee `self._watch_paths_real`.

Rationale: `os.path.realpath` hace syscalls (`lstat`); ejecutarlo por evento bajo `FAN_MARK_FILESYSTEM` (tráfico proporcional a todo el host) sería costoso. D31 exige canonicalizar una sola vez.

Thread-safety: `_read_loop` corre en el hilo `fan-reader` y lee `self._watch_paths_real`; los reload corren en el event loop y reasignan la lista. En CPython el rebind de un atributo es atómico bajo el GIL, así que el reader ve la lista vieja o la nueva completa, nunca una a medio construir. Esto es consistente con el modelo single-loop ya documentado en el detector. Se recomputa creando una lista nueva y reasignando (no mutando in-place) para preservar esta atomicidad.

### D4 — `out_of_scope_drops` solo en el payload del heartbeat, sin persistencia backend

El detector expone `out_of_scope_drops` (propiedad, análoga a `event_drops`); `agent/heartbeat.py::_publish` agrega el campo al payload. El backend NO cambia.

Rationale: hoy `event_drops` se publica pero el consumer (`_handle_heartbeat`) lee solo `queue_pressure` y `shutdown` — nunca lee `event_drops`, y `Agent` no tiene esa columna. Por analogía exacta con `event_drops` (RN-84/RN-125 "análogo al contador existente"), `out_of_scope_drops` se publica pero no se persiste. El consumer ya tolera campos desconocidos porque solo extrae claves específicas vía `.get()`. Persistirlo sería inventar un requisito que D31 no pide.

Alternativa descartada: agregar columna `Agent.out_of_scope_drops` + migración. Rechazada porque introduciría un cambio de schema backend no cerrado en ningún appendix y rompería la analogía con `event_drops`. Si en el futuro se quiere persistir métricas de descarte, sería una decisión aparte que también debería cubrir `event_drops`.

### D5 — Baseline: check de `realpath` antes de `write_entry`

En `init_scan` y `run_scan`, para cada `file_path` candidato (tras el `if not file_path.is_file()`), se evalúa `_realpath_in_scope(str(file_path), [realpath(watch_path)])`. Si falla, se loguea warning y se hace `continue` (no cuenta como `scanned`; puede contarse como `skipped` o registrarse aparte — se decide en tasks según el `ScanReport`). El `watch_path` se canonicaliza una vez por iteración de scan (no por candidato).

Rationale: cierra el vector de cifrar contenido externo (`/root/.ssh`) bajo un path que aparenta estar en scope. El scan ya es la frontera natural para esta verificación.

## Risks / Trade-offs

- **`commands.py` sigue usando `startswith` (D18/RN-116) mientras el detector/baseline usan `is_relative_to` (D31)** → inconsistencia parcial entre módulos. Mitigación: se documenta como observación; `commands.py` pertenece a un decision cerrado distinto (D18) y cambiar su semántica de containment es scope creep sobre otra regla. El helper nuevo queda disponible para que una futura change de hardening alinee `commands.py` si se decide. Se reporta al orquestador.
- **Falsos negativos por symlinks legítimos dentro de scope** → un symlink dentro de `watch_paths` que apunta a otro subárbol también vigilado se evalúa por su `realpath`; si el target está en otro `watch_path`, sigue en scope (el helper chequea contra TODOS los roots). Riesgo bajo. Mitigación: el helper recibe la lista completa de roots canonicalizados.
- **Race de reload durante lectura** → un reload que reduce `watch_paths` mientras `_read_loop` procesa un batch podría descartar/aceptar un evento con la config vieja por unos ms. Impacto: despreciable (a lo sumo un evento clasificado con la ventana previa). Mitigación: rebind atómico del cache; no se requiere lock (consistente con el modelo single-loop existente).
- **Costo de `realpath` en el scan de baseline** → un `init_scan` sobre árboles grandes hace un `realpath` extra por candidato. Impacto: bajo comparado con el hash+cifrado que ya hace por archivo. Sin mitigación especial.

## Migration Plan

- Sin migración de datos ni cambios de schema (D4). Deploy = actualizar el paquete del agente y reiniciar el servicio systemd.
- Rollback: revertir el paquete del agente. No hay estado persistido nuevo que limpiar. El backend es indiferente (nunca leyó los nuevos campos).
- Efecto observable tras el deploy: baja el volumen de eventos publicados en hosts de un solo mount (solo `watch_paths`), y `out_of_scope_drops` > 0 en el heartbeat cuando hay tráfico fuera de alcance.

## Open Questions

- Ninguna que bloquee. Toda la decisión (filtro en `_read_loop`, canonicalización única, skip de symlinks, contador análogo a `event_drops`) está cerrada en D31/RN-125. La única observación abierta (alinear `commands.py` a `is_relative_to`) es intencionalmente Non-Goal y se reporta, no se asume.
