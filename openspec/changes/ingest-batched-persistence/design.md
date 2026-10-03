## Context

Esta change aplica la **ampliación del 2026-10-03 de D87/RN-181, revisada tras la medición de la tarea 1.7** (fila D87 de
`docs/arquitectura_stack.md`; sección D87/RN-181 de `docs/reglas_de_negocio.md`), que reabre el
grupo 7 de la Change 69 (`openspec/changes/archive/2026-10-02-ingest-drain-resilience-and-throughput/`,
tareas 7.1–7.3 y D-7 de su `design.md`). La primera versión de este documento atribuía el costo al
`COMMIT` por evento y proponía sólo la persistencia por lote; la medición la refutó y el diseño quedó
en dos fases: **A**, obligatoria, un cliente HTTP de larga vida para las entregas, y **B**,
condicional, la persistencia por lote original. Las referencias `archivo:línea` son de `devel` en
`ada3d4e`; `/opsx:apply` MUST re-verificarlas antes de editar.

**Evidencia.** `tesis/cierre/evidencia/diagnostico-drenaje-v5.0-20261003/`: Batería 5 aislada sobre
`v5.0-tesis`, 2.995 eventos en 39,1 s de ventana de consumo (76,6 ev/s). `timing.jsonl` (2.995
muestras por evento, 64 lotes de media 47,5 mensajes): `auth_ms` 0,02, `validation_ms` 0,14,
`ingest_ms` media 12,27 / mediana 10,31 / p95 23,66 / mínimo 4,91 ms; flush de ACK 0,41 s en total.
El generador produce 3.000 cambios sobre 600 rutas (`eventos.csv`), así que un lote contiene varias
veces la misma ruta. Las reglas del laboratorio son `alert_only` (terminal): no hay `pending` y la
supersesión no se ejercita, pero cada evento alerta.

**Qué mide `ingest_ms`.** El tiempo de pared de
`loop.run_in_executor(None, functools.partial(_ingest, …))` (`events/consumer.py:547-551`). El
executor de ingesta es exclusivo y el despacho es secuencial, así que no hay espera de cola: es el
cuerpo de `_ingest_event_outcome` (`events/service.py:354-536`). Viajes a PostgreSQL por evento:

| # | Operación | Origen | Siempre |
|---|---|---|---|
| 1 | `SELECT 1` de `pool_pre_ping` al sacar la conexión | `core/database.py:38-45` | sí |
| 2 | `BEGIN` implícito | psycopg, primera sentencia | sí |
| 3 | `SELECT` de dedup por `event_id` | `service.py:429-431` | sí |
| 4 | `SELECT` del `pending` más reciente de la ruta | `get_pending_event_for_path`, `:290-296` | con ruta |
| 5 | `UPDATE` optimista a `superseded` (+ re-consulta si hay carrera) | `mark_superseded`, `:299-315` | con `pending` |
| 6 | `SELECT * FROM rules` | `determine_severity_for_path`, `rules/service.py:75` | con ruta |
| 7 | `INSERT … RETURNING id` | `session.flush()`, `:520` | sí |
| 8 | `SELECT` de `superseded` (+ `SELECT` de `audit_log` si supera 10) | `compact_chain`, `:318-351` | con cadena |
| 9 | `COMMIT`, con vaciado de WAL (`synchronous_commit=on` por defecto) | `:535` | sí |

Un evento nuevo con ruta y sin cadena paga 7 viajes y un `fsync` de WAL. En paralelo, cada evento
del laboratorio dispara en el carril de notificación (`alerts/service.py`): `_create_alert_row`
(pre-ping, `INSERT`, `COMMIT` con `fsync`, `refresh`), `_prepare_notification` (pre-ping, dos
`SELECT`), un `POST` a n8n con un `httpx.AsyncClient` nuevo por llamada (`alerts/notifier.py:45`)
y `_mark_delivered` (pre-ping, `SELECT`, `UPDATE`, `COMMIT` con `fsync`). n8n persiste su ejecución
en `fim_n8n` sobre la **misma** instancia de PostgreSQL. Son al menos tres `COMMIT` durables del
backend por evento más los de n8n, todos serializados por el mismo WAL.

**Atribución medida (tarea 1.7, `mediciones.md` §1).** La hipótesis de la primera versión —el `COMMIT`
y los viajes por evento en contención con el carril de notificación— quedó **refutada**. El banco
con la cadena de notificación sin stub (`--notify real --paths 600`) reproduce el laboratorio: 62,0
ev/s, `ingest_ms` 15,85 ms, contra 170-178 ev/s y 5,1-5,9 ms con stub. En ese modo:

- `commit_ms` es 1,085 ms, el 6,8 % de `ingest_ms`;
- `synchronous_commit=off` da 61,9 ev/s;
- `sys.setswitchinterval(1e-4)` da 59,6 ev/s;
- inyectar `httpx.AsyncClient(verify=False)` da **81,4 ev/s** e `ingest_ms` 11,96 ms.

`send_n8n` (`alerts/notifier.py:45`) y `send_webhook_fallback` (`:142`) construyen un
`httpx.AsyncClient` por llamada. httpx arma en esa construcción un `ssl.SSLContext` nuevo con la
carga del bundle de CA, aunque la URL sea `http://`, y ese trabajo de CPU retiene el GIL que el hilo
del executor de ingesta necesita entre sentencias. Por eso el costo aparece en `ingest_ms`, escala
con los viajes a la base y no con el `COMMIT`. La brecha residual (~12 contra ~5,5 ms) también queda
fuera del `COMMIT`: la lectura de trabajo es CPU del carril de notificación (fila `Alert`, SSE, JSON)
compitiendo por el GIL. Es una hipótesis, no una medición; la fase B ataca su componente de viajes
por evento si la fase A no alcanza.

**Restricciones.** Single-instance (RN-76). Despacho secuencial y FIFO (D75/RN-169). Todo acceso
síncrono a PostgreSQL desde una corrutina va al executor (D75/RN-169); el carril de notificación
tiene su executor propio (D76/RN-170). La notificación depende del `commit`, no del ACK (D-6 de la
Change 69). El agente resuelve `event_ack`/`event_nack` por `event_id` y republica tras 60 s sin
respuesta. Deben pasar sin modificación `test_fifo_order_preserved_after_batch_drain` y
`test_no_duplicate_after_transient_db_error_and_pel_redelivery`
(`backend/tests/test_ingest_offload_blocking_db.py:140,177`); este último invoca `_handle_message`
directamente con `_ingest` parcheado para lanzar `SQLAlchemyError`.
`test_batch_dispatch_is_strictly_sequential` reemplaza `_handle_message` por un doble de tres
argumentos y exige que `_process_batch` lo llame en serie por mensaje.

## Goals / Non-Goals

**Goals:**

- Fase A: quitar del proceso la construcción de un cliente HTTP y su contexto SSL por entrega, sin
  cambiar la verificación TLS, los timeouts ni la semántica de error y reintento de cada entrega.
- Medir la fase A con el banco sin stub y decidir la fase B con ese número.
- Fase B, si aplica: un único `COMMIT` por lote y ~1-2 viajes por evento, conservando dentro del lote
  la semántica por evento (dedup, rate limit, cadena `superseded`, carrera, RN-11/12/72, RN-98,
  rechazos y notificación), con todo el lote en la PEL ante un error transitorio.
- ≥95 ev/s en el laboratorio sobre `v5.1-tesis`; ≥1,5× la línea base sin stub en desarrollo
  (≥93 ev/s sobre 62,0).

**Non-Goals:**

- Apagar `synchronous_commit`, usar `commit_delay` o cambiar la configuración de PostgreSQL: medido
  sin efecto.
- `verify=False` o cualquier relajación de TLS.
- Un reintento inmediato dentro del mismo intento de entrega ante un reset de conexión: la escalera
  durable de D42/RN-136 ya cubre el caso y no se cambia la semántica de reintento.
- Cambiar el cliente del chequeo de salud de n8n (`core/health.py:107`): no está en el camino de los
  eventos y debe medir conectividad fresca.
- Separar la base de n8n en otra instancia: cambia el despliegue, no el producto.
- Concurrencia entre eventos del lote o entre lotes (D75/RN-169 la prohíbe).
- Corregir que `alerts.event_id` no tenga `ON DELETE` frente a la compactación (ver Risks).

## Decisions

### Fase A — cliente HTTP de larga vida (obligatoria)

#### A-1. Un único `httpx.AsyncClient` para las entregas, con ciclo de vida del lifespan

`alerts/notifier.py` gana tres funciones de módulo:

- `init_notify_http_client()` crea el cliente;
- `get_notify_http_client()` lo devuelve y lo crea de forma perezosa con la misma configuración si
  todavía no existe (tests, banco, scripts);
- `close_notify_http_client()` hace `aclose()` y lo descarta.

`send_n8n` y `send_webhook_fallback` usan `get_notify_http_client()` en lugar de
`async with httpx.AsyncClient(...)`. Su forma no cambia: `try`, `raise_for_status`, `True`/`False`
y los mismos logs. El timeout de cada canal pasa por pedido (`client.post(url, json=…,
timeout=timeout)`), así que los 10 s de cada canal se conservan aunque el cliente sea común.

El lifespan (`backend/app/main.py`) llama a `init_notify_http_client()` antes de lanzar los
consumers y a `close_notify_http_client()` en el apagado. El cierre va después de cancelar las
tareas que agendan entregas y antes de `notify_executor.shutdown`, para que ninguna entrega en
vuelo encuentre el cliente cerrado sin haber sido cancelada.

`backend/tests/conftest.py` agrega un fixture autouse que cierra y descarta el cliente después de
cada test. Las conexiones de httpx quedan ligadas al event loop que las abrió, y pytest-asyncio crea
un loop por test.

*Alternativa descartada:* un cliente por tarea de entrega o un caché de `SSLContext` pasado a cada
cliente nuevo. El caché quita el costo del contexto pero conserva la construcción del transporte y
el handshake TCP por entrega; un cliente único quita los tres.

*Alternativa descartada:* crear el cliente sólo en el lifespan y fallar si no existe. Obliga a todos
los tests y al banco a correr el lifespan; la creación perezosa con la misma configuración no cambia
el comportamiento de producción, donde el lifespan siempre lo crea primero.

#### A-2. TLS y pool

- **TLS.** El cliente se construye una vez con la verificación por defecto de httpx (activa, con su
  almacén de confianza); el `SSLContext` se arma una sola vez, en la construcción. `verify=False`
  MUST NOT aparecer en código de producción. Un test lo fija inspeccionando el contexto del
  transporte (`verify_mode == CERT_REQUIRED`, `check_hostname` activo).
- **Pool.** `httpx.Limits(max_connections=settings.notify_max_concurrent_deliveries,
  max_keepalive_connections=settings.notify_max_concurrent_deliveries, keepalive_expiry=4.0)`. Las
  entregas concurrentes ya están acotadas por ese mismo cupo (D76/RN-170), así que el pool nunca
  hace esperar a una entrega que tiene permiso. Los 4 s quedan por debajo del `keepAliveTimeout` de
  5 s que Node usa por defecto en su servidor HTTP: el cliente no reutiliza una conexión que n8n ya
  está por cerrar. La tarea 2.1 verifica ese valor en n8n 2.17.8; si n8n lo cambia, el
  `keepalive_expiry` se ajusta por debajo y se anota.

#### A-3. Reset de conexión y reinicio de n8n

Si n8n se reinicia o la conexión reutilizada se corta, el `post` lanza un `httpx.TransportError`;
`send_n8n` lo captura como hoy y devuelve `False`. La entrega sigue la escalera durable de
D42/RN-136 sin cambios. httpx descarta del pool la conexión rota, así que el intento siguiente
—de esta entrega o de otra— abre una conexión nueva. No se agrega un reintento inmediato dentro del
intento: cambiaría la semántica de reintento y la cuenta de `attempt_count` por una mejora de
latencia que la escalera ya cubre. Un test con un servidor local que cierra la conexión tras la
primera respuesta lo fija: la primera entrega puede fallar o no, y la siguiente se entrega.

#### A-4. Medición y compuerta de la fase B

Con la fase A, el banco se mide igual que la línea base (`--notify stub` y `--notify real --paths
600`, 3.000 eventos, 3 repeticiones más una perfilada) y se registra en `mediciones.md`. Si `real`
alcanza al menos 1,5× la línea base `real` (≥93 ev/s sobre 62,0), la fase B no se implementa y queda
registrada como no necesaria, con el número y la fecha. Si no, se implementa la fase B.

### Fase B — persistencia por lote (condicional a A-4)

Las decisiones D-2 a D-10 rigen sólo si A-4 no alcanza el umbral. D-1 está cumplida. El delta de
requisitos de la fase B no forma parte de la change mientras no se adopte, para que el archive no
lleve a las main specs requisitos sin implementar. Está redactado en `32d9e5d`, en
`openspec/changes/ingest-batched-persistence/specs/backend-event-consumer/spec.md`: el requisito
ADDED «Los eventos validados de un lote se persisten en una única transacción» y los MODIFIED de ACK
por lote y de perfilado. Se restaura, ajustado al requisito de piso vigente, antes de escribir
código de la fase B.

### D-1. Medir primero, con el banco sin stub (hecho, tareas 1.1–1.7)

Antes de tocar la ingesta, `lab/bench_ingest_consumer.py` gana el modo `--notify real`: siembra
una regla `high` que matchea las rutas del banco, apunta `N8N_WEBHOOK_URL` a un sumidero HTTP local
(un `asyncio` server en el mismo proceso del banco o un subproceso) que responde 2xx y por cada
pedido inserta y confirma una fila en una base `bench_n8n` de la **misma** instancia de PostgreSQL,
emulando la persistencia de ejecución de n8n; y `--paths N` reparte los eventos sobre N rutas en el
orden del generador (default 600 para 3.000 eventos). Se mantiene el modo actual (`--notify stub`)
para comparar con la Change 69. El perfilado por evento suma `commit_ms` en el camino por evento,
bajo el mismo flag, para atribuir la fracción del `COMMIT` dentro de `ingest_ms`.

La línea base (código de `devel` sin esta change, modo `real`) y cada paso se registran en
`mediciones.md` de esta change, con el formato de la Change 69: fecha, commit, comando, eventos,
ev/s por corrida y mediana, y desglose de `consumer.timing`.

*Alternativa descartada:* levantar n8n real en el banco. Reproduce mejor la carga de n8n, pero
mete el arranque y el aprovisionamiento de n8n en un banco que tiene que correr en minutos; el
sumidero que persiste una fila por pedido reproduce lo que importa para la contención: un `COMMIT`
ajeno por notificación sobre la misma instancia.

### D-2. Candidatos por lote en una `ContextVar`, sin tocar la firma de `_handle_message`

`_process_batch` crea, junto al acumulador de ACK de la Change 69, una lista de candidatos y la
publica en una `ContextVar` (`_ingest_batch_var`), por la misma razón que motivó la del ACK: el doble
de `test_batch_dispatch_is_strictly_sequential` tiene tres argumentos. En el camino feliz,
`_handle_message` con lote activo **no** llama a `_ingest`: agrega un `_IngestCandidate`
(`msg_id`, payload, `received_at`, `detected_at`, `agent_id`, `event_id`, `shared_secret`,
`payload_dump` y los tiempos de autenticación y validación ya medidos) y retorna. Sin lote activo
(llamada directa, como en `test_no_duplicate_after_transient_db_error_and_pel_redelivery`) conserva
el camino por evento actual sin cambios. Los rechazos de validación (pasos 1–5) siguen como hoy:
inmediatos.

Al terminar el bucle de mensajes, `_process_batch` despacha **una** vez al executor de ingesta la
persistencia del lote (D-3) y, con el resultado, aplica los efectos (D-5). El `finally` existente
sigue emitiendo el acumulado de ACK.

*Alternativa descartada:* persistir cada candidato dentro de `_handle_message` sobre una `Session`
abierta en `_process_batch` y compartida entre llamadas al executor. Mantiene la forma actual, pero
pasea una `Session` y su conexión entre hilos del pool en cada evento y conserva 50 saltos al
executor por lote; con una sola salida el trabajo de base de datos del lote corre en un solo hilo.

### D-3. Núcleo de ingesta único, sobre una `Session` dada y un contexto de lote

`_ingest_event_outcome` (`events/service.py:354`) se parte en dos: un núcleo
`_ingest_into_session(session, ctx, event_data, received_at, detected_at, accept_new)` que hace todo
lo que hoy hace dentro del `with Session` **salvo** abrir la `Session` y confirmar, y el envoltorio
actual, que abre la `Session`, llama al núcleo con un contexto de un solo evento y hace `commit`.
Así el camino por evento y el de lote comparten una única implementación de la derivación de estado,
la supersesión, la carrera, la severidad y la compactación.

El contexto de lote (`_IngestBatchContext`) lleva:

- `known_event_ids`: `event_id` presentes en la base para los candidatos del lote (un `SELECT
  event_id … WHERE event_id IN (…)`) más los ya vistos en el lote. Un candidato cuyo `event_id`
  está ahí es `duplicate` sin tocar la base ni el rate limit.
- `pending_by_path`: para las rutas del lote, el `pending` más reciente (un `SELECT … WHERE path IN
  (…) AND status = 'pending' ORDER BY created_at DESC`, reducido en Python al primero por ruta; es
  portable a SQLite de los tests, a diferencia de `DISTINCT ON`). Tras cada inserción del lote el
  mapa se actualiza: la ruta apunta al evento nuevo si quedó `pending`, o a `None` si quedó terminal
  (un terminal nunca es `pending`). Tras supersedir, el `pending` anterior sale del mapa. Así dos
  eventos de la misma ruta en el lote forman cadena.
- `rules`: la lista de `Rule` leída una vez por lote. `determine_severity_for_path` se refactoriza
  en una función pura `severity_from_rules(path, rules)` que ambas formas usan, y la firma pública
  `determine_severity_for_path(path, session)` se conserva llamándola (sigue siendo «única fuente de
  cálculo», `rules/service.py:71-73`).

El `UPDATE` optimista y la re-consulta ante carrera (D25/RN-121) **siguen siendo por evento** y
contra la base: una aprobación o un rechazo concurrente del operador sólo se ve ahí. Si
`mark_superseded` devuelve `False`, la re-consulta usa `get_pending_event_for_path` sobre la misma
`Session` (ve también los `pending` insertados por el lote) y el mapa se corrige con su resultado.
La compactación sigue por evento, dentro de la misma transacción (RN-98 sin cambio). Cada `Event`
nuevo se inserta con `session.flush()` individual —su `id` hace falta como `parent_event_id` del
siguiente de la misma ruta y el orden de `id` reproduce el del stream— y se desliga con `expunge`
inmediatamente después del `flush`, como hoy antes del `commit`, para que cruce al loop sin I/O.

Por evento quedan 1 viaje (`INSERT`) más el `UPDATE` y la compactación si hay cadena; por lote,
pre-ping, `BEGIN`, dedup, precarga de `pending`, `rules` y un `COMMIT`.

*Alternativa descartada:* `INSERT` multi-fila en un solo `flush` al final. Ahorra hasta 49 viajes
más, pero pierde el `id` intermedio que la cadena necesita y obliga a razonar el orden de
asignación de la secuencia; el `COMMIT` y las lecturas por evento son el grueso del ahorro. Si el
banco lo pide, se evalúa en otra change.

*Alternativa descartada:* `SAVEPOINT` por evento. Daría aislamiento fino ante errores, pero suma
dos viajes por evento (`SAVEPOINT` + `RELEASE`), que es justo lo que se quiere quitar; D-4 resuelve
el aislamiento del evento envenenado sin pagarlo en el camino feliz.

### D-4. Fallas: todo el lote a la PEL; re-ejecución sólo ante error determinista

La función de lote devuelve un resultado por candidato (la taxonomía `IngestOutcome` actual más
`invalid_transition`). `InvalidTransitionError` se captura por candidato dentro del núcleo, antes de
que ese candidato escriba nada, y no aborta la transacción.

Cualquier `SQLAlchemyError` del lote (sentencias o `COMMIT`) hace `rollback`, devuelve los tokens
consumidos (D-6) y propaga un resultado de lote fallido. Entonces:

- **`IntegrityError` o `DataError`** (deterministas: un evento que viola una restricción o no cabe
  en una columna): `_process_batch` re-ejecuta los candidatos uno por uno, en orden, por el camino
  por evento existente (`_ingest` en el executor, con su `Session` y su `commit`), y aplica sus
  efectos como hoy. Sólo el evento que vuelve a fallar queda en la PEL, igual que antes de esta
  change. Log `consumer.batch_replayed_per_event`.
- **Cualquier otro** (`OperationalError`, `InterfaceError`, …): ningún candidato recibe `XACK` ni
  respuesta y todos quedan en la PEL. Log `consumer.batch_db_error` con `exc_info=True` y la
  cantidad de candidatos. El agente republica tras 60 s; la re-entrega termina en dedup o en
  inserción, nunca en duplicado.

*Alternativa descartada:* re-ejecutar por evento ante cualquier error. Ante una base caída
multiplica por 50 los intentos fallidos en el peor momento y contradice el requisito de que un
error transitorio deje el lote entero en la PEL.

### D-5. Efectos después del `COMMIT`, en el orden del stream

Con el lote confirmado, `_process_batch` recorre los candidatos en orden y, según su resultado:
`persisted`, `duplicate` y `supersede_race` agregan `(msg_id, event_ack firmado)` al acumulador de
ACK (D-6 de la Change 69); `persisted` además agenda `notify_if_applicable(event)` con
`_fire_and_forget`, salvo que el evento haya sido eliminado por la compactación del mismo lote (el
contexto registra esos ids; la alerta no tendría fila a la que referir); `rate_limited` llama a
`_reject(..., rate_limited, ...)` con `retry_after` del estado vivo del limitador, como hoy;
`invalid_transition` ejecuta `XACK`, auditoría y `event_nack` terminal, como hoy. Después emite el
`consumer.timing` por evento si el perfilado está activo. El `finally` emite el acumulado.

Agendar la notificación tras el `COMMIT` del lote, y no tras el de cada evento, agrega a lo sumo la
duración de un lote (~0,5 s a 95 ev/s) a la latencia de notificación, contra los segundos que ya
cuesta la entrega; los eventos de un lote se notifican en orden.

### D-6. Rate limit: decisión por evento, tokens devueltos si el lote revierte

`accept_new` sigue llamándose dentro del núcleo, después del dedup y en el orden del lote, así que
la cantidad de admitidos y rechazados es la misma que con el camino por evento. El envoltorio de lote
cuenta los tokens consumidos por agente y, si la transacción revierte, llama a un método nuevo
`_RateLimiter.refund(key, n)` que devuelve `n` tokens sin superar `burst`, bajo el mismo lock. Sin
esto, un lote revertido y re-entregado consumiría dos veces su presupuesto y podría rechazar como
`rate_limited` eventos que el régimen admitía. En la re-ejecución por evento de D-4 los tokens ya
fueron devueltos y se vuelven a decidir.

### D-7. `synchronous_commit` permanece `on`

Con `off`, PostgreSQL devuelve el `COMMIT` antes de que el WAL llegue al disco; un corte en esa
ventana pierde filas que ya recibieron `event_ack`, y el agente las borra de su cola. Eso rompe el
al-menos-una-vez que sostiene el ítem 41. Un `COMMIT` por lote ya reduce los `fsync` del carril de
ingesta en ~50×.

### D-8. Perfilado por lote

`consumer.timing` con `scope="event"` conserva sus claves; en el modo de lote se emite después del
`COMMIT`, con `ingest_ms` igual al tiempo de las sentencias de ese candidato dentro de la
transacción (medido con `perf_counter` en el hilo del executor) y `total_ms = auth + validación +
ingest`. `scope="batch"` suma `candidates`, `ingest_db_ms` (transacción sin `COMMIT`) y
`commit_ms`. Con el flag apagado no se mide nada adicional.

### D-9. Paso condicional: fila `Alert` en la transacción del lote

Dentro de la fase B, si tras D-2…D-8 el banco en modo `real` no alcanza 1,5× su línea base, se escribe **antes del
código** un addendum de este documento y un delta de `backend-notifications` que muevan la creación
de la fila `Alert` a la transacción del lote: para cada evento persistido con severidad `critical` o
`high` y estado distinto de `superseded` al insertarse (RN-22, RN-52), un `Alert` con
`notification_id` acuñado, insertado tras el `INSERT` del evento. Tras el `COMMIT`,
`_process_batch` agenda una corrutina que publica en SSE y llama a `notify_event` con la alerta
ya persistida; `notify_if_applicable` conserva su forma para el camino por evento. La entrega, el
cupo de entregas y `_mark_delivered` no cambian. Es la enmienda acotada de D76/RN-170 cerrada en la
ampliación: la creación de la fila sale del executor de notificación. Ganancia esperada: un
`COMMIT` con `fsync` y ~4 viajes menos por alerta. Si se alcanza el umbral, no se implementa y se
registra.

### D-10. Tests de la Change 69 que se reescriben

Bajo la ampliación de RN-181 cambian tres tests de `backend/tests/test_ingest_drain_resilience.py`
que fijaban granularidad por evento dentro del lote:

- `test_each_ack_is_appended_after_the_commit_of_its_event` → cada agregado ocurre después del
  `COMMIT` del lote (espía sobre el `commit` de la `Session` del lote).
- `test_transient_db_error_in_the_middle_leaves_only_that_event_in_the_pel` → un error transitorio
  deja los tres en la PEL; se suma el caso `IntegrityError` en el del medio, que deja sólo ese.
- `test_timing_emitted_per_event_and_per_batch_when_flag_active` → suma las claves nuevas del lote.

Los demás tests de ese archivo y todos los de `test_ingest_offload_blocking_db.py` deben pasar sin
cambios; si alguno falla, el defecto está en la implementación.

## Risks / Trade-offs

- **[Resuelto] La atribución a la contención de `COMMIT` era una hipótesis.** → D-1 la midió y la
  refutó (tarea 1.7); el diseño pasó a las fases A y B.
- **[Riesgo] Un cliente compartido mal cerrado deja conexiones abiertas al apagar.** → A-1 lo cierra
  en el lifespan con un orden fijo y un test lo verifica.
- **[Riesgo] Una conexión reutilizada que n8n cerró hace fallar una entrega.** → `keepalive_expiry`
  de 4 s por debajo de los 5 s del servidor; si ocurre igual, la escalera de D42/RN-136 la reintenta y
  la entrega siguiente usa una conexión nueva (A-3).
- **[Riesgo] La fase A puede no alcanzar el umbral sola** (el diagnóstico con `verify=False` dio 81,4
  ev/s, por debajo de 93; el cliente único quita además la construcción del transporte y el handshake
  TCP por entrega, pero eso no está medido). → A-4 decide con el número y la fase B queda diseñada y
  lista.
- **[Riesgo] El banco de desarrollo no transfirió al laboratorio la vez anterior** (191,5 ev/s en
  desarrollo contra 76,6 en el laboratorio). → El modo `real` reproduce las dos diferencias
  conocidas (notificación con `COMMIT` ajeno en la misma instancia y rutas repetidas); el umbral se
  expresa como razón contra una línea base del mismo host (1,5× ≈ la mejora de 1,24× que el
  laboratorio necesita más 20 % de margen), no como número absoluto.
- **[Riesgo] Un error transitorio cuesta un lote entero.** → Sin pérdida ni duplicados: todo queda
  en la PEL y el agente republica a los 60 s. Es el comportamiento que pide la ampliación.
- **[Riesgo] Un evento envenenado provoca un rollback de lote cada vez que reaparece.** → D-4 lo
  aísla con la re-ejecución por evento ante `IntegrityError`/`DataError`; el costo es un lote lento
  por aparición.
- **[Trade-off] Las filas tocadas por el lote quedan bloqueadas hasta su `COMMIT`.** → A lo sumo
  la duración de un lote. Una aprobación concurrente sobre un `pending` que el lote supersede espera
  y luego falla su verificación optimista, que es la semántica actual de carrera.
- **[Trade-off] Las reglas son una instantánea por lote.** → Una regla cambiada durante un lote rige
  desde el siguiente; cerrado en la ampliación.
- **[Trade-off] La notificación de un evento espera al `COMMIT` de su lote.** → ≲0,5 s a 95 ev/s.
- **[Preexistente, fuera de alcance] `alerts.event_id` no declara `ON DELETE`**
  (`alerts/models.py:29`): si la compactación intenta borrar un `superseded` que tiene alerta, el
  `DELETE` viola la FK. Hoy ya ocurre por evento; con esta change ese `IntegrityError` dispara la
  re-ejecución por evento y queda aislado igual que hoy. Se registra como seguimiento.

## Migration Plan

1. Mergear sobre `devel` con las Changes 67, 68 y 69 archivadas. Sin migraciones de esquema ni
   cambios de compose ni settings nuevos (el pool usa `notify_max_concurrent_deliveries`).
2. Reconstruir y recrear el backend.
3. Etiquetar `v5.1-tesis` sólo con el umbral de desarrollo cumplido y registrado.
4. Rollback: revertir el commit y recrear el backend. No hay estado persistente nuevo; el cliente
   HTTP vive en memoria.

## Open Questions

Ninguna. La refutación de la primera hipótesis, la causa medida, el ciclo de vida del cliente, la
reutilización del contexto TLS, los límites del pool y el comportamiento ante un reset o un
reinicio de n8n, la forma de la transacción por lote, el tratamiento de fallas, la
devolución de tokens, la instantánea de reglas, la notificación de eventos compactados, el paso
condicional sobre `Alert` y los criterios de aceptación quedaron cerrados en la ampliación del
2026-10-03 de D87/RN-181, revisada tras la medición.
