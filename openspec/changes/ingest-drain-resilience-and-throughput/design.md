## Context

Esta change aplica **D87/RN-181** sobre el carril de ingesta, con la ampliación del 2026-10-02
(`docs/reglas_de_negocio.md:2791`, `docs/arquitectura_stack.md:2727`, commit `9e15858`), que cerró
los puntos abiertos de una versión anterior de este documento: valores de los timeouts, caché sólo
de éxitos, `NOGROUP` también en `command_ack` y criterio de medición del `INSERT` por lote. Las referencias `archivo:línea` son
de `devel` en `7306ecc`; las Changes 67 y 68 tocan `consumer.py` antes que esta, así que
`/opsx:apply` MUST re-verificarlas antes de editar.

**Estado actual — cliente Valkey.** `backend/app/core/valkey.py` construye dos clientes con
`from_url(url, decode_responses=True, **_tls_kwargs(url))`: el async en
`build_async_valkey_client` (`:72`) y el sync en `init_valkey` (`:77`). Ninguno fija timeouts. El
cliente async que crea `backend/app/main.py:137` es **compartido** por tres tareas: el consumer de
eventos (`:138`), el de heartbeat (`:139`) y el de `command_ack` (`:140`). Los tres hacen lecturas
bloqueantes con `BLOCK` de 2.000 ms (`events/consumer.py:116`, `agents/heartbeat_consumer.py:40`,
`agents/command_ack_consumer.py:68`).

**Estado actual — bucle del consumer.** `run_consumer` (`events/consumer.py:237-264`) tiene dos
fases. La de arranque (`:239-254`) llama a `_ensure_group` (`:267-275`) y relee la PEL con id `0`,
reintentando cada segundo. La principal (`:257-264`) llama a `_process_batch(client, ">")` y
trata **cualquier** excepción igual: `consumer.loop_error` y `sleep(1)`. Si el group desaparece,
cada iteración falla con `NOGROUP` para siempre.

**Estado actual — costo por evento.** `_process_batch` (`:278-300`) despacha en serie por contrato
(D75/RN-169, D-2 de `ingest-offload-blocking-db`). Por cada evento válido, `_handle_message`
(`:303-502`) paga: `_get_agent_auth` en el executor (`:342`; una `Session` y un `SELECT`, medido en
1,329 ms en D75), `_ingest` en el executor (`:446-448`; `SELECT` de dedup + `INSERT` + `commit`,
~1,564 ms el `INSERT`+`commit`) y `_ack_with_event_ack` (`:645-665`), un pipeline transaccional
**por evento** con `XADD commands` + `XACK events`. A ~13 ms por evento, los dos viajes a la base
explican ~3 ms; el resto no está atribuido. No existe instrumentación por etapa.

**Estado actual — compose.** El servicio `valkey` de `docker-compose.yml:75-87` no declara
`command` (usa el default de la imagen, sin AOF) y monta `valkey_data:/data`. El override
`docker-compose.tls.yml:49-67` reemplaza el `command` entero con los flags de TLS. El backend tiene
`restart: unless-stopped` (`docker-compose.yml:47`) y ningún healthcheck propio.

**Restricciones.** Backend single-instance (RN-76). Despacho secuencial y orden FIFO (D75/RN-169).
Todo acceso síncrono a PostgreSQL desde una corrutina va al executor (D75/RN-169). El agente
resuelve `event_ack`/`event_nack` por `event_id` y reintenta tras 60 s sin respuesta
(`agent/publisher.py:11-21`). No hay revocación de agente; todo caché tiene sólo TTL (D86/RN-180).
`test_fifo_order_preserved_after_batch_drain` y
`test_no_duplicate_after_transient_db_error_and_pel_redelivery`
(`backend/tests/test_ingest_offload_blocking_db.py:140,177`) se conservan sin tocar sus aserciones.

## Goals / Non-Goals

**Goals:**

- Que el consumer se recupere solo de la pérdida del group, sin reiniciar el backend.
- Que ninguna llamada a Valkey pueda colgarse indefinidamente.
- Que el stream, sus groups y sus PEL sobrevivan a un reinicio de Valkey.
- Atribuir el costo por evento a etapas medidas antes de optimizar.
- Llegar a ≥95 ev/s (objetivo 150) con el menor cambio que alcance, en el orden de D87.

**Non-Goals:**

- Healthcheck del backend o cambios de su política de `restart`. D87 sólo pide confirmar la
  hipótesis del reinicio con `docker inspect` en la batería.
- Manejo de `NOGROUP` en el consumer de heartbeat: no usa consumer group para leer, así que no
  puede recibir `NOGROUP`. El de `command_ack` **sí** entra en el alcance (ampliación de RN-181).
- Reemplazar el limitador de ingesta (Change 67) o el almacenamiento del secreto (Change 68).
- Concurrencia entre eventos del lote. D75/RN-169 la prohíbe y esta change no la reabre.
- Reclamar entradas viejas de la PEL en caliente (`XAUTOCLAIM`). Hoy la PEL sólo se relee al
  arrancar y, con esta change, también tras recrear el group.

## Decisions

### D-1. Perfilado primero, con un único flag de settings

`consumer.timing` se implementa antes que cualquier optimización, para que cada paso posterior se
mida contra el anterior con la misma vara. El flag es un campo de `Settings`,
`fim_profile_ingest: bool = False`, que pydantic-settings lee de `FIM_PROFILE_INGEST` (el modelo no
usa `env_prefix`, `config.py:36-41`). Las duraciones se toman con `time.perf_counter()` alrededor de
cada etapa de `_handle_message` y de la emisión del acumulado en `_process_batch`. Con el flag
apagado el costo es una comparación booleana por evento.

*Alternativa descartada:* un profiler de muestreo externo (py-spy). Da una vista de CPU, pero no
separa la espera del executor ni la del round-trip a Valkey, que es justo lo que hay que atribuir, y
no queda disponible en la batería.

### D-2. Valores de los timeouts del cliente Valkey

Tres settings nuevos con estos defaults:

| Setting | Default | Razón |
|---|---|---|
| `valkey_socket_connect_timeout_seconds` | 5,0 | Acota el intento de conexión a un Valkey caído sin abortar ante latencias normales de la red interna. |
| `valkey_socket_timeout_seconds` | 10,0 | MUST superar el `BLOCK` de 2 s de los tres consumers; 5 veces ese valor deja margen ante pausas de GC o carga. |
| `valkey_health_check_interval_seconds` | 15 | La biblioteca hace `PING` antes de reutilizar una conexión inactiva por más de este intervalo; detecta las conexiones semiabiertas que deja un reinicio de Valkey. |

Los valores quedaron cerrados en la ampliación de RN-181. Se aplican a los dos clientes desde un
único helper de kwargs, junto a `_tls_kwargs`. La relación
`socket_timeout > BLOCK` la fija un test que compara el setting contra los tres `_BLOCK_MS`; no se
refactorizan las tres constantes a una sola, porque eso excede el alcance de D87.

*Alternativa descartada:* timeouts sólo en el cliente async. El sync atiende `/health/components`
y servicios de negocio; colgarse ahí también es una falla, y D87 nombra ambas líneas (`:72,77`).

### D-3. `NOGROUP` se maneja en el bucle principal, con el mismo `_ensure_group`

El `except` del bucle principal distingue un error de respuesta cuyo texto contiene `NOGROUP`
(mismo criterio por texto que `_ensure_group` ya usa con `BUSYGROUP`, `consumer.py:272`). En ese
caso: log `consumer.group_recreated`, `await _ensure_group(client)`, `await
_process_batch(client, "0")` y vuelta al bucle sin `sleep`. Si `_ensure_group` falla, cae en el
tratamiento genérico (log + `sleep(1)`) y se reintenta en la próxima iteración, que volverá a ver
`NOGROUP` si Valkey ya respondió.

El group se recrea con id `0`, igual que al arrancar. Con AOF (D-4), el group no se pierde en un
reinicio y este camino queda como defensa en profundidad para una pérdida real de datos de Valkey,
en cuyo caso el stream también se perdió y `0` no re-lee nada. Con `$` se perderían las entradas
publicadas entre la vuelta de Valkey y la recreación del group.

**Consumidor de `command_ack`.** `_reader_loop` (`agents/command_ack_consumer.py:96-122`) tiene la
misma forma: fase de arranque con `_ensure_group` (`:125-133`, group `fim-command-ack` sobre
`event_ack`, id `0`) y bucle principal que trata todo error como `command_ack_consumer.loop_error`
(`:121`). Recibe el mismo tratamiento, con su propio `_ensure_group` y su propio
`_process_batch(client, "0")`, y el evento `command_ack_consumer.group_recreated`. No se extrae un
helper común a los dos consumers: cada uno tiene su group, su stream y sus logs, y el bloque es de
pocas líneas. Perder ese group hoy tiene una consecuencia propia: los `command_ack` dejan de
procesarse y el barrido de `_sweep_loop` termina marcando como vencidos comandos que el agente sí
aplicó.

*Alternativa descartada:* romper el bucle y volver a la fase de arranque. Funciona, pero mezcla dos
responsabilidades y hace que un error de lectura pueda reiniciar el procesamiento de pendientes en
condiciones no previstas por el requisito de arranque.

### D-4. AOF por `command`, con los flags repetidos en el override

El compose base agrega `command: ["valkey-server", "--appendonly", "yes", "--appendfsync",
"everysec"]`. El override TLS, cuyo `command` reemplaza al del base, agrega los mismos dos flags a
su lista. `everysec` acota la pérdida a ~1 s de escrituras ante un corte duro, que el agente cubre
republicando desde su cola durable. El AOF vive en `valkey_data:/data`, que ya existe.

*Alternativa descartada:* un `valkey.conf` montado. Agrega un archivo y un montaje para dos
parámetros, y obliga a re-declarar en él los flags de TLS que hoy viven en el override.

### D-5. Caché de autenticación sólo positivo, accedido desde el event loop

Un diccionario de módulo `agent_id → (_AgentAuth, expira_en)` con `time.monotonic()`. Una corrutina
`_resolve_agent_auth(agent_id)` consulta el caché en el event loop; ante fallo o vencimiento,
despacha `_get_agent_auth` al executor (D75/RN-169) y, al volver al loop, guarda el resultado
**sólo si tiene secreto**. Como lectura y escritura ocurren en el loop, no hace falta lock.
`_handle_message` (`:342`) y `_reject` (`:609-611`, vía `_get_shared_secret`) pasan a usar esta
corrutina. `_get_agent_auth` lee el secreto con el helper único de la Change 68; esta change no
toca cómo se desenvuelve.

No se cachean resultados negativos por dos razones: un `agent_id` falso por evento haría crecer el
caché sin límite, y un negativo cacheado podría rechazar como `unknown_agent` —con `XACK` y en
silencio— un evento de un agente recién enrolado. El costo es que un `agent_id` desconocido sigue
consultando la base por cada evento, como hoy.

*Alternativa descartada:* `functools.lru_cache` con TTL de biblioteca. No hay TTL en la biblioteca
estándar y una dependencia nueva no se justifica para un diccionario de pocas entradas.

### D-6. Acumulador de ACK por lote, opcional en `_handle_message`

`_process_batch` crea un acumulador y se lo pasa a `_handle_message`. En las tres ramas que hoy
llaman a `_ack_with_event_ack` (dedup `:489-492`, persistido `:494-497`, carrera `:498-502`) y que
sólo se alcanzan después de que `_ingest` retornó —es decir, después del `commit`—, el mensaje se
agrega `(msg_id, data_firmada)` al acumulador en lugar de emitirse. Al terminar el lote, un
`finally` emite el acumulado en un pipeline transaccional: un `XADD commands` por evento y un único
`XACK events` con todos los ids. Con los dobles de prueba asyncio que no exponen `pipeline` se
conserva la secuencia actual de `_ack_with_event_ack`: primero los `XADD`, después el `XACK`.

Si `_handle_message` se invoca **sin** acumulador —como en
`test_no_duplicate_after_transient_db_error_and_pel_redelivery`, que la llama directo y espera un
único `xack`—, emite de inmediato como hoy. Rechazos e `InvalidTransitionError` no cambian: su
`XACK` y su `event_nack` siguen siendo inmediatos, porque no se apoyan en un `commit` de `events`.

La notificación (`_fire_and_forget(notify_if_applicable(...))`, `:497`) se sigue agendando
apenas el evento queda persistido. Depende del `commit`, no del ACK, y diferirla hasta el final del
lote sólo agregaría latencia al carril de notificación (D76/RN-170).

*Alternativa descartada:* emitir el acumulado cada K eventos o cada T ms. Agrega un segundo
parámetro sin evidencia de que haga falta; el lote ya está acotado a 50 mensajes (`:117`).

### D-7. `INSERT` por lote sólo con evidencia y con un addendum previo

Todas las mediciones de desarrollo (línea base, tras D-5 y tras D-6) se toman con el arnés de
`lab/` (`lab/bateria4_publicador.py` para inyectar eventos firmados en el stream, con el backend
del build de desarrollo y `FIM_PROFILE_INGEST=1`) y se guardan en `mediciones.md`, dentro de la
carpeta de esta change: fecha, commit, comando exacto, cantidad de eventos, ev/s y desglose de
`consumer.timing` por etapa. Ese archivo es la evidencia de la decisión; no es un resultado de la
tesis, cuya re-medición sobre `v5.0-tesis` sigue siendo única (Change 61).

Si la medición tras D-5 y D-6 queda por debajo de 95 ev/s, el `INSERT` por lote se diseña en un
addendum de este documento **antes** de escribir código. Ese addendum MUST resolver: el dedup de
`event_id` dentro del mismo lote, la cadena `superseded` cuando dos eventos del lote comparten ruta,
la compactación (RN-98, en la misma transacción), la granularidad del rollback ante
`SQLAlchemyError` y su relación con el acumulado de ACK. Si la medición alcanza el mínimo, la change
registra el número y no lo implementa.

## Risks / Trade-offs

- **[Riesgo] Un caché de 5 s mantiene vivo un secreto rotado.** → El secreto sólo se escribe en el
  enrolamiento (`agents/service.py:79`) y `bootstrap_secret_hash` se anula en ese mismo paso
  (`:80`). La ampliación de D86/RN-180 declara que no hay rotación en `v5.0-tesis`. Si se agrega,
  esta ventana se documenta junto con ella.
- **[Riesgo] El ACK por lote retrasa la confirmación hasta el final del lote.** → Con 50 mensajes a
  ≥95 ev/s son ≲0,5 s, contra una ventana de 60 s del agente.
- **[Riesgo] Una entrada que queda en la PEL tras una falla del pipeline se relee recién al
  reiniciar o al recrear el group; si para entonces su `sent_at` cayó fuera de la ventana de 5 min,
  la validación de clock skew (paso 4) la rechaza antes del dedup (paso 6) y escribe una fila en
  `rejected_events_audit`.** → Comportamiento preexistente, idéntico al del `SQLAlchemyError`. El
  agente ya resolvió el evento por republicación (dedup → `event_ack`), y el `event_nack` resultante
  lo ignora por contención (D-4 de D37). No se pierde ni se duplica el evento.
- **[Riesgo] Activar AOF sobre un volumen con un snapshot RDB previo.** → La ampliación de RN-181
  exige verificarlo en Valkey 9.0.3 **antes de etiquetar** `v5.0-tesis`: el primer arranque con
  `appendonly yes` debe conservar los datos del RDB existente.
- **[Riesgo] Un group recreado con id `0` sobre un stream que **sí** sobrevivió (por ejemplo, un
  `XGROUP DESTROY` manual) relee el stream completo.** → Cada entrada vieja termina en dedup o en
  rechazo por clock skew; no hay duplicados ni pérdida, pero sí filas de auditoría. Se documenta;
  con AOF el caso exige intervención manual.
- **[Trade-off] El caché sólo positivo no protege a la base de un flujo de `agent_id` falsos.** →
  Ese caso ya lo cubren la firma HMAC y el carril de rechazo; no es objetivo de D87.

## Migration Plan

1. Mergear después de archivar las Changes 67 y 68.
2. `docker compose up -d valkey` recrea el contenedor con AOF; el volumen se conserva.
3. Reiniciar el backend para tomar los timeouts y el código nuevo.
4. Rollback: revertir el commit y recrear `valkey` y `backend`. El AOF es compatible con un
   arranque posterior sin `appendonly` (Valkey vuelve a usar RDB).

## Open Questions

Ninguna. Los tres puntos abiertos de la versión anterior (valores de los timeouts, `NOGROUP` en
`command_ack` y arnés de la medición de desarrollo) quedaron cerrados en la ampliación de
D87/RN-181 del 2026-10-02.
