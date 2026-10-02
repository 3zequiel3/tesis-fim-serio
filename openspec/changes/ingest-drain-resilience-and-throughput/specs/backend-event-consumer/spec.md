## ADDED Requirements

### Requirement: El bucle principal del consumer recrea el group ante NOGROUP

El consumer SHALL invocar, cuando una lectura del bucle principal de `run_consumer` (`XREADGROUP` con
id `>`) falla con un error cuyo mensaje contiene `NOGROUP`, `_ensure_group` dentro del mismo
bucle, SHALL releer su PEL (`XREADGROUP` con id `0`) y SHALL volver a leer entradas nuevas, sin
requerir un reinicio del proceso del backend (D87/RN-181). El consumer MUST loguear la recreación
con un evento propio (`consumer.group_recreated`), distinto de `consumer.loop_error`. Si
`_ensure_group` falla (por ejemplo, Valkey todavía no responde), el consumer MUST conservar el
comportamiento actual: loguear, esperar 1 segundo y reintentar en la siguiente iteración. El group
SHALL recrearse con el mismo id inicial que en el arranque (`0`) y con `MKSTREAM`, de modo que
ninguna entrada presente en el stream quede sin leer.

#### Scenario: Valkey vuelve sin el group y el consumer lo recrea sin reiniciar
- **WHEN** el consumer está en su bucle principal
- **AND** Valkey se reinicia sin conservar el consumer group `fim-backend`
- **AND** la siguiente lectura `XREADGROUP` falla con `NOGROUP`
- **THEN** el consumer invoca `_ensure_group` y el group `fim-backend` vuelve a existir
- **AND** el consumer registra `consumer.group_recreated`
- **AND** un evento publicado después de la recreación se ingesta y recibe `event_ack` sin reiniciar el backend

#### Scenario: Un error distinto de NOGROUP conserva el tratamiento actual
- **WHEN** la lectura del bucle principal falla con un error que no contiene `NOGROUP`
- **THEN** el consumer loguea `consumer.loop_error`, espera 1 segundo y reintenta
- **AND** no invoca `_ensure_group`

#### Scenario: La recreación falla mientras Valkey no responde
- **WHEN** la lectura falla con `NOGROUP` y la llamada a `_ensure_group` lanza un error de conexión
- **THEN** el consumer no termina
- **AND** reintenta en la siguiente iteración del bucle, después de esperar 1 segundo

### Requirement: La autenticación del agente se cachea en memoria con TTL de 5 segundos

El consumer SHALL cachear en memoria el resultado de `_get_agent_auth` por `agent_id` con un TTL de
5 segundos medido con reloj monótono (D87/RN-181). El caché SHALL invalidarse **sólo** por TTL,
porque no existe revocación de agente (`AgentStatus.revoked` nunca se asigna, D86/RN-180). Sólo se
SHALL cachear un resultado con secreto resuelto: un `agent_id` desconocido o sin secreto MUST NOT
quedar en el caché, de modo que el tamaño del caché queda acotado por la cantidad de agentes
registrados y un agente recién enrolado no se rechaza por un resultado negativo previo. El secreto
MUST obtenerse a través del helper único de lectura de D86/RN-180; el caché MUST NOT almacenar el
valor envuelto ni volver a leer `shared_secret_hex` por su cuenta. Un acierto del caché MUST NOT
abrir una `Session` ni pasar por el executor; un fallo SHALL resolver la consulta en el executor,
como exige D75/RN-169. El camino de rechazo (`_reject`, cuando necesita el secreto para firmar un
`event_nack`) SHALL usar el mismo caché.

#### Scenario: Eventos consecutivos del mismo agente dentro del TTL consultan la base una sola vez
- **WHEN** llegan dos eventos válidos del agente `a1` separados por menos de 5 segundos
- **THEN** la base se consulta para resolver la autenticación de `a1` una única vez
- **AND** ambos eventos se validan con el mismo secreto

#### Scenario: Vencido el TTL se vuelve a consultar la base
- **WHEN** transcurren más de 5 segundos desde que se cacheó la autenticación de `a1`
- **AND** llega un nuevo evento de `a1`
- **THEN** la autenticación de `a1` se vuelve a resolver contra la base

#### Scenario: Un agent_id desconocido no queda cacheado
- **WHEN** llega un evento de un `agent_id` que no existe en la base
- **THEN** el evento se rechaza como `unknown_agent`
- **AND** el caché no contiene una entrada para ese `agent_id`
- **AND** un evento posterior del mismo `agent_id`, enviado después de que el agente se registre y enrole, se resuelve contra la base

### Requirement: XACK y event_ack se emiten por lote y sólo después del commit de cada evento

Dentro de `_process_batch`, el consumer SHALL acumular la respuesta `event_ack` y el `XACK` de cada
evento que se resuelve con `event_ack` (ingesta persistida, re-entrega detectada en dedup y skip por
carrera de supersesión) y SHALL emitirlos juntos, en un único pipeline transaccional, al terminar
el lote (D87/RN-181). Ninguna entrada MUST agregarse al acumulado antes de que el `commit` de la
ingesta de su evento haya retornado con éxito. Un evento cuya ingesta lanza `SQLAlchemyError` MUST
NOT agregarse al acumulado ni recibir `XACK`, y MUST permanecer en la PEL, tal como exige el
requisito «Protocolo ACK end-to-end con persistencia y dedup idempotente». Los rechazos
(`_reject`) y el camino de `InvalidTransitionError` SHALL conservar su `XACK` y su `event_nack`
inmediatos. El despacho de mensajes del lote MUST seguir siendo secuencial (D75/RN-169). Si el
acumulado no puede emitirse (por ejemplo, Valkey se cae al final del lote), las entradas MUST
quedar en la PEL, y ninguna re-entrega posterior —desde la PEL o por republicación del agente—
MUST producir una segunda fila en `events`. Invocado fuera de un lote, `_handle_message` SHALL conservar la emisión inmediata de
`XACK` y `event_ack`.

#### Scenario: Un lote de eventos válidos se confirma con un único pipeline
- **WHEN** `_process_batch` recibe un lote de N eventos válidos y nuevos
- **THEN** los N eventos quedan persistidos
- **AND** los N `event_ack` y los N `XACK` se emiten en un único pipeline al final del lote

#### Scenario: El acumulado nunca precede al commit
- **WHEN** se procesa un lote de eventos válidos
- **THEN** para cada evento, el instante en que su `XACK` se agrega al acumulado es posterior al retorno del `commit` de su ingesta

#### Scenario: Un error transitorio de base de datos en medio del lote no confirma ese evento
- **WHEN** un lote contiene los eventos `e1`, `e2` y `e3`
- **AND** la ingesta de `e2` lanza `SQLAlchemyError`
- **THEN** `e1` y `e3` reciben `XACK` y `event_ack`
- **AND** `e2` no recibe `XACK` ni respuesta y permanece en la PEL

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
emisión del acumulado de ACK y el tamaño del lote (D87/RN-181). Con el setting inactivo, que es el
default, el consumer MUST NOT emitir `consumer.timing`. Los logs de perfilado MUST NOT incluir el
payload, el secreto ni la firma, y SHALL respetar la sanitización de logs existente (RN-89).

#### Scenario: Perfilado activo emite tiempos por etapa
- **WHEN** el backend corre con `FIM_PROFILE_INGEST=1`
- **AND** se ingesta un lote de eventos válidos
- **THEN** se registra un `consumer.timing` por evento con las duraciones de autenticación, validación, ingesta y total
- **AND** se registra un `consumer.timing` por lote con la duración de la emisión del ACK y el tamaño del lote

#### Scenario: Perfilado inactivo por defecto
- **WHEN** el backend corre sin `FIM_PROFILE_INGEST`
- **THEN** no se registra ningún `consumer.timing`

### Requirement: Piso de rendimiento de la ingesta y INSERT por lote condicional

El carril de ingesta SHALL sostener al menos 95 eventos por segundo, con objetivo de 150, medidos
con el arnés unificado de evaluación sobre el candidato `v5.0-tesis` (D87/RN-181). Las
optimizaciones SHALL adoptarse en este orden: caché de autenticación, ACK por lote y, **sólo si con
ambas el rendimiento medido sigue por debajo de 95 ev/s**, `INSERT` por lote. Si el `INSERT` por
lote se adopta, MUST preservar el orden FIFO de inserción, la cadena `superseded` —incluido el caso
en que dos eventos del mismo lote afectan la misma ruta— y el dedup idempotente por `event_id`, y
MUST NOT introducir concurrencia entre eventos del lote (D75/RN-169). La decisión de adoptarlo o no,
con la medición que la sustenta, SHALL quedar registrada en la change. El resultado de la re-corrida
SHALL registrarse tal como se mida, sin declarar una mejora antes de medirla.

#### Scenario: El rendimiento alcanza el mínimo sin INSERT por lote
- **WHEN** con el caché de autenticación y el ACK por lote el rendimiento medido es de al menos 95 ev/s
- **THEN** el `INSERT` por lote no se implementa
- **AND** la change registra la medición y la decisión

#### Scenario: Con INSERT por lote, dos eventos de la misma ruta en un lote forman cadena
- **WHEN** el `INSERT` por lote está adoptado
- **AND** un lote contiene dos eventos válidos consecutivos para la misma ruta, sin pending previo
- **THEN** el primero queda `superseded` y el segundo `pending` con `parent_event_id` igual al id del primero
