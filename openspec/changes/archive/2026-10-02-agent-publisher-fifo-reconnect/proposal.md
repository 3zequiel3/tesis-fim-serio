## Why

El publisher del agente no preserva el orden FIFO al reconectar, y la entrega fuera de orden ya se
midió: **359 entregas fuera de orden** en `v2-eval-20260923T215624Z`, resiliencia/run-03. RN-39
exige que, al restablecerse la conexión con Valkey, los eventos se envíen en el orden en que fueron
creados; el código actual tiene tres caminos que lo violan y un intervalo de sondeo que estira la
reconexión.

- **`_retry_loop` saltea el evento que falló.** `agent/publisher.py:637-639` atrapa la excepción del
  `XADD`, registra `publisher.retry_error` y **continúa con el evento siguiente** del mismo recorrido
  de `_pending`. Si Valkey vuelve a mitad de la pasada, el evento `k` queda sin transmitir y los
  eventos `k+1…n` —más nuevos— llegan antes.
- **`publish()` adelanta eventos nuevos al backlog.** `agent/publisher.py:168-196` sólo consulta
  `_is_paused()` (`:187`) antes de hacer `XADD` (`:192`): con eventos todavía sin transmitir, un
  evento recién detectado se publica de inmediato y los sobrepasa. Además, un `XADD` fallido deja el
  evento en `_pending` con el instante de encolado (`:183-186`), de modo que recién vuelve a
  intentarse cuando vence `_ACK_TIMEOUT_S` (60 s, `:62`, chequeo en `:618`), aunque nunca haya llegado
  al stream.
- **`_drain_queue` también continúa tras un error.** `agent/publisher.py:321-345` registra
  `publisher.drain_error` en el `except` de `:344` y sigue con la entrada siguiente de la cola en
  disco.
- **La pasada de reintento duerme 5 s.** `agent/publisher.py:613` fija el período del lazo; con
  backlog, la reconexión del agente toma entre 3,5 y 6,8 s.

La decisión que gobierna esta change ya está cerrada: **D79/RN-173**
(`docs/reglas_de_negocio.md:2697`, `docs/arquitectura_stack.md:2719`), con su ampliación del
2026-10-02 (`docs/reglas_de_negocio.md:2705`): `event_nack` terminal como salida de `_unsent`, eventos
de `rehydrate` detrás del backlog y del flush, y lock único sobre los `XADD`. Preserva **RN-39**
(`docs/reglas_de_negocio.md:306`). Change 61 no tiene dependencias en el DAG de `CHANGES.md`.

Esta change **invalida el candidato congelado `v4.0-tesis`**. La re-medición se hace una sola vez,
sobre `v5.0-tesis`, después de las Changes 61–69; esa re-medición satisface además la tarea 12.4,
aún abierta en la Change 51 `agent-attribution-and-detection-gap`.

## What Changes

- **Dos estructuras distintas en el publisher (D79/RN-173).** `_unsent` —eventos nunca
  transmitidos, en orden FIFO de creación— se separa de `_pending` —eventos transmitidos que esperan
  `event_ack`—. Un evento pasa de `_unsent` a `_pending` sólo cuando su `XADD` tuvo éxito. Un `XADD`
  fallido deja el evento en `_unsent`, no en `_pending`.
- **Sin adelantamiento.** Mientras `_unsent` no esté vacía, `publish()` agrega el evento nuevo al
  final de `_unsent` y **no** hace `XADD`. Sólo cuando `_unsent` está vacía, no hay backpressure y no
  hay otra transmisión en curso, `publish()` transmite el evento propio de inmediato (camino rápido,
  sin cambio de latencia en operación normal).
- **Vaciado estrictamente FIFO que se detiene en el primer error.** El vaciado de `_unsent` transmite
  desde la cabeza y, ante el primer error de `XADD`, **interrumpe la pasada** (`break`). `_retry_loop`
  y `_drain_queue` reemplazan su `continue` tras error por `break`.
- **Una sola transmisión a la vez.** Todo `XADD` de eventos —camino rápido de `publish()`, vaciado
  de `_unsent` y reenvío por vencimiento de ACK— se serializa con un único `asyncio.Lock`. Sin esa
  exclusión, dos corrutinas podían intercalar sus `XADD` y reordenar la entrega aun con `_unsent`
  correctamente ordenada.
- **Sondeo de 0,5 s mientras haya backlog.** El lazo de reintento pasa a esperar 0,5 s con `_unsent`
  no vacía y conserva los 5 s sin backlog; un evento que queda en `_unsent` despierta el lazo sin
  esperar el período completo.
- **El backlog de disco al arrancar es backlog.** La cola persistida se siembra en `_unsent` en orden
  FIFO antes del primer evento nuevo —incluidos los que publica la rehidratación del journal
  (`agent/__main__.py:380`, `agent/decision.py:194`), que hoy corre **antes** de `publisher.run()`—,
  y nada de ese backlog se transmite hasta que termine el flush de comandos (RN-85, requisito vigente
  de `agent-reconnect-ordering`).
- **Purga de `_unsent`.** Un evento sale de `_unsent` al recibir su `event_ack`, al ser desalojado
  por capacidad (`_forget_evicted_event`, `agent/publisher.py:198-202`) y al ser descartado
  (`max_attempts_exceeded`, `agent/publisher.py:621-631`, y `event_nack` terminal,
  `agent/publisher.py:537-546`). La purga es la misma operación que hoy retira el evento de
  `_pending`, aplicada a ambas estructuras.

No hay cambios **BREAKING** de contrato externo: el payload, la firma, el stream `events`, el
contrato `event_ack`/`event_nack` y el formato de la cola en disco no cambian. El cambio es de orden
y de temporización de la transmisión.

## Capabilities

### New Capabilities

Ninguna. RN-173 refina el orden de entrega que ya regula `agent-reconnect-ordering`.

### Modified Capabilities

- `agent-reconnect-ordering`: se agregan los requisitos de entrega FIFO estricta sin adelantamiento
  (separación `_unsent`/`_pending`, interrupción de la pasada en el primer error, serialización de
  las transmisiones, siembra del backlog de disco antes del primer evento nuevo, sondeo de 0,5 s) y
  de purga de `_unsent` en cada salida de la cola local.

## Impact

**Agente** — `agent/publisher.py` (`__init__`, `publish`, `_forget_evicted_event`, `_drain_queue`,
`_handle_command_async` en las ramas `event_ack` y `event_nack` terminal, `_retry_loop`).
`agent/queue.py` **no** cambia: `iter_entries()` (`agent/queue.py:460-480`) ya entrega los sobres en
orden FIFO por prefijo de timestamp. `agent/__main__.py` y `agent/decision.py` **no** cambian: la
siembra del backlog ocurre dentro del publisher, en el primer uso.

**Tests** — cambian de contrato, por D79, tres aserciones existentes:
`agent/tests/test_resilience_fixes.py:216-245` (`test_xadd_failure_keeps_event_in_pending`: el
evento con `XADD` fallido pasa a estar en `_unsent`, no en `_pending`),
`agent/tests/test_stream_ack_durability.py:482-492` (`test_drain_and_xadd_suppressed_while_paused`:
la entrada sembrada en pausa queda en `_unsent`) y los dos tests que detienen `_retry_loop`
parcheando `asyncio.sleep` (`agent/tests/test_publisher.py:192-196`,
`agent/tests/test_stream_ack_durability.py:519-532`), que pasan a parchear el punto de espera
dedicado. Se agrega `agent/tests/test_publisher_fifo.py`.

**Resultados de la tesis** — las corridas sobre `v4.0-tesis` dejan de ser representativas del orden
de entrega; la re-medición única sobre `v5.0-tesis` es condición para reportar.

**Reglas y decisiones** — aplica D79/RN-173; preserva RN-39, RN-85 (orden comandos → eventos),
D37/RN-131 (backpressure agente-wide, techo de intentos, cuatro desenlaces) y RN-84 (drop-oldest).
