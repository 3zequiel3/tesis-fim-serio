## ADDED Requirements

### Requirement: Entrega FIFO estricta sin adelantamiento de eventos nuevos

El publisher del agente SHALL distinguir dos conjuntos disjuntos de eventos de la cola local (D79 /
RN-173):

- `_unsent`: eventos **nunca transmitidos** en este proceso, en orden FIFO de creación.
- `_pending`: eventos cuyo `XADD` al stream `events` tuvo éxito y que esperan `event_ack`.

Un evento SHALL pasar de `_unsent` a `_pending` únicamente cuando su `XADD` tiene éxito. Un `XADD`
que falla MUST dejar el evento en `_unsent`, en su misma posición; MUST NOT registrarlo en `_pending`.

Mientras `_unsent` no esté vacía, todo evento nuevo SHALL agregarse al final de `_unsent` y MUST NOT
transmitirse de inmediato. El vaciado de `_unsent` SHALL ser estrictamente FIFO desde la cabeza y
SHALL detenerse en el primer error de transmisión: la pasada se interrumpe y ningún evento posterior
al que falló se transmite en esa pasada. El reenvío de eventos de `_pending` cuyo `event_ack` venció
SHALL interrumpirse igual ante el primer error, y una pasada interrumpida MUST NOT continuar con el
vaciado de `_unsent`.

Todas las transmisiones de eventos —la publicación inmediata, el vaciado de `_unsent` y el reenvío
por vencimiento de `event_ack`— SHALL estar serializadas: en ningún instante MUST haber dos `XADD`
de eventos en curso a la vez; la serialización SHALL hacerse con un único lock sobre los `XADD`
(ampliación de RN-173, 2026-10-02).

Al arrancar, los eventos de la cola en disco SHALL incorporarse a `_unsent` en orden FIFO por
prefijo de timestamp **antes** de que cualquier evento nuevo se agregue, incluidos los eventos que
publica la rehidratación del journal. Mientras el flush de comandos pendientes no haya terminado,
ningún evento de ese backlog MUST transmitirse (RN-85), y un evento nuevo que llega con backlog
pendiente SHALL quedar detrás de él. Los eventos re-emitidos por `rehydrate` SHALL encolarse detrás
del backlog de disco y después del flush de comandos: el orden es el de detección, no el de reinicio
(ampliación de RN-173, 2026-10-02).

Mientras `_unsent` no esté vacía, el lazo de reintento SHALL realizar una pasada cada 0,5 s; sin
backlog, conserva el período de 5 s. El backpressure agente-wide (D37/RN-131) sigue vigente: mientras
el publisher está pausado no se emite ningún `XADD` y los eventos nuevos se agregan a `_unsent`.

Preserva RN-39.

#### Scenario: Un evento nuevo no se publica antes que el backlog sin transmitir

- **WHEN** `_unsent` contiene `e1` y `e2` sin transmitir y el detector publica un evento nuevo `e3`
- **THEN** `e3` se agrega al final de `_unsent` y no se emite ningún `XADD` para `e3` en esa llamada
- **AND** cuando la conexión se restablece, el stream `events` recibe `e1`, `e2` y `e3` en ese orden

#### Scenario: Valkey falla los primeros XADD y vuelve a mitad de la pasada

- **WHEN** `_unsent` contiene `e1…e10`, Valkey rechaza los primeros tres intentos de `XADD` y acepta todos los siguientes, y el lazo de reintento ejecuta pasadas hasta vaciar `_unsent`
- **THEN** cada pasada que encuentra un error se interrumpe en ese evento sin transmitir ninguno posterior
- **AND** la secuencia de eventos aceptados por el stream es exactamente `e1, e2, …, e10`, sin huecos ni inversiones

#### Scenario: Un error en el vaciado inicial detiene el drenaje

- **WHEN** la cola en disco contiene `e1`, `e2` y `e3`, y el `XADD` de `e2` falla durante el drenaje de arranque
- **THEN** `e1` queda en `_pending` y `e2` y `e3` permanecen en `_unsent`, en ese orden
- **AND** no se emite ningún `XADD` para `e3` antes de que `e2` haya sido aceptado

#### Scenario: El XADD fallido deja el evento sin transmitir, no esperando ACK

- **WHEN** `publish()` intenta el `XADD` de un evento y Valkey no responde
- **THEN** el evento queda en `_unsent` y no figura en `_pending`
- **AND** se reintenta en la siguiente pasada del lazo, sin esperar el vencimiento del `event_ack`

#### Scenario: La rehidratación no adelanta eventos al backlog de disco

- **WHEN** el agente arranca con `e1` y `e2` en la cola en disco y la rehidratación del journal publica `r1` antes de que el publisher termine el flush de comandos
- **THEN** `r1` queda en `_unsent` detrás de `e1` y `e2`
- **AND** no se emite ningún `XADD` antes de que termine el flush de comandos
- **AND** el stream `events` recibe `e1`, `e2` y `r1` en ese orden

#### Scenario: Dos publicaciones concurrentes no intercalan sus XADD

- **WHEN** dos corrutinas llaman a `publish()` casi a la vez con `_unsent` vacía y el `XADD` de la primera todavía no terminó
- **THEN** la segunda agrega su evento a `_unsent` sin emitir `XADD`
- **AND** el stream recibe primero el evento de la primera llamada y después el de la segunda

#### Scenario: Sondeo de 0,5 s con backlog

- **WHEN** `_unsent` no está vacía y Valkey vuelve a estar disponible
- **THEN** la siguiente pasada del lazo de reintento ocurre a lo sumo 0,5 s después de la anterior

### Requirement: Purga de `_unsent` en cada salida de la cola local

Un evento SHALL retirarse de `_unsent` y de `_pending` en la misma operación en cada una de las
salidas de la cola local (D79 / RN-173 y su ampliación del 2026-10-02, que agrega el `event_nack`
terminal):

- al recibir su `event_ack` verificado;
- al ser desalojado por capacidad (drop-oldest, RN-84), mediante `_forget_evicted_event`;
- al ser descartado: por `max_attempts_exceeded` (D37/RN-131) o por un `event_nack` terminal.

Un evento retirado MUST NOT volver a transmitirse. La purga SHALL ser idempotente: retirar un
`event_id` ausente de alguna de las dos estructuras no es un error.

#### Scenario: Un ACK de un evento todavía en `_unsent` lo retira

- **WHEN** `e1` está en `_unsent` —por ejemplo, porque su `XADD` levantó una excepción después de que Valkey lo aceptara, o porque fue transmitido en un arranque anterior— y llega un `event_ack` verificado para `e1`
- **THEN** `e1` sale de `_unsent` y de la cola en disco
- **AND** el vaciado posterior no emite ningún `XADD` para `e1`

#### Scenario: El desalojo por capacidad retira el evento de `_unsent`

- **WHEN** encolar un evento nuevo desaloja por capacidad un evento que todavía estaba en `_unsent`
- **THEN** el evento desalojado sale de `_unsent` y de `_pending`
- **AND** ningún `XADD` posterior lo transmite

#### Scenario: El descarte retira el evento de `_unsent`

- **WHEN** un evento se descarta por `max_attempts_exceeded` o por un `event_nack` terminal
- **THEN** el evento sale de `_unsent` y de `_pending`
- **AND** ningún `XADD` posterior lo transmite
