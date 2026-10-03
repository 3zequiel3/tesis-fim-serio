## ADDED Requirements

### Requirement: Los eventos validados de un lote se persisten en una única transacción

Dentro de `_process_batch`, el consumer SHALL persistir los eventos del lote que superan la
validación (schema, agente, firma HMAC, clock skew y `event_id` no vacío) en **una única
transacción de base de datos por lote**, ejecutada en una única salida al executor de ingesta y en
el orden en que las entradas aparecen en el stream (ampliación del 2026-10-03 de D87/RN-181). El
despacho de mensajes MUST seguir siendo secuencial (D75/RN-169) y MUST NOT existir concurrencia
entre eventos del lote. Dentro de esa transacción, el sistema SHALL conservar la semántica por
evento de la ingesta:

- **Dedup**: un `event_id` ya presente en la base, o ya visto antes en el mismo lote, SHALL
  resolverse como re-entrega, sin una segunda fila en `events` y sin consumir rate limit.
- **Rate limit**: la decisión SHALL tomarse por evento nuevo, después del dedup y en el orden del
  lote. Si la transacción del lote se revierte, los tokens que sus candidatos consumieron SHALL
  devolverse al balde de su agente, sin superar su capacidad.
- **Cadena `superseded`**: el `pending` vigente de cada ruta SHALL incluir los eventos insertados
  antes en el mismo lote, de modo que un evento posterior de la misma ruta lo supersede con el
  `UPDATE` optimista y la re-consulta ante carrera de D25/RN-121. La máquina de estados (RN-11,
  RN-12, RN-72) y la compactación por evento en la misma transacción (RN-98) MUST NOT cambiar.
- **Severidad**: las reglas SHALL leerse una vez por lote; una regla modificada durante un lote
  rige desde el lote siguiente.
- **Orden**: el orden de inserción en `events` SHALL reproducir el orden del stream.

Un `InvalidTransitionError`, un descarte por carrera de supersesión o una decisión `rate_limited`
de un candidato MUST NOT abortar la transacción del lote. Los efectos que dependen del resultado de
la ingesta —`event_ack` y `XACK`, el rechazo `rate_limited`, el `XACK` + auditoría + `event_nack`
de `InvalidTransitionError` y el agendado de la notificación del evento persistido— SHALL aplicarse
**después** de que el `COMMIT` del lote retorne con éxito, en el orden del stream. El agendado de
la notificación MUST omitirse para un evento del lote que la compactación del mismo lote eliminó
antes del `COMMIT`. Los rechazos de la validación SHALL conservar su `XACK` y su `event_nack`
inmediatos.

Si cualquier operación de la transacción del lote o su `COMMIT` lanza `SQLAlchemyError`, el sistema
SHALL revertir la transacción y ningún candidato del lote MUST recibir `XACK` ni respuesta: todos
MUST permanecer en la PEL, y el consumer MUST loguear el error con `exc_info=True`. Si el error es
`IntegrityError` o `DataError`, el sistema SHALL además re-ejecutar los candidatos del lote uno por
uno por el camino de ingesta por evento, de modo que sólo el evento que vuelve a fallar quede en la
PEL. Invocado fuera de un lote, `_handle_message` SHALL conservar el camino de ingesta por evento,
con su propia transacción.

#### Scenario: Un lote de eventos válidos se confirma con un único COMMIT
- **WHEN** `_process_batch` recibe un lote de N eventos válidos y nuevos de rutas distintas
- **THEN** los N eventos quedan persistidos mediante una sola transacción con un único `COMMIT`
- **AND** el orden de inserción en `events` reproduce el orden del stream

#### Scenario: Dos eventos de la misma ruta en un lote forman cadena
- **WHEN** un lote contiene dos eventos válidos consecutivos para la misma ruta, ambos con estado derivado `pending` y sin `pending` previo en la base
- **THEN** el primero queda `superseded` con su `version` incrementada en 1
- **AND** el segundo queda `pending` con `parent_event_id` igual al id del primero

#### Scenario: Un evento terminal del lote supersede al pending insertado antes en el mismo lote
- **WHEN** un lote contiene un evento `pending` para `/etc/hosts` seguido de un evento para `/etc/hosts` cuyo estado derivado es `alert_only`
- **THEN** el primero queda `superseded`
- **AND** el segundo queda `alert_only` con `parent_event_id` igual al id del primero

#### Scenario: Un event_id repetido dentro del lote se resuelve como re-entrega
- **WHEN** un lote contiene dos entradas con el mismo `event_id`
- **THEN** se persiste una sola fila en `events`
- **AND** ambas entradas reciben `XACK` y `event_ack` después del `COMMIT` del lote
- **AND** la segunda entrada no consume rate limit

#### Scenario: Un error transitorio deja todo el lote en la PEL
- **WHEN** un lote contiene los eventos válidos `e1`, `e2` y `e3`
- **AND** la transacción del lote lanza un `SQLAlchemyError` que no es `IntegrityError` ni `DataError`
- **THEN** ninguna fila de `e1`, `e2` ni `e3` queda en `events`
- **AND** ninguno recibe `XACK` ni respuesta en `commands`, y los tres permanecen en la PEL
- **AND** los tokens de rate limit que consumieron se devuelven al balde del agente
- **AND** una re-entrega posterior de los tres los persiste una sola vez cada uno

#### Scenario: Un evento envenenado no bloquea a sus vecinos
- **WHEN** la transacción de un lote con `e1`, `e2` y `e3` lanza `IntegrityError` por causa de `e2`
- **THEN** el sistema revierte la transacción y re-ejecuta `e1`, `e2` y `e3` uno por uno
- **AND** `e1` y `e3` quedan persistidos y reciben `XACK` y `event_ack`
- **AND** `e2` no recibe `XACK` ni respuesta y permanece en la PEL

#### Scenario: Los efectos de la ingesta esperan al COMMIT del lote
- **WHEN** un lote contiene un evento persistido, un evento `rate_limited` y un evento cuya ingesta lanza `InvalidTransitionError`
- **THEN** el `event_ack`, el `event_nack` de `rate_limited`, el `XACK` + auditoría + `event_nack` de la transición inválida y el agendado de la notificación ocurren después del retorno del `COMMIT` del lote
- **AND** se aplican en el orden del stream

#### Scenario: Un rechazo de validación sigue siendo inmediato dentro del lote
- **WHEN** un lote contiene una entrada con firma HMAC inválida antes de eventos válidos
- **THEN** esa entrada recibe su `XACK` inmediato, antes del `COMMIT` del lote
- **AND** no forma parte de la transacción del lote

#### Scenario: Fuera de un lote se conserva el camino por evento
- **WHEN** `_handle_message` se invoca directamente, sin un lote en curso
- **THEN** el evento se ingesta en su propia transacción y se confirma de inmediato, como antes de esta change

## MODIFIED Requirements

### Requirement: XACK y event_ack se emiten por lote y sólo después del commit de cada evento

Dentro de `_process_batch`, el consumer SHALL acumular la respuesta `event_ack` y el `XACK` de cada
evento que se resuelve con `event_ack` (ingesta persistida, re-entrega detectada en dedup —en la
base o dentro del mismo lote— y skip por carrera de supersesión) y SHALL emitirlos juntos, en un
único pipeline transaccional, al terminar el lote (D87/RN-181). Como los eventos del lote se
persisten en una única transacción (ampliación del 2026-10-03 de D87/RN-181), ninguna entrada MUST
agregarse al acumulado antes de que el `COMMIT` de esa transacción haya retornado con éxito. Si la
transacción del lote lanza `SQLAlchemyError`, ninguna entrada que dependa de ella MUST agregarse al
acumulado ni recibir `XACK`, y todas MUST permanecer en la PEL, tal como exige el requisito
«Protocolo ACK end-to-end con persistencia y dedup idempotente»; la re-ejecución evento por evento
ante `IntegrityError`/`DataError` sigue el requisito «Los eventos validados de un lote se persisten
en una única transacción». Los rechazos de validación (`_reject`) SHALL conservar su `XACK` y su
`event_nack` inmediatos; el rechazo `rate_limited` y el camino de `InvalidTransitionError` SHALL
emitir su `XACK` y su `event_nack` después del `COMMIT` del lote. El despacho de mensajes del lote
MUST seguir siendo secuencial (D75/RN-169). Si el acumulado no puede emitirse (por ejemplo, Valkey
se cae al final del lote), las entradas MUST quedar en la PEL, y ninguna re-entrega posterior
—desde la PEL o por republicación del agente— MUST producir una segunda fila en `events`. Invocado
fuera de un lote, `_handle_message` SHALL conservar la emisión inmediata de `XACK` y `event_ack`.

#### Scenario: Un lote de eventos válidos se confirma con un único pipeline
- **WHEN** `_process_batch` recibe un lote de N eventos válidos y nuevos
- **THEN** los N eventos quedan persistidos
- **AND** los N `event_ack` y los N `XACK` se emiten en un único pipeline al final del lote

#### Scenario: El acumulado nunca precede al commit
- **WHEN** se procesa un lote de eventos válidos
- **THEN** para cada evento, el instante en que su `XACK` se agrega al acumulado es posterior al retorno del `COMMIT` de la transacción del lote

#### Scenario: Un error transitorio de base de datos en el lote no confirma ninguno de sus eventos
- **WHEN** un lote contiene los eventos `e1`, `e2` y `e3`
- **AND** la transacción del lote lanza un `SQLAlchemyError` transitorio
- **THEN** ni `e1`, ni `e2`, ni `e3` reciben `XACK` ni respuesta
- **AND** los tres permanecen en la PEL

#### Scenario: Valkey falla al emitir el acumulado
- **WHEN** el pipeline del final del lote falla
- **THEN** los eventos del lote quedan persistidos y sus entradas siguen en la PEL
- **AND** una re-entrega posterior de cualquiera de ellos no produce una segunda fila en `events`

#### Scenario: El orden FIFO y la ausencia de duplicados se preservan
- **WHEN** se drena un lote de eventos del mismo agente generados en orden
- **THEN** el orden de inserción en `events` reproduce el orden del stream
- **AND** ningún `event_id` aparece dos veces, incluida la re-entrega desde la PEL

### Requirement: Perfilado opcional de la ingesta por etapa

El consumer SHALL registrar, cuando el setting `fim_profile_ingest` está activo (variable de entorno
`FIM_PROFILE_INGEST` en `1`), un log estructurado `consumer.timing` por evento procesado con la duración
en milisegundos de cada etapa —resolución de autenticación (indicando si fue acierto del caché),
validación, ingesta transaccional y total— y un log `consumer.timing` por lote con la duración de la
emisión del acumulado de ACK y el tamaño del lote (D87/RN-181). Cuando los eventos del lote se
persisten en una única transacción (ampliación del 2026-10-03 de D87/RN-181), el `ingest_ms` por
evento SHALL ser la porción de tiempo de las operaciones de ese evento dentro de la transacción del
lote, el log por evento SHALL emitirse después del `COMMIT` del lote, y el log por lote SHALL
incluir además la cantidad de candidatos persistidos en la transacción (`candidates`), la duración
de la transacción sin el `COMMIT` (`ingest_db_ms`) y la duración del `COMMIT` (`commit_ms`). Con el
setting inactivo, que es el default, el consumer MUST NOT emitir `consumer.timing`. Los logs de
perfilado MUST NOT incluir el payload, el secreto ni la firma, y SHALL respetar la sanitización de
logs existente (RN-89).

#### Scenario: Perfilado activo emite tiempos por etapa
- **WHEN** el backend corre con `FIM_PROFILE_INGEST=1`
- **AND** se ingesta un lote de eventos válidos
- **THEN** se registra un `consumer.timing` por evento con las duraciones de autenticación, validación, ingesta y total
- **AND** se registra un `consumer.timing` por lote con la duración de la emisión del ACK, el tamaño del lote, `candidates`, `ingest_db_ms` y `commit_ms`

#### Scenario: Perfilado inactivo por defecto
- **WHEN** el backend corre sin `FIM_PROFILE_INGEST`
- **THEN** no se registra ningún `consumer.timing`

### Requirement: Piso de rendimiento de la ingesta y INSERT por lote condicional

El carril de ingesta SHALL sostener al menos 95 eventos por segundo, con objetivo de 150 (D87/RN-181).
Con el caché de autenticación y el ACK por lote, el laboratorio midió 76,6 ev/s sobre `v5.0-tesis`
(diagnóstico del 2026-10-03). La ampliación del 2026-10-03 de D87/RN-181, revisada tras medir,
atribuye la caída a la construcción de un cliente HTTP con su contexto SSL por cada entrega de
notificación. Por eso las optimizaciones SHALL adoptarse en este orden:

- **Fase A, obligatoria.** El cliente HTTP de larga vida del carril de notificación (requisito «Las
  entregas HTTP del carril de notificación reutilizan un cliente de larga vida» de
  `backend-notifications`).
- **Fase B, condicional.** Sólo si con la fase A el banco de desarrollo no alcanza el umbral de
  abajo: la persistencia de los eventos validados de un lote en una única transacción por lote. Debe
  preservar:
  - el orden FIFO de inserción;
  - la cadena `superseded`, incluido el caso en que dos eventos del mismo lote afectan la misma ruta;
  - el dedup idempotente por `event_id`, en la base y dentro del lote;
  - que un error transitorio deje todo el lote en la PEL.

  MUST NOT introducir concurrencia entre eventos del lote (D75/RN-169).
- **Dentro de la fase B, y sólo si tampoco alcanza el umbral,** la creación de la fila `Alert` en
  esa transacción (enmienda condicional de D76/RN-170).

Antes de etiquetar `v5.1-tesis`, el banco de desarrollo `lab/bench_ingest_consumer.py` SHALL medir,
con la cadena de notificación **sin stub**, al menos 1,5 veces su línea base sin stub en el mismo
host. Sin stub significa:

- reglas que hacen alertar a cada evento;
- un sumidero HTTP local que persiste una fila por pedido en otra base de la misma instancia de
  PostgreSQL;
- rutas repetidas como el generador de carga.

La línea base registrada es 62,0 ev/s, así que el umbral es ≥93 ev/s.

Si la fase A alcanza el umbral, la fase B MUST NOT implementarse y SHALL registrarse como no
necesaria, con su medición. Si la fase B se adopta, su delta de requisitos SHALL escribirse en la
change antes del código.

El piso de laboratorio SHALL medirse en la Batería 5 del arnés unificado sobre `v5.1-tesis`, como
ventana de consumo entre el primer y el último `received_at` de los eventos drenados. Las
mediciones de desarrollo, antes y después de cada fase, y las decisiones sobre la fase B y su paso
condicional SHALL quedar registradas en la change. El resultado del laboratorio SHALL registrarse
tal como se mida, sin declarar una mejora antes de medirla.

#### Scenario: La fase A alcanza el umbral de desarrollo
- **WHEN** el banco de desarrollo sin stub mide con la fase A al menos 1,5 veces su línea base sin stub en el mismo host
- **THEN** la persistencia por lote no se implementa
- **AND** la change registra ambas mediciones y la decisión

#### Scenario: La fase A no alcanza el umbral de desarrollo
- **WHEN** el banco de desarrollo sin stub mide con la fase A menos de 1,5 veces su línea base sin stub
- **THEN** se adopta la persistencia de los eventos validados de un lote en una única transacción, con su delta de requisitos escrito antes del código
- **AND** dos eventos válidos consecutivos de la misma ruta en un lote, sin pending previo, dejan al primero `superseded` y al segundo `pending` con `parent_event_id` igual al id del primero

#### Scenario: La ventana de consumo de la Batería 5 se registra
- **WHEN** la Batería 5 drena el stream tras restaurar Valkey
- **THEN** registra el ritmo como la cantidad de eventos drenados dividida por la diferencia entre el último y el primer `received_at`
