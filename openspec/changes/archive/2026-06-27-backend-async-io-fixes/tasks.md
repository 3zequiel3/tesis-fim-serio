# Tasks: backend-async-io-fixes

## 1. core/valkey.py — async singleton

- [x] 1.1 Importar `valkey.asyncio` como `valkey_async_pkg` en `core/valkey.py`
- [x] 1.2 Declarar variable module-level `_async_valkey_client: valkey_async_pkg.Valkey | None = None`
- [x] 1.3 Implementar `init_async_valkey(url: str) -> None` que inicializa el singleton async
- [x] 1.4 Implementar `get_async_valkey_client() -> valkey_async_pkg.Valkey` que retorna el singleton o lanza RuntimeError si no fue inicializado
- [x] 1.5 Implementar `close_async_valkey() -> None` (awaitable) que llama `await _async_valkey_client.aclose()` si existe

## 2. main.py — lifespan del cliente async

- [x] 2.1 Importar `init_async_valkey` y `close_async_valkey` desde `core/valkey.py`
- [x] 2.2 Llamar `init_async_valkey(VALKEY_URL)` en el bloque startup del lifespan (antes del `yield`)
- [x] 2.3 Llamar `await close_async_valkey()` en el bloque shutdown del lifespan (después del `yield`)

## 3. core/rate_limit.py — versiones async de los checks

- [x] 3.1 Importar `get_async_valkey_client` desde `core/valkey.py`
- [x] 3.2 Convertir `check_login_rate_limit` a `async def` usando `await async_client.incr(key)` y `await async_client.expire(key, window)`
- [x] 3.3 Convertir `check_api_rate_limit` a `async def` usando el cliente async
- [x] 3.4 Verificar que los tipos de retorno y las excepciones `HTTPException` se mantienen igual

## 4. core/deps.py — blacklist y rate limit no-bloqueantes

- [x] 4.1 Importar `get_async_valkey_client` desde `core/valkey.py`
- [x] 4.2 Reemplazar la llamada `valkey_client.exists(...)` por `await async_client.exists(...)` en `get_current_user`
- [x] 4.3 Actualizar la llamada a `check_api_rate_limit` para que sea `await check_api_rate_limit(...)` (ahora es async)
- [x] 4.4 Eliminar la inyección del cliente sync en `get_current_user` si ya no es necesaria para otras operaciones

## 5. events/consumer.py — run_in_executor, task set, startup resiliente

- [x] 5.1 Agregar `_background_tasks: set[asyncio.Task] = set()` como variable module-level
- [x] 5.2 Agregar helper `_fire_and_forget(coro)` que crea la task, la agrega al set, y registra el callback `discard`
- [x] 5.3 Envolver `_get_shared_secret(agent_id)` con `run_in_executor` en su call site dentro de la coroutine procesadora
- [x] 5.4 Envolver `_event_exists(event_id)` con `run_in_executor` en su call site
- [x] 5.5 Envolver `_reject(...)` con `run_in_executor` en su call site (la función sync llama Session internamente)
- [x] 5.6 Reemplazar `asyncio.create_task(notify_if_applicable(event))` por `_fire_and_forget(notify_if_applicable(event))`
- [x] 5.7 Envolver `_ensure_group(client)` y `_process_batch(client, "0")` en try/except en startup: loguear error y reintentar con `await asyncio.sleep(1)` hasta conectar

## 6. agents/heartbeat_consumer.py — run_in_executor, HMAC, sweep resiliente

- [x] 6.1 Importar `hmac`, `hashlib`, `json` si no están presentes; importar `verify_payload` del módulo de utils del events consumer (o duplicar la lógica si no hay módulo compartido)
- [x] 6.2 Agregar `_background_tasks: set[asyncio.Task] = set()` module-level (si se usa create_task aquí)
- [x] 6.3 Envolver la llamada a `_handle_heartbeat(msg_data)` con `run_in_executor` en `_reader_loop`
- [x] 6.4 Envolver la llamada a `_sweep_offline()` con `run_in_executor` en `_sweep_loop`
- [x] 6.5 Dentro de `_handle_heartbeat`: después del lookup del agente y antes del UPDATE, llamar `verify_payload(shared_secret_bytes, payload_json)` — si falla: log warning + return sin modificar DB
- [x] 6.6 Si `shared_secret_hex` es nulo o vacío: log error + return sin actualizar
- [x] 6.7 Si `agent_id` no existe en DB: log warning + return (ya existente; verificar que sea el caso)
- [x] 6.8 Envolver el cuerpo de `_sweep_loop` en try/except para loguear errores de DB sin matar el loop

## 7. alerts/service.py — task set para retry_alert

- [x] 7.1 Agregar `_background_tasks: set[asyncio.Task] = set()` module-level en `alerts/service.py`
- [x] 7.2 Agregar helper `_fire_and_forget(coro)` o importarlo si se centraliza
- [x] 7.3 Reemplazar `asyncio.create_task(notify_event(alert, event))` en `retry_alert` por `_fire_and_forget(notify_event(alert, event))`

## 8. core/health.py — task set para notificaciones

- [x] 8.1 Agregar `_background_tasks: set[asyncio.Task] = set()` module-level en `core/health.py`
- [x] 8.2 Reemplazar `asyncio.create_task(send_n8n(...))` por `_fire_and_forget(send_n8n(...))` (o helper equivalente)

## 9. Verificación

- [x] 9.1 Ejecutar `python -m pytest backend/tests/ -x -q` y confirmar que no hay regresiones
- [x] 9.2 Verificar con grep que no quedan llamadas directas a `valkey_client.exists`, `valkey_client.incr`, `valkey_client.expire` en `deps.py` y `rate_limit.py`
- [x] 9.3 Verificar con grep que no quedan `Session(engine)` llamados directamente desde coroutines async en los consumers (solo `run_in_executor`)
- [x] 9.4 Verificar con grep que todos los `asyncio.create_task(...)` en scope usan `_fire_and_forget` o referencia fuerte equivalente
