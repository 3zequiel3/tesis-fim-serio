## Why

La Change 58 (`ingest-offload-blocking-db`, archivada el 2026-09-19, D75/RN-169) sacó las `Session`
bloqueantes del event loop y las mandó a un pool de hilos. **No resolvió la contención: la mudó de
lugar.** El carril de ingesta y el carril de notificación comparten hoy un único `ThreadPoolExecutor`
de 10 hilos, y compiten por él con reglas de admisión opuestas.

La forma exacta del acoplamiento, con sus anclas:

1. `backend/app/main.py:114-118` construye **un solo** `ThreadPoolExecutor(max_workers=settings.db_executor_max_workers)`
   y lo instala con `asyncio.get_running_loop().set_default_executor(db_executor)`.
2. Por lo tanto **todo** `run_in_executor(None, ...)` del proceso tira de ese mismo pool. El tamaño
   por defecto es 10 (`db_executor_max_workers`, `backend/app/core/config.py:164`), acotado contra el
   pool de conexiones por el validador de `config.py:176-184`
   (`db_pool_size=10` + `db_max_overflow=10` − `_DB_CONNECTIONS_RESERVED_NON_EXECUTOR=10`).
3. El carril de **ingesta** le envía trabajo de forma **secuencial**, un evento por vez:
   `_get_agent_auth` (`backend/app/modules/events/consumer.py:342`) e `_ingest` (`:446`).
4. El carril de **notificación** le envía trabajo al **mismo** pool con **concurrencia no acotada**,
   desde corrutinas lanzadas con `_fire_and_forget` (`consumer.py:497`). Cada notificación encola
   varios trabajos de executor: `_create_alert_row` (`alerts/service.py:144`),
   `_prepare_notification` (`:304`), `_mark_delivered` (`:327`, `:344`), `_record_retry_attempt`
   (`:338`) y `_record_all_attempts_failed` (`:357`).
5. Consecuencia: ante una ráfaga de eventos `critical` o `high`, cientos de corrutinas de
   notificación encolan trabajo de executor **por delante** del `_ingest` del evento siguiente. La
   cola del executor es FIFO y no tiene cota del lado del `submit`. **La latencia del carril de
   ingesta pasa a ser una función del backlog de notificaciones.**

El mismo acoplamiento aparece dos veces más, también sin cota: `recover_pending_notifications`
(`alerts/service.py`) hace `asyncio.gather` sobre **todas** las alertas pendientes en el arranque, y
`retry_alert` (`:578`) lanza su propia corrutina desde el camino HTTP.

### Evidencia medida

Candidato `v2.0-tesis` (`9c523f4`, `env/procedencia.txt`), paquete
`tesis/cierre/evidencia/v2-eval-20260922T175053Z/`:

| Medición | Valor | Fuente |
|---|---|---|
| Notificación aislada | **302,8 ms** media, 349,4 ms máx (n=10) | `notificacion/procedencia.txt` |
| Cadena completa bajo carga, escenario secuencial | **5.233,672 ms** media, p95 6.469,887, máx 6.532,691 (n=300) | `notificacion/resumen.txt` |
| Cadena completa bajo carga, concurrencia 50 | 4.503,563 ms media, p95 6.075,028 | `notificacion/resumen.txt` |
| Cadena completa bajo carga, concurrencia 100 | 4.270,074 ms media, p95 5.966,762 | `notificacion/resumen.txt` |
| Latencia de ingesta sin carga de notificación | 45,797 ms media, p95 62,615 (n=483) | `latencia/resumen.txt` |

El intervalo medido es `events.received_at → alerts.delivered_at` contra un SMTP real local
(Mailpit), declarado en `notificacion/procedencia.txt`. Las tres escenarios comparten el mismo techo
—p95 entre 5,9 s y 6,5 s— y las 900 notificaciones se entregaron. **Una notificación que aislada
cuesta 302,8 ms cuesta 5.233,672 ms cuando el carril de ingesta está trabajando: ~17× de inflación.**
El canal SMTP no lo explica —es el mismo canal en las dos mediciones—: lo que cambia es la espera en
la cola del executor compartido. Ésta es la evidencia más fuerte del acoplamiento.

El drenaje lo confirma con una degradación consistente. Tres repeticiones de la Batería 5, con el
canal de notificación real:

| Repetición | Encolados | Entregados | Descartados | Ventana | Tasa |
|---|---|---|---|---|---|
| `run-01` | 2671 | 2671 | 0 | 141,061 s | 18,94 ev/s |
| `run-02` | 2664 | 2664 (+35 residuales) | 0 | 120,366 s | 22,13 ev/s |
| `run-03` | 2663 | 2663 | 0 | 150,150 s | 17,74 ev/s |

Mediana **141,061 s**, preservación **100 %** de los encolados en las tres, **0** descartados, **0**
rechazos y **0** duplicados (eventos = únicos en las tres). Contra la corrida con el canal en
`log_only` —es decir, sin costo real de entrega—, que drenó **2.920 eventos en 58,809 s ≈ 49,7 ev/s**:
la degradación atribuible al acoplamiento es de **≈ 2,6×**.

> **Corrección de contabilidad, anotada para que no se repita.** Una lectura previa de este mismo
> paquete reportó `run-02` con una ventana de 566,004 s (4,77 ev/s) y, a partir de ahí, una varianza
> de 4× entre repeticiones idénticas que se ofreció como síntoma de encolamiento dependiente del
> backlog. **Ese número era un artefacto y la varianza no existe.** `run-02` arrancó con 35 eventos
> residuales ya en la base —`initial: events=35` en `resiliencia/run-02/bateria5_run-02.log`, contra
> `events=0` en las otras dos—, y la ventana se calcula como `max(received_at) − min(received_at)`:
> esos 35 corrieron `min(received_at)` hacia atrás e inflaron la ventana. La traza muestra un hueco de
> 442,869 s entre el evento 35 y el 36. Descontados los residuales, la ventana real de `run-02` es
> **120,366 s** y las tres repeticiones caen en una dispersión estrecha (120,4 s – 150,2 s). El
> argumento de varianza **no se usa en ninguna parte de esta change**; el que sostiene el diagnóstico
> es la inflación de ~17× de la latencia de notificación, que no depende de esta corrección.

### Supuesto abierto que esta change declara y NO resuelve

**La contabilidad causal de las operaciones que no llegaron a encolarse no cierra.** El generador
emite **3.000** operaciones por repetición; el log del agente marca **420** líneas `modify colapsado`
por repetición; y **420 + 2.671 = 3.091 > 3.000**. Es decir: el marcador de colapso **no particiona
el universo de operaciones**. Alguna operación contada como colapsada produjo igualmente un evento
encolado antes de colapsar, de modo que las dos cuentas se solapan en una cantidad que la
instrumentación actual no permite determinar.

**No se infiere ninguna explicación acá, y esta change no la resuelve.** Queda declarado que la
atribución causal por operación no encolada está **sin cerrar con la instrumentación vigente**. No
afecta el diagnóstico del acoplamiento —que se funda en la latencia de notificación y en la tasa de
drenaje, no en la contabilidad de operaciones del generador— ni afecta la preservación, que es del
100 % sobre los eventos **encolados** en las tres repeticiones. Cerrar esa atribución requiere
instrumentación adicional en el agente y es materia de otra change.

### El principio que esta change existe para honrar

**La notificación es una reacción, no un acoplamiento.** La recuperación de un backlog de ingesta no
puede ser función de cuánto tarda un mail. Hoy lo es, por construcción: un único pool compartido, con
un carril que envía de a uno y otro que envía sin cota.

## What Changes

- **Executor dedicado para el carril de notificación.** Se agrega un segundo `ThreadPoolExecutor`,
  dimensionado por separado, exclusivo del camino de notificación. El carril de ingesta **conserva el
  executor por defecto para sí solo**: no se le quita ni un hilo, se le quita un competidor. Como
  `set_default_executor` más `run_in_executor(None, ...)` es exactamente el mecanismo que hoy comparte
  los pools, los call sites de notificación **pasan a referenciar su executor de forma explícita** en
  lugar de `None`. Los demás usuarios del executor por defecto (`events/consumer.py`,
  `agents/heartbeat_consumer.py`, `agents/command_ack_consumer.py`, `rules/service.py`, `core/health.py`)
  **no cambian**.

- **Concurrencia acotada del carril de notificación, con comportamiento de desborde declarado.**
  `_fire_and_forget` hoy permite acumulación no acotada de corrutinas. Se introduce un semáforo que
  acota las **entregas concurrentes**. El semáforo vive **dentro de `notify_event`**, no en el call
  site, de modo que cubre las tres puertas de entrada del camino de entrega —el consumer, la
  recuperación del arranque y el reintento manual— con un solo mecanismo.

  **Comportamiento de desborde: la corrutina espera su turno (FIFO). No se descarta, no se rechaza y
  no se difiere.** Esto es una decisión, no un default. El fundamento y las alternativas evaluadas
  están en D-4 del design; el resumen es que descartar o diferir una entrega exigiría un barrido de
  recuperación periódico que hoy **no existe** —`recover_pending_notifications` corre una sola vez, en
  el arranque—, de modo que "diferir" significaría en los hechos "entregar en el próximo reinicio":
  una degradación silenciosa de la semántica al-menos-una-vez. La creación de la fila `Alert` queda
  **fuera** del semáforo: es el registro durable y nunca se estrangula.

  El costo residual —la cola de espera del semáforo no tiene cota— se declara, se acota
  aritméticamente contra el rate limit de ingesta (D-4 del design) y se hace **observable** con un
  umbral de advertencia disparado por flanco.

- **Presupuesto de conexiones recalculado.** El validador de `config.py:176-184` contabiliza **un**
  executor. Con dos, la desigualdad cambia y se vuelve a escribir de forma explícita:

  ```
  db_executor_max_workers + db_notify_executor_max_workers
      ≤ db_pool_size + db_max_overflow − _DB_CONNECTIONS_RESERVED_NON_EXECUTOR
  ```

  Con los defaults propuestos: `10 + 8 ≤ 10 + 18 − 10 = 18`. ✔ El pool crece de 20 a 28 conexiones
  (`db_max_overflow` pasa de 10 a 18); la reserva no-executor y el tamaño del carril de ingesta **no
  se tocan**. 28 conexiones entran holgadas en el `max_connections=100` por defecto de
  `postgres:18.3` (`docker-compose.yml:46`, sin override), para un backend single-instance (RN-76).
  El arranque sigue abortando con `ValidationError` si la desigualdad se viola: mismo criterio
  fail-fast de D75/RN-169.

- **Todos los invariantes vigentes se preservan, y se verifican explícitamente.** En particular:
  `notification_id` estable a lo largo de toda la escalera de reintentos (D40/RN-134, D41/RN-135),
  que se sostiene únicamente porque `_build_payload` se invoca **una sola vez**, dentro de
  `_prepare_notification` y **fuera** del bucle; la semántica de entrega al-menos-una-vez; la cascada
  de canales n8n → SMTP → webhook_fallback → log_only y sus `RETRY_DELAYS = [5, 30, 120]`; el
  despacho secuencial del lote y los ítems 40 y 41 del protocolo (D75/RN-169); el `expunge` de los
  objetos ORM que cruzan el límite del executor; y el orden `_flush_commands()` antes de
  `_drain_queue()` (`agent/publisher.py:151-158`), que se conserva por no tocarse: esta change es
  **sólo de backend**.

- **Sin migración a `AsyncSession`.** D75 lo excluye y RN-76 sigue vigente. No se reabre.

- **Sin cambios de contrato.** Ni el payload canónico de notificación (D40/RN-134), ni el contrato
  del stream `events`, ni el esquema de base de datos, ni el default de producción del rate limit
  (D38/RN-132).

- **Re-medición obligatoria.** Esta change **invalida el candidato congelado `v2.0-tesis`**: las
  mediciones de notificación y de resiliencia del paquete `v2-eval-20260922T175053Z` dejan de
  describir el binario. Se re-corre el arnés unificado `~/fim-lab/corrida_unificada.sh` y se emite un
  tag nuevo. **No se declara mejora anticipada**: primero se implementa, después se mide, y el número
  medido se registra sea cual sea.

### Fuera de alcance — dirección declarada, no omisión

**Stream de Valkey separado y proceso consumer separado para notificaciones.** Es aislamiento a
nivel de **proceso**, y resuelve el problema de forma más completa: un backlog de notificaciones no
podría tocar ni el event loop ni el pool de conexiones del proceso de ingesta, y cada lado escalaría
por separado. Queda **explícitamente fuera de esta change** porque es otra magnitud de cambio —stream
nuevo, consumer group nuevo, unidad de despliegue nueva, protocolo de reintento y de DLQ propio,
y una revisión de RN-76— y porque el aislamiento de recursos dentro del proceso es la corrección
mínima que la evidencia justifica hoy. Se deja **nombrada acá para que la decisión quede en el
registro**, no como una omisión.

Con la misma condición queda fuera el **barrido periódico de notificaciones pendientes**, del que
depende cualquier política de desborde que quiera descartar o diferir en vez de esperar (D-4 del
design).

## Capabilities

### New Capabilities

- _Ninguna._ Esta change no introduce capabilities: modifica dos que ya existen.

### Modified Capabilities

- `backend-async-consumer`: el requisito **"Dimensionamiento conjunto y explícito del pool de
  conexiones y del executor"** (`openspec/specs/backend-async-consumer/spec.md:126`) describe hoy
  **un** executor —"El backend SHALL instalar un executor de hilos propio […] de modo que todo
  `run_in_executor(None, ...)` del proceso tire de un único presupuesto"—. Ese enunciado es
  precisamente el que produce el acoplamiento. Se amplía a **dos** executors con presupuestos
  separados y una desigualdad que los suma, se fija que el carril de ingesta conserva el executor por
  defecto en exclusiva, y se conserva sin cambio el criterio fail-fast y la reserva como constante no
  configurable.

- `backend-notifications`: el requisito **"Notificación asincrónica post-ingesta de eventos críticos
  o altos"** (`openspec/specs/backend-notifications/spec.md:6`) garantiza hoy que ninguna `Session`
  del camino por evento corre sobre el event loop, pero no dice nada sobre **de qué pool** sale el
  hilo ni sobre cuántas notificaciones pueden estar en vuelo. Con un único executor compartido, esa
  garantía se cumple al pie de la letra mientras el carril de ingesta espera detrás de la cola de
  notificaciones. Se amplía para exigir aislamiento de recursos respecto del carril de ingesta y
  concurrencia acotada con desborde declarado, preservando explícitamente la estabilidad de
  `notification_id`, la cascada de canales y la semántica al-menos-una-vez.

## Impact

**Backend — configuración y arranque**:
- `backend/app/core/config.py:162-164` — campo nuevo `db_notify_executor_max_workers`; default de
  `db_max_overflow` de 10 a 18; el `model_validator` de `:167-186` pasa a validar la suma de los dos
  executors. La constante `_DB_CONNECTIONS_RESERVED_NON_EXECUTOR = 10` (`:33`) **no cambia** y sigue
  siendo constante, no knob.
- `backend/app/main.py:104-118` — construcción del segundo executor y su cierre ordenado en el
  shutdown; `set_default_executor(db_executor)` se conserva tal cual para el carril de ingesta.
- Módulo nuevo para los handles de executors, de modo que `alerts/service.py` no importe `main.py`.
- Template de entorno del backend — documentación de las variables nuevas y del default cambiado.

**Backend — notificaciones** (`backend/app/modules/alerts/service.py`):
- `:144`, `:304`, `:327`, `:338`, `:344`, `:357` — los seis `run_in_executor` del camino por evento
  dejan de pasar `None` y referencian el executor de notificaciones.
- `notify_event` (`:277`) — semáforo de entregas concurrentes alrededor del cuerpo, **después** de la
  guarda `alert.id is None` y **sin** mover `_prepare_notification` ni tocar el bucle de reintentos.
- `recover_pending_notifications` — su `asyncio.gather` sobre todas las pendientes queda acotado por
  el mismo semáforo, sin cambiar su lógica de selección ni su manejo de eventos huérfanos.
- `_build_payload` (`:169`), `_prepare_notification` (`:212`), `_mark_delivered` (`:361`),
  `_record_retry_attempt` (`:242`), `_record_all_attempts_failed` (`:262`), `_try_fallbacks` (`:388`)
  — **firmas y cuerpos sin cambios**. Sólo cambian call sites, igual criterio que D21 y D75.

**Backend — tests**: aislamiento efectivo de los pools, cota de concurrencia y su desborde,
estabilidad de `notification_id` a lo largo de la escalera, invariante de dimensionamiento, y no
regresión de FIFO ni de duplicados.

**Medición**: re-corrida completa de `~/fim-lab/corrida_unificada.sh` y tag nuevo; el paquete
`v2-eval-20260922T175053Z` queda como línea de base de comparación.

**Sin impacto**: `agent/`, `frontend/`, esquema de base de datos, contrato del stream `events`,
contrato de notificación (D40/RN-134), cascada de canales, `RETRY_DELAYS`, default de producción del
rate limit (D38/RN-132), despacho secuencial del consumer.

Reglas cubiertas: **RN-170** (nueva, la que gobierna), **RN-169** (ampliada), **RN-76**
(single-instance, sin escalado horizontal), **RN-134** y **RN-135** (contrato y deduplicación de
notificación, ratificadas sin cambio), **RN-86** y **RN-102** (lifecycle de `alerts`, ratificadas sin
cambio), **RN-71** (léxico snake_case). Decisiones aplicadas: **D76/RN-170**; **D75/RN-169**
(ampliada); **D21** (no reabierta); **D40/RN-134** y **D41/RN-135** (preservadas); **D38/RN-132** (no
modificada).

**Dependencias del DAG** (CHANGES.md, Change 59): change 58 `ingest-offload-blocking-db` —archivada
en `openspec/changes/archive/2026-09-19-ingest-offload-blocking-db/` ✔—, dueña de D75/RN-169, del
executor único y del validador de dimensionamiento que esta change modifica. Change 51
`agent-attribution-and-detection-gap`, de donde sale el instrumental de medición que produjo el
paquete `v2-eval-20260922T175053Z` ✔.
