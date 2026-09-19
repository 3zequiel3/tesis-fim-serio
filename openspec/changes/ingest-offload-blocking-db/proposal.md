## Why

El ítem 43 del protocolo de medición (`docs/plan_medicion_cap5.md:353`) pide que el drenaje completo
tras una reconexión tarde **menos de 30 s**. La corrida del 2026-09-18 sobre el candidato
`v1.0-tesis` (`devel`, `7a906c2`), con el límite de ingesta elevado a 100000/60 s y declarado según
D38/RN-132, drenó **2.893 eventos en 59,389 s**: 48,7 ev/s, unos **20,4 ms por evento**. Evidencia en
`docs/cierre/evidencia/oficial-cap5-20260917T223823Z/bateria5/corte-valkey/`.

El perfilado por componente, medido **dentro del contenedor del backend con el engine y el cliente
reales**, descarta al broker y señala a la base de datos:

| Operación | Costo medido |
|---|---|
| Sesión + `SELECT` de agente | 1,493 ms |
| `_get_agent_auth` real | 1,329 ms |
| `INSERT` + `commit` | 1,564 ms |
| Valkey `PING` | 0,267 ms |
| Valkey `XADD` | 0,149 ms |
| Cadena de notificación completa (`notify.alert_created` → `notify.delivered`, canal `log_only`) | ~5,7 ms |

No es latencia de red ni del broker: son **operaciones de base de datos bloqueantes serializadas
dentro del event loop**. El consumer lee lotes de 50 (`_BATCH_SIZE`, `consumer.py:115`) con
`xreadgroup` (`:258-262`) y los despacha **estrictamente mensaje a mensaje** (`:268-269`), de modo
que cada evento espera a que el anterior termine su viaje completo a PostgreSQL.

La asimetría es reveladora: el carril de **rechazo** ya saca su trabajo del loop —
`await loop.run_in_executor(None, _write_rejection_audit, audit)` (`:420`, `:554`) y
`run_in_executor(None, _get_shared_secret, agent_id)` (`:563`)—. El carril **feliz** no:
`_get_agent_auth` (`:305`) y `_ingest` (`:400`) se llaman de forma síncrona dentro de la corrutina,
y la cadena de notificación que dispara `_fire_and_forget(notify_if_applicable(...))` (`:449`) abre
su propia `Session` bloqueante (`alerts/service.py:116-119`) sobre el mismo loop.

El comentario que hoy justifica la llamada síncrona de `:305` ("La ingesta ya usa SQLModel sincrónico
en este carril ordenado; resolver la única fila de autenticación evita un cambio de executor
redundante") quedó **explícitamente derogado**: el carril ordenado es precisamente donde el bloqueo
se acumula.

La decisión que gobierna esta change ya está cerrada y no se reinterpreta acá: **D75/RN-169**
(`docs/reglas_de_negocio.md:2421`, con su fila resumen en `docs/arquitectura_stack.md:2713`), que
amplía **D21** (`docs/arquitectura_stack.md:2296-2306`) — cuya enumeración de funciones a desbloquear
era cerrada y dejaba afuera el carril de ingesta. No se abre ninguna suposición nueva.

## What Changes

- **El carril feliz del consumer deja de bloquear el event loop.** `_get_agent_auth`
  (`consumer.py:305`) y `_ingest` (`:400`) pasan a `await loop.run_in_executor(None, fn, *args)`,
  replicando exactamente el patrón que el carril de rechazo ya usa en ese mismo archivo. Las
  funciones síncronas **no cambian de interfaz** — sólo el call site (mismo criterio que D21).

- **La creación de la fila `Alert` sale del loop.** La `Session` que `notify_if_applicable` abre por
  su cuenta (`alerts/service.py:116-119`) pasa al executor. Aunque la notificación ya es
  fire-and-forget y por eso no bloquea a `_handle_message` de forma directa, su `Session` **sí frena
  el event loop**, y por lo tanto frena el bucle de despacho secuencial: es exactamente de ahí que
  sale el solapamiento buscado.

- **El despacho SIGUE SIENDO SECUENCIAL.** No se introduce `gather` ni concurrencia entre eventos.
  Los ítems **40** (orden FIFO preservado) y **41** (cero duplicados) del protocolo no se pueden
  degradar y no se tocan. La ganancia buscada es de **solapamiento** —que la cadena de notificación
  de eventos previos avance mientras la ingesta del evento actual espera a la base en un hilo—,
  **no** de paralelismo de ingesta ni de aceleración del evento individual.

- **El pool y el executor se dimensionan en conjunto y de forma explícita.** Hoy
  `core/database.py:20-24` construye el engine sólo con `pool_pre_ping=True` y `echo=False`, así que
  rigen los defaults de SQLAlchemy: `pool_size=5` + `max_overflow=10` = **15 conexiones** (verificado
  en ejecución: `QueuePool size=5 overflow_max=10`), contra un executor por defecto de
  `min(32, cpu_count + 4)` = **16 hilos** en el anfitrión de medición (12 CPUs), compartidas además
  con las dependencias HTTP de FastAPI y el consumer de heartbeat. Mandar el trabajo bloqueante al
  executor sin tocar el pool cambiaría un cuello de botella por **agotamiento de conexiones**, que
  además falla en vez de degradar. `pool_size`, `max_overflow` y el tamaño del executor pasan a ser
  explícitos y configurables vía `Settings`, siguiendo el patrón que D38/RN-132 usó para el rate
  limit, con el número de hilos **acotado por el pool** descontando las reservas.

- **Sin migración a `AsyncSession`.** D75 lo excluye explícitamente: el fundamento de D21 sigue
  vigente —el costo del refactor es desproporcionado para un backend single-instance (RN-76)— y esta
  change no lo reabre.

- **Sin escalado horizontal.** RN-76 se mantiene: backend single-instance.

- **Medición posterior prevista, sin declarar incumplimiento anticipado.** Queda una tarea de
  re-medición de la Batería 5 con el protocolo completo (corte de Valkey, límite efectivo declarado
  según D38/RN-132, y el drenaje medido **desde `received_at` en la base, no desde el sondeo del
  arnés**). El umbral de 30 s del ítem 43 **no se redefine en esta change**: primero se implementa y
  se mide. Si tras medir el drenaje siguiera por encima del umbral, eso abre un ajuste de criterio
  declarado propio con número nuevo a la vista — declararlo antes de medir sería exactamente la
  reinterpretación silenciosa que la tabla de ajustes del Change 57 existe para evitar.

## Capabilities

### New Capabilities

- _Ninguna._ Esta change no introduce capabilities: amplía el alcance de dos que ya existen.

### Modified Capabilities

- `backend-async-consumer`: el requisito **"Operaciones DB en consumers ejecutadas en threadpool"**
  enumera hoy una lista **cerrada** (`_get_shared_secret`, `_event_exists`, `_reject`,
  `_handle_heartbeat`, `_sweep_offline`) que deja afuera el carril de ingesta. Se amplía con
  `_get_agent_auth`, `_ingest` y la `Session` que `notify_if_applicable` abre por su cuenta, y se le
  suma la garantía explícita de que el despacho del lote sigue siendo secuencial. Se agrega además un
  requisito nuevo de **dimensionamiento conjunto de pool y executor**, con el número de hilos acotado
  por la capacidad del pool.

- `backend-notifications`: el requisito **"Notificación asincrónica post-ingesta de eventos críticos
  o altos"** afirma hoy que la notificación es "asincrónica no bloqueante" y tiene un escenario
  ("Notificación no bloquea el consumer") que sólo cubre el envío del webhook. La `Session` con la
  que se crea la fila `Alert` —y las del camino de entrega— corren sobre el event loop, así que la
  capability asegura hoy una no-bloqueancia que no entrega. El requisito se amplía para fijar que
  ninguna `Session` síncrona del camino de notificación por evento se abre dentro del event loop.

## Impact

**Backend — consumer de eventos** (`backend/app/modules/events/consumer.py`):
- `:305` — `agent_auth = _get_agent_auth(agent_id)` pasa a `run_in_executor`; se reemplaza el
  comentario que justificaba la llamada síncrona, citando su derogación por D75/RN-169.
- `:400` — `outcome = _ingest(...)` pasa a `run_in_executor`, conservando el manejo de
  `InvalidTransitionError` y `SQLAlchemyError` tal cual está.
- `:268-269` — el bucle de despacho **no se toca**: sigue siendo `for ... await _handle_message(...)`.
- `:141-205` — `_RateLimiter` pasa a ser thread-safe: su premisa documentada ("Single-threaded
  asyncio") deja de valer cuando `check()` corre en un hilo del executor.

**Backend — notificaciones** (`backend/app/modules/alerts/service.py`):
- `:116-119` — la `Session` de creación de `Alert` pasa al executor.
- `:203`, `:246`, `:268`, `:286` — `Session` del camino de entrega (`notify_event`,
  `_mark_delivered`), que corre por evento dentro de la misma corrutina fire-and-forget.

**Backend — engine y configuración**:
- `backend/app/core/database.py:20-24` — `pool_size`, `max_overflow` y `pool_timeout` explícitos.
- `backend/app/core/config.py` — campos nuevos en `Settings` con validación fail-fast del invariante
  hilos ≤ capacidad del pool menos reservas, al estilo de `rejected_events_retention_days`.
- `backend/app/main.py` — el lifespan instala el executor acotado como executor por defecto del loop.
- `backend/.env.example` (o su equivalente vigente) — documentación de las variables nuevas.

**Backend — tests**: pruebas de que el orden FIFO y la ausencia de duplicados siguen intactos, de que
el despacho no se volvió concurrente, y del invariante de dimensionamiento.

**Medición**: re-corrida de la Batería 5 con el protocolo del ítem 43 y registro del resultado.

**Sin impacto**: `agent/`, `frontend/`, esquema de la base, contrato del stream `events`, contrato de
notificación (D40/RN-134), valor por defecto de producción del rate limit (D38/RN-132), umbral de
30 s del ítem 43.

Reglas cubiertas: **RN-169** (nueva, la que gobierna), **RN-76** (single-instance, sin escalado
horizontal), **RN-88** (rate limit de ingesta, ratificada sin cambio), **RN-71** (léxico snake_case).
Decisiones aplicadas: **D75/RN-169**; **D21** (ampliada); **D38/RN-132** (no modificada);
**D37/RN-131** (matriz de respuestas, ratificada sin cambio).

**Dependencias del DAG** (CHANGES.md, Change 58): change 30 `backend-async-io-fixes`, dueña de D21 —
archivada en `openspec/changes/archive/2026-06-27-backend-async-io-fixes/` ✔; change 51
`agent-attribution-and-detection-gap`, de donde sale el instrumental de medición — sus artefactos de
planificación están completos y el instrumental ya produjo la evidencia del 2026-09-18 sobre la que
se funda esta propuesta ✔.
