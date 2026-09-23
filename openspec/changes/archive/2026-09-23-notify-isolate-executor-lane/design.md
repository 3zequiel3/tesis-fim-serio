## Context

La Change 58 (D75/RN-169) sacó del event loop las `Session` síncronas del carril de ingesta y del
camino de notificación por evento. El diagnóstico era correcto y el trabajo está hecho y verificado.
Lo que no se anticipó es que **desbloquear el loop no separa los carriles**: los pone a competir por
el mismo recurso nuevo.

### El estado actual, con anclas

`backend/app/main.py:114-118` construye un único executor y lo instala como executor por defecto del
loop:

```python
db_executor = ThreadPoolExecutor(
    max_workers=settings.db_executor_max_workers,
    thread_name_prefix="fim-db",
)
asyncio.get_running_loop().set_default_executor(db_executor)
```

El comentario que lo acompaña dice explícitamente por qué se hizo así, y merece citarse porque esta
change **deroga parcialmente esa premisa**:

> Deliberado: NO se crea un executor separado para el carril de ingesta — eso partiría el presupuesto
> en dos números y volvería el invariante de dimensionamiento no verificable con una sola cuenta.

La premisa —un solo número es más verificable que dos— era razonable y se sostuvo mientras el único
consumidor relevante del executor fuera el carril de ingesta. Deja de sostenerse cuando dos carriles
con **reglas de admisión opuestas** comparten ese número: el de ingesta envía de a uno
(`consumer.py:299-300`, el bucle `for msg_id, msg_data in messages: await _handle_message(...)`), y
el de notificación envía sin cota (`_fire_and_forget`, `consumer.py:497`). Un presupuesto único no es
verificable si no se sabe quién lo consume; es sólo un número.

### Por qué la cola FIFO del executor convierte esto en acoplamiento

`ThreadPoolExecutor` atiende su `SimpleQueue` en orden de llegada y **no tiene cota del lado del
`submit`**. Cada notificación encola entre 2 y 5 trabajos (`_create_alert_row`,
`_prepare_notification`, y uno de `_mark_delivered` / `_record_retry_attempt` /
`_record_all_attempts_failed` por intento). Con 100 eventos `high` en ráfaga, el `_ingest` del evento
101 se encola **detrás de entre 200 y 500 trabajos de notificación**. El carril de ingesta no está
lento: está esperando en una fila que no es suya.

Eso explica las dos observaciones que de otro modo no encajan:

- **~17× de inflación** de la misma notificación entre aislamiento (302,8 ms,
  `notificacion/procedencia.txt`) y carga (5.233,672 ms media,
  `notificacion/resumen.txt`), con el **mismo** canal SMTP en las dos. Es la evidencia principal.
- **≈ 2,6× de degradación del drenaje** entre el canal en `log_only` (2.920 eventos en 58,809 s ≈
  49,7 ev/s) y el canal real (mediana de tres repeticiones: 141,061 s para ~2.670 eventos ≈
  18,9 ev/s).

> **Lo que NO se usa como argumento.** Una lectura previa de este paquete reportó una varianza de 4×
> entre repeticiones idénticas (141,061 s contra 566,004 s) y la ofreció como síntoma de encolamiento
> dependiente del backlog. **Esa varianza no existe.** `run-02` arrancó con 35 eventos residuales en
> la base (`initial: events=35` en `resiliencia/run-02/bateria5_run-02.log`, contra `events=0` en
> `run-01` y `run-03`), y como la ventana se calcula `max(received_at) − min(received_at)`, esos 35
> la inflaron: hay un hueco de 442,869 s entre el evento 35 y el 36. La ventana real es **120,366 s**,
> y las tres repeticiones caen en **120,366 / 141,061 / 150,150 s** — dispersión estrecha. El
> argumento de varianza no aparece en ninguna parte de esta change. Se deja anotado acá porque el
> modo de falla —un residual que corre el extremo inferior de una ventana calculada por diferencia de
> extremos— reaparecerá en la re-medición de D-10 si no se verifica `initial: events=0` antes de cada
> repetición.

Hay un detalle contraintuitivo en los números de notificación que conviene dejar anotado, porque a
primera vista parece contradecir la tesis: la media **baja** al subir la concurrencia (5.233,672 ms
secuencial contra 4.270,074 ms con concurrencia 100). No es una mejora del sistema. En el escenario
secuencial cada notificación espera detrás de la cola completa del executor; en los concurrentes, el
arnés emite las notificaciones en paralelo y el intervalo medido (`received_at → delivered_at`)
empieza a solaparse entre ellas, de modo que el mismo tiempo de cola se reparte entre más muestras.
Los tres escenarios comparten el mismo techo —p95 entre 5,9 s y 6,5 s—, que es la firma de una cola
saturada, no de un sistema que escala.

### Restricciones vigentes que no se negocian acá

- **RN-76**: backend single-instance. No hay escalado horizontal disponible como respuesta.
- **D21 / D75**: no se migra a `AsyncSession`.
- **D75/RN-169**: el despacho del lote sigue siendo secuencial; los ítems 40 (FIFO) y 41 (cero
  duplicados) del protocolo no son degradables.
- **D40/RN-134 y D41/RN-135**: `notification_id` estable a lo largo de toda la escalera de
  reintentos. Es el invariante más frágil de esta change y tiene su propia decisión (D-7).

## Goals / Non-Goals

**Goals:**

1. Que el trabajo de notificación **no pueda ocupar un hilo que el carril de ingesta necesita**, por
   construcción y no por disciplina de uso.
2. Que la concurrencia del carril de notificación esté **acotada**, con un comportamiento de desborde
   **declarado y verificable**, en lugar de la acumulación no acotada que hoy produce
   `_fire_and_forget`.
3. Que el presupuesto de conexiones siga siendo una **desigualdad verificable con los valores de
   `Settings`**, ahora con dos executors, y que su violación siga matando el arranque.
4. Que todos los invariantes vigentes del camino de notificación sobrevivan **verificados**, no
   asumidos.
5. Que la re-medición del candidato quede como tarea obligatoria, sin declarar el resultado por
   anticipado.

**Non-Goals:**

- **No** se separa la notificación a un stream de Valkey ni a un proceso propio. Es la dirección
  correcta a mayor escala y está declarada en el proposal; es otra magnitud de cambio (D-11).
- **No** se agrega un barrido periódico de notificaciones pendientes (D-4).
- **No** se migra a `AsyncSession`, no se escala horizontalmente, no se cambia el contrato de
  notificación, la cascada de canales, los `RETRY_DELAYS`, el esquema de base de datos ni el default
  de producción del rate limit.
- **No** se toca `agent/` ni `frontend/`.
- **No** se declara por anticipado que esta change mejora ningún número medido.

## Decisions

### D-1 — Dos executors, no uno particionado ni un `Semaphore` sobre el executor compartido

**Decisión.** Se construye un segundo `ThreadPoolExecutor` exclusivo del carril de notificación. El
carril de ingesta **conserva el executor por defecto del loop, en exclusiva**.

**Alternativas evaluadas y descartadas:**

- *Un solo executor más grande.* No aísla nada: con la cola FIFO compartida, agrandar el pool sube el
  techo de trabajo concurrente pero no impide que 500 trabajos de notificación se encolen delante de
  un `_ingest`. Mueve el número, no el acoplamiento.
- *Un semáforo que limite cuántos trabajos de notificación hay en vuelo **en el executor
  compartido**.* Acota la ocupación pero no la **posición en la cola**: un `_ingest` que llega
  mientras el semáforo está lleno igual espera a que se libere un hilo que está haciendo trabajo de
  notificación. La ingesta seguiría siendo función del backlog ajeno, que es exactamente lo que se
  quiere romper.
- *Un executor con prioridades.* `ThreadPoolExecutor` no las soporta; implementarlo significa una
  cola de prioridad propia y un scheduler propio. Complejidad muy superior a la de dos pools, para un
  problema que dos pools resuelven de forma total.

**Por qué dos pools bastan.** Con pools disjuntos, la propiedad buscada es estructural y no
depende de ningún parámetro: **ningún trabajo de notificación puede estar ocupando un hilo del pool
de ingesta, porque no tiene forma de llegar a él.** Es verificable leyendo los call sites, y es
testeable.

### D-2 — Los call sites de notificación referencian su executor **explícitamente**; `None` queda reservado al carril de ingesta

**Decisión.** Los seis `run_in_executor` del camino de notificación por evento
(`alerts/service.py:144`, `:304`, `:327`, `:338`, `:344`, `:357`) dejan de pasar `None` y pasan el
handle del executor de notificaciones. `set_default_executor(db_executor)` en `main.py:118`
**se conserva sin cambios**.

**Fundamento.** `set_default_executor` más `run_in_executor(None, ...)` es *precisamente* el
mecanismo que hoy comparte los pools. Mientras un call site pase `None`, está pidiendo el executor de
ingesta, diga lo que diga el comentario que tenga al lado. La separación tiene que ser explícita en
el argumento o no existe.

**Consecuencia deliberada:** los demás usuarios de `run_in_executor(None, ...)` del proceso
—`events/consumer.py:342`, `:446`, `:468`, `:602`, `:611`; `agents/heartbeat_consumer.py:66`, `:207`;
`agents/command_ack_consumer.py:150`, `:326`; `rules/service.py:453`; `core/health.py:51`, `:65`—
**no se tocan**. Siguen en el executor por defecto, que ahora tiene un competidor menos. Esta change
no le quita hilos al carril de ingesta; le quita un competidor.

**Alternativa descartada:** invertir la asignación (dar el executor por defecto a las notificaciones
y uno explícito a la ingesta). Produciría un diff mucho mayor —hay once call sites del lado de
ingesta y anexos contra seis del lado de notificación— y, peor, dejaría el carril crítico dependiendo
de que nadie olvide el argumento. El default debe pertenecer al carril que **no** puede degradarse.

### D-3 — Los handles viven en un módulo propio de `core`, no en `main.py`

**Decisión.** Un módulo nuevo bajo `backend/app/core/` guarda los dos executors y expone accesores.
El lifespan de `main.py` los construye y los cierra; `alerts/service.py` obtiene su handle por
accesor.

**Fundamento.** `alerts/service.py` no puede importar `main.py` sin ciclo: `main.py` importa los
routers, que importan los services. Un módulo de `core/` es la ubicación que el proyecto ya usa para
recursos de proceso compartidos (`core/database.py` para el engine, `core/config.py` para
`Settings`).

**Contrato del accesor.** Devuelve el executor instalado, y **falla de forma explícita** si se lo
invoca antes de que el lifespan lo haya construido. Un fallback silencioso al executor por defecto
volvería a mezclar los pools en cualquier camino que corriera fuera del lifespan —los tests son el
caso obvio— y el aislamiento se perdería sin que nada lo señale. Los tests que ejerciten el camino de
notificación instalan el executor explícitamente, igual que ya instalan el resto del entorno.

### D-4 — El semáforo acota **entregas**, vive dentro de `notify_event`, y el desborde **espera**

Esta es la decisión con más consecuencias y la que el proposal pide dejar explícita.

**Qué se acota.** El número de **entregas concurrentes**, entendiendo por entrega el cuerpo de
`notify_event`: preparación del payload, escalera de reintentos de n8n, cascada de fallbacks y
registro del resultado.

**Qué NO se acota.** La creación de la fila `Alert` (`_create_alert_row`, `:144`). Queda **fuera** del
semáforo, deliberadamente. Es el registro durable del que dependen la DLQ (RN-86/RN-102), el
broadcaster SSE y la recuperación; estrangularlo convertiría un problema de latencia de entrega en
un problema de pérdida de visibilidad. Una alerta que tarda en entregarse sigue siendo visible; una
alerta que tarda en **crearse** no existe para nadie.

**Dónde vive.** Dentro de `notify_event`, envolviendo su cuerpo después de la guarda
`if alert.id is None` (`:295-296`). No en el call site.

**Por qué ahí y no en `_fire_and_forget`.** `notify_event` tiene **tres** puertas de entrada, y dos
de ellas ya son fuentes de concurrencia no acotada por derecho propio:

| Puerta | Ancla | Concurrencia actual |
|---|---|---|
| Consumer de eventos | `consumer.py:497` → `notify_if_applicable` → `:164` | No acotada (una corrutina por evento `critical`/`high`) |
| Recuperación del arranque | `recover_pending_notifications` | **`asyncio.gather` sobre TODAS las pendientes** |
| Reintento manual desde la DLQ | `alerts/service.py:578` | Una por request HTTP |

La recuperación del arranque es el peor caso de los tres: dispara de golpe tantas corrutinas de
entrega como filas pendientes haya, justo en el arranque, que es cuando el consumer está por empezar
a drenar. Un semáforo puesto en el call site del consumer no la tocaría. Puesto dentro de
`notify_event`, un solo mecanismo cubre las tres y ninguna puerta futura se lo puede saltear por
olvido.

**Comportamiento de desborde: la corrutina espera su turno, en orden de llegada. No se descarta, no
se rechaza y no se difiere.**

Las alternativas, con el motivo exacto del descarte:

- *Descartar la entrega al llenarse la cota.* Viola la semántica al-menos-una-vez que
  `notify_event` documenta en su docstring (`:291-293`) y que los receptores deduplican por
  `notification_id` (D41/RN-135). Descartado sin más análisis: no se degrada una garantía entregada
  para resolver un problema de latencia.
- *Diferir: dejar la fila `Alert` pendiente y que la recoja la recuperación.* Es atractivo porque la
  fila **ya es durable** y `recover_pending_notifications` selecciona exactamente
  `delivered_at IS NULL AND failed_at IS NULL AND notification_id IS NOT NULL`. Pero esa recuperación
  **corre una sola vez, en el arranque**. Diferir significaría, en los hechos, "entregar en el próximo
  reinicio": una degradación silenciosa de al-menos-una-vez disfrazada de control de admisión.
  Volverla periódica es viable y probablemente correcto, pero es maquinaria nueva con su propio
  presupuesto de conexiones y su propia cadencia, y se convierte en la política de desborde de la que
  esta change dependería. Queda **fuera de alcance y nombrada** (D-11), y con ella cualquier política
  de desborde que quiera descartar o diferir.
- *Liberar el permiso durante los `asyncio.sleep` de la escalera de reintentos.* Elimina el bloqueo
  de cabeza de línea, pero vacía la cota de contenido: con los permisos liberados durante las esperas
  —que son la mayor parte del tiempo de vida de una entrega que falla—, el número de corrutinas vivas
  vuelve a no tener cota. Se descarta por no acotar lo que dice acotar.

**El costo residual, declarado.** Con "esperar" como desborde, el número de corrutinas **en espera**
no tiene cota. Se asume, y se acota aritméticamente contra el rate limit de ingesta: con el default
de producción de `rate_limit_ingest_events = 100` por `rate_limit_ingest_window_seconds = 60.0` y por
`agent_id` (`config.py:98-99`), un agente no puede generar más de 100 alertas por minuto. La escalera
completa de reintentos suma `5 + 30 + 120 = 155 s` de esperas (`RETRY_DELAYS`, `alerts/service.py:55`)
más los timeouts de los canales, de modo que el peor caso de corrutinas vivas por agente durante una
degradación total del canal es del orden de **unos cientos**, y escala linealmente con la cantidad de
agentes. Cada una retiene un `Future`, una `Alert` desligada y un `Event` desligado: costo de memoria
pequeño y acotado por esa cuenta, no por el semáforo.

Ese residuo se hace **observable**: al cruzar un umbral declarado de corrutinas en espera se emite un
log de advertencia con el conteo, **disparado por flanco** —una vez al cruzar hacia arriba y una vez
al volver hacia abajo—, nunca por evento. Un log por notificación bajo saturación sería exactamente
la clase de amplificación que agrava la condición que pretende reportar.

### D-5 — La aritmética del presupuesto, con dos executors

**La desigualdad nueva:**

```
db_executor_max_workers + db_notify_executor_max_workers
    ≤ db_pool_size + db_max_overflow − _DB_CONNECTIONS_RESERVED_NON_EXECUTOR
```

**Por qué la suma y no dos desigualdades separadas.** Los dos pools de hilos tiran del **mismo** pool
de conexiones. Dos desigualdades independientes admitirían una configuración donde cada executor
cabe por separado y juntos agotan el pool: exactamente el modo de falla que D75/RN-169 existe para
prevenir, con la agravante de parecer validado.

**Los valores por defecto propuestos, y de dónde sale cada uno:**

| Parámetro | Antes | Ahora | Fundamento |
|---|---|---|---|
| `db_pool_size` | 10 | **10** | Sin cambio. |
| `db_max_overflow` | 10 | **18** | Crece 8 para alojar el executor nuevo sin tocar el carril de ingesta. |
| `_DB_CONNECTIONS_RESERVED_NON_EXECUTOR` | 10 | **10** | Sin cambio. El reparto de D-4 de la Change 58 —6 dependencias HTTP de FastAPI + 2 consumer de heartbeat + 2 corrutinas del lifespan con `Session` sobre el loop— no se altera: esta change no agrega ningún consumidor fuera de executor. |
| `db_executor_max_workers` | 10 | **10** | Sin cambio, y es el punto: **el carril de ingesta no cede nada**. |
| `db_notify_executor_max_workers` | — | **8** | Nuevo. Ver abajo. |

**Verificación:** `10 + 8 = 18 ≤ 10 + 18 − 10 = 18`. ✔ Saturada exactamente, misma disciplina que
dejó D75/RN-169 (donde `10 ≤ 10 + 10 − 10 = 10`).

**Por qué 8 para el carril de notificación.** El trabajo de base de datos de una entrega es
**estrictamente serial dentro de su corrutina**: `_prepare_notification` termina antes de que empiece
el primer `send_n8n`, y `_mark_delivered` o `_record_retry_attempt` corren después. Nunca hay más de
un trabajo de executor en vuelo por notificación. El número de hilos fija entonces el **paralelismo
instantáneo de base de datos del carril**, no su concurrencia total —esa la fija el semáforo, y las
dos cosas son distintas a propósito (D-6)—. Ocho hilos sostienen holgadamente el trabajo de base de
datos de decenas de entregas concurrentes, porque cada entrega pasa la mayor parte de su vida
esperando en la red o durmiendo entre reintentos. Y se elige **estrictamente menor que 10**: ante
cualquier duda de dimensionamiento, el carril que no puede degradarse se queda con la porción mayor.

**Por qué crecer el pool en lugar de repartir los 10 actuales.** Repartir daría, por ejemplo, 6 de
ingesta y 4 de notificación: le sacaría capacidad al carril crítico para financiar su aislamiento,
que es la dirección contraria a la que esta change persigue. Crecer cuesta 8 conexiones más contra
un `postgres:18.3` sin override de `max_connections` (`docker-compose.yml:46`), es decir con el
default de **100**, para un backend **single-instance** (RN-76). El techo no está cerca: 28 de 100.

**La reserva sigue siendo constante, no knob.** Se conserva el criterio de D75/RN-169: un parámetro
configurable para la reserva permitiría desactivar el invariante ajustándolo.

**Fail-fast, igual que antes.** El `model_validator` sigue abortando el arranque con `ValidationError`
y un mensaje que nombra los cinco valores en juego, la reserva, el máximo permitido y la suma
recibida. Una configuración capaz de agotar el pool tiene que matar el arranque, no descubrirse bajo
carga como un `TimeoutError` intermitente.

### D-6 — El semáforo y el tamaño del executor son dos cotas distintas, y se dimensionan por separado

**Decisión.** La cota de entregas concurrentes es un parámetro propio, **mayor** que el número de
hilos del executor de notificación.

**Fundamento.** Acotan recursos distintos:

- El **executor** acota el paralelismo de **base de datos** del carril: cuántas `Session` puede tener
  abiertas a la vez. Está atado al pool de conexiones por D-5.
- El **semáforo** acota las **corrutinas de entrega** en vuelo, que pasan la mayor parte de su tiempo
  en espera de red o durmiendo entre reintentos, **sin ocupar ningún hilo ni ninguna conexión**.

Igualarlos sería un error de dimensionamiento con consecuencia concreta: ocho entregas durmiendo sus
120 s de tercer reintento bloquearían el carril completo mientras los ocho hilos del executor están
ociosos. La cota de entregas debe ser generosa respecto de la de hilos; el executor es el estrangulador
de base de datos, el semáforo es el tope de trabajo en vuelo.

**Default propuesto: 32 entregas concurrentes.** Cubre el caso normal —a ~302,8 ms de costo aislado
por notificación, 32 en vuelo sostienen un orden de magnitud más de notificaciones por segundo de las
que el rate limit de ingesta permite generar— sin que la cota deje de ser una cota. Configurable,
como el resto del dimensionamiento.

### D-7 — `notification_id` estable: lo que esta change tiene prohibido tocar

**El invariante.** `_build_payload` (`alerts/service.py:169`) se invoca **exactamente una vez** por
entrega, dentro de `_prepare_notification` (`:236`), que a su vez se invoca **una sola vez, fuera del
bucle de reintentos** (`:304`). Ésa es la única razón por la que `notification_id` es estable a lo
largo de toda la escalera, y la estabilidad es la única razón por la que sirve como clave de
deduplicación (D40/RN-134, D41/RN-135). El docstring de `notify_event` (`:283-293`) lo declara como
INVARIANTE con todas las letras.

**Por qué corre riesgo en esta change y no en otras.** Introducir un semáforo alrededor del cuerpo de
`notify_event` invita a dos movimientos naturales y ambos rompen el invariante:

1. *Adquirir el permiso **después** de preparar el payload*, para "no gastar el permiso en trabajo
   barato". Deja `_prepare_notification` —una `Session` con `commit` y `refresh`— **fuera** de la
   cota, y con eso el carril vuelve a tener un tramo de base de datos no acotado.
2. *Reintentar la adquisición del permiso por cada vuelta del bucle*, que es lo que saldría de
   envolver el bloque equivocado. Eso mueve efectivamente la preparación adentro del bucle, y con
   ella `_build_payload`: un `notification_id` por intento, y un reintento se vuelve indistinguible
   de una notificación nueva. Es exactamente la ambigüedad que el campo existe para resolver.

**Decisión.** El permiso se adquiere **una vez**, antes de `_prepare_notification`, y se sostiene
hasta que la entrega termina —entregada, fallida en todos los canales, o cortocircuitada por el
`return` de idempotencia cuando `_prepare_notification` devuelve `None` (`:305-306`)—. `_build_payload`
y `_prepare_notification` **no cambian de posición ni de cantidad de invocaciones**. El bucle de
reintentos (`:314-340`) no se toca. Se agrega un test que falla si `_build_payload` se invoca más de
una vez por entrega, para que esto no dependa de que nadie lo mueva.

### D-8 — Los objetos ORM que cruzan el límite del segundo executor se tratan igual que antes

Ningún cambio de criterio: `session.expunge(...)` antes de cerrar la `Session`, con los atributos ya
materializados, para que leerlos desde el loop no dispare I/O. Ya es lo que hacen `_create_alert_row`
(`:108`) y `recover_pending_notifications`. Que ahora el hilo venga de otro pool no altera nada: la
propiedad que importa es que la `Session` sea **local a la invocación** y no cruce el límite, y eso
vale para los dos pools por igual.

Se anota explícito porque un segundo executor invita a la idea de "un executor con estado propio".
No lo hay: ninguna `Session` se comparte entre hilos, se guarda en estado de módulo ni cruza el
límite del executor, en ninguno de los dos.

### D-9 — Cierre ordenado: primero el de notificación, después el de ingesta

**Decisión.** En el shutdown del lifespan, los dos executors se cierran con `shutdown(wait=True)`
**después** del `gather` de cancelación de tasks que ya existe, y el de notificación **antes** que el
de ingesta.

**Fundamento del orden.** Las corrutinas de notificación son las últimas en tener trabajo pendiente
—una entrega en curso puede estar a mitad de su escalera— y son las únicas que envían trabajo a su
propio executor. Cerrar primero el de ingesta no ayuda a nadie; cerrar primero el de notificación
deja que el drenaje de la cola de notificaciones termine mientras el resto del proceso todavía
existe. Con `wait=True` después del `gather` de cancelación, ninguno de los dos puede colgar el
shutdown a la espera de una task que ya fue cancelada.

### D-10 — La re-medición es obligatoria y no anticipa su resultado

Esta change **invalida el candidato congelado `v2.0-tesis`** (`9c523f4`, `env/procedencia.txt`). Las
mediciones de notificación y de resiliencia del paquete `v2-eval-20260922T175053Z` describen un
binario con un solo executor compartido; después de esta change no describen nada.

Se re-corre el arnés unificado `~/fim-lab/corrida_unificada.sh` completo —no un subconjunto— y se
emite un **tag nuevo**. El paquete previo queda como línea de base de comparación, no se borra ni se
sobrescribe.

**No se declara mejora por anticipado.** Se implementa, se mide, y se registra el número medido sea
cual sea. Si el aislamiento no mueve los números, eso se escribe con la misma claridad con la que la
Change 58 escribió que no había mejorado el ítem 43. Un diseño correcto sobre un cuello que estaba en
otro lado sigue siendo un diseño correcto y un resultado nulo; confundir las dos cosas es lo que la
tabla de ajustes del Change 57 existe para impedir.

### D-11 — Stream y proceso separados: la dirección, declarada y fuera de alcance

**Lo que resolvería.** Publicar las notificaciones a un stream de Valkey propio, consumido por un
proceso separado, lleva el aislamiento de **recursos dentro del proceso** a aislamiento de
**proceso**. Un backlog de notificaciones no podría tocar el event loop, ni el pool de conexiones, ni
la memoria del proceso de ingesta. Cada lado se dimensionaría y se reiniciaría por separado.

**Por qué no acá.** Es otra magnitud de cambio: stream nuevo y su contrato, consumer group nuevo,
unidad de despliegue nueva en el compose, política propia de reintento y de DLQ del lado del consumer
de notificaciones, y una revisión de RN-76, que hoy fija el backend como single-instance. El
aislamiento de recursos dentro del proceso es la **corrección mínima** que la evidencia disponible
justifica, y es un prerrequisito natural de la separación por proceso: obliga a delimitar con
precisión qué trabajo pertenece al carril de notificación, que es exactamente lo que habría que
mover.

**Queda nombrado para que la decisión esté en el registro**, no como omisión. Con él queda el
**barrido periódico de notificaciones pendientes** del que dependería cualquier política de desborde
que descarte o difiera (D-4).

## Risks / Trade-offs

**[La cola de espera del semáforo no tiene cota]** → Asumido y declarado (D-4). Acotado
aritméticamente contra el rate limit de ingesta (100 eventos/60 s por `agent_id`) y hecho observable
con un umbral de advertencia disparado por flanco. Las alternativas que sí lo acotarían —descartar o
diferir— degradan la semántica al-menos-una-vez o dependen de un barrido periódico que no existe.

**[Bloqueo de cabeza de línea: entregas lentas ocupando permisos]** → Real. Una degradación total del
canal deja hasta 32 permisos tomados durante los ~155 s de la escalera. Mitigación: la cota de
entregas se dimensiona holgada respecto de los hilos del executor (D-6), la creación de la fila
`Alert` queda fuera del semáforo de modo que la **visibilidad** de la alerta nunca se bloquea (D-4), y
la condición es observable. Liberar el permiso durante los `sleep` se evaluó y se descartó por vaciar
la cota de contenido.

**[Un `run_in_executor` nuevo que olvide el argumento vuelve a mezclar los pools]** → El modo de falla
es silencioso: funciona, y el aislamiento desaparece sin señal. Mitigación: un test que verifique que
ningún call site del camino de notificación pasa `None`, y que el trabajo de notificación corre en
hilos con el prefijo de nombre del executor de notificación.

**[Mover `_prepare_notification` respecto del semáforo rompe `notification_id`]** → El riesgo más
grave de la change, porque el daño no se ve: el sistema sigue entregando, y lo que se rompe es la
deduplicación del **receptor** (D40/RN-134, D41/RN-135). Mitigación: D-7 fija la posición del permiso,
y un test falla si `_build_payload` se invoca más de una vez por entrega.

**[28 conexiones contra el pool de PostgreSQL]** → Bajo. `postgres:18.3` sin override de
`max_connections` (`docker-compose.yml:46`) da 100 por defecto, contra un backend single-instance
(RN-76). El validador fail-fast sigue cubriendo la configuración; lo que el validador **no** cubre es
el techo del servidor, así que el número se deja escrito en el comentario del bloque de `Settings`
para que un cambio futuro de `max_connections` o de la topología lo encuentre.

**[La recuperación del arranque se vuelve más lenta]** → Deliberado. Hoy su `asyncio.gather` dispara
todas las entregas pendientes de golpe, compitiendo con el consumer justo cuando éste empieza a
drenar. Bajo el semáforo procesa de a 32: tarda más en total y deja de ser una ráfaga que golpea el
arranque. Es el comportamiento que se busca, no un efecto colateral.

**[Dos números de dimensionamiento en lugar de uno]** → La premisa que `main.py:110-113` dejó
escrita. Mitigación: la desigualdad de D-5 los **suma**, de modo que sigue habiendo una sola cuenta
que verificar; lo que cambia es que ahora tiene dos términos. Un presupuesto único compartido por
carriles con reglas de admisión opuestas no era más verificable: era menos informativo.

## Migration Plan

Sin migración de datos: no hay cambios de esquema, de contrato de stream ni de contrato de
notificación.

**Orden de despliegue — restricción, no preferencia.** El presupuesto de conexiones (D-5) va **antes**
que la creación del segundo executor, y ésta **antes** que el cambio de los call sites. Crear el
executor sin haber ampliado el pool deja una configuración que el validador rechaza —el arranque
falla, que es el comportamiento correcto pero no el orden útil—; cambiar los call sites antes de que
el executor exista deja el accesor fallando en el primer evento `high`.

**Rollback.** Revertir el commit. No queda estado persistido ni consumido que haya que deshacer: los
executors son recursos de proceso, el semáforo es estado en memoria, y las filas `alerts` que la
versión nueva haya creado son indistinguibles de las que crea la versión vieja. Una entrega en vuelo
al momento del reinicio queda pendiente en la tabla y la recoge `recover_pending_notifications`, que
es el comportamiento vigente y no cambia.

**Configuración.** Las variables nuevas son opcionales: un despliegue que no las declare arranca con
los defaults de D-5. El default de `db_max_overflow` **cambia** de 10 a 18, así que un despliegue que
hoy lo fije explícitamente en 10 y no lo actualice **fallará el arranque** con el `ValidationError`
del invariante. Es el comportamiento buscado —fail-fast antes que agotamiento bajo carga— y tiene que
quedar documentado en el template de entorno, no descubrirse en el despliegue.

## Open Questions

1. **La contabilidad causal de las operaciones no encoladas no cierra.** El generador emite 3.000
   operaciones por repetición; el log del agente marca 420 líneas `modify colapsado` por repetición;
   y `420 + 2.671 = 3.091 > 3.000`. El marcador de colapso **no particiona** el universo de
   operaciones: alguna operación contada como colapsada produjo igualmente un evento encolado antes,
   en una cantidad que la instrumentación vigente no permite determinar. **Queda declarado como
   supuesto abierto y esta change no lo resuelve ni infiere una explicación.** No afecta el diseño
   —el diagnóstico del acoplamiento se funda en la latencia de notificación y en la tasa de drenaje,
   no en la contabilidad de operaciones del generador— ni afecta la preservación, que es del 100 %
   sobre los eventos **encolados** en las tres repeticiones. Cerrarlo requiere instrumentación
   adicional en el agente y es materia de otra change.

2. **La re-medición de D-10 debe verificar `initial: events=0` antes de cada repetición.** No es una
   duda de diseño sino una precondición del protocolo, aprendida del artefacto de `run-02` descrito
   en el Context: una ventana calculada como diferencia de extremos de `received_at` es sensible a
   cualquier residual previo, y el arnés hoy reporta el conteo inicial pero no aborta ni corrige por
   él.

Ninguna de las dos bloquea la implementación. La primera es una brecha de instrumentación declarada;
la segunda es una precondición de la medición posterior.
