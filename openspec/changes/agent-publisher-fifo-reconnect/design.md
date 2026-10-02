## Context

`agent/publisher.py` (639 líneas) mantiene hoy una sola estructura en memoria para los eventos que
aún no recibieron `event_ack`: `_pending: dict[str, tuple[float, dict]]` (`:87`), indexada por
`event_id` y con el instante de la última transmisión. La misma estructura mezcla dos estados
distintos:

- eventos que **sí** llegaron al stream y esperan ACK;
- eventos cuyo `XADD` falló o se difirió y que **nunca** llegaron al stream.

Los tres caminos de transmisión tratan esa mezcla de forma independiente y sin coordinación:

| Camino | Ubicación | Comportamiento actual ante error / backlog |
|---|---|---|
| `publish()` | `:168-196` | Registra en `_pending` antes del `XADD` (`:183-186`). Consulta sólo `_is_paused()` (`:187`); con backlog sin transmitir hace `XADD` igual (`:192`). Si el `XADD` falla, `except Exception: pass` (`:194-195`). |
| `_drain_queue()` | `:321-345` | Recorre `iter_entries()` en FIFO; ante error registra `publisher.drain_error` (`:344-345`) y **continúa** con la entrada siguiente. |
| `_retry_loop()` | `:604-639` | Duerme 5 s (`:613`); recorre `_pending` y reenvía lo que superó `_ACK_TIMEOUT_S` = 60 s (`:62`, `:618`); ante error registra `publisher.retry_error` (`:639`) y **continúa**. |

Consecuencias medidas y derivadas:

1. **Inversión dentro de una pasada.** Con Valkey caído al inicio de la pasada y de vuelta a mitad
   de ella, los primeros eventos fallan, los siguientes se aceptan, y el stream recibe los nuevos
   antes que los viejos. Es la causa de las **359 entregas fuera de orden** de
   `v2-eval-20260923T215624Z`, resiliencia/run-03.
2. **Adelantamiento por evento nuevo.** Un evento detectado con backlog sin transmitir se publica
   antes que el backlog.
3. **Reintento tardío de lo nunca transmitido.** Un evento cuyo primer `XADD` falló queda en
   `_pending` con el instante de encolado y sólo se reintenta cuando vence el plazo de ACK (60 s),
   aunque nunca haya llegado al stream. Mientras tanto, eventos posteriores con `XADD` exitoso ya
   fueron entregados.
4. **Reconexión lenta.** El período de 5 s hace que la reconexión con backlog tome 3,5–6,8 s.
5. **Arranque.** `agent/__main__.py:379-381` ejecuta `decision_engine.rehydrate(publisher)` **antes**
   de `asyncio.gather(*coroutines)`, que es donde arranca `publisher.run()` (`:363`). Los eventos que
   la rehidratación publica (`agent/decision.py:194`) se transmiten antes de `_flush_commands()` y
   antes del drenaje de la cola en disco, lo que contradice RN-39 y el orden de arranque de
   `agent-reconnect-ordering` (flush de comandos → drenaje). Además, `detector.start()` corre en el
   mismo `gather` que `publisher.run()` (`:372-373`), así que el detector puede publicar mientras el
   flush de comandos todavía no terminó.

`agent/queue.py` no participa del defecto: `iter_entries()` (`:460-480`) ya devuelve los sobres en
orden FIFO por el prefijo `{detected_at_ms:016d}` del nombre (`:425`), y `enqueue()` invoca
`on_evict` sincrónicamente por cada desalojo (`:450-451`).

La decisión que gobierna esta change está cerrada en **D79/RN-173**
(`docs/reglas_de_negocio.md:2697-2705`, `docs/arquitectura_stack.md:2719`), incluida su
**ampliación del 2026-10-02** (`docs/reglas_de_negocio.md:2705`, commit `9e15858`): el `event_nack`
terminal también retira de `_unsent`, los eventos de `rehydrate` se encolan detrás del backlog de
disco y después del flush de comandos, y los `XADD` se serializan con un único lock. Preserva **RN-39**
(`docs/reglas_de_negocio.md:306-310`) y el contrato de **D37/RN-131** (backpressure, techo de
intentos, cuatro desenlaces).

## Goals / Non-Goals

**Goals:**

- Que el orden en que el stream `events` **acepta por primera vez** cada evento coincida con el orden
  de creación de los eventos (RN-39), también cuando Valkey falla y vuelve a mitad de una pasada.
- Que un evento nuevo nunca se transmita antes que un evento más viejo sin transmitir.
- Que lo nunca transmitido se reintente al ritmo del sondeo (0,5 s con backlog), no al del plazo de
  ACK (60 s).
- Que `_unsent` no retenga eventos que ya salieron de la cola local.
- Cero cambios en el payload, la firma, el formato de la cola en disco y el contrato
  `event_ack`/`event_nack`.

**Non-Goals:**

- **Orden de los reenvíos por vencimiento de ACK respecto de eventos más nuevos.** Un evento de
  `_pending` ya fue aceptado por el stream; su reenvío es una duplicación que el backend deduplica
  por `event_id`. RN-39 y RN-173 hablan del orden de entrega, que quedó fijado en la primera
  aceptación. Esta change no reordena reenvíos.
- **Orden de consumo en el backend.** El consumidor del backend procesa el stream en orden
  (`backend/app/modules/events/consumer.py`, ítem 40 de D75); no se toca.
- **Cambios en `agent/queue.py`**, en el techo de intentos, en la semántica de `attempts` ni en el
  backpressure.
- **Reconciliación offline al arrancar** (Change 62, D80/RN-174), que depende de esta change pero no
  forma parte de ella.
- **Re-medición.** La corrida sobre `v5.0-tesis` ocurre una sola vez, después de las Changes 61–69.

## Decisions

### D-1 — `_unsent` es un `OrderedDict` disjunto de `_pending`

`_unsent: collections.OrderedDict[str, dict[str, Any]]` (`event_id` → payload estable). Orden de
inserción = orden FIFO; `popitem(last=False)` / `next(iter(...))` dan la cabeza en O(1); `pop(eid,
None)` retira por `event_id` en O(1), que es lo que necesitan las cuatro purgas.

Los conjuntos son **disjuntos**: un evento está en `_unsent` o en `_pending`, nunca en ambos. La
transición `_unsent → _pending` ocurre sólo tras un `XADD` exitoso y registra el instante de la
transmisión, de modo que el plazo de ACK cuenta desde que el evento llegó al stream, no desde que se
encoló.

Invariante que esto produce y que el diseño usa: **todo evento de `_pending` fue creado antes que
todo evento de `_unsent`**. Se cumple porque `_unsent` se vacía estrictamente desde la cabeza, un
evento nuevo sólo se transmite directamente cuando `_unsent` está vacía, y las purgas sólo retiran.

*Alternativas descartadas.* (a) `collections.deque` de payloads: la purga por `event_id` sería O(n) y
el chequeo «¿ya está en `_unsent`?» del drenaje también. (b) Mantener `_pending` como único dict con
un flag `transmitted`: preserva la mezcla de estados que causó el defecto y obliga a todo recorrido
a filtrar; D79 pide explícitamente dos colas distintas.

### D-2 — Un único `asyncio.Lock` serializa todos los `XADD` de eventos

Exigido por la ampliación de RN-173 (`docs/reglas_de_negocio.md:2705`).

Se agrega `_send_lock = asyncio.Lock()`. Lo toman: el camino rápido de `publish()`, el vaciado de
`_unsent` y el reenvío por vencimiento de ACK. `_xadd_with_trace` (`:132-145`) no cambia; quien lo
llama ya tiene el lock.

Por qué hace falta aun con `_unsent` bien ordenada: hoy `publish()` es awaitable y lo invocan
corrutinas concurrentes (`agent/detector.py:898,998,1168`, `agent/detector.py:731`,
`agent/decision.py:194`). Sin exclusión, la corrutina A puede estar esperando su `XADD` mientras B ve
`_unsent` vacía y transmite el suyo; si el de A falla y el de B no, B quedó adelante.

`publish()` **no espera** el lock: si está tomado, agrega su evento a `_unsent` y retorna. En asyncio
de un solo hilo no hay ventana entre la condición «`_unsent` vacía» y la liberación del lock del
vaciador, porque no hay `await` entre ambas; el evento agregado lo encuentra el vaciador en su
próxima vuelta o el lazo en su próxima pasada.

*Alternativa descartada.* Que `publish()` espere el lock y vacíe todo `_unsent` inline: el detector
quedaría bloqueado en `await publish()` durante el drenaje de un backlog de miles de eventos.

### D-3 — Camino rápido de `publish()` acotado al evento propio

Secuencia de `publish()`:

1. `_ensure_backlog_seeded()` (D-5).
2. `enqueue` en disco (sin cambio, `:175-179`).
3. Agregar el payload al final de `_unsent`.
4. Transmitir de inmediato **sólo si** el evento propio es la cabeza y el único elemento de
   `_unsent`, no hay backpressure (`_is_paused()`), el gate de arranque está abierto (D-5) y el lock
   está libre. En ese caso, bajo el lock: `XADD`; si tiene éxito, mover a `_pending` y
   `bump_attempts` (como hoy, `:192-193`); si falla, el evento queda en la cabeza de `_unsent`.
5. En cualquier otro caso, o si el `XADD` falló, despertar al lazo (D-4).

Con Valkey sano y sin backlog la latencia y la cantidad de operaciones por evento son las de hoy.
El evento queda en `_unsent` desde el paso 3, así que una segunda corrutina concurrente siempre lo
encuentra y se encola detrás.

El log `publisher.event_published` (`:196`) se conserva con su nombre; se agrega el campo
`deferred=True|False` para que el log distinga lo transmitido de lo encolado detrás del backlog. La
traza experimental registra `xadd_deferred` con `reason="backlog"` cuando el evento queda detrás de
`_unsent` (hoy existe con `reason="backpressure"`, `:188`); `ExperimentTrace` sólo restringe nombres
de campo (`agent/experiment_trace.py:25`), no valores.

### D-4 — Lazo de reintento: sondeo 0,5 s con backlog, despertar explícito, pasada que corta

Constantes de módulo: `_BACKLOG_POLL_S = 0.5`, `_IDLE_POLL_S = 5.0` (D79).

Espera entre pasadas en un método propio, `_wait_for_next_pass(stop_event)`:

- si la pasada anterior terminó en error: dormir `_BACKLOG_POLL_S` sin atender despertares (evita
  martillar a Valkey con un intento por cada evento nuevo durante una caída);
- si no: esperar un `asyncio.Event` `_wake` con timeout `_BACKLOG_POLL_S` si hay backlog o
  `_IDLE_POLL_S` si no; limpiar `_wake` al despertar.

El método es además el punto de inyección de los tests: los tests que hoy detienen el lazo
parcheando `asyncio.sleep` del módulo (`agent/tests/test_publisher.py:192-195`,
`agent/tests/test_stream_ack_durability.py:519-532`) pasan a parchear `_wait_for_next_pass`.

Cuerpo de una pasada, bajo `_send_lock`:

1. Si hay backpressure: no transmitir nada (`:614-615`, sin cambio).
2. **Reenvío por vencimiento de ACK**, recorriendo `_pending` en orden de inserción, como hoy
   (`:617-636`), incluida la rama de descarte por `max_attempts_exceeded` que sigue siendo un
   `continue` (no es un error de transmisión). Ante el primer error de `XADD`: `break`, log
   `publisher.retry_error` (nombre conservado), la pasada termina y **no** se vacía `_unsent`.
3. **Vaciado de `_unsent` desde la cabeza.** Por cada cabeza: `XADD`; si tiene éxito, `popitem` de
   `_unsent`, alta en `_pending` con el instante actual, `bump_attempts`. Ante el primer error:
   `break`, log `publisher.unsent_drain_stopped` con `event_id` y `remaining`.

Por qué primero el reenvío: por la invariante de D-1, todo evento de `_pending` es más viejo que
todo evento de `_unsent`. Si un evento cuya primera aceptación se perdió en Valkey necesita
reenviarse, debe ir antes que los más nuevos.

Al reasignar `self._pending[event_id] = (now, payload)` tras un reenvío exitoso (`:636`) la clave
conserva su posición en el dict, así que el orden de recorrido sigue siendo el de primera
transmisión.

*Alternativa descartada.* Período fijo de 0,5 s siempre: recorrer `_pending` (potencialmente miles
de entradas) diez veces más seguido sin necesidad. D79 fija 0,5 s **mientras haya backlog**.

### D-5 — El backlog de disco se siembra en el primer uso y queda retenido hasta el flush

Exigido por la ampliación de RN-173 (`docs/reglas_de_negocio.md:2705`): el orden es el de detección,
no el de reinicio.

`_ensure_backlog_seeded()` es idempotente (flag `_backlog_seeded`). En su primera invocación recorre
`self._queue.iter_entries()` y agrega a `_unsent`, en ese orden FIFO, todo `event_id` que no esté ya
en `_unsent` ni en `_pending`. Si sembró al menos uno, cierra el gate `_hold_until_flush = True`.

Se invoca desde `publish()` (antes de agregar el evento propio) y desde `_drain_queue()`. Así, el
primer `publish()` del proceso —sea de la rehidratación, que corre antes de `run()`, o del
detector— encuentra el backlog de disco por delante. No se siembra en `__init__` para no leer y
descifrar la cola entera en cada construcción del publisher en los tests.

`_drain_queue()` pasa a ser: sembrar, **abrir el gate** (`_hold_until_flush = False`) y ejecutar una
pasada de vaciado de `_unsent` bajo el lock (D-4 paso 3), respetando backpressure. `run()` sigue
llamándolo después de `_flush_commands()` (`:151-158`), así que nada del backlog sale antes del flush
(RN-85). Los eventos sembrados que ya habían sido transmitidos en un arranque anterior (`attempts >
0`) se tratan como no transmitidos en este proceso: se reenvían en orden, como hoy hace el drenaje.

Sin backlog en disco el gate nunca se cierra y `publish()` conserva el camino rápido antes de
`run()`, como hoy. Esto acota el cambio observable al caso que D79 regula.

*Alternativas descartadas.* (a) Mover la rehidratación después del flush en `agent/__main__.py`:
toca el orquestador del arranque y la secuencia de RN-83, y no resuelve el detector publicando
durante el flush. (b) Sembrar sólo en `_drain_queue`: la rehidratación adelanta al backlog de disco,
que es la violación que D79 prohíbe.

### D-6 — Purga uniforme en ambas estructuras

Se agrega `_retire(event_id)`, que hace `_unsent.pop(event_id, None)` y `_pending.pop(event_id,
None)`. La usan las cuatro salidas de la cola local:

| Salida | Ubicación actual |
|---|---|
| `event_ack` verificado | `:503-509` (hoy `self._pending.pop`, `:505`) |
| Desalojo por capacidad | `_forget_evicted_event`, `:198-202` (hoy `:201`) |
| `max_attempts_exceeded` | `_retry_loop`, `:621-631` (hoy `:623`) |
| `event_nack` terminal | `:537-546` (hoy `:540`) |

La ampliación de RN-173 (`docs/reglas_de_negocio.md:2705`) incorpora el `event_nack` terminal a la
lista de D79 «como cualquier descarte». Sin esa purga, un evento con `event_nack` terminal que
siguiera en `_unsent` se reenviaría con su archivo ya descartado.

¿Puede un evento de `_unsent` recibir ACK o NACK? Sí, en dos casos reales: un `XADD` que levanta
excepción del lado del cliente después de que Valkey lo aceptó, y un evento sembrado desde disco que
un proceso anterior ya había transmitido.

El techo de intentos sigue evaluándose sólo en el reenvío de `_pending`: `attempts` se incrementa
sólo con `XADD` exitoso (`bump_attempts`, `:193`, `:342`, `:635`), de modo que lo que nunca llegó
al stream no consume intentos, igual que hoy.

### D-7 — Interacción con backpressure

Con backpressure activo, `publish()` encola y agrega a `_unsent` sin transmitir (hoy agregaba a
`_pending` sin transmitir, `:187-189`). Al vencer la pausa, la siguiente pasada vacía `_unsent` en
FIFO. Mientras dure la pausa con backlog el lazo despierta cada 0,5 s y no transmite. No cambia
ninguna regla de D37/RN-131: no hay `XADD` durante la pausa, el intento no se cuenta, nada se
descarta.

### D-8 — Tests: verificación del orden de primera aceptación con un cliente falso

El archivo nuevo `agent/tests/test_publisher_fifo.py` usa un cliente falso cuyo `xadd` sigue un guion
de éxitos y fallos y registra el `event_id` de cada `XADD` **aceptado**. La aserción de orden es
sobre la secuencia aceptada, no sobre las llamadas: las llamadas fallidas repetidas de la cabeza son
esperables y correctas. Los tests son `async` con `@pytest.mark.asyncio` explícito porque
`agent/pyproject.toml:20` fija `asyncio_mode = "strict"`.

## Risks / Trade-offs

- **[Riesgo] Cabeza envenenada: un evento cuyo `XADD` falla siempre por una causa del propio evento
  bloquea todo el backlog.** → El `XADD` sólo falla por transporte (conexión, timeout, `OOM` de
  Valkey); el payload ya se serializó y se firmó en `_stamp_and_sign` antes del `XADD` (`:313-317`),
  y un error de serialización ocurriría antes. La validación de contenido es del backend y vuelve
  como `event_nack`, que purga (D-6). Se registra `publisher.unsent_drain_stopped` con `event_id` en
  cada corte para que una cabeza atascada sea visible. Si apareciera una causa por evento, la
  respuesta es otra decisión, no un `continue`.
- **[Riesgo] Latencia de eventos nuevos con backlog.** Con backlog, un evento recién detectado espera
  a todo el backlog. → Es exactamente lo que RN-39 y D79 exigen; el despertar explícito (D-4) evita
  sumar el período de sondeo.
- **[Riesgo] Más trabajo por segundo durante una caída.** El lazo intenta un `XADD` cada 0,5 s en vez
  de cada 5 s. → Es un solo intento por pasada (corta en el primer error) contra hasta N intentos por
  pasada de hoy; el saldo neto es menor.
- **[Riesgo] Tests existentes acoplados a `_pending` y a `asyncio.sleep`.** → Inventariados en
  `tasks.md` §4 con el motivo de cada cambio de aserción; ninguno pierde cobertura de su intención
  original.
- **[Trade-off] El reenvío por vencimiento de ACK que falla bloquea el vaciado de `_unsent` en esa
  pasada.** → Necesario por la invariante de D-1: si el reenvío de un evento más viejo no pudo salir,
  transmitir uno más nuevo lo adelantaría.
- **[Trade-off] Duplicados.** Un `XADD` que Valkey aceptó pero cuyo cliente levantó excepción se
  reenvía. → Ya ocurre hoy; el backend deduplica por `event_id` (RN-40).

## Migration Plan

Sin migración de datos: la cola en disco, su formato y su cifrado no cambian, y `_unsent` vive sólo en
memoria. Un agente actualizado con eventos en cola los siembra en `_unsent` al arrancar y los drena
tras el flush de comandos. Rollback: revertir `agent/publisher.py` y los tests; no queda estado que
limpiar.

Antes y después de `openspec archive`, `python3 scripts/check_spec_integrity.py` (D47/RN-141).

## Open Questions

Ninguna. Las dos cuestiones abiertas en la primera versión de este diseño —purga en `event_nack`
terminal (D-6) y retención de los eventos de `rehydrate` detrás del backlog hasta el flush (D-5)— se
cerraron en la ampliación de D79/RN-173 del 2026-10-02 (`docs/reglas_de_negocio.md:2705`,
`docs/arquitectura_stack.md:2719`, commit `9e15858`).
