## 1. Helper de containment compartido

- [x] 1.1 Agregar un helper puro `_realpath_in_scope(path: str, canonical_roots: list[str]) -> bool` (en `agent/detector.py`, o en un módulo util reutilizable por `baseline.py`) que canonicalice `path` con `os.path.realpath` y devuelva `True` si `Path(real).is_relative_to(root)` para algún root ya canonicalizado. Roots vacíos → `False` (nada en scope, RN-04 "excepciones: ninguna").
- [x] 1.2 Test unitario del helper: path dentro de un root → True; path fuera → False; prefijo falso (`/etc/apple` vs root `/etc/app`) → False; symlink que resuelve dentro → True; symlink que resuelve fuera → False; lista de roots vacía → False.

## 2. Cache de watch_paths canonicalizados (detector)

- [x] 2.1 Agregar `self._watch_paths_real: list[str]` en `FanotifyDetector.__init__` (inicializar desde `watch_paths` o vacío).
- [x] 2.2 Recomputar `self._watch_paths_real` (lista nueva, rebind atómico) en `start()`, `reload_paths()` y `reload_watch_paths()` — incluida la rama `noop_no_fan` de `reload_watch_paths`. Canonicalizar con `os.path.realpath` una sola vez por path.
- [x] 2.3 Test: tras `start()`/`reload_paths()`/`reload_watch_paths()`, `_watch_paths_real` refleja los `realpath` de los `watch_paths` actuales; un `watch_path` que es symlink queda representado por su target canonicalizado.

## 3. Filtro de scope en `_read_loop` (detector)

- [x] 3.1 Agregar `self._out_of_scope_drops: int = 0` y la propiedad pública `out_of_scope_drops` (análoga a `event_drops`).
- [x] 3.2 En `_read_loop`, dentro del `for ev in raw_events`, tras el guard `ev.path is None` y ANTES de construir `FanotifyEvent`: si `not _realpath_in_scope(ev.path, self._watch_paths_real)` → incrementar `out_of_scope_drops`, emitir `log.warning("detector.out_of_scope_drop", path=..., total_drops=...)` y `continue` (no construir el evento, no `call_soon_threadsafe`).
- [x] 3.3 Test: evento cuyo `realpath` cae dentro de un `watch_path` → se encola (`_raw_queue` recibe el `FanotifyEvent`). Evento fuera de todos los `watch_paths` → NO se encola y `out_of_scope_drops` incrementa. Evento in-scope no toca el contador.
- [x] 3.4 Test: un symlink cuyo `realpath` escapa del scope generado como evento → se descarta en `_read_loop`.

## 4. Contador en el heartbeat (agente)

- [x] 4.1 En `agent/heartbeat.py::_publish`, agregar al payload `"out_of_scope_drops": self._detector.out_of_scope_drops if self._detector is not None else 0` (mismo patrón que `event_drops`).
- [x] 4.2 Test: el payload del heartbeat incluye `out_of_scope_drops` reflejando el contador del detector; con detector `None` → `0`.

## 5. Skip de out-of-scope en el baseline scan

- [x] 5.1 En `agent/baseline.py::init_scan`: canonicalizar `watch_path` una vez por iteración; para cada `file_path` candidato (tras `if not file_path.is_file()`), si `not _realpath_in_scope(str(file_path), [realpath_del_watch_path])` → `log.warning("baseline.out_of_scope_skip", path=...)` y `continue` (no `write_entry`; contabilizar como `skipped`).
- [x] 5.2 Aplicar el mismo criterio en `run_scan` (rescan y paths recién añadidos).
- [x] 5.3 Test: symlink dentro de un `watch_path` que apunta afuera (p. ej. a un archivo externo en `tmp_path`) → se omite con warning y NO se crea entry de baseline. Archivo regular in-scope → se baselina normalmente. `run_scan` se comporta igual que `init_scan`.

## 6. Verificación y cierre

- [x] 6.1 Correr la suite del agente (`pytest agent/tests/`) y confirmar que no hay regresiones en detector, baseline ni heartbeat existentes.
- [x] 6.2 Verificación manual/log: en un host de un solo mount, un cambio fuera de `watch_paths` ya no genera evento publicado; el heartbeat reporta `out_of_scope_drops` > 0 ante tráfico fuera de alcance; un symlink dentro de `watch_paths` que apunta afuera se omite del baseline con warning.
- [x] 6.3 Confirmar que el backend no requirió cambios (consumer de heartbeat ignora `out_of_scope_drops`; sin migración).
