## Why

Los consumers asyncio del backend (`events`, `heartbeat`) ejecutan operaciones de base de datos síncronas directamente en el event loop, bloqueando todo el proceso durante cada round-trip a PostgreSQL. Las dependencias FastAPI de autenticación y rate limit usan el cliente Valkey síncrono en contexto async, con el mismo efecto. Adicionalmente, el heartbeat consumer no verifica HMAC, creando una asimetría de seguridad con el events consumer, y tres ubicaciones usan `asyncio.create_task()` sin guardar referencia, exponiéndose a cancelación silenciosa por el GC.

## What Changes

- **run_in_executor en consumers**: las funciones DB síncronas de `events/consumer.py` (`_get_shared_secret`, `_event_exists`, `_reject`) y `agents/heartbeat_consumer.py` (`_handle_heartbeat`, `_sweep_offline`) se envuelven con `run_in_executor` en sus call sites, sin cambiar su interfaz.
- **Cliente Valkey async para dependencias FastAPI**: se agrega `valkey.asyncio.Valkey` como segundo singleton en `core/valkey.py`; `core/deps.py` y `core/rate_limit.py` pasan a usar el cliente async para blacklist check y rate limit (D21).
- **HMAC en heartbeat consumer**: `_handle_heartbeat` verifica firma HMAC-SHA256 antes de actualizar estado del agente, simétrico con el events consumer (D22 / RN-119).
- **Referencias de `asyncio.create_task`**: agregar `_background_tasks: set` module-level en `events/consumer.py` y `alerts/service.py`; `health.py` usa la misma estrategia. Callback `discard` al completar.
- **Resiliencia de consumer startup**: envolver `_ensure_group` y `_process_batch("0")` en try/except antes del loop principal; un Valkey no disponible al arrancar no mata el consumer permanentemente.
- **Resiliencia de `_sweep_loop`**: envolver `_sweep_offline()` en try/except; un error de DB no colapsa el heartbeat consumer completo.

## Capabilities

### New Capabilities

- `backend-async-consumer`: Operaciones DB en consumers asyncio corren en threadpool via `run_in_executor`; dependencias FastAPI usan cliente Valkey async. El event loop no se bloquea durante I/O de DB o Valkey.
- `backend-heartbeat-hmac`: El heartbeat consumer verifica HMAC-SHA256 por mensaje antes de actualizar estado del agente (RN-119).

### Modified Capabilities

- `backend-event-consumer`: El consumer de eventos ya no bloquea el event loop en `_get_shared_secret`, `_event_exists`, ni `_reject`. Resiliencia mejorada en startup y manejo de tasks.
- `backend-notifications`: `asyncio.create_task` en `notify_if_applicable` y `retry_alert` guarda referencia para evitar GC.
- `backend-health`: `asyncio.create_task` en health check guarda referencia.

## Impact

- `backend/app/core/valkey.py` — nuevo cliente async (`init_async_valkey`, `get_async_valkey_client`)
- `backend/app/core/deps.py` — blacklist check via async Valkey
- `backend/app/core/rate_limit.py` — versiones async de `check_login_rate_limit` y `check_api_rate_limit`
- `backend/app/modules/events/consumer.py` — run_in_executor para 3 funciones, task set, startup try/except
- `backend/app/modules/agents/heartbeat_consumer.py` — run_in_executor para 2 funciones, HMAC en `_handle_heartbeat`, try/except en `_sweep_loop`
- `backend/app/modules/alerts/service.py` — task set para `asyncio.create_task`
- `backend/app/core/health.py` — task set para `asyncio.create_task`
- Reglas cubiertas: RN-119 (D22). Decisiones aplicadas: D21, D22.
- Sin breaking changes en la API HTTP. Sin cambios en esquemas de DB. Sin cambios en el agente FIM.
