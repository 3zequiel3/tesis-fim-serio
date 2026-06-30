## Context

El backend FIM usa un event loop único de asyncio (single-instance, RN-76). Los consumers de `events` y `heartbeat` corren como tasks del lifespan junto con los endpoints HTTP de FastAPI. Cualquier operación síncrona bloqueante ejecutada directamente en el loop (DB query, Valkey call) detiene todos los otros coroutines hasta que retorna.

Estado actual:
- `_get_shared_secret`, `_event_exists`, `_reject` en `events/consumer.py` usan `Session(engine)` síncrono llamado desde coroutines async.
- `_handle_heartbeat`, `_sweep_offline` en `heartbeat_consumer.py` son funciones síncronas llamadas directamente desde `_reader_loop` y `_sweep_loop` async.
- `get_current_user` en `deps.py` llama `valkey_client.exists()` síncrono.
- `check_login_rate_limit` y `check_api_rate_limit` en `rate_limit.py` llaman `valkey_client.incr()`/`expire()` síncronos.
- `_handle_heartbeat` confía en `agent_id` del payload sin verificar HMAC.

## Goals / Non-Goals

**Goals:**
- Eliminar bloqueo del event loop en consumers y dependencias FastAPI
- Agregar verificación HMAC al heartbeat consumer (simetría con events consumer)
- Prevenir cancelación silenciosa de tasks de notificación y health por GC
- Hacer los consumers resilientes a fallo de Valkey al startup y a errores de DB en sweep

**Non-Goals:**
- Migrar a `AsyncSession` de SQLAlchemy (invasivo, fuera de scope para tesis)
- Convertir route handlers HTTP a `def` síncrono (impacto bajo dado perfil de carga single-instance)
- Implementar async I/O en servicios de negocio (actions, rules, agents)

## Decisions

### D-1: run_in_executor en call sites, no en las funciones

Las funciones síncronas (`_get_shared_secret`, `_event_exists`, etc.) mantienen su interfaz actual. El wrap con `asyncio.get_running_loop().run_in_executor(None, fn, *args)` se aplica solo en los call sites dentro de coroutines.

**Alternativa descartada**: hacer las funciones async internamente con `AsyncSession`. Requiere migrar todo el código de DB a `await session.exec(...)`, tocando todos los servicios, modelos y tests. El scope supera el propósito de este change.

### D-2: Cliente Valkey async separado para deps/rate_limit

Se agrega un segundo cliente `valkey.asyncio.Valkey` en `core/valkey.py` como singleton independiente. Las dependencias FastAPI (`deps.py`, `rate_limit.py`) usan este cliente async; el cliente sync existente lo siguen usando los servicios HTTP.

**Alternativa descartada**: `run_in_executor` para el cliente Valkey sync. No es idiomático en el context de FastAPI dependencies que ya son `async def`; el cliente async es la API correcta.

**Nota sobre dos singletons**: la librería `valkey` expone `valkey.Valkey` (sync) y `valkey.asyncio.Valkey` (async) como clientes distintos. Mantener dos singletons es el patrón recomendado — no comparten estado interno ni conexiones.

### D-3: HMAC verification con shared_secret ya disponible

En `_handle_heartbeat`, el agente ya se consulta en DB antes de actualizar. El `shared_secret_hex` está disponible desde esa query. La verificación HMAC se inserta entre el lookup y el update — costo cero de queries adicionales.

**Flujo resultante**: parsear JSON → lookup agent_id → si no existe: return → convertir `shared_secret_hex` a bytes → `verify_payload(secret, payload)` → si falla: log + return → actualizar estado.

### D-4: Task set para evitar GC de create_task

`asyncio.create_task()` sin referencia fuerte es elegible para GC. La solución estándar es un set module-level:

```python
_background_tasks: set[asyncio.Task] = set()

def _fire_and_forget(coro):
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
```

Aplicar en: `events/consumer.py` (notify_if_applicable), `alerts/service.py` (retry_alert, notify_event en retry), `core/health.py` (send_n8n).

## Risks / Trade-offs

- **ThreadPoolExecutor saturado bajo carga**: `run_in_executor` usa el executor por defecto del loop (ThreadPoolExecutor con `min(32, cpu+4)` threads). Con 50 mensajes/s de eventos, cada uno spawneando 3 executor calls, el pool puede saturarse. Mitigación: el perfil de carga de un FIM académico single-host es de baja frecuencia; documentar el límite.

- **Dos clientes Valkey en memoria**: cada cliente mantiene su propio connection pool. Duplica las conexiones abiertas a Valkey (típicamente 2-5 sync + 2-5 async). Aceptable para single-instance.

- **Tests de consumers que mockean Session()**: los tests existentes que parchean `Session` directamente pueden necesitar actualización para parchear el `run_in_executor` o las funciones internas. Evaluar caso por caso.

## Migration Plan

1. Actualizar `core/valkey.py` primero (nueva función init/get async).
2. Actualizar `main.py` para llamar `init_async_valkey()` en lifespan.
3. Actualizar `deps.py` y `rate_limit.py` para usar cliente async.
4. Actualizar `events/consumer.py` con run_in_executor y task set y startup try/except.
5. Actualizar `heartbeat_consumer.py` con run_in_executor, HMAC, y try/except en sweep.
6. Actualizar `alerts/service.py` y `health.py` con task set.
7. Ejecutar tests completos.

Rollback: revertir en orden inverso. No hay cambios de schema de DB ni de API.

## Open Questions

Ninguno — todas las decisiones de diseño están cerradas en los appendices (D21, D22).
