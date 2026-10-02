## 0. Precondiciones

- [x] 0.1 Confirmar con `openspec list --json` y `eza openspec/changes/archive` que la Change 61 (`agent-publisher-fifo-reconnect`, D79/RN-173) está archivada. Si no lo está, **detenerse**: esta change no se aplica antes (dependencia del DAG en `CHANGES.md`, Change 62).
- [x] 0.2 Correr `python3 scripts/check_spec_integrity.py` y registrar que pasa antes de tocar código.
- [x] 0.3 Re-verificar las líneas citadas en `design.md` contra el árbol vigente (la Change 61 toca `agent/publisher.py` y puede haber corrido líneas de `agent/__main__.py`). Si alguna rama del detector o de `init_scan` cambió de forma, no de posición, detenerse y reportar.

## 1. Agente — `initialized_roots` en `state.json` (D80/RN-174, D-5)

- [x] 1.1 En `agent/state.py`, agregar `initialized_roots: list[str] = field(default_factory=list)` a `AgentState`, leerlo en `load_state` con `data.get("initialized_roots", [])` (una lista de strings; cualquier otra forma → lista vacía con `log.warning("state.initialized_roots_invalid")`) e incluirlo **ordenado** en el `json.dumps` de `save_state`.
- [x] 1.2 Verificar con `rg -n "save_state\(" agent --glob '!tests'` que todo escritor usa la instancia de `AgentState` creada en `agent/__main__.py`, de modo que ninguna escritura descarte `initialized_roots`. Si aparece un escritor con otra instancia, es un bug preexistente de F2: detenerse y reportar.
- [x] 1.3 Tests en `agent/tests/test_state_initialized_roots.py`: ida y vuelta de `initialized_roots`; `state.json` previo sin la clave → lista vacía sin tratarlo como corrupto; persistir el cursor de comandos y persistir reglas conservan `initialized_roots`.

## 2. Agente — `init_scan` sólo da de alta raíces no inicializadas (D-5)

- [x] 2.1 Extraer en `agent/baseline.py` un helper privado que itere los candidatos de una raíz con las reglas actuales de `init_scan` (symlink antes que archivo, `rglob`, descarte de no-archivos, `_target_in_scope` para archivos regulares con su `log.warning("baseline.out_of_scope_skip")`). `init_scan` y la fase B del reconcile lo comparten; `run_scan` puede seguir con su bucle propio.
- [x] 2.2 Cambiar la firma a `init_scan(self, watch_paths: list[str], initialized_roots: Collection[str] = ()) -> ScanReport`: omitir toda raíz incluida en `initialized_roots`; recorrer las demás como hoy; agregar a `ScanReport` el campo `initialized: list[str]` con las raíces existentes que completó. Una raíz inexistente no se informa.
- [x] 2.3 Actualizar el docstring de `init_scan`: deja de ser «solo procesa archivos sin entry» para todas las raíces; citar D80/RN-174 y explicar por qué una raíz inicializada no se recorre (sus archivos nuevos se reportan en el reconcile, no se aprueban en silencio).
- [x] 2.4 Tests en `agent/tests/test_baseline.py`: primer arranque marca la raíz y no emite; raíz inicializada con un archivo nuevo → `init_scan` no crea la entrada; raíz inexistente no se marca; raíz nueva agregada a la configuración se escanea y se marca.

## 3. Agente — `reconcile_on_start` (D-1, D-6, D-7)

- [x] 3.1 Definir en `agent/baseline.py` los dataclasses `OfflineFinding(path: str, event_class: str)` (con `event_class` ∈ `file_deleted`, `file_modified`, `file_created`) y `ReconcilePlan(findings: list[OfflineFinding], unchanged: int, suppressed_already_reported: int, errors: int)`.
- [x] 3.2 Implementar `BaselineEngine.read_approval_candidate(path) -> ApprovalCandidate | None`: descifra el candidato de `_candidate_path`; `InvalidTag`, `OSError`, `ValueError`, `TypeError` o `json.JSONDecodeError` → `None`. No borra ni modifica el candidato.
- [x] 3.3 Implementar un helper de hash del disco con la regla de D33/RN-127: symlink → `sha256(os.readlink(path))`; archivo regular → SHA-256 del contenido completo, sin el límite de 10 MiB (igual que `write_entry`). Devuelve también si el objeto es symlink.
- [x] 3.4 Implementar `reconcile_on_start(self, watch_paths, initialized_roots) -> ReconcilePlan`, fase A: para cada path de `list_entries()` ubicado bajo una raíz de `initialized_roots ∩ watch_paths` (igualdad para raíz archivo, `Path(path).is_relative_to(Path(root))` para directorio), aplicar la tabla de D-6. El tipo de objeto del baseline sale de `entry.symlink_target is not None`.
- [x] 3.5 Fase B: recorrer cada una de esas raíces con el helper de 2.1 y producir `file_created` para todo candidato sin entrada (`_entry_path(...).exists()` falso).
- [x] 3.6 Supresión de D-7 sólo para `file_modified`: suprimir y contar en `suppressed_already_reported` cuando `read_approval_candidate` devuelve un candidato `present` con el mismo hash y el mismo tipo de objeto que el disco.
- [x] 3.7 `BaselineIntegrityError` u `OSError` por path → `log.warning("baseline.reconcile.path_error", path=..., error=type(exc).__name__)`, `errors += 1` y seguir. Ordenar `findings` por path y deduplicar (un path, a lo sumo un hallazgo).
- [x] 3.8 Verificar leyendo el diff que `reconcile_on_start` no llama a `write_entry`, `write_symlink_entry`, `mark_absent`, `add_snapshot`, `stage_approval_candidate` ni a nada del publisher o del motor de decisión.
- [x] 3.9 Tests unitarios en `agent/tests/test_offline_reconcile.py` sobre `reconcile_on_start`: modificado, eliminado, `absent` que reaparece, archivo nuevo sin entrada en raíz inicializada, sin cambios (`unchanged`), cambio de tipo symlink ↔ regular, raíz no inicializada sin hallazgos, entrada con GCM inválido cuenta en `errors` sin detener el resto, y que ningún blob del baseline cambia tras la llamada (comparar bytes antes y después).
- [x] 3.10 Tests de la supresión: candidato con el mismo hash → suprimido; candidato con otro hash → `file_modified`; candidato ilegible → `file_modified`; candidato con el mismo hash no suprime un `file_deleted` ni un `file_created`.

## 4. Agente — emisión por el camino normal del detector (D-2, D-3, D-4)

- [x] 4.1 En `agent/detector.py`, cambiar `FanotifyEvent.pid` a `int | None` y `DetectedChange.process_pid` a `int | None`. Revisar con `rg -n "\.pid\b|process_pid" agent --glob '!tests'` que ningún consumidor asume entero (incluido `ExperimentTrace`); si alguno lo asume, adaptarlo o detenerse y reportar.
- [x] 4.2 Agregar `detected_offline: bool = False` a `DetectedChange`. Verificar que `to_event_data` lo serializa siempre.
- [x] 4.3 Cambiar la firma a `_process_event(self, fan_event, *, forced_class: str | None = None, detected_offline: bool = False)`: si `forced_class` no es `None` reemplaza a `_classify_event`; propagar `detected_offline` a las tres construcciones de `DetectedChange`. Ninguna otra línea de las tres ramas cambia.
- [x] 4.4 Implementar `async def emit_offline(self, finding: OfflineFinding) -> None`: arma un `FanotifyEvent(path=finding.path, pid=None, uid=None, exe=None, timestamp=<ahora UTC ISO 8601>, mask=0)` y llama a `_process_event` con `forced_class` mapeado (`file_modified` → `close_write`; los otros dos, iguales) y `detected_offline=True`. Comentar citando D80/RN-174, D49/RN-143 (contexto de proceso nulo) y D-4 (por qué no `mtime`).
- [x] 4.5 Verificar leyendo el diff que `emit_offline` no llama directamente a `publisher.publish`, `evaluate_and_act` ni a métodos del baseline: todo pasa por `_process_event`.
- [x] 4.6 Test **modificación offline** (`agent/tests/test_offline_reconcile.py`): baseline con `H1`, se cambia el archivo a `H2` sin detector, se corre el reconcile y se emiten los hallazgos con un detector real, un `DecisionEngine` real con reglas vacías y un publisher falso. Se publica exactamente un `file_modified` con `detected_offline: true`, `hash_detected = H2`, `hash_expected = H1` y proceso nulo; el hash activo del baseline sigue en `H1` (BUG-03).
- [x] 4.7 Test **eliminación offline**: se borra el archivo sin detector; el reconcile publica exactamente un `file_deleted` con `detected_offline: true` y la entrada queda `absent`.
- [x] 4.8 Test **recreación idéntica tras eliminación offline reportada**: continúa 4.7; con el detector en marcha se recrea el archivo con el contenido original y se entrega un evento de creación a `_process_event`. Se publica un `file_created` (hoy suprimido por `detector.py:945-951`) con `detected_offline: false`.
- [x] 4.9 Test **creación offline**: archivo nuevo en raíz inicializada → un `file_created` con `detected_offline: true` y entrada `present` creada por la rama normal.
- [x] 4.10 Test **`absent` que reaparece**: entrada `absent`, el archivo existe al arrancar → un `file_created` con `detected_offline: true`.
- [x] 4.11 Test **no re-emisión**: tras 4.6, simular un segundo arranque sin aprobar ni tocar el archivo → cero publicaciones y `suppressed_already_reported = 1`. Cambiar el archivo a `H3` y simular un tercer arranque → un `file_modified` nuevo.
- [x] 4.12 Test **el reconcile no publica por separado**: con un `DecisionEngine` instrumentado que devuelve un payload marcado y un `commit_fn` espía, cada `publisher.publish` recibe exactamente ese payload y `commit_fn` se invoca después de cada publicación; la cantidad de publicaciones es igual a la de llamadas a `evaluate_and_act`.
- [x] 4.13 Test de acción automática: una regla `auto_restore` sobre el path de una modificación offline restaura el archivo y el evento publicado refleja la acción.
- [x] 4.14 Test de regresión: un evento de fanotify en línea sigue publicando `detected_offline: false` y conserva `process_pid`/`process_uid`/`process_exe` resueltos.

## 5. Agente — arranque y `update_config` (D-5, D-8)

- [x] 5.1 En `agent/__main__.py`, antes de `engine.init_scan` (`:258`): podar `state.initialized_roots` a `cfg.watch_paths`. Pasar `initialized_roots` a `init_scan`, agregar `report.initialized` al conjunto y llamar a `save_state(state)` si el conjunto cambió. Agregar `initialized=len(report.initialized)` al log `baseline.init_scan.complete`.
- [x] 5.2 Implementar `_run_offline_reconcile(engine, detector, state, cfg)` en `agent/__main__.py`: `reconcile_on_start` en `asyncio.to_thread`; `await detector.emit_offline(f)` por hallazgo, en orden; `log.info("baseline.reconcile.complete", deleted=..., modified=..., created=..., suppressed_already_reported=..., unchanged=..., errors=..., duration_ms=...)`. Una excepción inesperada → `log.error("baseline.reconcile.failed", error=type(exc).__name__)` sin relanzar.
- [x] 5.3 Invocar `_run_offline_reconcile` dentro del `try` (`:376`), inmediatamente después de `await decision_engine.rehydrate(publisher)` (`:380`) y antes de `await asyncio.gather(*coroutines)` (`:381`). Sin detector, registrar `log.info("baseline.reconcile.skipped", reason="no_detector")` y no llamar al reconcile.
- [x] 5.4 En `agent/commands.py`, `handle_update_config` (`:578`): agregar a `state.initialized_roots` las raíces escaneadas con `run_scan(added_paths)` que existan y quitar las retiradas, antes del `save_state(state)` existente (`:621`). No agregar una escritura adicional.
- [x] 5.5 Test de orden de arranque: con `BaselineEngine`, `DecisionEngine.rehydrate`, `FanotifyDetector.emit_offline` y `FanotifyDetector.start` instrumentados, `main` registra la secuencia rehidratación → emisiones del reconcile → `start`. Si `main` no es testeable sin refactor, testear `_run_offline_reconcile` y verificar la ubicación leyendo el diff; dejar constancia en el test de cuál de las dos vías se usó.
- [x] 5.6 Test: `reconcile_on_start` que lanza → se registra `baseline.reconcile.failed` y `_run_offline_reconcile` retorna sin propagar.
- [x] 5.7 Test de `handle_update_config`: una raíz agregada queda en `initialized_roots` persistido; una retirada sale.
- [x] 5.8 Test del log de cierre: un reconcile con una eliminación, una modificación y una creación registra `baseline.reconcile.complete` con `deleted=1`, `modified=1`, `created=1`.

## 6. Backend — columna, ingesta y salida (D-9)

- [x] 6.1 Crear `backend/db/migrations/023_add_event_detected_offline.sql` con el encabezado de convención (número, D80/RN-174, Change 62, por qué no hay backfill: `NULL` = el agente no informó el dato, distinto de `false`) y la única sentencia `ALTER TABLE events ADD COLUMN IF NOT EXISTS detected_offline BOOLEAN;`. Sin `DEFAULT`, sin `UPDATE`, sin índice. Mencionar en el encabezado que, cuando exista `schema_migrations` (D84/RN-178, Change 66), esta migración se registra por su número.
- [x] 6.2 En `backend/app/modules/events/models.py`, agregar `detected_offline: bool | None = Field(default=None)` a `Event`, con comentario citando D80/RN-174 y el significado de los tres valores.
- [x] 6.3 En `backend/app/modules/events/service.py` (`_ingest_event_outcome`, construcción de `Event` en `:402-428`): leer `event_data.get("detected_offline")`; `bool` → tal cual; ausente → `None`; otro tipo → `None` y `log.warning("consumer.detected_offline_invalid", event_id=..., value_type=...)`. Usar `isinstance(value, bool)`, no `bool(value)`.
- [x] 6.4 En `backend/app/modules/events/router.py`, agregar `detected_offline: bool | None = None` a `EventOut`, con comentario citando D80/RN-174.
- [x] 6.5 Tests en `backend/tests/test_event_detected_offline.py`: ingesta con `true`, `false`, sin clave y con `"yes"` (con el log); el status derivado no cambia con el campo; `GET /events` y `GET /events/{id}` exponen el valor, incluido `null`; la migración contiene una sola sentencia `ADD COLUMN IF NOT EXISTS` sin `DEFAULT`, `UPDATE` ni `CREATE INDEX` (mismo estilo que el test de `008_add_event_action_error.sql` en `backend/tests/test_event_action_error.py:245`).

## 7. Frontend — indicador en el detalle (D-10)

- [x] 7.1 En `frontend/src/api/events.ts`, agregar `detected_offline?: boolean | null` a `EventListItem`, con comentario citando D80/RN-174.
- [x] 7.2 En `frontend/src/pages/EventDetail.tsx`, agregar `OfflineDetectionBadge` junto a `SymlinkBadge`/`StatusBadge`/`ActionFailedBadge`/`AckStatusBadge` (`:119-122`): se renderiza sólo con `true`, con etiqueta corta y un `title` que explique que el cambio ocurrió con el agente detenido y que `detected_at` es el instante de detección al arrancar. Estilo visual distinto de `ActionFailedBadge`.
- [x] 7.3 No tocar la tabla de eventos. Verificarlo leyendo el diff.
- [x] 7.4 Tests en `frontend/src/pages/EventDetail.test.tsx`: con `true` el indicador aparece con su explicación; con `false`, `null` y ausente no aparece y los demás indicadores siguen iguales.

## 8. Cierre

- [x] 8.1 Correr la suite completa del agente, la del backend y la del frontend; las tres pasan.
- [x] 8.2 Correr `python3 scripts/check_spec_integrity.py`; pasa.
- [x] 8.3 Verificar que los tests requeridos por el Done de la Change 62 en `CHANGES.md` existen y pasan: eliminación (4.7), modificación (4.6), creación (4.9) y recreación idéntica tras eliminación (4.8), cada uno con `detected_offline`; el reconcile no publica sin `DecisionEngine` (4.12); migración `023` aditiva (6.5); el detalle muestra la marca (7.4).
- [x] 8.4 Antes y después de `openspec archive`, correr `python3 scripts/check_spec_integrity.py` (D47/RN-141). El archive lo produce el CLI; nunca escribir a mano bajo `openspec/changes/archive/`.
