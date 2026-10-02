## Why

El carril de ingesta tiene dos defectos que la guía de laboratorio v29 hizo visibles y que se
verificaron contra el código en `devel` (`7306ecc`): no tolera bien la pérdida de Valkey y no
alcanza el rendimiento mínimo que la evaluación necesita.

**Resiliencia.** Los dos clientes Valkey se construyen con `from_url` sin ningún timeout
(`backend/app/core/valkey.py:72` para el cliente async y `:77` para el sync): ni
`socket_timeout`, ni `socket_connect_timeout`, ni `health_check_interval`. Una conexión
semiabierta tras un corte de Valkey puede dejar una llamada colgada indefinidamente. Además, el
bucle principal de `run_consumer` (`backend/app/modules/events/consumer.py:257-264`) trata todo
error como transitorio —loguea `consumer.loop_error` y duerme 1 s— y `_ensure_group`
(`consumer.py:267-275`) sólo se invoca en el bloque de arranque (`:239-254`). Si Valkey vuelve
sin el consumer group —que es exactamente lo que ocurre hoy, porque Valkey corre **sin AOF** en
`docker-compose.yml:75-87` y en `docker-compose.tls.yml:49-67`—, cada `XREADGROUP` responde
`NOGROUP` y el consumer queda en un bucle de error permanente hasta que el backend se reinicie. En
run-03 el backend empezó a consumir 33,5 s después de restaurar Valkey; la hipótesis de D87 es un
reinicio del contenedor (`restart: unless-stopped`, `docker-compose.yml:47`, sin healthcheck), a
confirmar con `docker inspect` en la batería.

**Rendimiento.** La ingesta ronda los 76 ev/s (~13 ms por evento). D87/RN-181 fija un mínimo de
95 ev/s con objetivo de 150. El despacho es secuencial por contrato (`_process_batch`,
`consumer.py:278-300`, D75/RN-169) y cada evento paga, en serie: una consulta de autenticación a
PostgreSQL (`_get_agent_auth`, `consumer.py:535-547`, despachada al executor en `:342`), la
ingesta transaccional (`_ingest`, `consumer.py:507-524`, en el executor en `:446-448`) y un
round-trip a Valkey propio para `XADD event_ack` + `XACK` (`_ack_with_event_ack`,
`consumer.py:645-665`). No existe hoy instrumentación por etapa que diga cuál de los tres domina.

Origen: guía de laboratorio de la tesis v29 (ítems L-2…L-9). La decisión que gobierna esta change
ya está cerrada: **D87/RN-181** (`docs/arquitectura_stack.md:2727`,
`docs/reglas_de_negocio.md:2777`), con su ampliación del 2026-10-02
(`docs/reglas_de_negocio.md:2791`, commit `9e15858`) que fija los valores de los timeouts, el caché
sólo de éxitos, el `NOGROUP` también en el consumidor de `command_ack` y el criterio de medición
del `INSERT` por lote. Depende de **D85/RN-179** (Change 67) y **D86/RN-180**
(Change 68), y preserva **D40/RN-134**, **D41/RN-135**, **D75/RN-169** y **D76/RN-170**.

## What Changes

- **Timeouts del cliente Valkey.** `build_async_valkey_client` e `init_valkey`
  (`backend/app/core/valkey.py:68-77`) pasan `socket_timeout`, `socket_connect_timeout` y
  `health_check_interval`, expuestos como settings con defaults de 5, 10 y 15 s respectivamente
  (ampliación de RN-181). `socket_timeout` MUST superar el
  mayor `BLOCK` de los `XREADGROUP`/`XREAD` que comparten el cliente (hoy 2.000 ms en los tres
  consumers), o el bloqueo normal se convertiría en un timeout espurio.
- **`NOGROUP` → `_ensure_group` dentro del bucle.** El bucle principal de `run_consumer` reconoce
  el error `NOGROUP`, recrea el group con `_ensure_group` y relee la PEL antes de volver a `>`,
  sin reiniciar el proceso. El mismo tratamiento se aplica al lector del consumidor de
  `command_ack` (`_reader_loop`, `backend/app/modules/agents/command_ack_consumer.py:96-122`), que
  tiene el mismo defecto y también recrea su group `fim-command-ack` desde `0`.
- **AOF en Valkey.** `--appendonly yes --appendfsync everysec` en `docker-compose.yml` y en
  `docker-compose.tls.yml` (el override reemplaza el `command` completo, así que los flags se
  repiten ahí).
- **Perfilado opcional `consumer.timing`.** Con `FIM_PROFILE_INGEST=1`, un log por evento con la
  duración de cada etapa (autenticación, validación, ingesta, ACK). Apagado por defecto y sin costo
  medible cuando está apagado. Se implementa **primero**: las optimizaciones siguientes se miden
  contra él.
- **Caché de `_get_agent_auth` con TTL de 5 s.** Sólo TTL, porque no existe revocación de agente
  (D86/RN-180), y sólo de resoluciones exitosas (ampliación de RN-181). Lee el secreto mediante el helper único que introduce la Change 68.
- **`XACK` + `event_ack` por lote.** `_process_batch` acumula las respuestas de los eventos ya
  commiteados y las emite en un único pipeline al final del lote. Ninguna entrada se acumula antes
  de que el `commit` de su evento haya retornado.
- **`INSERT` por lote, sólo condicional.** Se decide con el arnés de `lab/` sobre el build de
  desarrollo y la medición se guarda en la carpeta de la change. Si con lo anterior el rendimiento
  medido sigue por debajo de 95 ev/s, se agrupan los `INSERT`, preservando el orden FIFO y la cadena `superseded`.
  Si se alcanza el mínimo, esta parte **no se implementa** y la change lo registra.
- **Re-corrida del arnés unificado sobre `v5.0-tesis`** registrada con su resultado, **sin declarar
  mejora anticipada**.

No hay cambios **BREAKING** de contrato: el protocolo `event_ack`/`event_nack` no cambia de forma,
sólo el instante en que se emite dentro del lote, y el agente lo resuelve por `event_id` con una
ventana de 60 s (`agent/publisher.py:11-21`).

## Capabilities

### New Capabilities

Ninguna. Los cambios son requisitos nuevos sobre capabilities existentes.

### Modified Capabilities

- `backend-event-consumer`: el bucle principal recrea el group ante `NOGROUP`; la autenticación del
  agente se cachea con TTL de 5 s; `XACK` + `event_ack` se emiten por lote después de cada
  `commit`; perfilado `consumer.timing` bajo `FIM_PROFILE_INGEST=1`; piso de rendimiento de
  95 ev/s y `INSERT` por lote condicional.
- `backend-command-ack`: el lector del consumidor de `command_ack` recrea su group ante `NOGROUP`
  sin reiniciar el backend.
- `backend-core`: el cliente Valkey (sync y async) fija `socket_timeout`, `socket_connect_timeout`
  y `health_check_interval`.
- `infra-compose`: Valkey corre con AOF (`appendonly yes`, `appendfsync everysec`) en el compose
  base y en el override TLS.

## Impact

**Backend** — `backend/app/core/valkey.py` (`build_async_valkey_client`, `init_valkey`),
`backend/app/core/config.py` (settings de timeouts y `fim_profile_ingest`),
`backend/app/modules/events/consumer.py` (`run_consumer`, `_process_batch`, `_handle_message`,
`_get_agent_auth`, `_get_shared_secret`, `_ack_with_event_ack`),
`backend/app/modules/agents/command_ack_consumer.py` (`_reader_loop`). El limitador de ingesta
(`_RateLimiter`) **no** se toca: lo reemplaza la Change 67.

**Compose** — `docker-compose.yml` (servicio `valkey`), `docker-compose.tls.yml` (`command` del
servicio `valkey`). El volumen `valkey_data:/data` ya existe y aloja el AOF.

**Dependencias de roadmap** — Change 67 (`ingest-token-bucket-rate-limit`) y Change 68
(`agent-secret-wrap-at-rest`) tocan `consumer.py`; la 68 además provee el helper de lectura del
secreto que usa el caché. **Ninguna de las dos está creada ni archivada** a la fecha de esta
propuesta: `/opsx:apply` de esta change MUST esperar a que ambas estén archivadas, y las
referencias `archivo:línea` de los artefactos se re-verifican entonces.

**Tests** — MUST seguir en verde sin modificar sus aserciones:
`test_fifo_order_preserved_after_batch_drain` (`backend/tests/test_ingest_offload_blocking_db.py:140`)
y `test_no_duplicate_after_transient_db_error_and_pel_redelivery` (`:177`). Se agregan tests para
`NOGROUP`, timeouts, caché, ACK por lote y el orden ACK-después-de-commit.

**Resultados de la tesis** — la medición oficial es la re-corrida única sobre `v5.0-tesis`
(Change 61) y sigue siendo única. Las mediciones de desarrollo de esta change se toman con el
arnés de `lab/`, se guardan en `mediciones.md` dentro de la carpeta de la change y sólo deciden si
el `INSERT` por lote hace falta; no se reportan como resultado.
