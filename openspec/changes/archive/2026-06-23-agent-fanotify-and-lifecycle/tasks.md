## 1. F2 — Escritura unificada de state.json (sin race)

- [x] 1.1 En `agent/state.py`: agregar campo `rules: list = field(default_factory=list)` a `AgentState`; `load_state` lee `rules` (default `[]`).
- [x] 1.2 En `agent/state.py`: hacer `save_state` no destructivo — serializa `{ruleset_version, last_stream_command_id, rules}` desde el estado, escritura atómica `.tmp` + `os.replace`, `0600`.
- [x] 1.3 En `agent/rules.py`: `RulesCache._persist` deja de abrir `state.json`; actualiza `state.rules` y `state.ruleset_version` y llama `save_state(state)`. Ajustar `update()` para que reciba/mantenga el `AgentState`.
- [x] 1.4 Verificar que `RulesCache._load_from_file` siga cargando `rules` desde `state.json` correctamente tras el cambio de formato.
- [x] 1.5 Test: persistir cursor de comandos no borra `rules` ni `ruleset_version`; persistir reglas no borra `last_stream_command_id`.

## 2. F3 — Fallback a snapshots en restauración

- [x] 2.1 En `agent/baseline.py`: agregar helper puro `select_restorable_content(entry) -> tuple[bytes, str] | None` que devuelve `(content_bytes, expected_hash)` del contenido activo o, si es `None`, del snapshot más reciente con `content_b64` no nulo (descomprimiendo si `gzip=True`).
- [x] 2.2 En `agent/decision.py::_auto_restore`: usar el helper; si retorna `None` lanzar `_ActionFailed("no_restorable_content")`; verificar SHA-256 contra el `expected_hash` devuelto.
- [x] 2.3 En `agent/commands.py::handle_restore_file`: usar el helper; si retorna `None` journalizar fallo `no_restorable_content`; verificar SHA-256 contra el `expected_hash` devuelto.
- [x] 2.4 Test: auto_restore restaura desde snapshot cuando `content_b64` activo es `None`; snapshot `gzip=True` se descomprime; sin snapshot utilizable → `no_restorable_content`; contenido activo presente conserva comportamiento previo.
- [x] 2.5 Test: `handle_restore_file` cubre los mismos cuatro casos.

## 3. D12 — Detector fanotify multi-evento + operation_type

- [x] 3.1 En `agent/detector.py`: extender `_mark_paths` (y `reload_paths`/`reload_watch_paths`) con la máscara `FAN_CLOSE_WRITE | FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO | FAN_CREATE`.
- [x] 3.2 En `_read_loop`: capturar el tipo/máscara del evento (`ev`) además del path; agregar el campo a `FanotifyEvent`. Si `ev.path is None`: `log.warning` y descartar (no encolar).
- [x] 3.3 En `_process_event`: despachar por tipo — `FAN_DELETE`/`FAN_MOVED_FROM` → `operation_type="file_deleted"`, sin hash, `mark_absent(path)`; `FAN_CREATE`/`FAN_MOVED_TO` → `operation_type="file_created"`, hash + `write_entry(path)`; `FAN_CLOSE_WRITE` → lógica actual (`file_modified`/`file_absent`).
- [x] 3.4 En `DetectedChange.to_event_data()`: emitir el campo `operation_type` (snake_case) en el payload. Mantener compatibilidad: el consumer trata payloads sin el campo como `file_modified`.
- [x] 3.5 Test: cada tipo de evento produce el `operation_type` correcto; `file_deleted` emite `hash` nulo y marca baseline `absent`; `file_created` hashea y persiste entry; `ev.path is None` se descarta con warning.

## 4. G4 — Propagación de shutdown al heartbeat

- [x] 4.1 En `agent/__main__.py::_shutdown`: llamar `publisher.set_shutdown(True)` antes de `_drain_then_stop` y de activar `stop_event`.
- [x] 4.2 En `agent/heartbeat.py`: que `run`/`_publish` lean `publisher.shutdown` como fuente de verdad del flag (consolidar con `shutdown_flag`). Verificar que ningún otro consumidor dependa de `shutdown_flag`; si no, eliminarlo.
- [x] 4.3 Test: tras `SIGTERM`, `publisher.set_shutdown(True)` es llamado y los heartbeats durante el drenaje contienen `shutdown=true`.

## 5. G3 — Renovación proactiva de certificado

- [x] 5.1 En `agent/config.py`: agregar `cert_renewal_check_interval_h: float = 24.0` a `AgentConfig` (default cuando ausente en YAML).
- [x] 5.2 En `agent/bootstrap.py`: extraer función reutilizable de verificación de cert (CA firma + CN + clave pública) consumible por bootstrap y renovación.
- [x] 5.3 En `agent/__main__.py`: implementar `_cert_renewal_loop(cfg, stop_event)` — sleep interrumpible cada `cert_renewal_check_interval_h`; lee `not_valid_after_utc`; si vence en ≤ 15 días llama `POST /agents/renew` con `httpx.AsyncClient(cert=(cert,key), verify=ca_pem)` sin `bootstrap_secret`.
- [x] 5.4 Persistir el cert renovado con escritura atómica `0600` solo tras pasar la verificación; cualquier fallo → `log.warning` + continuar.
- [x] 5.5 Registrar `_cert_renewal_loop` entre las corrutinas del loop principal solo si el agente está bootstrapped; pasar `stop_event` para terminación en shutdown.
- [x] 5.6 Test: renovación gatillada en ≤ 15 días y omitida si vigente; éxito persiste cert; 404/error de red/cert inválido → warning + cert actual intacto; intervalo configurable respetado; loop termina al activar `stop_event`.

## 6. Cierre

- [x] 6.1 Correr la suite de tests del agente (`agent/tests`) y asegurar que pasa en verde.
- [x] 6.2 Verificar que no se introdujeron servidores HTTP nuevos (RN-108/D8) ni dependencias nuevas (httpx ya presente).
