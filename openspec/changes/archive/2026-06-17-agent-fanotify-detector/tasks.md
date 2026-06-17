## 1. Módulo detector — esqueleto y tipos

- [x] 1.1 Crear `agent/detector.py` con clase `FanotifyDetector(agent_id, watch_paths, baseline, queue, stop_event)`
- [x] 1.2 Definir dataclass `FanotifyEvent(path, pid, uid, exe, timestamp)` para el evento interno raw
- [x] 1.3 Definir dataclass `DetectedChange(event_id, path, event_type, previous_hash, current_hash, diff_text, process_pid, process_uid, process_exe, detected_at, parent_event_id)` como payload a encolar

## 2. Inicialización fanotify y marcado de filesystems

- [x] 2.1 Implementar `FanotifyDetector._init_fan()` — inicializar grupo pyfanotify con `FAN_CLOEXEC | FAN_CLASS_NOTIF`
- [x] 2.2 Implementar `FanotifyDetector._mark_paths(paths)` — llamar `FAN_MARK_FILESYSTEM | FAN_MARK_ADD` con máscara `FAN_CLOSE_WRITE` para cada path
- [x] 2.3 Añadir `FAN_MARK_FILESYSTEM | FAN_MARK_IGNORED_MASK` sobre `/var/lib/fim-agent` para excluir el directorio de trabajo del agente
- [x] 2.4 Verificar que el marcado falla con error descriptivo si el proceso no tiene `CAP_SYS_ADMIN`

## 3. Loop de lectura en hilo dedicado

- [x] 3.1 Implementar `FanotifyDetector._read_loop()` — bucle bloqueante sobre `pyfanotify.read_events()`, chequea `stop_event.is_set()` cada iteración
- [x] 3.2 Lanzar `_read_loop` en `threading.Thread(daemon=True)` desde `FanotifyDetector.start()`
- [x] 3.3 Publicar cada evento raw en una `asyncio.Queue` compartida con el loop principal (thread-safe via `loop.call_soon_threadsafe`)
- [x] 3.4 Implementar `FanotifyDetector.start()` como corrutina asyncio que arranca el hilo y consume la queue

## 4. Captura de contexto del proceso causante

- [x] 4.1 Implementar `_get_exe(pid: int) -> str | None` — resuelve `/proc/<pid>/exe` con `os.readlink`; devuelve `None` en `OSError`
- [x] 4.2 Extraer `pid`, `uid` del evento pyfanotify y poblar `FanotifyEvent` con resultado de `_get_exe`

## 5. Comparación SHA-256 contra baseline

- [x] 5.1 Implementar `_hash_file(path: str) -> str | None` — SHA-256 hex del contenido actual; `None` si `FileNotFoundError`
- [x] 5.2 Al procesar un evento: obtener `previous_hash` desde `baseline.get(path)` y `current_hash` con `_hash_file`
- [x] 5.3 Si `current_hash == previous_hash` y ambos son no-None: descartar el evento (return sin encolar)
- [x] 5.4 Si `current_hash is None` (archivo borrado): setear `event_type="file_absent"` y llamar `baseline.set_absent(path)`
- [x] 5.5 Si `current_hash != previous_hash` o archivo nuevo: `event_type="file_modified"`, actualizar baseline con nuevo hash

## 6. Generación de diff textual

- [x] 6.1 Implementar `_is_text(path: str) -> bool` — leer primeros 8 KB, retorna `False` si contiene byte `\x00`, `True` si no
- [x] 6.2 Implementar `_generate_diff(path, baseline) -> str | None` — obtener snapshot cifrado anterior de `baseline.get_snapshot(path)`, diff con `difflib.unified_diff` contra contenido actual; retorna `None` si archivo > 1 MB o binario
- [x] 6.3 Poblar `DetectedChange.diff_text` con resultado de `_generate_diff` (solo cuando `event_type="file_modified"`)

## 7. Deduplicación por path con parent_event_id

- [x] 7.1 Añadir `_pending: dict[str, str]` (path → event_id) como atributo de `FanotifyDetector`
- [x] 7.2 Al encolar un `DetectedChange`: si el path ya está en `_pending`, setear `parent_event_id = _pending[path]`; siempre actualizar `_pending[path] = nuevo_event_id`
- [x] 7.3 Implementar `FanotifyDetector.on_ack(event_id: str)` — eliminar de `_pending` la entrada cuyo valor sea `event_id`
- [x] 7.4 Hacer que el command consumer (C08) llame `detector.on_ack(event_id)` al procesar `event_ack`

## 8. Recarga en caliente de watch_paths

- [x] 8.1 Implementar `FanotifyDetector.reload_paths(new_paths: list[str])` — llamar `FAN_MARK_FLUSH`, luego `_mark_paths(new_paths)`, actualizar `self.watch_paths`
- [x] 8.2 Detectar paths nuevos (en `new_paths` pero no en `self.watch_paths`) y llamar `baseline.scan_path(path)` para cada uno antes del marcado
- [x] 8.3 Conectar `reload_paths` al handler de `update_config` en el command consumer (`agent/publisher.py` o `agent/bootstrap.py`)

## 9. Graceful shutdown SIGTERM

- [x] 9.1 Registrar handler SIGTERM en `agent/bootstrap.py` que llama `stop_event.set()`
- [x] 9.2 En `FanotifyDetector.start()`: al `stop_event` dispararse, dejar de consumir la queue de eventos fanotify
- [x] 9.3 Implementar `FanotifyDetector.drain(timeout=30)` — espera a que `queue.py` reporte cola vacía o pasan los 30 s
- [x] 9.4 Durante el drenaje el heartbeat (C08) ya publica con `shutdown=true` al recibir la señal; verificar que el wiring está activo
- [x] 9.5 Tras `drain()`, llamar `sys.exit(0)`

## 10. Wiring en bootstrap

- [x] 10.1 En `agent/bootstrap.py`: instanciar `FanotifyDetector(agent_id, watch_paths, baseline, queue, stop_event)` junto a los módulos C07 y C08
- [x] 10.2 Arrancar el detector con `asyncio.create_task(detector.start())` en el lifespan del agente
- [x] 10.3 Pasar referencia `detector` al command consumer para que llame `on_ack` y `reload_paths`

## 11. Tests unitarios

- [x] 11.1 `tests/agent/test_detector_hash.py` — test `_hash_file`: archivo existente retorna hex SHA-256; archivo borrado retorna `None`
- [x] 11.2 `tests/agent/test_detector_diff.py` — test `_is_text` con archivo de texto y binario; test `_generate_diff` devuelve diff válido para texto y `None` para binario
- [x] 11.3 `tests/agent/test_detector_dedup.py` — test que segundo evento en mismo path tiene `parent_event_id`; test que `on_ack` limpia `_pending`
- [x] 11.4 `tests/agent/test_detector_discard.py` — test que evento con mismo hash no encola nada
- [x] 11.5 `tests/agent/test_detector_context.py` — test `_get_exe` con symlink válido y con `OSError` (retorna `None`)
- [x] 11.6 `tests/agent/test_detector_reload.py` — test `reload_paths` mockeando fanotify: flush llamado, nuevos paths marcados, `scan_path` llamado solo para paths nuevos
- [x] 11.7 Marcar todos los tests de detector con `@pytest.mark.skipif(sys.platform != "linux", reason="fanotify requires Linux")` donde aplique
