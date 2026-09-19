# Spec: backend-async-consumer

## Purpose
Define los requisitos de comportamiento asíncrono correcto para los consumers de Valkey y las dependencias FastAPI del backend FIM. El event loop de asyncio NO debe bloquearse con operaciones de I/O síncronas.
## Requirements
### Requirement: Operaciones DB en consumers ejecutadas en threadpool

Las funciones síncronas de los consumers que acceden a PostgreSQL MUST ejecutarse via
`asyncio.get_running_loop().run_in_executor(None, fn, *args)` en sus call sites dentro de coroutines
async. Las funciones síncronas NO deben ser convertidas a async — solo el call site cambia.

El alcance de esta obligación es **todo** camino síncrono a PostgreSQL que se invoque desde una
corrutina de un consumer, **sin excepción para el carril ordenado de ingesta** (D75/RN-169, que
amplía D21). En particular incluye, además de las funciones que D21 ya enumeraba:

- `_get_shared_secret`, `_event_exists`, `_reject` (`events/consumer.py`) — D21.
- `_handle_heartbeat`, `_sweep_offline` (`agents/heartbeat_consumer.py`) — D21.
- `_get_agent_auth` (`events/consumer.py`) — D75/RN-169. La justificación previa de su llamada
  síncrona ("resolver la única fila de autenticación evita un cambio de executor redundante") queda
  **derogada**: el carril ordenado es precisamente donde el bloqueo se acumula, porque cada evento
  espera a que el anterior termine su viaje a la base.
- `_ingest` (`events/consumer.py`), y con él la `Session` que `ingest_event` abre en
  `events/service.py` — D75/RN-169.

El despacho de mensajes del lote MUST permanecer **secuencial**: el lote SHALL procesarse mensaje a
mensaje, y el sistema MUST NOT introducir `gather`, `TaskGroup`, `create_task` por mensaje ni
ninguna otra forma de concurrencia entre eventos del mismo lote. La ganancia buscada es de
**solapamiento** —que la cadena de notificación de eventos previos avance mientras la ingesta del
evento actual espera a la base en un hilo—, NO de paralelismo de ingesta. El orden FIFO de entrega y
la ausencia de eventos duplicados MUST NOT degradarse.

El sistema MUST NOT migrar a `AsyncSession` de SQLAlchemy: el fundamento de D21 sigue vigente para un
backend single-instance (RN-76).

Las `Session` abiertas desde hilos del executor MUST ser locales a la invocación: ninguna `Session`
SHALL compartirse entre hilos, guardarse en estado de módulo ni cruzar el límite del executor. Los
objetos ORM que sí crucen ese límite MUST estar desligados (`expunge`) con sus atributos ya
materializados antes de devolverse, de modo que leerlos desde el event loop no dispare I/O.

#### Scenario: Lookup de shared_secret no bloquea el loop

- **WHEN** el consumer de eventos llama `_get_shared_secret(agent_id)` durante el procesamiento de un mensaje
- **THEN** la llamada se realiza via `run_in_executor` en el threadpool por defecto
- **AND** el event loop queda libre para procesar otros coroutines durante el I/O de DB

#### Scenario: Múltiples mensajes pueden entrelazarse con otras tasks

- **WHEN** el consumer procesa un mensaje mientras hay requests HTTP entrantes
- **THEN** el event loop no queda bloqueado durante las operaciones DB del consumer
- **AND** los endpoints HTTP reciben respuesta sin esperar a que el consumer complete su DB I/O

#### Scenario: La resolución de autenticación del agente no bloquea el loop

- **WHEN** el consumer de eventos resuelve la credencial HMAC y el estado de revocación del agente en
  el carril feliz de ingesta
- **THEN** la consulta se realiza via `run_in_executor` y no sobre el event loop
- **AND** la función síncrona conserva su firma y su tipo de retorno sin convertirse en `async def`

#### Scenario: La inserción del evento no bloquea el loop

- **WHEN** el consumer de eventos persiste un evento del carril feliz
- **THEN** la sesión, la deduplicación por `event_id`, el `INSERT` y el `commit` se ejecutan en un
  hilo del executor y no sobre el event loop
- **AND** la taxonomía de resultado (persistido, duplicado, carrera de supersesión, limitado por
  tasa) y las excepciones de transición inválida y de error transitorio de base de datos se propagan
  al call site con la misma semántica de `XACK` / no-`XACK` que antes del cambio

#### Scenario: El despacho del lote sigue siendo mensaje a mensaje

- **WHEN** el consumer lee un lote de mensajes del stream de eventos
- **THEN** hay a lo sumo un mensaje en procesamiento en cualquier instante
- **AND** el lote se despacha en el mismo orden en que el broker lo entregó

#### Scenario: El orden FIFO se preserva tras un drenaje

- **WHEN** se drena una cola acumulada durante una desconexión del broker
- **THEN** el orden de los eventos persistidos, ordenados por su marca de detección, es monótono
  respecto del orden en que el agente los generó

#### Scenario: El drenaje no produce duplicados

- **WHEN** se drena una cola acumulada durante una desconexión del broker
- **THEN** ningún `event_id` aparece más de una vez en la tabla de eventos

#### Scenario: El objeto persistido cruza el límite del executor sin disparar I/O

- **WHEN** el hilo del executor devuelve el evento recién persistido al event loop
- **THEN** leer sus atributos desde el event loop no abre ninguna sesión ni emite ninguna consulta
- **AND** ninguna `Session` queda viva fuera del hilo que la abrió

#### Scenario: El limitador de tasa de ingesta tolera el cruce de hilos

- **WHEN** el presupuesto de ingesta se consume desde un hilo del executor y el remanente para el
  `retry_after` se consulta desde el event loop
- **THEN** el estado de la ventana deslizante queda protegido frente a accesos concurrentes
- **AND** el límite efectivo y el `retry_after` derivado conservan exactamente la semántica previa

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

### Requirement: Dimensionamiento conjunto y explícito del pool de conexiones y del executor

El engine de base de datos y el executor de hilos del backend MUST dimensionarse **en conjunto y de
forma explícita**, nunca por los defaults implícitos de la librería (D75/RN-169). Mover trabajo
bloqueante al executor sin acotar el pool cambia un cuello de botella por **agotamiento de
conexiones**, que además falla en vez de degradar.

El engine SHALL construirse con `pool_size`, `max_overflow` y `pool_timeout` explícitos. El backend
SHALL instalar un executor de hilos propio, con un número máximo de hilos explícito, como executor
por defecto del event loop, de modo que todo `run_in_executor(None, ...)` del proceso tire de un
único presupuesto acotado y verificable.

`pool_size`, `max_overflow` y el número máximo de hilos del executor MUST ser configurables por
entorno a través de `Settings`, con valores por defecto que reproduzcan el dimensionamiento
documentado. El número de hilos del executor MUST ser menor o igual que `pool_size + max_overflow`
descontando las conexiones reservadas para las dependencias HTTP de FastAPI y para el consumer de
heartbeat.

La reserva de conexiones no destinadas al executor SHALL ser una constante documentada del código,
NO un parámetro configurable: permitir ajustarla habilitaría desactivar el invariante que esta
regla existe para sostener.

El arranque del backend MUST abortar con error de validación si la configuración viola ese
invariante, con el mismo criterio fail-fast que el resto de `Settings`. Un dimensionamiento capaz de
agotar el pool MUST NOT descubrirse bajo carga.

El backend MUST NOT escalar horizontalmente para resolver este problema: sigue siendo single-instance
(RN-76).

#### Scenario: El engine se construye con pool explícito

- **WHEN** el backend crea el engine de base de datos
- **THEN** `pool_size`, `max_overflow` y `pool_timeout` provienen de valores explícitos y no de los
  defaults de la librería

#### Scenario: El executor acotado es el executor por defecto del loop

- **WHEN** el backend completa su arranque
- **THEN** existe un único executor de hilos propio del proceso, con su número máximo de hilos
  tomado de la configuración, instalado como executor por defecto del event loop
- **AND** los call sites que ya usaban el executor por defecto pasan a tirar de ese mismo presupuesto
  sin ser modificados

#### Scenario: Una configuración que puede agotar el pool aborta el arranque

- **WHEN** se configura un número de hilos del executor mayor que la capacidad del pool menos las
  conexiones reservadas
- **THEN** el arranque falla con un error de validación antes de aceptar tráfico

#### Scenario: Valores fuera de dominio abortan el arranque

- **WHEN** se configura un `pool_size` menor que 1, un `max_overflow` negativo o un número de hilos
  menor que 1
- **THEN** el arranque falla con un error de validación

#### Scenario: El executor se cierra ordenadamente en el shutdown

- **WHEN** el backend recibe señal de apagado
- **THEN** el executor propio se cierra esperando a sus hilos en vuelo, dentro del mismo ciclo de
  vida que gestiona el resto de los recursos del proceso

#### Scenario: Un despliegue sin configuración explícita arranca con el dimensionamiento documentado

- **WHEN** el entorno no declara ninguna de las tres variables
- **THEN** el backend arranca con los valores por defecto documentados y el invariante se cumple

