## Context

**El número que abre esta change.** Ítem 43 del protocolo (`docs/plan_medicion_cap5.md:353`): el
drenaje completo tras una reconexión debe tardar **< 30 s**. La corrida del 2026-09-18 sobre el
candidato `v1.0-tesis` (`devel`, `7a906c2`), con el límite de ingesta elevado a 100000/60 s y
declarado según D38/RN-132, drenó **2.893 eventos en 59,389 s** = 48,7 ev/s ≈ **20,4 ms por evento**.
Evidencia: `docs/cierre/evidencia/oficial-cap5-20260917T223823Z/bateria5/corte-valkey/`.

**El perfilado descarta al broker.** Medido dentro del contenedor del backend, con el engine y el
cliente reales:

| Componente | Costo |
|---|---|
| Sesión + `SELECT` de agente | 1,493 ms |
| `_get_agent_auth` real | 1,329 ms |
| `INSERT` + `commit` | 1,564 ms |
| Valkey `PING` | 0,267 ms |
| Valkey `XADD` | 0,149 ms |
| Cadena de notificación completa (`notify.alert_created` → `notify.delivered`, `N8N_WEBHOOK_URL` vacío ⇒ canal `log_only`) | ~5,7 ms |

Valkey aporta décimas de milisegundo contra milisegundos enteros de PostgreSQL. **El broker no es el
cuello.**

**Estado actual del consumer** (`backend/app/modules/events/consumer.py`):

- `:258-262` — `xreadgroup` lee lotes de `_BATCH_SIZE = 50` (`:115`).
- `:268-269` — despacho **estrictamente secuencial**: `for msg_id, msg_data in messages: await
  _handle_message(client, msg_id, msg_data)`. Sin concurrencia, sin `gather`.
- `:305` — `agent_auth = _get_agent_auth(agent_id)`: **síncrona, bloqueante, dentro del event loop**.
  Lleva un comentario que la justifica: *"La ingesta ya usa SQLModel sincrónico en este carril
  ordenado; resolver la única fila de autenticación evita un cambio de executor redundante."*
  **D75/RN-169 deroga explícitamente esa premisa**: el carril ordenado es precisamente donde el
  bloqueo se acumula, porque cada evento espera a que el anterior termine su viaje a la base.
- `:400` — `outcome = _ingest(payload, ...)`: **síncrona, bloqueante**. `_ingest` (`:459`) delega en
  `_ingest_event_outcome` (`events/service.py:281`), que abre `with Session(engine)`
  (`events/service.py:340`).
- `:449` — `_fire_and_forget(notify_if_applicable(outcome.event))`, con el helper en `:99-103`.

**La asimetría que esta change corrige.** El carril de **rechazo** ya saca su trabajo del loop:
`await loop.run_in_executor(None, _write_rejection_audit, audit)` (`:420` y `:554`) y
`await loop.run_in_executor(None, _get_shared_secret, agent_id)` (`:563`). El carril **feliz**, que
es el que corre 2.893 veces durante un drenaje, no. El patrón a replicar ya vive en el mismo archivo.

**Estado actual de la notificación** (`backend/app/modules/alerts/service.py`):
`notify_if_applicable` (`:90`) es fire-and-forget, así que **no** bloquea a `_handle_message` de
forma directa — pero abre `with Session(engine)` para crear la fila `Alert` (`:116-119`, add +
commit + refresh) **dentro de una corrutina**, y eso **sí frena el event loop**. Como el loop es
quien despacha el mensaje siguiente, frenar el loop es frenar el despacho. Es exactamente de ahí que
sale el solapamiento que esta change busca. Y no es un camino excepcional: en el laboratorio las
reglas sembradas clasifican todos los eventos `high`, así que se crea **una alerta por cada evento**
(481 alertas para 481 eventos).

**Estado actual del engine** (`backend/app/core/database.py:20-24`): se construye sólo con
`pool_pre_ping=True` y `echo=False`, de modo que rigen los defaults de SQLAlchemy — `pool_size=5` +
`max_overflow=10` = **15 conexiones**, verificado en ejecución (`QueuePool size=5 overflow_max=10`).
El executor por defecto de asyncio en Python 3.13 es `min(32, cpu_count + 4)` = **16 hilos** en el
anfitrión de medición (12 CPUs). Son 16 hilos contra 15 conexiones, compartidas además con las
dependencias HTTP de FastAPI y con el consumer de heartbeat.

**Decisión de gobierno.** **D75/RN-169** (`docs/reglas_de_negocio.md:2421`, fila resumen en
`docs/arquitectura_stack.md:2713`) está cerrada y commiteada. Amplía **D21**
(`docs/arquitectura_stack.md:2296-2306`), cuya enumeración de funciones a desbloquear era **cerrada**
(`_get_shared_secret`, `_event_exists`, `_reject`, `_handle_heartbeat`, `_sweep_offline`) y no
contemplaba el carril de ingesta ni `alerts/service.py`. Este design **implementa** D75; no la
reinterpreta ni la amplía.

## Goals / Non-Goals

**Goals:**

- Que ninguna operación de base de datos del carril feliz de ingesta se ejecute sobre el event loop.
- Que la cadena de notificación por evento —que corre en **todos** los eventos— deje de frenar el
  loop, de modo que su trabajo se **solape** con el viaje a la base del evento siguiente.
- Que el pool del engine y el executor queden dimensionados **en conjunto, de forma explícita y
  configurable**, con el número de hilos acotado por la capacidad del pool: mover el trabajo al
  executor sin tocar el pool cambiaría un cuello por **agotamiento de conexiones**, que además falla
  en vez de degradar.
- Que el orden FIFO (ítem 40) y la ausencia de duplicados (ítem 41) queden **demostrados por tests**,
  no supuestos.
- Que quede registrada una tarea de re-medición de la Batería 5, con su metodología explícita.

**Non-Goals:**

- **No** se introduce concurrencia entre eventos. Sin `gather`, sin `TaskGroup`, sin despacho
  paralelo del lote. Ver D-2.
- **No** se migra a `AsyncSession`. D75 lo excluye explícitamente y el fundamento de D21 sigue
  vigente por RN-76 (backend single-instance). **No se reabre.**
- **No** se propone escalado horizontal (RN-76).
- **No** se cambia el valor por defecto de producción del rate limit de ingesta en función de las
  mediciones (D38/RN-132).
- **No** se redefine el umbral de 30 s del ítem 43. Ver D-9.
- **No** se toca el esquema de la base, el contrato del stream `events`, el contrato de notificación
  (D40/RN-134) ni la matriz de respuestas de D37/RN-131.
- **No** se toca `agent/` ni `frontend/`.

## Decisions

### D-1 — `run_in_executor` en los call sites; las funciones síncronas no cambian de interfaz

`_get_agent_auth` (`consumer.py:305`) y `_ingest` (`:400`) pasan a
`await loop.run_in_executor(None, fn, *args)`. Ninguna de las dos se convierte en `async def`, ni
cambia su firma, ni cambia su cuerpo. Es el **mismo criterio que D21** y el **mismo patrón que ya vive
en el archivo** (`:420`, `:554`, `:563`).

Para `_ingest`, que recibe cuatro argumentos posicionales, el call site usa
`functools.partial` o un lambda cerrado sobre los argumentos — lo que el resto del archivo ya haga.
El manejo de excepciones **no cambia**: `run_in_executor` re-lanza en el `await`, así que el
`try/except InvalidTransitionError / SQLAlchemyError` de `:400-427` sigue capturando exactamente lo
mismo, en el mismo lugar, con la misma semántica de XACK / no-XACK.

El `loop` ya está resuelto en `_handle_message` (`:303`, `loop = asyncio.get_running_loop()`) — hoy
se obtiene ahí y recién se usa en `:420`. Deja de ser una línea huérfana.

*Alternativa considerada — `AsyncSession`:* excluida por D75 y por RN-76. No se reabre.

*Alternativa considerada — `asyncio.to_thread`:* equivalente funcional, pero usa siempre el executor
**por defecto** del loop y no acepta un executor explícito. Como D-3 instala un executor acotado
propio como executor por defecto, las dos formas convergen; se elige `run_in_executor(None, ...)`
por consistencia literal con los tres call sites que ya existen y con el texto de D21 y D75.

### D-2 — El despacho sigue siendo secuencial: la ganancia es de solapamiento, no de paralelismo

**Esta es la parte que más fácil se malinterpreta al implementar. Leerla antes de tocar `:268-269`.**

El bucle `for msg_id, msg_data in messages: await _handle_message(...)` (`:268-269`) **no se toca**.
No hay `gather`, no hay `TaskGroup`, no hay `create_task` por mensaje. En todo momento hay **un solo**
`_handle_message` en vuelo.

El mecanismo de la ganancia, evento por evento:

- **Hoy**: mientras el loop ejecuta `_get_agent_auth` e `_ingest` del evento *N*, **nada más avanza**
  — ni la cadena de notificación del evento *N−1*, que ya está encolada como task y sólo necesita que
  el loop le dé el control. El costo por evento es la **suma** de ingesta + notificación.
- **Después**: mientras el hilo del executor ejecuta `_get_agent_auth` e `_ingest` del evento *N*, el
  loop queda libre y **retoma** la task de notificación del evento *N−1*. El costo por evento tiende
  al **máximo** entre ingesta y notificación, más el costo del handoff.

Lo que NO cambia y no debe esperarse que cambie:

- El evento individual **no se acelera**. Al contrario: cruzar al executor agrega overhead (D-11).
- La ingesta **no se paraleliza**: un solo evento a la vez llega a `_ingest`.
- El ítem 40 (**orden FIFO preservado**) se sostiene porque el orden de despacho es literalmente el
  mismo bucle de antes.
- El ítem 41 (**cero duplicados**) se sostiene porque cada mensaje sigue teniendo exactamente un
  `_handle_message` y un XACK, y la deduplicación por `event_id` dentro de la transacción
  (`events/service.py:341-346`) sigue siendo el mismo `SELECT` dentro de la misma `Session`.

Si durante la implementación aparece la tentación de "aprovechar y paralelizar el lote": **detenerse**.
Eso degradaría los ítems 40 y 41, está fuera de D75 y sería una decisión nueva que va al appendix
primero.

*Alternativa considerada — despacho concurrente con `gather` y un `Semaphore`:* rechazada. El orden
FIFO del ítem 40 se verifica sobre la monotonía del sufijo del generador ordenando por `detected_at`;
un lote concurrente no garantiza el orden de inserción y rompería tanto el ítem 40 como la cadena de
supersesión por path (`get_pending_event_for_path` / `mark_superseded`), que asume un único escritor
ordenado por ruta. D75 lo excluye de forma explícita.

### D-3 — Un único executor acotado, propio del proceso, instalado como executor por defecto del loop

El lifespan de FastAPI (`backend/app/main.py`) crea un
`concurrent.futures.ThreadPoolExecutor(max_workers=settings.db_executor_max_workers,
thread_name_prefix="fim-db")` y lo instala con `loop.set_default_executor(...)` durante el startup,
y lo cierra (`shutdown(wait=True)`) en el shutdown, junto al resto del ciclo de vida que el lifespan
ya gestiona.

**Por qué el executor por defecto y no uno dedicado sólo al carril de ingesta.** Si el carril de
ingesta usara un executor propio de *K* hilos y el resto del backend siguiera usando el executor por
defecto de asyncio (`min(32, cpu_count + 4)` = 16 hilos), el total de hilos capaces de tomar una
conexión sería *K* + 16, y el invariante "hilos ≤ capacidad del pool" dejaría de ser verificable con
una sola cuenta. Con **un solo** executor acotado instalado como default, todos los
`run_in_executor(None, ...)` del backend —los tres que ya existen por D21 y los nuevos— tiran del
**mismo presupuesto**, y ese presupuesto es **un solo número configurable** que se puede contrastar
contra la capacidad del pool.

Efecto colateral deliberado y deseable: los call sites de D21 que hoy usan el executor por defecto de
16 hilos (`:420`, `:554`, `:563`, y el `_handle_heartbeat` / `_sweep_offline` de
`agents/heartbeat_consumer.py:66` y `:207`) quedan automáticamente dentro del presupuesto, sin
tocarlos.

*Alternativa considerada — dejar el executor por defecto y sólo agrandar el pool:* rechazada. Deja
16 hilos como número implícito derivado del `cpu_count` del anfitrión, es decir un parámetro de
concurrencia que cambia con la máquina y que nadie declaró. D75 exige que ambos valores sean
explícitos.

### D-4 — Dimensionamiento concreto: 10 + 10 conexiones contra 10 hilos

| Parámetro | Valor propuesto | Dónde |
|---|---|---|
| `db_pool_size` | **10** | `Settings` → `create_engine(pool_size=...)` |
| `db_max_overflow` | **10** | `Settings` → `create_engine(max_overflow=...)` |
| `db_executor_max_workers` | **10** | `Settings` → `ThreadPoolExecutor(max_workers=...)` |
| `pool_timeout` | **30 s** (default de SQLAlchemy, explicitado) | `create_engine(pool_timeout=30)` |

**La aritmética del reparto**, sobre una capacidad total de `pool_size + max_overflow` = **20**
conexiones:

| Consumidor | Reserva | Fundamento |
|---|---|---|
| Dependencias HTTP de FastAPI (`get_session`) | **6** | Los route handlers son `async def` con `Session` **sync** (D21): cada request en vuelo retiene su conexión durante toda la request, no sólo durante el I/O. 6 cubre el perfil de un dashboard de seguridad single-instance con holgura. |
| Consumer de heartbeat | **2** | `_handle_heartbeat` (`heartbeat_consumer.py:66`) y el barrido periódico `_sweep_offline` (`:207`) pueden coincidir. |
| Corrutinas del lifespan que abren `Session` directamente sobre el loop | **2** | `retention_task` (`events/service.py:467`) y la lectura de `outbox_publisher_task` (`rules/service.py:441`) no pasan por el executor. Ver D-8. |
| **Reservado total** | **10** | |
| **Presupuesto del executor** | **20 − 10 = 10** | |

El invariante que D75 exige —*"El número de hilos del executor SHALL ser menor o igual que
`pool_size + max_overflow`, descontando las conexiones que consumen las dependencias HTTP de FastAPI
y el consumer de heartbeat"*— se verifica: 10 ≤ 20 − 6 − 2 = **12**, con 2 de margen que absorben
las corrutinas del lifespan.

La reserva del heartbeat es **deliberadamente conservadora**: como D-3 mete al heartbeat dentro del
mismo executor, sus 2 conexiones ya están contadas en los 10 hilos. Contarlas dos veces mantiene el
invariante válido incluso si una change futura le diera al heartbeat un executor propio. El margen
que eso deja es intencional, no un error de cuenta.

De 1 operación de base de datos concurrente efectiva (el estado actual, por serialización en el loop)
se pasa a hasta 10, sin que el pool pueda agotarse por construcción.

**Validación fail-fast.** `Settings` incorpora una constante documentada
`_DB_CONNECTIONS_RESERVED_NON_EXECUTOR = 10` y un `model_validator` que aborta el arranque con
`ValidationError` si `db_executor_max_workers > db_pool_size + db_max_overflow -
_DB_CONNECTIONS_RESERVED_NON_EXECUTOR`. Mismo criterio fail-fast que
`rejected_events_retention_days: int = Field(default=90, ge=1)`: una configuración que puede agotar
el pool tiene que matar el arranque, no descubrirse bajo carga como un `TimeoutError` intermitente.
Los tres campos llevan además `ge=` (`pool_size ≥ 1`, `max_overflow ≥ 0`, `max_workers ≥ 1`).

**Por qué la reserva es una constante y no un cuarto knob.** D75 pide que *"ambos valores"* —pool y
executor— queden configurables, no la reserva. Un cuarto parámetro permitiría desactivar el
invariante ajustándolo, que es exactamente lo que la validación existe para impedir. Queda como
constante con el fundamento escrito al lado.

**Por qué `pool_timeout` se explicita pero no se configura.** Es el default de SQLAlchemy (30 s), y
escribirlo deja claro en el código que el agotamiento del pool **falla de forma visible** con un
`TimeoutError` en vez de colgarse. Convertirlo en knob sería un parámetro nuevo que D75 no enumera:
sería una suposición nueva y va al appendix primero.

### D-5 — Seguridad de hilos: el pool soporta el paralelismo del executor, y ninguna `Session` cruza hilos

Verificación asentada, requerida explícitamente por el alcance de esta change:

1. **El `Engine` y su `QueuePool` son thread-safe.** Es el contrato de SQLAlchemy: un `Engine` es un
   objeto global compartido y su pool está diseñado para que múltiples hilos hagan checkout
   concurrente. Lo que **no** es thread-safe es la `Session`.
2. **Ninguna `Session` se comparte entre hilos.** Cada helper afectado abre y cierra la suya dentro
   del mismo `with`, en el mismo hilo: `_get_agent_auth` (`consumer.py:488-489`),
   `_ingest_event_outcome` (`events/service.py:340`), `notify_if_applicable`
   (`alerts/service.py:116`). Ninguna `Session` se guarda en un atributo de módulo, en un `dict`
   global ni se pasa como argumento a través del límite del executor.
3. **Los objetos ORM que cruzan el límite del executor ya están desligados.**
   `_ingest_event_outcome` hace `session.expunge(event)` **antes** del `commit`
   (`events/service.py:446-448`), con el comentario que ya explica por qué: *"Separar la fila ya
   materializada antes del commit evita que el despacho dispare un SELECT por expiración del
   objeto."* Lo mismo para el camino de duplicado (`session.expunge(duplicate)`,
   `events/service.py:344`). Así, el `Event` que viaja del hilo del executor al loop y de ahí a
   `notify_if_applicable` es una instancia **detached con todos sus atributos materializados**: leer
   `event.status`, `event.severity`, `event.path`, `event.id` desde el loop no dispara ningún I/O ni
   toca ninguna `Session`. La invariante ya existía; esta change la vuelve **carga**, así que los
   tests la fijan explícitamente (grupo 6 de tasks).
4. **Visibilidad de memoria**: la resolución del `Future` que `run_in_executor` devuelve establece la
   relación de orden entre la escritura en el hilo worker y la lectura en el loop. No hace falta
   sincronización adicional para el objeto devuelto.
5. **Máximo de conexiones simultáneas** = número de hilos del executor + las coroutines que abren
   `Session` sobre el loop, acotado por D-4.

### D-6 — `_RateLimiter` pasa a ser thread-safe

`_RateLimiter` (`consumer.py:141-205`) documenta en su propio docstring la premisa *"Ventana
deslizante por agent_id (RN-88). **Single-threaded asyncio.**"*, y no tiene ningún lock.

Con D-1 esa premisa deja de valer: `check()` se invoca desde **el hilo del executor** (llega por el
`accept_new=lambda: _rate_limiter.check(agent_id)` que `_ingest` pasa a `_ingest_event_outcome`,
`consumer.py:471-476`), mientras `seconds_until_available()` se invoca desde **el loop** (`:565`, vía
`_reject`). Las dos hacen lectura-modificación-escritura sobre el mismo `deque` del mismo bucket
(`popleft` en el bucle de purga, `append` en el alta).

Con el despacho secuencial de D-2 no hay solapamiento **hoy**: `_handle_message` espera a que
`_ingest` termine antes de llegar a `_reject`. Pero el invariante pasa a depender de una propiedad no
local del bucle de despacho, y el docstring quedaría afirmando algo falso. Se agrega un
`threading.Lock` que envuelve el cuerpo de `check()`, `seconds_until_available()` y `reset()`, y se
reescribe el docstring para decir que el limiter se toca desde el loop y desde hilos del executor, y
por qué. El costo es despreciable (un lock sin contención real) y el algoritmo no cambia: RN-88 y el
`retry_after` derivado de D37/RN-131 quedan idénticos.

*Alternativa considerada — dejarlo sin lock y documentar la dependencia del despacho secuencial:*
rechazada. Deja una bomba de relojería cuyo detonante es exactamente el refactor que D-2 advierte que
alguien va a querer hacer.

### D-7 — Alcance en `alerts/service.py`: la `Session` enumerada y las del camino de entrega por evento

D75 enumera en su **Descripción** *"la sesión que `notify_if_applicable` abre por su cuenta
(`backend/app/modules/alerts/service.py:116-119`)"*. Su **Condición** es más amplia:

> *"Consumers de `events` y `agent_heartbeat`, y **cualquier camino que abra una `Session` síncrona
> dentro de una corrutina**."*

El relevamiento del módulo encuentra siete `Session(engine)`. Cuatro de ellas están en el camino que
corre **por evento** dentro de la misma corrutina fire-and-forget:

| Línea | Función | Corre |
|---|---|---|
| `:116` | `notify_if_applicable` — creación de la fila `Alert` | por evento (enumerada por D75) |
| `:203` | `notify_event` | por evento |
| `:246` | `notify_event` (rama de reintento) | por evento |
| `:268` | `notify_event` | por evento |
| `:286` | `_mark_delivered`, llamada desde `notify_event` | por evento |

**Decisión: las cinco entran en alcance.** Fundamento: los ~5,7 ms medidos de la cadena de
notificación se miden justamente **de `notify.alert_created` a `notify.delivered`**, es decir que
incluyen `:203`–`:286`, no sólo `:116`. Desbloquear sólo `:116` dejaría el resto de la cadena
frenando el loop y **derrotaría el mecanismo de solapamiento que D-2 describe**: la notificación del
evento *N−1* seguiría sin poder avanzar mientras… y peor, seguiría frenando el despacho del evento
*N+1*. Sería implementar la letra de la enumeración perdiendo el objetivo de la decisión.

Esto **no es una suposición nueva**: cae dentro de la Condición textual de D75. Se registra acá de
forma explícita porque va más allá de la enumeración literal, y se declara en el delta de
`backend-notifications` como requisito, no como detalle de implementación.

El tratamiento es el mismo de D-1: las porciones síncronas se extraen a helpers síncronos (o se usan
los que ya existen, como `_mark_delivered`) y se invocan por `run_in_executor` desde la corrutina.
Ninguna función síncrona cambia de interfaz.

### D-8 — Fuera de alcance, relevado y declarado: las `Session` de baja frecuencia sobre el loop

Las otras `Session(engine)` que corren sobre una corrutina y **no** entran en esta change:

| Sitio | Frecuencia | Por qué queda afuera |
|---|---|---|
| `alerts/service.py:335`, `:361` — `recover_pending_notifications` | **una vez**, en el startup del lifespan | No está en el carril por evento. Su costo no participa del drenaje. |
| `events/service.py:467` — `retention_task` | periódica, baja frecuencia | Idem. Su conexión está **reservada** en la cuenta de D-4. |
| `rules/service.py:441` — lectura de `outbox_publisher_task` | cada 30 s | Idem; su publicación ya usa `run_in_executor` (`rules/service.py:453`). Reservada en D-4. |

Se dejan relevadas para que la próxima lectura no tenga que redescubrirlas, y su consumo de
conexiones **sí** está contabilizado en el presupuesto. Si en algún momento se decide moverlas, será
una change propia con su propia justificación: acá no aportan al número que se está atacando y
agregarlas sería alcance sin fundamento medido.

### D-9 — El umbral de 30 s del ítem 43 no se redefine acá

D75 es explícita: *"el umbral de 30 s del ítem 43 **no se redefine acá**. Si tras implementar y medir
el drenaje siguiera por encima del umbral, eso abre un ajuste de criterio declarado propio, con el
número nuevo a la vista; declararlo antes de medir sería exactamente la reinterpretación silenciosa
que la tabla de ajustes del Change 57 existe para evitar."*

Este design **no anticipa el resultado**, ni en un sentido ni en el otro. Lo que sí deja escrito es
la aritmética del objetivo y el estado del conocimiento:

- Objetivo del ítem 43 sobre el mismo volumen: 2.893 eventos en < 30 s ⇒ **> 96,4 ev/s ⇒ < 10,4 ms
  por evento**, contra los 20,4 ms medidos.
- Los componentes perfilados suman ~10,3 ms de esos 20,4 ms (1,329 de `_get_agent_auth` + ~1,6 del
  `INSERT` + `commit` + ~1,5 de la sesión y el `SELECT` + ~5,7 de la cadena de notificación + las
  décimas de Valkey). **El resto no está atribuido.** Cuánto de ese residual responde al solapamiento
  y cuánto a otra causa no se puede estimar antes de medir — y ésa es precisamente la razón por la
  que la conclusión sobre el ítem 43 se pospone hasta la re-medición, en vez de anticiparse.

La re-medición está en el plan de tareas (grupo 8) con su metodología, no como una intención.

### D-10 — La re-medición se hace con el protocolo, y el drenaje se mide desde `received_at` en la base

La tarea de re-medición re-corre la **Batería 5** con el protocolo del ítem 43, y el detalle
metodológico que la hace comparable es explícito:

- Corte de Valkey, con la duración **real** registrada (ítem 36).
- **Límite de ingesta efectivo declarado** según D38/RN-132, igual que en la corrida del 2026-09-18.
  El valor por defecto de producción **no se cambia** en función de estas mediciones.
- El drenaje se mide **desde `received_at` en la base, no desde el sondeo del arnés**: el sondeo tiene
  su propio período y su propia latencia, y midiendo desde él se está midiendo el instrumento además
  del sistema. Los dos extremos de la ventana salen de la columna `received_at` de `events`.
- Se re-verifican los ítems **40** (monotonía del sufijo del generador ordenando por `detected_at`) y
  **41** (la query de duplicados del protocolo, que debe devolver 0 filas).

### D-11 — El costo del handoff se asume y se declara

Cada `run_in_executor` cuesta un checkout de hilo, la resolución de un `Future` y dos cambios de
contexto: del orden de décimas de milisegundo. Esta change agrega dos handoffs nuevos por evento en
el consumer (`_get_agent_auth`, `_ingest`) más los del camino de notificación.

Se asume conscientemente: el trabajo que se saca del loop es de **milisegundos enteros** (1,329 +
~1,6 + ~1,5, más los ~5,7 de la notificación) contra décimas de milisegundo de overhead, y el
beneficio no es el ahorro directo sino el solapamiento que habilita (D-2). Para un evento aislado, en
un sistema sin cola, esta change lo hace **marginalmente más lento**. Para un drenaje de 2.893
eventos encolados, que es el caso que el ítem 43 mide, es al revés. Esta asimetría está declarada
para que no se lea como una regresión cuando aparezca en un test de latencia de un solo evento.

## Risks / Trade-offs

**[Agotamiento del pool de conexiones]** → Mitigado por construcción: D-4 acota el número de hilos
del executor por la capacidad del pool menos las reservas, y el `model_validator` de `Settings` aborta
el arranque si alguien configura una combinación que rompe el invariante. `pool_timeout=30` explícito
hace que un agotamiento imprevisto falle de forma visible en vez de colgarse.

**[Alguien "aprovecha y paraleliza el lote"]** → El riesgo más probable de esta change, porque el
cambio *parece* pedirlo. Mitigado en tres capas: D-2 lo dice explícitamente; el delta de
`backend-async-consumer` lo fija como requisito con escenario propio; y los tests del grupo 6 lo
verifican (un test que afirma que no hay más de un `_handle_message` en vuelo, y los de FIFO y
no-duplicación).

**[Regresión silenciosa de FIFO o duplicados]** → Los ítems 40 y 41 **no se pueden degradar**.
Mitigado con tests explícitos antes de la re-medición (grupo 6) y con la re-verificación de los dos
ítems en la re-corrida de la Batería 5 (grupo 8). Si un test de FIFO o de duplicados falla, la change
se detiene ahí: no se ajusta el test.

**[Carrera en `_RateLimiter`]** → D-6: `threading.Lock` y docstring reescrito. El algoritmo y el
`retry_after` derivado (D37/RN-131) no cambian.

**[`DetachedInstanceError` al cruzar el `Event` del executor al loop]** → No debería ocurrir: el
`session.expunge(event)` antes del `commit` ya existe y es deliberado (D-5.3). El riesgo real es que
una change futura lo elimine por parecer redundante; mitigado con un test que falla si el `Event`
devuelto por `_ingest` no tiene sus atributos materializados fuera de la `Session`.

**[El evento individual se vuelve marginalmente más lento]** → Asumido y declarado (D-11).

**[El drenaje sigue por encima de 30 s tras la implementación]** → **No se anticipa acá** (D-9). Si
ocurre, el camino está definido: un ajuste de criterio declarado propio, con el número nuevo a la
vista, en la tabla de ajustes — nunca una reinterpretación silenciosa del umbral.

**[La re-medición no es comparable con la del 2026-09-18]** → Mitigado por D-10: mismo protocolo,
límite efectivo declarado, y el drenaje medido desde `received_at` en la base.

## Migration Plan

Sin migración de datos: esta change no toca el esquema, ni el contrato del stream, ni el contrato de
notificación. Un agente desplegado no percibe ninguna diferencia.

**Despliegue**: configuración nueva en el entorno del backend (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
`DB_EXECUTOR_MAX_WORKERS`), todas con default y por lo tanto opcionales — un despliegue que no las
declare arranca con los valores de D-4. Redeploy del contenedor del backend. Sin ventana de
mantenimiento y sin coordinación con el agente.

**Orden**: los grupos 1 a 7 de tasks (implementación, configuración y tests) se completan **antes**
de la re-medición del grupo 8. Medir sobre una implementación parcial produce un número que no
corresponde a nada.

**Rollback**: revertir el commit. No hay estado persistido que quede inconsistente. Si el problema
fuera de dimensionamiento y no de código, la mitigación intermedia es bajar
`DB_EXECUTOR_MAX_WORKERS` por variable de entorno sin redeploy de imagen.

## Open Questions

- **Ninguna que bloquee la implementación.** D75/RN-169 cierra el enfoque, la exclusión de
  `AsyncSession`, la condición de dimensionamiento y el tratamiento del umbral del ítem 43.
- Los valores concretos de D-4 (10 / 10 / 10) son una elección de implementación **dentro** del
  invariante que D75 fija, no una decisión nueva: son configurables y la re-medición del grupo 8 es
  la que dirá si conviene moverlos. Si la re-medición sugiriera cambiarlos de forma permanente en el
  default de producción, eso se registra con su fundamento medido.
- Si durante el apply apareciera una suposición **no** cubierta por D75 —por ejemplo, necesitar
  concurrencia entre eventos, tocar el default de producción del rate limit, o redefinir el umbral—:
  **detenerse**, cerrar la decisión en el appendix "Decisiones de implementación — Abril 2026" del
  doc canónico que corresponda, y recién entonces continuar.
