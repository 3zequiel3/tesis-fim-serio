# Spec: backend-async-consumer

## Purpose

Define los requisitos de comportamiento asíncrono correcto para los consumers de Valkey y las dependencias FastAPI del backend FIM. El event loop de asyncio NO debe bloquearse con operaciones de I/O síncronas.

## ADDED Requirements

### Requirement: Operaciones DB en consumers ejecutadas en threadpool

Las funciones síncronas de los consumers que acceden a PostgreSQL (`_get_shared_secret`, `_event_exists`, `_reject` en `events/consumer.py`; `_handle_heartbeat`, `_sweep_offline` en `heartbeat_consumer.py`) MUST ejecutarse via `asyncio.get_running_loop().run_in_executor(None, fn, *args)` en sus call sites dentro de coroutines async. Las funciones síncronas NO deben ser convertidas a async — solo el call site cambia.

#### Scenario: Lookup de shared_secret no bloquea el loop

- **WHEN** el consumer de eventos llama `_get_shared_secret(agent_id)` durante el procesamiento de un mensaje
- **THEN** la llamada se realiza via `run_in_executor` en el threadpool por defecto
- **AND** el event loop queda libre para procesar otros coroutines durante el I/O de DB

#### Scenario: Múltiples mensajes pueden entrelazarse con otras tasks

- **WHEN** el consumer procesa un mensaje mientras hay requests HTTP entrantes
- **THEN** el event loop no queda bloqueado durante las operaciones DB del consumer
- **AND** los endpoints HTTP reciben respuesta sin esperar a que el consumer complete su DB I/O

### Requirement: Cliente Valkey async para dependencias FastAPI

Las dependencias FastAPI que hacen I/O a Valkey (`get_current_user` en `deps.py`, `check_login_rate_limit` y `check_api_rate_limit` en `rate_limit.py`) MUST usar un cliente `valkey.asyncio.Valkey` async. El módulo `core/valkey.py` SHALL exponer funciones `init_async_valkey(url)` y `get_async_valkey_client()` que gestionen el singleton async, independiente del singleton sync existente.

#### Scenario: Blacklist check JWT es no-bloqueante

- **WHEN** un request autenticado llega y `get_current_user` verifica la blacklist JTI en Valkey
- **THEN** la verificación usa `await async_client.exists(key)` sin bloquear el event loop

#### Scenario: Rate limit check es no-bloqueante

- **WHEN** `check_api_rate_limit` incrementa el contador de rate limit para un usuario
- **THEN** la operación `incr`/`expire` usa el cliente async sin bloquear el event loop

### Requirement: Ciclo de vida del cliente Valkey async alineado con el lifespan de FastAPI

El cliente Valkey async MUST inicializarse en el lifespan de FastAPI durante el startup (`init_async_valkey(url)`) y cerrarse durante el shutdown (`await async_client.aclose()`).

#### Scenario: Cliente async disponible durante toda la vida de la aplicación

- **WHEN** FastAPI arranca y el lifespan ejecuta init
- **THEN** `get_async_valkey_client()` retorna un cliente funcional para los requests subsiguientes

#### Scenario: Cliente async cerrado limpiamente en shutdown

- **WHEN** FastAPI recibe señal de shutdown
- **THEN** el lifespan llama `await async_valkey.aclose()` antes de terminar
