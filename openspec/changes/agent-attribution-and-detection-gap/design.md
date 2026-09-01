## Context

Esta change cierra tres defectos verificados contra el código en el commit actual. Los tres
comparten una forma: el sistema representa la ausencia de información con un valor que significa
otra cosa.

**Estado actual — atribución.** El detector resuelve el usuario del proceso causante fuera de banda.
El kernel entrega únicamente el `pid` en `struct fanotify_event_metadata`; el UID sale de
`/proc/<pid>/status` y el ejecutable de `/proc/<pid>/exe`. Las dos lecturas están en
`agent/detector.py:91-106` y se invocan desde el hilo lector en `:392-400`. `_get_exe` ya es honesta
—devuelve `None` en `OSError`—; `_get_uid` no: está declarada `-> int` y devuelve `0`. La asimetría
no es intencional, es un descuido con consecuencia semántica máxima, porque `0` es root.

La ventana de fallo es rutinaria, no excepcional: `_process_event` hashea el archivo con reintentos
que suman hasta 150 ms antes de armar el `DetectedChange`, de modo que cualquier proceso corto ya
salió cuando se consulta `/proc`. En `agent/decision.py:151` la ventana ni siquiera existe: la
rehidratación del journal corre al arrancar el agente, después de un reinicio, y el proceso original
está muerto **por definición**. Ahí el `0` es incondicional.

El backend y el frontend ya son null-safe: `backend/app/modules/events/models.py:58` declara
`process_uid: int | None`, `EventOut.process_uid` lo propaga como `int | None`
(`backend/app/modules/events/router.py:39`) y `processContextLabel`
(`frontend/src/components/ui/EventsTable.tsx:29-35`) omite el bloque entero cuando los tres campos
son nulos. **No hace falta migración para este punto.**

**Estado actual — cobertura.** `agent/_fanotify.py` define la máscara de eventos y las banderas de
`init`/`mark`, pero no `FAN_Q_OVERFLOW`. `_parse_events` (`:241-258`) desempaqueta `_META` y arma un
`FanEvent(path, pid, mask)` por cada registro; el `mask` viaja pero nadie lo compara contra el bit de
desbordamiento. Río abajo, `_read_loop` (`agent/detector.py:369-397`) descarta con
`log.warning("detector.event_null_path")` todo evento cuyo `path` sea `None` — y un evento de
desbordamiento **no tiene path**, así que hoy caería exactamente en esa rama y se perdería con un
warning genérico.

Los contadores existentes miden otra cosa. `_event_drops` (`agent/detector.py:402-411`) cuenta
`asyncio.QueueFull` sobre la cola interna de 1000 elementos: un punto de pérdida **posterior**, ya
del lado del agente. `queue_pressure` (`agent/heartbeat.py:100`) viene de `agent/queue.py`, la cola
offline durable de 100 MB en disco, y no tiene relación alguna con `fanotify`. La afirmación de
`docs/arquitectura_stack.md` (limitación 3) de que el agente «monitorea activamente el nivel de
backpressure y lo reporta como anomalía en el heartbeat (`queue_pressure` flag)» era falsa; se
corrigió en esta misma change.

**Estado actual — el modelo del backend.** `Event.path` es `str` NOT NULL con índice
(`models.py:30`) y `ingest_event` hace `path = event_data.get("path", "")` (`service.py:164`). El
agente emite `event_type` en todo payload desde siempre (`DetectedChange.event_type`,
`agent/detector.py:66`) y el backend **nunca lo persistió**: no existe la columna.

**Restricciones.** Backend single-instance (RN-76). Sin Alembic: migraciones SQL manuales numeradas
e idempotentes bajo `backend/db/migrations/` (D3); la última es `011_timestamptz.sql`. Léxico de
eventos en minúsculas snake_case (RN-71). El agente no expone servidor HTTP: todo viaja por Valkey
Streams (RN-108, D8). El backend es la única autoridad sobre `EventStatus` y sobre `severity`
(D34/RN-128, D35/RN-129).

**Decisiones normativas que gobiernan esta change** — ya cerradas, no se re-deciden acá:
D49/RN-143 (`docs/reglas_de_negocio.md:1559`), D50/RN-144 (`:1590`), D51/RN-145 (`:1625`).

## Goals / Non-Goals

**Goals:**

- Que `process_uid: null` signifique «no se pudo resolver» y `0` signifique «root», sin ambigüedad,
  en la ruta de detección en vivo y en la de rehidratación.
- Que un desbordamiento de la cola de `fanotify` en el kernel produzca un registro observable en la
  bandeja del operador, no sólo una métrica.
- Que ese registro sobreviva: que no lo borre la supersesión por path ni la compactación de cadena.
- Que el tipo de evento que el agente ya emite llegue a la UI, para que un evento sin ruta sea
  distinguible de cualquier otro.
- Que nada de lo anterior rompa el motor de decisión, el pipeline de ingesta ni los 550 tests
  existentes del backend.

**Non-Goals:**

- **No** se implementa detección de pérdida en el nivel de la cola interna del agente más allá de lo
  que `event_drops` ya hace. Es un punto de pérdida distinto y ya tiene su métrica.
- **No** se cambia el mecanismo de supersesión para eventos **con** ruta. La cadena por path se
  mantiene exactamente como está.
- **No** se agrega validación de `event_type` contra un enum en el backend. La tolerancia hacia
  adelante es explícita en D51/RN-145, con el mismo criterio que `action` y `action_error`
  (D33, D36/RN-130).
- **No** se toca `agent/requirements.txt:6` ni el docstring de `agent/_fanotify.py:5`: el primero ya
  declara correctamente que no se depende de `pyfanotify` y el segundo es una referencia legítima al
  wrapper descartado.
- **No** se modifican las fixtures `_make_change()` con `process_uid: 0` de `test_decision.py:60-77`,
  `test_restore_metadata.py:77` y `test_symlink_hardening.py:565`: representan un proceso root real.
- **No** se implementa inspección pre-escritura (`FAN_CLASS_PRE_CONTENT`). Sigue siendo trabajo
  futuro, como declara la limitación 2 del stack.

## Decisions

### D-1 — `_get_uid` devuelve `int | None`, no un centinela

`_get_uid` pasa a `-> int | None` y devuelve `None` en `OSError`, alineándose con `_get_exe`, que ya
lo hace. `FanotifyEvent.uid` (`agent/detector.py:55`) y `DetectedChange.process_uid` (`:72`) cambian
a `int | None`. Las tres ramas de `_process_event` que construyen un `DetectedChange` pasan
`fan_event.uid` sin transformarlo, así que el nulo se propaga solo.

**Alternativa descartada — un centinela distinto (`-1`, `65534`).** Cualquier entero que se elija
colisiona con un uid real o con uno reservado, y ninguno se distingue de un valor genuino sin
conocimiento fuera de banda. El campo ya es nullable de punta a punta; usar el nulo no cuesta nada y
es la única representación que no miente.

**Alternativa descartada — un booleano `uid_resolved` al lado del entero.** Agrega una columna al
backend, un campo a la API y una rama al frontend para expresar lo que el nulo ya expresa. Además
deja el `0` visible en la base, de modo que una consulta SQL directa —la ruta más probable en el
análisis de la tesis— seguiría contaminada.

### D-2 — La rehidratación emite `null` en los tres campos de proceso, no sólo en `uid`

`agent/decision.py:151` escribe hoy `process_pid: 0`, `process_uid: 0`, `process_exe: None`. Los tres
se unifican en `None`. El `pid` de un proceso que ya no existe no es dato: `0` es el pid del
scheduler del kernel, no el de un proceso de usuario, y presentarlo como contexto forense de un
cambio de archivo es tan falso como el uid. D49/RN-143 lo dice explícitamente («lo mismo aplica a
`process_pid` y `process_exe` en la ruta de rehidratación»).

### D-3 — El evento de desbordamiento nace en el hilo lector, no en `_parse_events`

`_parse_events` es una función pura de parseo de buffer: propaga el `mask` en `FanEvent` y no
decide nada. Se agrega la constante `FAN_Q_OVERFLOW = 0x00004000` a `agent/_fanotify.py` y el
reconocimiento del bit ocurre en `_read_loop` (`agent/detector.py:369-397`), **antes** del chequeo
`if ev.path is None`, que hoy se tragaría el evento.

Ubicarlo ahí tiene tres consecuencias deseables: (1) el evento de desbordamiento **no pasa** por
`_path_location_in_scope`, que lo descartaría por no tener ruta; (2) no pasa por `_process_event`,
que asume `path` no nulo en su primera línea (`path.endswith(".fim_restore_tmp")`); (3) se publica
por el mismo `Publisher` que el resto, así que hereda cola offline, firma HMAC, `schema_version` y
reintentos sin código nuevo.

**Alternativa descartada — encolar el evento sintético en `_raw_queue` como un `FanotifyEvent` con
`path=None`.** Obligaría a `_process_event` a ramificar en su primera línea y a arrastrar la nulidad
del path por todo el pipeline de hashing, diff y baseline, que no tienen nada que hacer con este
evento. Peor: bajo saturación la cola interna es justamente lo que está lleno, así que el aviso de
pérdida podría perderse por `QueueFull`, que es la falla que se está tratando de hacer visible.

### D-4 — Deduplicación por ventana de tiempo, no por desbordamiento

D50/RN-144 lo fija: **a lo sumo un `detection_gap` por ventana de 60 segundos**, contando los
desbordamientos suprimidos y reportando esa cuenta en el evento. El detector mantiene dos campos de
estado privados en el hilo lector: el instante del último `detection_gap` emitido y el contador de
supresiones desde entonces. Al primer desbordamiento de una ventana nueva se emite con
`suppressed_count: 0`; los siguientes 60 segundos sólo incrementan; el primero de la ventana
siguiente emite con la cuenta acumulada y la resetea.

**Por qué por ventana y no por desbordamiento.** Bajo saturación sostenida el kernel emite
`FAN_Q_OVERFLOW` repetidamente —una vez por cada lectura que encuentra la cola desbordada—. Emitir
uno por cada uno inundaría la tabla de eventos justo cuando menos capacidad hay para procesarla: el
evento diagnóstico se convertiría en una segunda falla, y encima haría que el operador pierda de
vista los eventos de integridad reales entre miles de avisos idénticos.

**Por qué 60 segundos.** Es el orden de magnitud del intervalo de heartbeat y de la paciencia de un
operador frente a la consola. Una ventana mucho más corta no resuelve la inundación; una mucho más
larga agrupa brechas que ocurrieron en situaciones distintas bajo un solo registro.

**Nota sobre reinicio.** El estado de la ventana es en memoria del hilo lector. Un reinicio del
agente la resetea, de modo que el primer desbordamiento después de arrancar emite siempre. Es el
comportamiento correcto: tras un reinicio la ventana anterior ya no es comparable.

### D-5 — El `detection_gap` no atraviesa el motor de decisión

El motor evalúa reglas contra la **ruta** (`RulesCache.evaluate` matchea globs contra el path) y sus
dos acciones físicas —`_auto_restore` y `_quarantine`— reciben `path` como argumento posicional y
operan sobre el filesystem. Un evento sin ruta no tiene nada que matchear ni nada sobre qué actuar.

El detector publica el `detection_gap` con `action: "alert_only"` ya puesto en el payload, **sin**
llamar a `evaluate_and_act` y **sin** escribir en el journal. No hay acción que rehidratar, así que
el journal no aporta nada, y saltear la llamada evita tener que enseñarle al motor a manejar un
`path` nulo — cambio de contrato con superficie mucho mayor que la del problema.

Río abajo, `derive_event_status("alert_only", False)` (`service.py:78-79`) ya retorna
`EventStatus.alert_only` sin tocar nada más, e `is_terminal` lo trata como resolución automática sin
operador (`resolved_at = received_at`, `resolved_by = NULL`). Cero código nuevo en esa ruta.

**Alternativa descartada — hacer que el motor devuelva `alert_only` para path nulo.** Requiere
guardas en `evaluate_and_act`, en `RulesCache.evaluate` y en las dos acciones, más el journal
transaccional que no tiene sentido para un evento sin acción. Cuatro puntos de cambio para llegar al
mismo resultado que una rama en el punto de emisión.

### D-6 — El nulo llega nulo hasta la columna: la cadena vacía es el defecto real

`ingest_event` hace `path = event_data.get("path", "")` y ese `""` es la **clave de supersesión**:
`get_pending_event_for_path(session, "")` encontraría el `detection_gap` anterior y lo marcaría
`superseded`. Con la ingesta actual, cada brecha nueva borraría la anterior de la vista del
operador — exactamente el dato que D50 existe para preservar, destruido por una línea de
compatibilidad.

La ingesta pasa a `path = event_data.get("path")` (sin default) y `Event.path` a `str | None`. Se
agregan dos guardas explícitas en `ingest_event`:

1. Si `path is None`, **no** se llama a `get_pending_event_for_path`. El evento entra con
   `parent_event_id = None`.
2. Si `path is None`, **no** se llama a `compact_chain`. Ya está garantizado por el hecho de que
   `compact_chain` sólo se invoca cuando `parent_event_id is not None`, pero la guarda se declara en
   la spec para que un refactor futuro no la pierda por accidente.

`get_pending_event_for_path` y `compact_chain` mantienen su firma `path: str` — no reciben nunca un
nulo, porque el llamador no las invoca. Esa es la contención mínima.

**Alternativa descartada — un valor sintético de path (`"<detection_gap>"`, `"/"`)**. Reintroduce
exactamente el problema del `""`: dos brechas comparten clave y se supersedan. Además contamina el
filtro `path_prefix` del listado y el índice `ix_events_path` con un valor que no es una ruta.

### D-7 — Severidad `high` fija por ausencia de ruta, decidida por el backend

`determine_severity_for_path(path, session)` deriva la severidad de las reglas que matchean el path;
sin matches retorna `low` (D-C15-01). Un evento sin ruta no matchea ninguna regla, así que caería en
`low`, que es lo contrario de lo que significa una pérdida de cobertura.

La excepción se dispara por **ausencia de ruta**, no por `event_type == "detection_gap"`. Es
deliberadamente estrecha en esa dirección: un tipo de evento sin ruta que aparezca en el futuro
hereda el tratamiento correcto sin tocar el código. Y sigue siendo el backend quien decide — el
valor que el agente proponga se ignora, igual que hoy.

`high` y no `critical`: una brecha de detección es una **pérdida de garantía**, no una violación de
integridad confirmada. Reservar `critical` para lo confirmado mantiene informativa a la severidad
máxima, que es lo que la change 45 (`frontend-severity-triage`) construyó la consola para explotar.

### D-8 — `event_type` se persiste sin validación contra enum

Columna `str` NOT NULL. Sin `CHECK`, sin tipo enum de PostgreSQL, sin validación en Pydantic. Mismo
criterio de tolerancia hacia adelante que `action` y `action_error` (D33, D36/RN-130): un valor
desconocido emitido por un agente más nuevo se guarda tal cual en vez de rechazar el evento. Un
enum a nivel de base convertiría «el agente va adelantado del backend» en **pérdida de eventos de
integridad**, que es el peor resultado posible para este sistema.

El default de columna es `file_modified` para las filas previas a la migración. No es una
adivinanza: hasta esta change el backend sólo persistía eventos de `FAN_CLOSE_WRITE` con hash
distinto, `FAN_DELETE`/`FAN_MOVED_FROM` y `FAN_CREATE`/`FAN_MOVED_TO`, y el `event_type` real no se
puede reconstruir retroactivamente porque nunca se guardó. `file_modified` es el caso mayoritario y
el valor documentado como default en D51/RN-145.

### D-9 — La migración va en esta change, no separada

`012_add_event_type_and_nullable_path.sql`, misma convención que 005–011: SQL manual, idempotente
(`ADD COLUMN IF NOT EXISTS`), con encabezado de comentario que explica el porqué y la línea de
aplicación (`psql $DATABASE_URL -f ...`). Sin Alembic (D3).

Separarla no aporta nada y crea una ventana en la que el modelo SQLModel declara una columna que la
base no tiene: `create_all` no altera tablas existentes, así que el backend arrancaría y fallaría en
la primera ingesta con `UndefinedColumn`. Las dos operaciones —agregar `event_type`, relajar
`path`— son aditivas y compatibles hacia atrás con el código anterior, así que el orden
migración-antes-de-deploy es seguro pero no obligatorio.

`ALTER COLUMN path DROP NOT NULL` no es idempotente por sintaxis, pero **sí lo es por efecto**:
ejecutarlo sobre una columna ya nullable es un no-op sin error en PostgreSQL. Se documenta en el
encabezado del script.

### D-10 — El frontend discrimina por `event_type`, no por `path === null`

`EventListItem` incorpora `event_type: string` y `path: string | null`. La tabla y el detalle
podrían ramificar sobre el nulo del path, pero ramifican sobre el `event_type`: es el discriminador
que D51/RN-145 introduce precisamente para eso, y produce una etiqueta legible («brecha de
detección») en vez de un hueco.

En `EventsTable.tsx:134`, la celda de path hoy es un `<Link>` con `{item.path}`. Cuando `path` es
nulo, el `<Link>` al detalle se mantiene —el evento es navegable— y el texto pasa a la etiqueta del
tipo de evento con tratamiento visual propio, en la línea de la insignia `symlink` que ya existe en
`:136-144`. En `EventDetail.tsx:89` la fila de path se reemplaza por la del tipo de evento y su
causa. Sin guiones, sin celdas vacías, sin `path ?? '—'`.

### D-11 — La cobertura de tests que hoy falta se declara explícitamente

Verificado: los tests que ejercen `engine.rehydrate()` están en `agent/tests/test_decision.py`
líneas 220, 364, 399 y 419, y **ninguno** asserta sobre `process_uid`. El cambio de `decision.py:151`
quedaría sin cobertura. Las tasks incluyen dos tests nuevos obligatorios: la aserción de nulidad en
la ruta de rehidratación, y `_get_uid` sobre un pid inexistente.

Las fixtures `_make_change()` con `process_uid: 0` de `test_decision.py:60-77`,
`test_restore_metadata.py:77` y `test_symlink_hardening.py:565` son helpers tipo `MagicMock` con
`process_pid: 100` que alimentan `evaluate_and_act()`. Representan un proceso root **real** y son
correctas tal como están: **no se tocan**. Modificarlas para «alinearlas» con el cambio destruiría
la única cobertura del caso root legítimo.

## Risks / Trade-offs

**[El `detection_gap` inunda la tabla bajo saturación sostenida]** → Deduplicación por ventana de 60
segundos con contador de supresiones (D-4). En el peor caso el sistema produce 60 eventos por hora
de saturación continua, cada uno con la cuenta real de desbordamientos que representa.

**[La ventana de deduplicación esconde brechas distintas dentro de los mismos 60 segundos]** →
Aceptado y acotado: el `suppressed_count` del evento dice cuántos desbordamientos hubo. La
información que se pierde es el instante exacto de cada uno, no su existencia. Y el evento no
afirma «se perdieron N cambios», afirma «entre estos dos instantes pude haber perdido cambios»:
agrupar por ventana es coherente con esa semántica.

**[Un evento sin ruta rompe un consumidor del listado que asume `path` no nulo]** → El único
consumidor tipado es el frontend, que se actualiza en esta misma change. `path_prefix` en
`GET /events` filtra con `LIKE` sobre la columna, y un `NULL` simplemente no matchea: los
`detection_gap` quedan fuera de un filtro por prefijo, que es el comportamiento correcto. La
verificación de que no hay otros consumidores está en las tasks.

**[`ALTER COLUMN path DROP NOT NULL` sobre una tabla grande bloquea]** → En PostgreSQL, quitar un
`NOT NULL` es una operación de catálogo: no reescribe la tabla ni la recorre. Toma un `ACCESS
EXCLUSIVE` momentáneo. Con backend single-instance (RN-76) y despliegue por Docker Compose, la
ventana es irrelevante.

**[El default `file_modified` etiqueta mal eventos históricos que eran `file_created` o
`file_deleted`]** → Real e irreparable: el dato nunca se guardó y no se puede reconstruir. Se acepta
explícitamente en D51/RN-145 y se documenta en el encabezado de la migración. El impacto está
acotado por el punto siguiente.

**[Los resultados del Capítulo 5 corresponden al esquema y al comportamiento previos]** → **Los
datos actuales de `resultados/` no son reportables tal cual.** Fueron producidos contra un esquema
sin `event_type`, con `path` NOT NULL, y contra un agente que atribuía a root toda atribución no
resuelta. Toda afirmación de la tesis sobre la fiabilidad de la atribución de procesos medida sobre
esos datos es insostenible: el sistema no distinguía «fue root» de «no sé quién fue», así que la
proporción de eventos atribuidos a root está inflada por una cantidad desconocida. La **re-corrida
completa de las baterías del Capítulo 5 es condición para reportar**, no una mejora opcional de los
números. El usuario aceptó explícitamente re-correrlas al aprobar esta change.

**[El estado de la ventana de deduplicación no sobrevive al reinicio del agente]** → Intencional
(D-4). El primer desbordamiento tras un reinicio emite siempre. Un desbordamiento inmediatamente
después de arrancar es información valiosa, no ruido.

## Migration Plan

1. Aplicar `backend/db/migrations/012_add_event_type_and_nullable_path.sql`
   (`psql $DATABASE_URL -f ...`). Aditiva y compatible hacia atrás: el backend anterior sigue
   funcionando contra el esquema nuevo, porque `event_type` tiene default y `path` sigue aceptando
   valores no nulos.
2. Desplegar backend y frontend. El backend nuevo requiere la columna `event_type`; el orden
   1 → 2 es obligatorio.
3. Desplegar el agente. Un agente viejo contra el backend nuevo sigue ingiriendo: `event_type`
   ausente cae en el default del modelo y `path` siempre viene. Un agente nuevo contra un backend
   viejo pierde `event_type` (como hoy) y falla al ingerir un `detection_gap` por `NOT NULL` en
   `path`; el evento queda en el PEL y se reintenta tras el paso 1, sin pérdida.
4. Re-correr las baterías del Capítulo 5 contra el sistema migrado y regenerar `resultados/`.

**Rollback.** El código revierte por despliegue. El esquema **no necesita revertirse**: `event_type`
es una columna extra que el backend anterior ignora, y `path` nullable acepta todo lo que el backend
anterior escribe. Si se revirtiera de todos modos, `ALTER COLUMN path SET NOT NULL` fallaría
mientras existan filas de `detection_gap`; habría que borrarlas primero, lo que destruye
precisamente la evidencia que esta change existe para preservar. **No revertir el esquema.**

## Open Questions

Ninguna. Las tres decisiones normativas (D49/RN-143, D50/RN-144, D51/RN-145) están cerradas en
`docs/reglas_de_negocio.md` y cubren todos los puntos de ambigüedad que aparecieron durante el
diseño: valor de la atribución no resuelta, criterio de deduplicación, vocabulario y nulabilidad del
modelo, y severidad de un evento sin ruta.
