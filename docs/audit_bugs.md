# Auditoría de bugs — FIM Platform

Resultado de revisión multi-agente (5 agentes en paralelo) sobre el código completo de `backend/`, `agent/` y módulos relacionados. Fecha: 2026-06-23.

---

## Resumen ejecutivo

| Severidad | Cantidad |
|-----------|----------|
| Crítico   | 10       |
| Alto      | 8        |
| Medio     | 9        |
| **Total** | **27**   |

Las funcionalidades core afectadas por críticos: restore/quarantine de archivos (no-op), mTLS 8443 (no arranca), pérdida silenciosa de eventos de integridad, bypass de autenticación.

---

## CRÍTICOS

### C1 — `register_command_handlers()` nunca se llama — restore/quarantine son no-op

**Área**: Agente · **Archivo**: `agent/publisher.py:103-120`, `agent/__main__.py:135`

`register_command_handlers` setea `_baseline_engine` y `_agent_state` en el publisher, que son los guards de la rama de comandos destructivos. Como nunca se llama (solo se llama `register_callbacks`), la condición en `_handle_command_async:222-225` siempre es falsa:

```python
if (self._baseline_engine is not None and self._agent_state is not None):
    _commands.dispatch(...)  # nunca llega acá
else:
    log.warning("publisher.command_handler_not_registered", ...)  # siempre acá
```

**Impacto**: `baseline_update`, `restore_file`, `quarantine_file`, `rescan_baseline` son silenciosamente ignorados. El backend ordena una restauración de archivo, el agente loguea un warning y no hace nada.

**Fix**: Llamar `publisher.register_command_handlers(baseline_engine, agent_state)` en `__main__.py` junto al resto de la inicialización.

---

### C2 — Comandos `event_ack`, `update_config`, `rule_sync` sin verificación HMAC (viola RN-79)

**Área**: Agente · **Archivo**: `agent/publisher.py:182-216`

La ruta "viva" del listener de `fim:commands` parsea y ejecuta estos comandos sin llamar `verify_payload`:

```python
if cmd_type == "event_ack":
    self._queue.remove(event_id)         # borra cola sin verificar firma
elif cmd_type == "update_config":
    self._on_update_config_cb(new_paths) # reconfigura fanotify sin firma
elif cmd_type == "rule_sync":
    self._on_rule_sync_cb(rules_payload, ruleset_version)  # inyecta reglas sin firma
```

**Impacto**: Cualquiera con acceso de escritura al stream `fim:commands` puede purgar la cola offline, reapuntar los watchers de fanotify a paths arbitrarios, o inyectar reglas de decisión falsas — sin la `shared_secret`. RN-79 exige "comandos con signature inválida se descartan".

**Fix**: Llamar `verify_payload(payload, shared_secret)` antes del dispatch, igual que hace `commands.dispatch`.

---

### C3 — `update_config` por ruta publisher no verifica `ruleset_version`

**Área**: Agente · **Archivo**: `agent/publisher.py:202-206`

La ruta viva de `update_config` solo invoca `_on_update_config_cb(new_paths)` sin comparar el `ruleset_version` del comando contra el local ni persistir el nuevo estado. La implementación correcta está en `commands.handle_update_config` (que sí chequea versión y persiste), pero esa ruta está muerta por C1.

**Impacto**: Comandos `update_config` viejos o reordenados reconfiguran los watchers de fanotify, violando la monotonía de versiones (RN-75).

**Fix**: Resolver C1 primero. Una vez activa la ruta de `commands.dispatch`, este bug desaparece.

---

### C4 — Race condition en `_pending` del detector sin lock

**Área**: Agente · **Archivo**: `agent/detector.py:282-283`, `agent/detector.py:368-372`

`self._pending` (dict path→event) se lee/escribe en `_process_event` (loop asyncio) y se muta en `on_ack` (llamado desde el command consumer, potencialmente en otra tarea). No hay lock:

```python
# _process_event (línea 282)
self._pending[path] = event_id

# on_ack (línea 370) — puede correr concurrentemente
del self._pending[path]
```

**Impacto**: Corrupción del dict `_pending`, pérdida o duplicación de `parent_event_id` en la cadena de eventos superseded.

**Fix**: Proteger `_pending` con `asyncio.Lock` o garantizar que `on_ack` siempre corre en el mismo loop via `loop.call_soon_threadsafe`.

---

### C5 — `file_absent` falso por race entre evento fanotify y lectura de hash

**Área**: Agente · **Archivo**: `agent/detector.py:262-264`, `agent/baseline.py:mark_absent`

`_hash_file` devuelve `None` para cualquier `FileNotFoundError`. Si un archivo existe pero fue renombrado o movido entre el evento fanotify y la lectura del hash (patrón de escritura atómica de editores: write-tmp + rename), se emite un `file_absent` falso y se llama `mark_absent(path)`, destruyendo el baseline de un archivo que sigue existiendo.

**Impacto**: Pérdida de baseline de archivos en edición activa; restauraciones futuras fallan.

**Fix**: Reintentar el hash con un pequeño backoff (ej. 50-100ms x2) antes de considerar el archivo ausente.

---

### C6 — Refresh token usable como access token (bypass de TTL)

**Área**: Backend · **Archivo**: `backend/app/core/deps.py:32-57`

`get_current_user` llama `decode_token(token)` y nunca verifica `payload.get("type")`. El refresh token tiene `"type": "refresh"` y TTL de 7 días. Puede usarse directamente como Bearer access token contra cualquier endpoint protegido, bypaseando el TTL de 15 minutos del access token.

**Impacto**: Un refresh token comprometido da acceso full por 7 días en vez de 15 minutos.

**Fix**: En `get_current_user`, agregar:
```python
if payload.get("type") == "refresh":
    raise HTTPException(status_code=401, detail="token_type_invalid")
```

---

### C7 — Endpoints de `events/` no usan `require_full_access` — bypass de `must_change_password`

**Área**: Backend · **Archivo**: `backend/app/modules/events/router.py:63,100`

Los endpoints `GET /events` y `GET /events/{id}` usan `Depends(get_current_user)` en vez de `Depends(require_full_access)`. Un usuario con `must_change_password=True` recibe un token con `scope=password_change_only`, pero puede leer todos los eventos de integridad del sistema sin cambiar su password.

**Impacto**: El flujo de seguridad `must_change_password` queda bypasseado para el dominio events.

**Fix**: Reemplazar `get_current_user` por `require_full_access` en ambos endpoints de events.

---

### C8 — Consumer hace `xack` cuando `event is None` — pérdida silenciosa de eventos

**Área**: Backend · **Archivo**: `backend/app/modules/events/consumer.py:186-194`

```python
event = _ingest(payload, received_at, detected_at)
await client.xack(STREAM_EVENTS, CONSUMER_GROUP, msg_id)  # ACK incondicional
if event is not None and event_id:
    ...
elif event is None:
    log.warning("consumer.event_ingest_skipped", ...)
```

Cuando `mark_superseded` devuelve `None` por carrera (race legítima), `_ingest` retorna `None`, pero el `xack` ya se ejecutó. El evento de integridad no se persiste y nunca se reintenta.

**Impacto**: Eventos de modificación de archivo se pierden silenciosamente bajo carga concurrente.

**Fix**: Mover el `xack` dentro del bloque `if event is not None`, o después de verificar que la ingesta fue exitosa.

---

### C9 — `compact_chain` viola FK `parent_event_id` — `IntegrityError` o cadena rota

**Área**: Backend · **Archivo**: `backend/app/modules/events/service.py:119-124`, `backend/app/modules/events/models.py:26`

`compact_chain` borra eventos `superseded` más antiguos, pero cada uno puede ser el `parent_event_id` del siguiente. La FK no tiene `ondelete` → default `NO ACTION` en PostgreSQL. El `DELETE` lanza `IntegrityError` y aborta toda la transacción de `ingest_event`, perdiendo el nuevo evento. Si se borra en orden incorrecto, el hijo queda con `parent_event_id` apuntando a un ID inexistente.

**Impacto**: `ingest_event` falla con `IntegrityError` en paths con historial largo, o la cadena superseded queda rota.

**Fix**: Agregar `ondelete="SET NULL"` en `parent_event_id`, o borrrar los eventos en orden inverso (hijos antes que padres).

---

### C10 — mTLS thread llama `signal.signal()` desde non-main thread — puerto 8443 nunca arranca

**Área**: Backend · **Archivo**: `backend/app/core/pki.py:193-217`

`asyncio.run(server.serve())` corre dentro de un thread secundario. `uvicorn.Server.serve()` llama `install_signal_handlers()`, que invoca `signal.signal()`. Python solo permite `signal.signal()` desde el main thread — en otro thread lanza `ValueError`. El `except (SystemExit, Exception)` lo captura y loguea `pki.mtls_server.exited`, pero el servidor mTLS nunca queda activo.

**Impacto**: El puerto 8443 está cerrado. Los agentes FIM no pueden conectarse al backend via mTLS. Toda la funcionalidad del agente está rota en producción.

**Fix**: Pasar `config.install_signal_handlers = False` antes de crear el `uvicorn.Server`, o usar `uvicorn.Config(app, ..., workers=1)` con señales deshabilitadas en el thread secundario.

---

## ALTOS

### H1 — Cola FIFO rota por sort lexicográfico — drop-oldest borra el evento equivocado

**Área**: Agente · **Archivo**: `agent/queue.py:44-45`, `agent/queue.py:80-81`

El nombre del archivo es `{detected_at_ms}_{event_id}.json` y el sort es lexicográfico sobre strings. Timestamps de diferente longitud de dígitos no ordenan cronológicamente:

```
sorted(['1700000000000_a.json', '999999999999_b.json'])
# => ['1700000000000_...', '999999999999_...']  — 12 dígitos ordena después de 13
```

`drop-oldest` usa `files[0].unlink()` tras el sort → puede borrar el evento más nuevo.

**Fix**: Zero-pad el timestamp a longitud fija (16 dígitos), o usar `sorted(..., key=lambda f: int(f.stem.split('_')[0]))`.

---

### H2 — Journal sin HMAC y escritura no atómica

**Área**: Agente · **Archivo**: `agent/journal.py:98-107`

`_write` hace `self._path(...).write_text(json.dumps(...))` — escritura no atómica (sin tmp+rename, sin fsync). Si el proceso muere a mitad, la entrada queda truncada; `_read` la descarta silenciosamente con `except Exception: return None`. RN-83 exige rehidratación de acciones pendientes al reiniciar — con entradas perdidas eso no es posible. Además no hay HMAC; no se puede detectar manipulación del journal por un atacante con acceso al filesystem.

**Fix**: Escritura atómica (write tmp → fsync → rename). HMAC con `shared_secret` sobre el contenido JSON.

---

### H3 — Bootstrap: cert descargado sin verificación criptográfica — MITM aceptado

**Área**: Agente · **Archivo**: `agent/bootstrap.py:108,117-128`

El POST de bootstrap usa `verify=False`. El cert recibido se escribe directamente sin verificar:
- que chainee al `ca_cert_pem` recibido,
- que la clave pública coincida con la `private_key` local (que el backend firmó el CSR correcto),
- que el CN sea el `agent_id` esperado.

`is_bootstrapped` solo chequea expiración, nada más.

**Impacto**: Un MITM puede devolver un cert arbitrario que el agente acepta como ancla de confianza para mTLS futuro.

**Fix**: Validar la cadena cert→CA con `cryptography` antes de persistir. El primer request puede ir sin verificar el servidor, pero el material recibido debe verificarse localmente.

---

### H4 — `update_from_command` destruye snapshots y content_b64 existentes

**Área**: Agente · **Archivo**: `agent/baseline.py:439-471`

Construye un `BaselineEntry` con `snapshots=[]` y `content_b64=None` y lo escribe vía `_atomic_write`, sobreescribiendo el entry existente completo. Cualquier `restore_file` posterior al primer `baseline_update` del backend falla con `no_baseline_content`.

**Fix**: Leer el entry existente, actualizar solo `hash`, `last_updated` y `ruleset_version`, preservar `snapshots` y `content_b64`.

---

### H5 — `asyncio.create_task()` sin guardar referencia — tasks garbage-collected mid-execution

**Área**: Backend · **Archivos**: `backend/app/modules/events/consumer.py:192`, `backend/app/modules/alerts/service.py:272`

```python
asyncio.create_task(notify_if_applicable(event))  # sin referencia
asyncio.create_task(notify_event(...))             # sin referencia
```

Tasks sin referencia fuerte pueden ser garbage-collected antes de completar. Alertas críticas y reintentos de notificación se pierden silenciosamente.

**Fix**: Guardar referencia en un set y limpiarla en el callback `add_done_callback`.

---

### H6 — `publish_rule_sync` commitea `RulesetVersion` antes de publicar a Valkey

**Área**: Backend · **Archivo**: `backend/app/modules/rules/service.py:88-140`

El flujo commitea Rule + RulesetVersion en PostgreSQL y después llama `publish_rule_sync`. Si Valkey está caído, el commit ya ocurrió pero los agentes nunca reciben las reglas. La versión avanzó pero el ruleset real no cambió en los agentes.

**Fix**: Implementar outbox pattern: guardar el mensaje pendiente en DB en la misma transacción, publicar a Valkey en un background task que retry.

---

### H7 — SSE broadcaster memory leak — queue sin límite y clientes desconectados no se limpian

**Área**: Backend · **Archivo**: `backend/app/modules/alerts/stream.py:34-36`, `backend/app/modules/alerts/router.py:142-154`

`publish()` hace `queue.put_nowait()` sobre `asyncio.Queue()` sin `maxsize`. Un cliente lento o desconectado acumula dicts indefinidamente. La limpieza (`unsubscribe`) depende del `finally` del generador, que solo corre cuando el generator termina — hasta 15s de latencia tras desconexión.

**Fix**: `asyncio.Queue(maxsize=100)` con descarte del oldest al overflow; detectar `request.is_disconnected()` en loop tight.

---

### H8 — I/O síncrono de DB dentro del event loop en heartbeat consumer

**Área**: Backend · **Archivo**: `backend/app/modules/agents/heartbeat_consumer.py:61-85`, `heartbeat_consumer.py:100`

`_handle_heartbeat` y `_sweep_offline` son funciones `def` síncronas que abren `Session(engine)` y hacen `session.commit()`, llamadas directamente desde coroutines async sin `run_in_executor`. Bloquean el event loop durante cada round-trip a PostgreSQL.

**Fix**: Convertir a `async def` con `AsyncSession`, o envolver con `asyncio.get_event_loop().run_in_executor(None, ...)`.

---

## MEDIOS

### M1 — Rate limit fixed-window (no sliding) + stuck-key lockout

**Archivo**: `backend/app/core/rate_limit.py`

El `expire` solo se setea cuando `count == 1`. Si `incr` tiene éxito pero `expire` falla (error de red a Valkey), la key queda sin TTL → lockout permanente del IP/usuario. Además el docstring dice "sliding-window" pero es fixed-window: hasta `2*max` requests en el boundary.

---

### M2 — Paginación de `/events` carga toda la tabla en memoria

**Archivo**: `backend/app/modules/events/router.py:82-86`

```python
all_events = session.exec(q).all()  # trae TODO a memoria
total = len(all_events)
items = all_events[offset : offset + page_size]
```

Con volumen real de un FIM esto es OOM/DoS.

**Fix**: `func.count()` en query separada + `.offset(offset).limit(page_size)` en la query principal.

---

### M3 — `UserItem.email` se llena con `username` — modelo inconsistente

**Archivos**: `backend/app/modules/users/router.py:102`, `backend/app/modules/users/schemas.py:30`

`UserItem(id=u.id, email=u.username, ...)` — el campo `email` del schema devuelve el username. `CreateUserRequest.email` acepta cualquier string (no `EmailStr` pese a estar importada).

---

### M4 — `_sweep_offline` no detecta agentes con `last_heartbeat = NULL`

**Archivo**: `backend/app/modules/agents/heartbeat_consumer.py:107-125`

`Agent.last_heartbeat < offline_threshold` excluye filas NULL (en SQL, `NULL < x` es NULL/falso). Agentes que nunca latieron nunca transicionan a offline/dead.

---

### M5 — `update_agent_config` genera JSON inválido en audit log

**Archivo**: `backend/app/modules/agents/service.py:163-168`

```python
detail=f'{{"agent_id": "{agent_id}", "watch_paths": {watch_paths}}}'
```

`watch_paths` es `list[str]` de Python → `str(list)` usa comillas simples → JSON inválido. Si un path contiene `"` o `\`, también rompe la estructura.

**Fix**: `json.dumps({"agent_id": agent_id, "watch_paths": watch_paths})`.

---

### M6 — `RulesetVersion.increment` no es atómico

**Archivos**: `backend/app/modules/rules/service.py:67-82`, `backend/app/modules/actions/service.py:61-75`

Dos implementaciones duplicadas que hacen `SELECT` + `rv.version += 1` + `flush`. Sin `SELECT FOR UPDATE`, dos requests concurrentes pueden leer la misma versión y ambas escribir `version+1`.

**Fix**: `UPDATE ruleset_versions SET version = version + 1 RETURNING version` en una sola query atómica.

---

### M7 — `ruleset_version` gate inconsistente entre rules.py y commands.py

**Archivos**: `agent/rules.py:86`, `agent/commands.py:218`

`rules.py` rechaza cuando `ruleset_version <= state.ruleset_version` (igual rechazado). `commands.py` rechaza cuando `cmd_version < state.ruleset_version` (igual aceptado). Un comando redelivered con la misma versión se re-aplica por la ruta commands y se rechaza por la ruta rules.

---

### M8 — `reject_single` en caso `baseline absent` no publica comando al agente

**Archivo**: `backend/app/modules/actions/service.py:264-276`

Si `baseline_entry.status == absent`, el código hace log de no-op y no publica ningún comando — ni siquiera para `action=quarantine`. El evento queda marcado `rejected` en DB pero el agente no recibe la orden. Divergencia estado-backend vs acción-real sin feedback al usuario.

---

### M9 — `_check_n8n` en health: `HTTPStatusError` es dead code

**Archivo**: `backend/app/core/health.py:70-78`

`client.head()` sin `raise_for_status()` nunca lanza `HTTPStatusError`. El `except httpx.HTTPStatusError` nunca se ejecuta. El fallback GET documentado tampoco existe.

---

## Lo que está correcto (no son bugs)

- AES-GCM: nonce fresco por write con `os.urandom(12)` — correcto y testeado.
- HKDF key derivation: construcción correcta, determinística por `agent_id`.
- Rotación de snapshots: `all_snaps[-_MAX_SNAPSHOTS:]` guarda los 3 más nuevos, descarta los más viejos — correcto.
- Decision engine "first rule wins": `rules.py:63-75` retorna en el primer match — correcto.
- `verify_payload` con `hmac.compare_digest` (constant-time) — correcto.
- Lifespan shutdown con `gather(..., return_exceptions=True)` — correcto.
- `decode_token` fallback dual-key (current/previous JWT secret) — correcto.
- `TraceIdMiddleware` contextvar bind/unbind/reset — correcto.
- Quarantine con `shutil.move` remueve el original — correcto.
