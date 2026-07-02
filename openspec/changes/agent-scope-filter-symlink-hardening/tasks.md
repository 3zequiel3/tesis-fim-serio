## 1. Agente — containment por ubicación del link (`agent/detector.py`)

- [x] 1.1 Renombrar `_realpath_in_scope` a `_target_in_scope` y actualizar todas sus referencias; documentar que queda SOLO para checks de metadata (destino resuelto), nunca en el punto de descarte
- [x] 1.2 Implementar `_path_location_in_scope(path, watch_paths)`: canonicaliza `os.path.realpath(os.path.dirname(path))` y compara el `basename` literal contra los `watch_paths` canonicalizados, sin seguir el componente final
- [x] 1.3 Reemplazar el uso del containment por `realpath` completo por `_path_location_in_scope` en el punto de descarte de `_read_loop` (mantener el cache de `watch_paths` canonicalizados de `start()`/`reload_paths()`/`reload_watch_paths()`)
- [x] 1.4 Verificar que la excepción "`watch_path` que es él mismo un symlink" (D31) se conserva: se canonicaliza una vez y ese `realpath` define el límite

## 2. Agente — symlink-as-object (`agent/detector.py`)

- [x] 2.1 Agregar la rama symlink en `_process_event`: si el componente final es symlink, usar `os.lstat`/`os.readlink`; NUNCA abrir/hashear/cifrar el contenido del destino
- [x] 2.2 Reportar con léxico RN-71 (`file_created`/`file_deleted`/`file_modified`, sin `event_type` nuevo); `hash_detected = sha256(os.readlink(path))`; `diff`/contenido = `None`
- [x] 2.3 Incluir `is_symlink=true` y `symlink_target` (string de `readlink`) en el payload del evento
- [x] 2.4 Confirmar que el re-pointing de un symlink existente se detecta como `file_modified` (cambia el string de `readlink` → cambia el hash)

## 3. Agente — baseline symlink-aware (`agent/baseline.py`)

- [x] 3.1 Agregar `symlink_target: str | None = None` a `BaselineEntry` con default retrocompatible en `from_dict`
- [x] 3.2 Implementar `write_symlink_entry` (usa `os.lstat`/`os.readlink`; `content_b64=None`; `hash=sha256(target)`; `symlink_target=target`)
- [x] 3.3 En `init_scan` y `run_scan`, chequear `p.is_symlink()` ANTES de `p.is_file()` y derivar los symlinks a `write_symlink_entry`
- [x] 3.4 Confirmar que un archivo regular cuyo `realpath` escapa del `watch_path` (vía dir intermedio simbólico) se sigue omitiendo con warning

## 4. Agente — contador detective de hardlinks (`agent/detector.py`, `agent/heartbeat.py`)

- [x] 4.1 Incrementar `hardlink_suspected` al crear un archivo regular en scope con `st_nlink >= 2`, SIN alterar clasificación/hash/cifrado/publicación
- [x] 4.2 Exponer `hardlink_suspected` en el payload del heartbeat (campo opcional, análogo a `out_of_scope_drops`)

## 5. Agente — tests (`agent/tests/`)

- [x] 5.1 Matriz de edge cases (contrato del diseño, obs #238 §3): create/delete/modify de symlink, dir intermedio simbólico in-scope, dir intermedio simbólico out-of-scope, `watch_path` simbólico, archivo regular
- [x] 5.2 No-regresión C35: un `file_deleted` de un archivo regular dentro de scope DEBE seguir publicándose
- [x] 5.3 Symlink-as-object: el contenido del destino (in y out of scope) nunca se abre/hashea/cifra; `hash_detected == sha256(readlink)`
- [x] 5.4 Baseline: `write_symlink_entry` no lee contenido; `from_dict` parsea entradas viejas sin `symlink_target`; delete de symlink registrado no es espurio (LOW-1)
- [x] 5.5 `auto_restore` sobre un symlink degrada limpiamente (`select_restorable_content` retorna `None` con `content_b64=None`), sin crash
- [x] 5.6 `hardlink_suspected` se incrementa con `st_nlink >= 2` y no cambia el comportamiento del create de archivo regular

## 6. Backend — modelo y migración (`backend/app/modules/events/models.py`, `backend/db/migrations/`)

- [x] 6.1 Agregar columnas `is_symlink: bool = False` y `symlink_target: str | None = None` a `Event`
- [x] 6.2 Crear migración SQL idempotente `005_*.sql` (próximo número tras `004_add_command_ack_tracking.sql`, convención D3) con `ADD COLUMN IF NOT EXISTS`

## 7. Backend — ingesta y exposición (`service.py`, `EventOut`)

- [x] 7.1 `ingest_event` toma `is_symlink`/`symlink_target` del payload con `.get()` tolerante y los persiste en el `Event`
- [x] 7.2 `EventOut` expone `is_symlink`/`symlink_target` (mismo patrón que `ack_status` de D30/C36) en `GET /events` y `GET /events/{id}`
- [x] 7.3 Confirmar que la validación cheap-to-expensive y la lógica de supersede/optimistic-locking no cambian

## 8. Backend — tests (`backend/tests/`)

- [x] 8.1 Ingesta de un payload de symlink persiste `is_symlink`/`symlink_target` en el `Event`
- [x] 8.2 Payload de agente viejo (sin las keys) ingiere con defaults `false`/`null` sin error
- [x] 8.3 `EventOut` serializa el metadato para eventos de symlink y con defaults para archivos regulares
- [x] 8.4 La migración es idempotente (re-ejecutar no falla)

## 9. Frontend — badge de symlink (`frontend/src/api/events.ts`, tabla/detalle de eventos)

- [x] 9.1 Agregar `is_symlink: boolean` y `symlink_target: string | null` al tipo del evento en `frontend/src/api/events.ts`
- [x] 9.2 Renderizar un badge/indicador de symlink con su `symlink_target` en la tabla de eventos, solo cuando `is_symlink` es true
- [x] 9.3 Mostrar el indicador y el `symlink_target` en el detalle de evento; los eventos de archivo regular renderizan sin cambios

## 10. Cierre

- [x] 10.1 Correr la suite del agente, del backend y el build/lint del frontend; todo verde
- [x] 10.2 Verificar contra los delta specs (5 capabilities) que cada scenario tiene cobertura
- [ ] 10.3 Actualizar el estado de C39 en CHANGES.md si corresponde al momento de archivar (fase de archive, no de apply)
