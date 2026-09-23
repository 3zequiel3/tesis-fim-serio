# backend-notifications Specification

## Purpose
TBD - created by archiving change backend-notifications. Update Purpose after archive.
## Requirements
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

### Requirement: Envío al canal n8n con retry exponencial 3x

El sistema SHALL intentar enviar `POST {N8N_WEBHOOK_URL}` con timeout 10s. Si falla, MUST esperar 5 segundos y reintentar; si vuelve a fallar, MUST esperar 30 segundos; si falla de nuevo (3er intento), MUST esperar 120 segundos. Si el 4to intento (contando el primero) también falla, MUST marcar la fila en `alerts` con `failed_at=now()`, `last_error=<mensaje>`, `retry_count=3`. En cualquier intento exitoso MUST actualizar `alerts` con `delivered_at=now()`, `channel=n8n`, `retry_count=<intentos_realizados>`.

#### Scenario: Entrega exitosa en primer intento
- **WHEN** n8n responde 2xx en el primer intento
- **THEN** `alerts.delivered_at` está poblado, `alerts.channel = n8n`, `retry_count = 0`

#### Scenario: Entrega exitosa en tercer intento
- **WHEN** n8n falla los primeros 2 intentos y responde 2xx en el 3ro
- **THEN** `alerts.delivered_at` está poblado, `retry_count = 2`

#### Scenario: Fallo total de n8n — DLQ
- **WHEN** n8n falla en los 4 intentos
- **THEN** la cascada continúa con el canal SMTP (si configurado); si todos los canales fallan, `alerts.failed_at` está poblado y `delivered_at IS NULL`

### Requirement: Cascada de canales — SMTP → webhook_fallback → log_only

Si n8n falla en todos sus reintentos, el sistema SHALL intentar los canales en orden:
1. `smtp_fallback` — solo si `SMTP_HOST` está configurado; envía email async con `aiosmtplib`, respetando `smtp_starttls` / `smtp_ssl`.
2. `webhook_fallback` — solo si `WEBHOOK_FALLBACK_URL` está configurado; `POST` async con httpx.
3. `log_only` — SIEMPRE ejecutado como piso (RN-54); emite log estructurado de nivel `critical`.

El valor de retorno de `_try_cascade` MUST distinguir dos escenarios (D23, RN-120):
- Al menos un canal configurado (n8n / SMTP / webhook_fallback) tuvo éxito → retorna `(True, canal)`. La alerta queda marcada como entregada con `delivered_at=now()` y `channel=<canal>`.
- Todos los canales configurados fallaron → `log_only` se ejecuta igualmente como piso (RN-54, no puede fallar), pero `_try_cascade` retorna `(False, None)`. El retry loop de `notify_event` continúa su ciclo de espera (RETRY_DELAYS) y, tras agotar todos los reintentos, setea `failed_at=now()` en la fila `alerts`. La alerta queda en la DLQ (`failed_at NOT NULL AND delivered_at IS NULL`).
- Si NO hay ningún canal primario configurado (n8n, SMTP y webhook_fallback todos ausentes), `log_only` es el canal intencional y `_try_cascade` retorna `(True, AlertChannel.log_only)`.

Cada canal actualiza `alerts.channel` con el canal que finalmente se usó para la entrega exitosa.

El payload que recorre la cascada SHALL ser el definido por `notification-payload-contract` (D40/RN-134), idéntico en todos los canales.

#### Scenario: SMTP entrega cuando n8n está caído
- **WHEN** n8n falla 4 veces y SMTP_HOST está configurado
- **THEN** se intenta envío SMTP; si exitoso, `alerts.channel = smtp_fallback` y `delivered_at` poblado

#### Scenario: log_only cuando no hay canales configurados — entrega exitosa
- **WHEN** `N8N_WEBHOOK_URL`, `SMTP_HOST` y `WEBHOOK_FALLBACK_URL` son None (no configurados)
- **THEN** se emite log crítico y `alerts.channel = log_only`, `delivered_at = now()`

#### Scenario: Canales configurados fallan — log_only como piso y alerta a DLQ
- **WHEN** `N8N_WEBHOOK_URL` está configurado pero n8n falla en los 4 intentos
- **AND** SMTP y webhook_fallback no están configurados
- **THEN** en cada intento se emite log crítico vía log_only (RN-54)
- **AND** tras agotar RETRY_DELAYS, `alerts.failed_at` está poblado y `delivered_at IS NULL`
- **AND** la alerta aparece en `GET /alerts/failed`

#### Scenario: Canal configurado como N8N_WEBHOOK_URL vacío — degraded
- **WHEN** `N8N_WEBHOOK_URL` no está configurado
- **THEN** el canal n8n se salta y se intenta directamente el siguiente canal disponible

#### Scenario: El payload no se degrada en el fallback
- **WHEN** la cascada entrega por `webhook_fallback` tras fallar n8n
- **THEN** el cuerpo enviado contiene los mismos campos de `notification-payload-contract` que se habrían enviado a n8n

### Requirement: GET /alerts/failed — DLQ de alertas fallidas

El sistema SHALL exponer `GET /alerts/failed` (requiere JWT admin) que retorna alertas con `delivered_at IS NULL AND failed_at IS NOT NULL`, ordenadas por `failed_at DESC`. La respuesta SHALL ser `{"items": [...], "total": int}`. Cada ítem incluye `id`, `event_id`, `severity`, `channel`, `failed_at`, `last_error`, `retry_count`, `created_at`.

#### Scenario: DLQ retorna solo alertas fallidas
- **WHEN** existen 2 alertas entregadas y 1 fallida, y se hace `GET /alerts/failed`
- **THEN** la respuesta contiene `total=1` con solo la alerta fallida

#### Scenario: DLQ vacía retorna lista vacía
- **WHEN** no hay alertas fallidas
- **THEN** la respuesta es `{"items": [], "total": 0}`

### Requirement: POST /alerts/{id}/retry — reintento manual desde DLQ

El sistema SHALL exponer `POST /alerts/{id}/retry` (requiere JWT admin) que toma una alerta fallida (`failed_at IS NOT NULL`) y la re-intenta enviando la notificación. MUST resetear `failed_at=null`, `last_error=null`, `retry_count=0` antes de re-intentar. Si el alerta no existe o ya fue entregada → 404 o 409. Cada reintento aceptado MUST registrar una fila en `audit_log` (RN-94, US-29) con `action="alert_retry"`, `user_id` del admin, `target_type="alert"`, `target_id` igual al id de la alerta y `detail` con el `event_id`, confirmada en el mismo commit que el reset. Un reintento rechazado con 404 o 409 MUST NOT dejar fila en `audit_log`. El reintento masivo del frontend, que emite una llamada por alerta, MUST producir una fila por alerta reintentada.

#### Scenario: Retry exitoso
- **WHEN** un admin hace `POST /alerts/42/retry` y el canal n8n responde 2xx
- **THEN** `alerts.delivered_at` está poblado y la alerta ya no aparece en `GET /alerts/failed`

#### Scenario: Retry registra audit_log
- **WHEN** un admin hace `POST /alerts/42/retry` sobre una alerta fallida
- **THEN** existe una fila en `audit_log` con `action="alert_retry"`, `user_id` del admin, `target_type="alert"` y `target_id=42`

#### Scenario: Reintento masivo deja una fila por alerta
- **WHEN** un admin reintenta las alertas fallidas 41, 42 y 43 con una llamada `POST /alerts/{id}/retry` por cada una
- **THEN** existen tres filas `alert_retry` en `audit_log`, con `target_id` 41, 42 y 43

#### Scenario: Retry de alerta ya entregada retorna 409
- **WHEN** la alerta ya tiene `delivered_at NOT NULL`
- **THEN** la respuesta es `409 Conflict`
- **AND** no se escribe ninguna fila en `audit_log`

#### Scenario: Alerta no encontrada retorna 404
- **WHEN** el `id` no existe en `alerts`
- **THEN** la respuesta es `404 Not Found`
- **AND** no se escribe ninguna fila en `audit_log`

### Requirement: DELETE /alerts/{id} — descartar alerta de la DLQ

El sistema SHALL exponer `DELETE /alerts/{id}` (requiere JWT admin) que elimina la fila de `alerts`. Permite descartar alertas de la DLQ que no se desean reintentar. Cada descarte MUST registrar una fila en `audit_log` (RN-94, US-29) con `action="alert_discard"`, `user_id` del admin, `target_type="alert"`, `target_id` igual al id de la alerta y `detail` con el `event_id`, confirmada en el mismo commit que la eliminación. Un descarte rechazado con 404 MUST NOT dejar fila en `audit_log`.

#### Scenario: Delete exitoso
- **WHEN** existe la alerta con `id=42` y se hace `DELETE /alerts/42`
- **THEN** la respuesta es `204 No Content` y la fila ya no existe en DB

#### Scenario: Delete registra audit_log
- **WHEN** un admin hace `DELETE /alerts/42` sobre una alerta existente con `event_id=7`
- **THEN** existe una fila en `audit_log` con `action="alert_discard"`, `target_type="alert"`, `target_id=42` y `detail` que contiene `event_id=7`

#### Scenario: Delete de alerta inexistente retorna 404
- **WHEN** el `id` no existe
- **THEN** la respuesta es `404 Not Found`
- **AND** no se escribe ninguna fila en `audit_log`

### Requirement: Retry manual de alerta con referencia fuerte a la task asyncio

El endpoint `POST /alerts/{id}/retry` MUST guardar una referencia fuerte a la `asyncio.Task` creada para `notify_event`. La referencia SHALL mantenerse en un `set` module-level hasta que la task complete, previniendo cancelación silenciosa por el GC durante los sleeps del retry loop (hasta 120 s de espera).

#### Scenario: Task de reintento no es cancelada durante sleep

- **WHEN** un operador llama `POST /alerts/{id}/retry` y `notify_event` está esperando en `asyncio.sleep(30)`
- **THEN** la task mantiene una referencia fuerte durante el sleep
- **AND** el GC no puede cancelar la task antes de que complete el reintento

### Requirement: `_build_payload` produce el contrato canónico

`_build_payload` en `app/modules/alerts/service.py` SHALL producir el payload definido por la capability `notification-payload-contract` (D40/RN-134). El payload SHALL derivarse de la fila `Event` asociada a la alerta, leyendo las columnas ya persistidas — SHALL NO requerir captura adicional por parte del agente ni migración de esquema.

El mismo payload SHALL usarse en todos los canales de la cascada (n8n, `smtp_fallback`, `webhook_fallback`, `log_only`), de modo que un fallback no entregue menos información que el canal principal.

#### Scenario: El payload se arma desde el Event persistido
- **WHEN** se notifica una alerta cuyo `Event` tiene `process_pid=4242`, `process_uid=0` y `process_exe="/usr/bin/curl"`
- **THEN** el payload emitido contiene esos tres valores
- **AND** no se consulta al agente para obtenerlos

#### Scenario: El fallback entrega la misma información
- **WHEN** n8n falla y la cascada entrega por `smtp_fallback`
- **THEN** el contenido enviado por SMTP se deriva del mismo payload que se intentó enviar a n8n

### Requirement: Configuración explícita de TLS para SMTP

`Settings` SHALL exponer `smtp_starttls` y `smtp_ssl` como booleanos configurables. `send_smtp` SHALL NO forzar `start_tls=True` de manera incondicional.

El comportamiento SHALL ser:
- `smtp_ssl=true` → conexión TLS implícita (SMTPS, típicamente puerto 465); `start_tls` no se aplica.
- `smtp_starttls=true` y `smtp_ssl=false` → conexión en claro con `STARTTLS` (típicamente puerto 587). Este SHALL ser el default, preservando el comportamiento actual.
- ambos `false` → conexión sin cifrar, admitida sólo para relays internos.

Declarar ambos en `true` SHALL considerarse configuración inválida y SHALL registrarse como error.

#### Scenario: Relay en 465 con TLS implícito
- **WHEN** `smtp_ssl=true` y el relay escucha SMTPS en 465
- **THEN** el envío se realiza sobre TLS implícito y no se invoca `STARTTLS`

#### Scenario: Default preserva el comportamiento actual
- **WHEN** no se configura `smtp_starttls` ni `smtp_ssl`
- **THEN** el envío usa `STARTTLS`, igual que antes de este change

#### Scenario: Relay interno sin TLS
- **WHEN** `smtp_starttls=false` y `smtp_ssl=false`
- **THEN** el envío se realiza sin cifrado y no falla por ausencia de `STARTTLS`

#### Scenario: Configuración contradictoria
- **WHEN** `smtp_starttls=true` y `smtp_ssl=true`
- **THEN** el sistema registra un error de configuración identificando ambas variables

### Requirement: GET /alerts/failed/count — conteo de la DLQ para el banner

El sistema SHALL exponer `GET /alerts/failed/count` (requiere JWT admin) que responde `{"count": int}` con la cantidad de alertas que cumplen `delivered_at IS NULL AND failed_at IS NOT NULL` (US-29, US-05, D6/RN-102) — la misma definición de fallo terminal que `list_failed_alerts`, **sin** umbral adicional de `retry_count`: una alerta agotada con `retry_count = 0` (n8n sin configurar) MUST contarse igual que una con `retry_count = 3`. La ruta MUST resolverse antes que cualquier ruta con parámetro `/{alert_id}`.

#### Scenario: Cuenta alertas en fallo terminal, sin importar retry_count
- **WHEN** existen una alerta entregada, una alerta fallida con `retry_count = 3`, una alerta fallida con `retry_count = 0` (n8n sin configurar) y una alerta pendiente
- **THEN** `GET /alerts/failed/count` responde `{"count": 2}`

#### Scenario: DLQ vacía cuenta cero
- **WHEN** no hay alertas con `failed_at IS NOT NULL`
- **THEN** la respuesta es `{"count": 0}`

#### Scenario: Requiere admin
- **WHEN** se llama `GET /alerts/failed/count` sin token válido
- **THEN** la respuesta es `401`

