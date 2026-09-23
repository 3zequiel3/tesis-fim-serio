## MODIFIED Requirements

### Requirement: Notificación asincrónica post-ingesta de eventos críticos o altos

El sistema SHALL disparar una notificación asincrónica no bloqueante (`asyncio.create_task`) tras
persistir exitosamente un evento en DB. La notificación MUST evaluarse solo para eventos con
`status != superseded` (RN-22). La severidad SHALL determinarse buscando en la tabla `rules` las
reglas cuyo `pattern` (glob) matchee el `event.path` usando `fnmatch.fnmatch`; si hay matches, se usa
la severidad más alta; si no hay matches, se usa `low`. La notificación solo se envía si la severidad
resultante es `critical` o `high` (RN-52).

"No bloqueante" SHALL entenderse en sentido estricto: ninguna operación síncrona a PostgreSQL del
camino de notificación **por evento** MUST ejecutarse sobre el event loop (D75/RN-169, que extiende
D21 a todo camino que abra una `Session` síncrona dentro de una corrutina). Esto alcanza tanto a la
`Session` con la que se crea la fila `Alert` como a las `Session` del camino de entrega y de la
marca de entregado. Todas ellas MUST ejecutarse via `run_in_executor`; las funciones síncronas NO
deben convertirse en async — solo cambia el call site.

**No bloquear el event loop no alcanza: el carril de notificación MUST estar aislado en recursos del
carril de ingesta** (D76/RN-170). Ejecutar fuera del loop pero sobre el **mismo** pool de hilos
mantiene el acoplamiento por otra vía: la cola del executor es FIFO y sin cota del lado del `submit`,
de modo que el trabajo de base de datos de la ingesta espera detrás del backlog de notificaciones. En
consecuencia:

- Las operaciones de base de datos del camino de notificación por evento MUST ejecutarse en un
  **executor dedicado al carril de notificación**, referenciado **explícitamente** por sus call sites.
  Pasar `None` MUST considerarse un defecto, porque designa el executor de ingesta.
- El carril de ingesta MUST conservar su executor en exclusiva. Esta obligación NO SHALL satisfacerse
  reduciendo la capacidad del carril de ingesta.
- El dimensionamiento conjunto de los dos executors contra el pool de conexiones se rige por el
  requisito de dimensionamiento de `backend-async-consumer`.

**La concurrencia del carril de notificación MUST estar acotada, con un comportamiento de desborde
declarado** (D76/RN-170). El número de **entregas** concurrentes SHALL estar limitado por una cota
configurable. Esa cota MUST aplicarse a **todas** las puertas de entrada del camino de entrega —el
consumer de eventos, la recuperación de notificaciones pendientes del arranque y el reintento manual
desde la DLQ—, de modo que ninguna pueda saltearla.

Al alcanzarse la cota, la entrega SHALL **esperar su turno en orden de llegada**. El sistema MUST NOT
descartar la notificación, MUST NOT rechazarla y MUST NOT diferirla a un barrido posterior: la
semántica de entrega al-menos-una-vez no se degrada para resolver un problema de latencia. La
cantidad de entregas en espera SHALL ser observable, y el cruce de un umbral declarado SHALL emitir
una advertencia **disparada por flanco**, nunca una por notificación.

**La creación de la fila `Alert` MUST quedar fuera de esa cota.** Es el registro durable del que
dependen la DLQ, el stream SSE y la recuperación; estrangularlo convertiría un problema de latencia
de entrega en pérdida de visibilidad.

La cota de entregas concurrentes y el número de hilos del executor de notificación SHALL ser
parámetros **distintos**, dimensionados por separado: el executor acota el paralelismo de base de
datos del carril, mientras que las entregas pasan la mayor parte de su vida esperando en la red o
entre reintentos, sin ocupar hilo ni conexión.

**El instante en que un canal aceptó la notificación MUST quedar registrado de forma durable, y MUST
ser distinto de la marca de entregado** (D77/RN-171). La marca de entregado existente se escribe
dentro del hilo del executor, es decir después del retorno del envío, después del despacho al
executor —que bajo la cota de entregas puede esperar— y después del `commit`; por construcción
**no** marca la aceptación del canal, y el intervalo que produce es estrictamente mayor que el que el
protocolo de medición define. En consecuencia:

- La fila `Alert` SHALL tener una columna de timestamp **anulable** que registre el instante en que
  un canal aceptó la notificación.
- Ese instante SHALL capturarse en la corrutina de entrega, **inmediatamente después** de que la
  operación de envío devolvió éxito, y **antes** de despachar cualquier trabajo al executor. Esto
  aplica por igual al canal primario y a cada canal de la cascada de fallbacks.
- El valor capturado SHALL persistirse **en el mismo `commit`** que escribe la marca de entregado. El
  sistema MUST NOT abrir una transacción adicional ni un despacho adicional al executor para
  escribirlo.
- La marca SHALL escribirse **únicamente cuando un canal aceptó**. Si toda la cascada falla, la
  columna MUST permanecer en `NULL`.
- La columna MUST NOT tener backfill sobre filas anteriores a su creación: una alerta entregada antes
  de que la marca existiera MUST quedar en `NULL`. Derivarla de la marca de entregado produciría un
  valor que aparenta medir la aceptación del canal y mide otra cosa.
- La semántica de la marca de entregado MUST permanecer **exactamente** como está: se escribe dentro
  del executor, al persistir el éxito. Esta obligación **agrega** una marca; **no** redefine ninguna.
  Hay mediciones ya emitidas que dependen de ese significado.
- El estado derivado de la alerta (`delivered` / `failed` / `pending`) MUST seguir derivándose
  **solo** de la marca de entregado y de la marca de fallo. La marca de aceptación MUST NOT participar
  de esa derivación.
- La marca MUST NOT incorporarse al payload canónico de notificación (D40/RN-134) ni al modelo de
  respuesta de la API de alertas: es registro durable de medición, no superficie de producto.

**Invariantes que este aislamiento MUST preservar sin excepción:**

- `_build_payload` MUST invocarse **exactamente una vez por entrega**, fuera del bucle de reintentos.
  Es la única razón por la que `notification_id` es estable a lo largo de toda la escalera, y esa
  estabilidad es la única razón por la que sirve como clave de deduplicación (D40/RN-134, D41/RN-135).
  El permiso de la cota SHALL adquirirse **una sola vez, antes** de la preparación del payload, y
  sostenerse hasta que la entrega termina: adquirirlo después dejaría la preparación fuera de la
  cota, y readquirirlo por vuelta del bucle produciría un `notification_id` por intento.
- La cascada de canales n8n → SMTP → webhook_fallback → log_only, sus umbrales, sus contadores y sus
  delays de reintento MUST conservar exactamente su comportamiento.
- El payload publicado al broadcaster SSE y el orden de las operaciones —crear fila, loguear la
  creación, publicar al broadcaster, intentar la entrega— MUST permanecer idénticos.
- Los objetos ORM que crucen el límite de cualquiera de los dos executors MUST estar desligados con
  sus atributos ya materializados; ninguna `Session` SHALL compartirse entre hilos ni cruzar ese
  límite.
- El registro del instante de aceptación MUST NOT alterar la estructura de la corrutina de entrega: ni
  el bucle de reintentos, ni la cascada, ni los delays, ni el punto en que se adquiere el permiso de
  la cota.

Las `Session` de los caminos que NO corren por evento quedan fuera de la obligación de ejecutar en el
executor de notificación: su costo no participa del carril de ingesta.

#### Scenario: Evento critical o high dispara notificación
- **WHEN** se ingiere un evento cuyo path matchea una regla con `severity=critical`
- **THEN** se crea una fila en `alerts` con `severity=critical` y se intenta el envío al canal primario

#### Scenario: Evento con severidad low o medium no notifica
- **WHEN** se ingiere un evento cuyo path matchea solo reglas con `severity=low` o `severity=medium`
- **THEN** no se crea ninguna fila en `alerts`

#### Scenario: Evento sin regla matching no notifica
- **WHEN** se ingiere un evento cuyo path no matchea ninguna regla
- **THEN** no se crea ninguna fila en `alerts`

#### Scenario: Evento superseded no notifica
- **WHEN** se ingiere un evento que resulta en `status=superseded`
- **THEN** no se crea ninguna fila en `alerts`

#### Scenario: Notificación no bloquea el consumer
- **WHEN** el envío del webhook n8n tarda 5 segundos
- **THEN** el consumer procesa el siguiente evento de Valkey sin esperar al webhook

#### Scenario: La creación de la fila de alerta no bloquea el event loop
- **WHEN** la notificación crea la fila `alerts` correspondiente a un evento recién persistido
- **THEN** la sesión, el alta y el commit se ejecutan en un hilo del executor y no sobre el event loop
- **AND** el estado publicado al broadcaster SSE y el payload canónico de notificación no cambian

#### Scenario: La actualización del estado de entrega no bloquea el event loop
- **WHEN** la notificación registra el resultado de un intento de entrega sobre la fila `alerts`
  (entregada, con canal y contador de reintentos, o fallida con su último error)
- **THEN** la sesión y el commit correspondientes se ejecutan en un hilo del executor y no sobre el
  event loop
- **AND** la cascada de canales y la política de reintentos conservan exactamente su comportamiento
  previo

#### Scenario: El despacho del consumer avanza mientras una notificación previa está en curso
- **WHEN** el consumer despacha un evento mientras la cadena de notificación de un evento anterior
  está resolviendo su trabajo de base de datos
- **THEN** ninguna de las dos espera a que la otra libere el event loop

#### Scenario: El trabajo de notificación corre en el executor dedicado
- **WHEN** cualquiera de las operaciones de base de datos del camino de notificación por evento se
  ejecuta
- **THEN** corre en un hilo del executor de notificación
- **AND** ningún hilo del executor de ingesta queda ocupado por ella

#### Scenario: Una ráfaga de notificaciones no retrasa la ingesta del evento siguiente
- **WHEN** hay una cantidad de notificaciones en curso suficiente para saturar el executor de
  notificación
- **THEN** la operación de base de datos de la ingesta del evento siguiente no espera detrás de ese
  trabajo

#### Scenario: La cota de entregas concurrentes se respeta
- **WHEN** se dispara una cantidad de notificaciones mayor que la cota configurada
- **THEN** el número de entregas simultáneamente en curso nunca excede la cota

#### Scenario: Al alcanzarse la cota, la entrega espera y no se descarta
- **WHEN** una notificación llega con la cota completa
- **THEN** su entrega espera su turno y termina realizándose
- **AND** no se descarta, no se rechaza y no se marca como fallida por esa causa

#### Scenario: La creación de la fila de alerta no espera a la cota de entregas
- **WHEN** la cota de entregas está completa y llega un evento `critical` o `high`
- **THEN** su fila en `alerts` se crea y se publica al broadcaster SSE sin esperar un permiso de
  entrega

#### Scenario: La recuperación del arranque también queda acotada
- **WHEN** el backend arranca con más notificaciones pendientes que la cota configurada
- **THEN** las entregas se procesan respetando la cota en lugar de dispararse todas a la vez
- **AND** todas terminan entregándose o registrando su fallo, sin descartes

#### Scenario: El reintento manual desde la DLQ también queda acotado
- **WHEN** se solicita el reintento manual de una alerta con la cota completa
- **THEN** su entrega respeta la cota igual que las demás puertas de entrada

#### Scenario: El backlog de entregas en espera es observable
- **WHEN** la cantidad de entregas en espera cruza el umbral declarado
- **THEN** se emite una advertencia con el conteo, una sola vez por cruce y no una por notificación

#### Scenario: `notification_id` es estable a lo largo de toda la escalera de reintentos
- **WHEN** una entrega falla y recorre la escalera completa de reintentos y la cascada de canales
- **THEN** el payload construido se arma una sola vez y todos los intentos transportan el mismo
  `notification_id`

#### Scenario: La recuperación de notificaciones pendientes del arranque conserva su implementación
- **WHEN** el backend arranca y recupera las notificaciones pendientes
- **THEN** su lógica de selección de filas pendientes y su manejo de eventos huérfanos no cambian

#### Scenario: El canal primario acepta y la aceptación queda registrada
- **WHEN** el envío al canal primario devuelve éxito
- **THEN** la fila `alerts` queda con la marca de aceptación del canal con un instante no nulo
- **AND** ese instante es anterior o igual a la marca de entregado de la misma fila

#### Scenario: Un canal de la cascada de fallbacks acepta y la aceptación queda registrada
- **WHEN** el canal primario se agota y un canal de la cascada de fallbacks acepta la notificación
- **THEN** la fila `alerts` queda con la marca de aceptación del canal con un instante no nulo
- **AND** el canal registrado es el que aceptó

#### Scenario: La cascada completa falla y no se registra aceptación
- **WHEN** el canal primario se agota y todos los canales de la cascada fallan
- **THEN** la marca de aceptación del canal permanece en `NULL`
- **AND** la fila queda marcada como fallida, disponible en la DLQ

#### Scenario: La marca de aceptación no altera la marca de entregado
- **WHEN** una notificación se entrega exitosamente
- **THEN** la marca de entregado sigue escribiéndose al persistir el éxito, con la misma semántica que
  antes de existir la marca de aceptación
- **AND** el estado derivado de la alerta sigue calculándose solo a partir de la marca de entregado y
  la marca de fallo

#### Scenario: Registrar la aceptación no agrega transacciones al camino caliente
- **WHEN** una notificación se entrega exitosamente
- **THEN** la marca de aceptación y la marca de entregado se escriben en el mismo `commit`
- **AND** no se despacha ningún trabajo adicional al executor para escribirla

#### Scenario: Una alerta anterior a la columna no recibe un valor inventado
- **WHEN** existe una fila `alerts` entregada antes de que la marca de aceptación fuera introducida
- **THEN** su marca de aceptación es `NULL`
- **AND** no se deriva de la marca de entregado ni de ninguna otra columna

#### Scenario: La marca de aceptación no cambia el contrato de notificación ni el de la API
- **WHEN** se inspecciona el payload canónico enviado a un canal y la respuesta de la API de alertas
- **THEN** ninguno de los dos incluye la marca de aceptación del canal
