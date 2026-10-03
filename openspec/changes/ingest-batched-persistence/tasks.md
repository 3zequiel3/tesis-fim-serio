## 0. Precondiciones

- [x] 0.1 Confirmar con `openspec list --json` y `fd . openspec/changes/archive` que las Changes 67 (`ingest-token-bucket-rate-limit`), 68 (`agent-secret-wrap-at-rest`) y 69 (`ingest-drain-resilience-and-throughput`) están archivadas. Si alguna no lo está, detenerse.
- [x] 0.2 Re-verificar contra el árbol actual las referencias `archivo:línea` de `design.md` (tomadas en `ada3d4e`): `_process_batch`, `_handle_message`, `_ingest`, `_ack_or_defer`, `_flush_acks`, `_reject`, `_RateLimiter` en `events/consumer.py`; `_ingest_event_outcome`, `get_pending_event_for_path`, `mark_superseded`, `compact_chain` en `events/service.py`; `determine_severity_for_path` en `rules/service.py`; `_create_alert_row`, `notify_if_applicable`, `_mark_delivered` en `alerts/service.py`. Anotar desplazamientos en este archivo antes de editar.
  - Verificado en `32d9e5d`: sin desplazamientos relevantes (±1 línea: `run_in_executor` de `_ingest` en `consumer.py:548-551`; el resto coincide con `design.md`).
- [x] 0.3 Correr la suite de backend y `python3 scripts/check_spec_integrity.py` en la base y anotar cualquier falla preexistente como evidencia.
  - Base: 1061 passed / 4 skipped (147,8 s), sin fallas; `check_spec_integrity.py`: OK, 58 specs, 446 requisitos.

## 1. Banco sin stub y línea base (D-1)

- [x] 1.1 En `lab/bench_ingest_consumer.py`, agregar `--notify {stub,real}` (default `stub`, el comportamiento actual). En `real`: no reemplazar `notify_if_applicable`; sembrar una regla de severidad `high` que matchee las rutas del banco; levantar un sumidero HTTP local que responda 2xx y, por cada pedido, inserte y confirme una fila en una base `bench_n8n` de la misma instancia de PostgreSQL (crearla si no existe); apuntar `settings.n8n_webhook_url` a ese sumidero.
- [x] 1.2 Agregar `--paths N` (default: una ruta por evento, el comportamiento actual) que reparta los eventos sobre N rutas en orden cíclico, para reproducir la repetición del generador (600 rutas para 3.000 eventos).
- [x] 1.3 En modo `real`, cada drenaje MUST esperar, además de los N `event_ack`, a que las N alertas tengan `delivered_at`, y registrar por separado el tiempo hasta el último `event_ack` (ev/s de ingesta) y hasta la última entrega. Verificar al final de cada drenaje N filas en `events`, PEL vacía y N filas en el sumidero.
- [x] 1.4 Agregar `commit_ms` al `consumer.timing` por evento del camino por evento (perfilado bajo `fim_profile_ingest`, medido alrededor del `session.commit()` de `_ingest_event_outcome` y devuelto en el resultado, sin loguear desde el hilo del executor), con su test.
- [x] 1.5 Crear `mediciones.md` en la carpeta de esta change con el formato de la Change 69 (fecha, commit, host, servicios, comando exacto, eventos, ev/s por corrida y mediana, desglose de `consumer.timing`) y la aclaración de que son mediciones de desarrollo, no resultados de la tesis.
- [x] 1.6 Medir la línea base sobre el código actual, sin cambios de ingesta: `--notify stub` (comparable con la Change 69) y `--notify real --paths 600`, 3.000 eventos, 3 repeticiones más una perfilada. Registrar en `mediciones.md`, con la fracción de `commit_ms` dentro de `ingest_ms`.
- [x] 1.7 Contrastar la atribución de `design.md` con 1.6: si `ingest_ms` en modo `real` no crece respecto de `stub` o si `commit_ms` es marginal, detenerse y reabrir el diseño antes del grupo 2; anotar la conclusión en `mediciones.md`.
  - **STOP (2026-10-03):** `commit_ms` = 1,085 ms = 6,8 % de `ingest_ms` en modo `real` (15,85 ms, 62 ev/s) contra 5,05-5,91 ms y 170-178 ev/s en `stub`; la hipótesis de contención en el `COMMIT` queda contradicha. Ver `mediciones.md` §1. Grupo 2 no iniciado. Con la revisión del diseño (fases A y B) ese grupo pasó a ser la fase B condicional, grupo 5; la causa medida (cliente HTTP por entrega, 81,4 ev/s con `verify=False`) abre la fase A, grupos 2–4.

## 2. Fase A — cliente HTTP de larga vida (A-1, A-2, A-3)

- [x] 2.1 Verificar el `keepAliveTimeout` efectivo del servidor HTTP de n8n 2.17.8 (default de Node, 5 s, salvo que n8n lo cambie): leerlo en el código o la configuración de n8n o medirlo contra el contenedor. Si es menor o igual a 4 s, bajar `keepalive_expiry` por debajo de ese valor y anotarlo acá y en la fila D87.
  - Medido sobre la imagen `n8nio/n8n:2.17.8` (contenedor descartable, no el del usuario): `http.createServer().keepAliveTimeout` = 5000 ms (Node v24.14.1) y `rg keepAliveTimeout` no encuentra override en `dist` de n8n. Se mantiene `keepalive_expiry=4,0 s`.
- [x] 2.2 En `backend/app/modules/alerts/notifier.py`, agregar `init_notify_http_client()`, `get_notify_http_client()` (creación perezosa con la misma configuración si no existe) y `close_notify_http_client()` (`aclose()` y descarte). Configuración: verificación TLS por defecto de httpx (nunca `verify=False`), `httpx.Limits(max_connections=settings.notify_max_concurrent_deliveries, max_keepalive_connections=settings.notify_max_concurrent_deliveries, keepalive_expiry=4.0)`.
- [x] 2.3 En `send_n8n` y `send_webhook_fallback`, reemplazar `async with httpx.AsyncClient(timeout=timeout)` por `get_notify_http_client().post(url, json=…, timeout=timeout)`, conservando `raise_for_status`, el `try/except` que devuelve `False`, los logs y el sello `backend_dispatched_at`. Comentar citando la ampliación del 2026-10-03 de D87/RN-181 y la medición de `mediciones.md` §1.
- [x] 2.4 En `backend/app/main.py`, llamar a `init_notify_http_client()` en el lifespan antes de lanzar los consumers y a `await close_notify_http_client()` en el apagado, después de cancelar las tareas que agendan entregas y antes de `notify_executor.shutdown`.
- [x] 2.5 En `backend/tests/conftest.py`, agregar un fixture autouse que cierre y descarte el cliente después de cada test (las conexiones quedan ligadas al loop de cada test).
- [x] 2.6 Verificar con `rg -n "httpx.AsyncClient\(" backend/app` que el único sitio por llamada restante es el chequeo de salud de n8n (`core/health.py`), fuera del camino de los eventos, y anotar el resultado acá.
  - `rg -n "httpx.AsyncClient\(" backend/app`: `core/health.py:107` (chequeo de salud, fuera del camino de eventos) y `alerts/notifier.py:55` (la construcción única del cliente compartido). No quedan clientes por llamada.

## 3. Fase A — tests

- [x] 3.1 El cliente se reutiliza: dos llamadas consecutivas a `send_n8n` (y una a `send_webhook_fallback`) contra un servidor HTTP local usan la misma instancia, y `httpx.AsyncClient.__init__` se invoca una sola vez (espía).
- [x] 3.2 El cliente se cierra al apagar: ejecutar el lifespan de la app con dependencias dobladas como en los tests de lifespan existentes y verificar que, tras el apagado, el cliente quedó cerrado (`is_closed`) y descartado.
- [x] 3.3 La verificación TLS sigue activa: el contexto SSL del transporte del cliente tiene `verify_mode == ssl.CERT_REQUIRED` y `check_hostname` activo, y `rg -n "verify=False" backend/app` no encuentra nada.
- [x] 3.4 Recuperación ante reset: un servidor local que cierra la conexión tras responder (o que se detiene y vuelve a levantarse en el mismo puerto entre dos entregas) → la entrega afectada, si falla, devuelve `False` sin lanzar, y la entrega siguiente devuelve `True` sobre una conexión nueva.
- [x] 3.5 El timeout por canal se conserva: un servidor que no responde hace fallar `send_n8n` por timeout con el valor pasado por pedido.
- [x] 3.6 Correr la suite de notificaciones y la completa de backend; los tests existentes de `send_n8n`/`send_webhook_fallback` que parchean `httpx.AsyncClient` se adaptan al cliente compartido sin cambiar lo que afirman, y cada adaptación se anota acá.
  - Adaptaciones: `test_send_n8n_success` y `test_send_n8n_failure` (`backend/tests/test_notifications.py`) parcheaban `httpx.AsyncClient` con un doble de context manager; ahora parchean `app.modules.alerts.notifier.get_notify_http_client` con un doble cuyo `post` devuelve lo mismo. Afirman lo mismo (`True` en 2xx, `False` ante excepción). Resto de la suite sin cambios: 1072 passed / 4 skipped (1063 + 9 nuevos).

## 4. Fase A — medición y compuerta de la fase B (A-4)

- [x] 4.1 Medir con la fase A igual que en 1.6 (`--notify stub` y `--notify real --paths 600`, 3.000 eventos, 3 repeticiones más una perfilada) y registrar en `mediciones.md` los ev/s, `ingest_ms`, `commit_ms` y la tasa de entrega.
- [x] 4.2 Decidir y anotar en `mediciones.md`: si `real` alcanza al menos 1,5× la línea base `real` de 1.6 (≥93 ev/s sobre 62,0), marcar todo el grupo 5 como no aplicable («Fase B no necesaria», con el número y la fecha) y pasar al grupo 6; si no, seguir con el grupo 5.
  - **Fase B necesaria (2026-10-03):** `real --paths 600` con la fase A = 86,0 ev/s (1,39× de 62,0) < 93. Ver `mediciones.md` §2.

## 5. Fase B — persistencia por lote (condicional a 4.2)

- [x] 5.0 Sólo si 4.2 no alcanza el umbral: restaurar en `specs/backend-event-consumer/spec.md` el delta de la fase B redactado en `32d9e5d` (ADDED «Los eventos validados de un lote se persisten en una única transacción», MODIFIED de ACK por lote y de perfilado), ajustado al requisito de piso vigente, y correr `openspec validate ingest-batched-persistence --strict` **antes** de escribir código.
  - Delta restaurado de `32d9e5d` (ADDED + MODIFIED de ACK y perfilado) junto al MODIFIED vigente de piso; `openspec validate --strict` OK.

### B-1 Núcleo de ingesta y severidad puros (D-3)

- [x] 5.1 En `backend/app/modules/rules/service.py`, extraer `severity_from_rules(path, rules)` con el cuerpo actual de `determine_severity_for_path`, y hacer que `determine_severity_for_path(path, session)` la invoque tras su `SELECT`. Tests: misma severidad para inclusión, negación y sin match que la función actual.
- [x] 5.2 En `backend/app/modules/events/service.py`, extraer `_ingest_into_session(session, ctx, event_data, received_at, detected_at, accept_new)` con todo lo que hoy ocurre dentro del `with Session` de `_ingest_event_outcome` salvo el `commit`, y un `_IngestBatchContext` (`known_event_ids`, `pending_by_path`, `rules`, ids eliminados por compactación, tokens consumidos por agente, tiempos por candidato). `_ingest_event_outcome` conserva firma y comportamiento: abre la `Session`, construye un contexto de un evento que consulta la base como hoy, llama al núcleo y hace `commit`.
- [x] 5.3 Dentro del núcleo, capturar `InvalidTransitionError` por candidato antes de cualquier escritura de ese candidato y devolverla como resultado `invalid_transition`; en el camino por evento, conservar la propagación actual de la excepción para que `_handle_message` no cambie.
- [x] 5.4 Correr la suite completa: ningún test existente de ingesta cambia de resultado con el refactor.

### B-2 Persistencia del lote (D-3, D-4, D-6)

- [x] 5.5 Implementar `_ingest_batch(items, accept_new_for)` en `events/service.py`: una `Session`, dedup en bloque (`SELECT event_id … WHERE event_id IN (…)`), precarga de `pending` por ruta reducida en Python al más reciente, `rules` una vez, núcleo por candidato en orden con `flush` y `expunge` por evento, actualización de `pending_by_path` tras cada inserción y supersesión, y un único `commit`. Devuelve los resultados en orden y los tiempos `ingest_db_ms`, `commit_ms` y por candidato.
  - Desviación menor: `_ingest_batch(items, accept_new_for, refund=None)` recibe además `refund` (inyectado por el consumer) para devolver tokens sin que `events/service.py` importe el limitador de `consumer.py`. Los ítems son `IngestBatchItem` (definidos en `service.py`); `compact_chain` ahora devuelve los ids eliminados.
- [x] 5.6 Dedup dentro del lote: un `event_id` ya visto en el lote resulta `duplicate` sin tocar la base ni el rate limit.
- [x] 5.7 Ante `mark_superseded` en `False`, re-consultar con `get_pending_event_for_path` sobre la misma `Session` y corregir `pending_by_path` con su resultado (D25/RN-121).
- [x] 5.8 Registrar en el contexto los ids eliminados por `compact_chain` durante el lote.
- [x] 5.9 Agregar `_RateLimiter.refund(key, n)` (bajo el lock, sin superar `burst`, sin crear estado para claves desconocidas) y su test. En `_ingest_batch`, ante `SQLAlchemyError`, `rollback`, devolver los tokens consumidos por agente y propagar la excepción.
- [x] 5.10 Tests de servicio contra el motor de pruebas: N eventos nuevos → N filas, un `commit`, `id` en orden del lote; dos eventos `pending` de la misma ruta → cadena `superseded` con `version` incrementada y `parent_event_id`; `pending` seguido de `alert_only` en la misma ruta → el terminal supersede al `pending` del lote; `event_id` repetido en el lote → una fila; `pending` previo en la base supersedido por el primer evento del lote; carrera simulada (`mark_superseded` en `False` con y sin `pending` vigente); rollback ante error inyectado en el `commit` → cero filas y tokens devueltos; 12 eventos `pending` de la misma ruta en un lote → la compactación deja 10 `superseded` y reporta los ids eliminados.

### B-3 Integración en el consumer (D-2, D-4, D-5, D-8)

- [x] 5.11 Agregar `_IngestCandidate` y la `ContextVar` `_ingest_batch_var` en `events/consumer.py`, creada y reseteada por `_process_batch` junto a `_ack_batch_var`. En `_handle_message`, con lote activo, el camino feliz agrega el candidato y retorna; sin lote, conserva el camino por evento sin cambios.
- [x] 5.12 En `_process_batch`, al terminar el bucle de mensajes sin excepción y con candidatos, despachar una vez `_ingest_batch` al executor de ingesta (`run_in_executor(None, …)`, D75/RN-169).
- [x] 5.13 Ante `IntegrityError` o `DataError` del lote: log `consumer.batch_replayed_per_event` y re-ejecutar los candidatos en orden por el camino por evento (`_ingest` en el executor) aplicando sus efectos como hoy. Ante cualquier otro `SQLAlchemyError`: log `consumer.batch_db_error` con `exc_info=True` y cantidad de candidatos, sin `XACK` ni respuesta para ningún candidato.
- [x] 5.14 Con el lote confirmado, aplicar los efectos en el orden del stream: `persisted`/`duplicate`/`supersede_race` → `_ack_or_defer`; `persisted` además `_fire_and_forget(notify_if_applicable(event))` salvo ids eliminados por compactación; `rate_limited` → `_reject` con `retry_after` del limitador; `invalid_transition` → `XACK`, auditoría y `event_nack` terminal, como hoy.
- [x] 5.15 Perfilado (D-8): `consumer.timing` por evento tras el `COMMIT` con `ingest_ms` de su porción en la transacción; por lote, `candidates`, `ingest_db_ms` y `commit_ms` además de las claves actuales. Nada nuevo con el flag apagado.
- [x] 5.16 Comentar el código citando la ampliación del 2026-10-03 de D87/RN-181, D75/RN-169 (una sola salida al executor, sin concurrencia entre eventos) y por qué el `COMMIT` precede a todo efecto.

### B-4 Tests del consumer

- [x] 5.17 Correr sin modificar `test_fifo_order_preserved_after_batch_drain`, `test_no_duplicate_after_transient_db_error_and_pel_redelivery` y `test_batch_dispatch_is_strictly_sequential` (`backend/tests/test_ingest_offload_blocking_db.py`) y el resto de ese archivo. Si alguno falla, el defecto está en la implementación.
- [x] 5.18 Reescribir en `backend/tests/test_ingest_drain_resilience.py`, citando la ampliación de RN-181 (D-10): `test_each_ack_is_appended_after_the_commit_of_its_event` (agregados posteriores al `COMMIT` del lote), `test_transient_db_error_in_the_middle_leaves_only_that_event_in_the_pel` (error transitorio → los tres en la PEL, sin respuestas) y `test_timing_emitted_per_event_and_per_batch_when_flag_active` (claves nuevas del lote). Los demás tests del archivo, sin cambios.
  - Reescritos los tres tests con sus nombres originales. `test_timing_emitted_per_event_and_per_batch_when_flag_active` seguía pasando porque las claves nuevas son un superconjunto; se extendió con `candidates`, `ingest_db_ms` y `commit_ms` del lote. El caso `IntegrityError` quedó en `test_ingest_batched_persistence_consumer.py` (5.20).
- [x] 5.19 Test «dos eventos de la misma ruta en un lote forman cadena» a través de `_process_batch`: el primero `superseded`, el segundo `pending` con `parent_event_id` del primero, ambos con `event_ack` en un único pipeline.
- [x] 5.20 Test: `IntegrityError` causado por el evento del medio → `e1` y `e3` persistidos con `XACK` y `event_ack`, `e2` sin respuesta.
- [x] 5.21 Test: un lote con un persistido, un `rate_limited` y un `InvalidTransitionError` → con un doble que registra el orden, el `commit` precede a los tres efectos, que salen en orden del stream; el persistido agenda notificación.
- [x] 5.22 Test: un lote con firma inválida al principio → su `XACK` es inmediato y anterior al `commit` del lote.
- [x] 5.23 Test: error transitorio del lote seguido de re-entrega de las mismas entradas desde la PEL → cada evento persistido una sola vez, tokens del primer intento devueltos (el balde tras la re-entrega coincide con el de una sola admisión).
- [x] 5.24 Test: un evento del lote eliminado por la compactación del mismo lote no agenda notificación.
- [x] 5.25 Verificar con `rg -n "run_in_executor" backend/app/modules/events/consumer.py` que el camino de lote hace una sola salida al executor de ingesta por lote y que ningún acceso a PostgreSQL quedó en el event loop.
  - `rg -n "run_in_executor" backend/app/modules/events/consumer.py`: una sola salida del camino de lote (`_persist_batch`, `consumer.py:460`); las demás son autenticación con caché, auditoría de rechazos y el camino por evento (`_ingest_one`, también la repetición ante `IntegrityError`/`DataError`). Ningún acceso a PostgreSQL en el event loop.

### B-5 Medición tras la persistencia por lote

- [x] 5.26 Medir igual que en 1.6 y 4.1 (`stub` y `real --paths 600`) y registrar en `mediciones.md` los ev/s, `ingest_db_ms`, `commit_ms` por lote y `ingest_ms` por evento.
- [x] 5.27 Decidir y anotar en `mediciones.md` el paso condicional de D-9: si `real` alcanza al menos 1,5× la línea base `real` de 1.6 (≥93 ev/s), marcar B-6 como no aplicable con el número y la fecha y pasar al grupo 6.
  - **2026-10-03:** `real --paths 600` = 179,4 ev/s (2,89× de 62,0; entrega 109,4 ev/s, 1,77×) ≥ 93 → B-6 no aplicable. Ver `mediciones.md` §3.

### B-6 Fila `Alert` en la transacción del lote (D-9)

- [x] 5.28 Sólo si la decisión de B-5 no alcanza el umbral: escribir el addendum de D-9 en `design.md` y un delta `specs/backend-notifications/spec.md` (MODIFIED del requisito «Notificación asincrónica post-ingesta de eventos críticos o altos») **antes** de escribir código, y correr `openspec validate ingest-batched-persistence --strict`.
  - **NO APLICABLE (2026-10-03):** la decisión 5.27 alcanzó el umbral (179,4 y 109,4 ev/s ≥ 93); no se escribe addendum de D-9 ni delta de `backend-notifications` adicional.
- [x] 5.29 Sólo si aplica: implementar según el addendum, con tests de que el evento y su alerta se confirman en el mismo `COMMIT`, de que un rollback no deja alerta, de que RN-22 y RN-52 se conservan y de que la entrega, el cupo y `_mark_delivered` no cambian; re-medir como en B-5 y registrar.
  - **NO APLICABLE (2026-10-03):** ver 5.28.

## 6. Batería 5 y cierre

- [x] 6.1 En `lab/bateria5.sh`, al cerrar el drenaje, registrar `consumption_window_s` y `consumption_ev_s` calculados desde el primer y el último `received_at` de los eventos drenados (misma consulta que produjo `eventos.csv` del diagnóstico), sin quitar las líneas existentes.
  - Agrega, tras el resumen y antes de `=== end ===`, `consumption_window_s` y `consumption_ev_s` desde `min/max(received_at)` de `events`; las líneas existentes quedan intactas. `bash -n lab/bateria5.sh` OK; la consulta se probó contra la base efímera del banco (3000 eventos, 16,5 s).
- [x] 6.2 Correr la suite completa de backend y `python3 scripts/check_spec_integrity.py`.
- [x] 6.3 Verificar que `mediciones.md` contiene la línea base (1.6), la medición de la fase A (4.1), la decisión de 4.2 y, si la fase B aplicó, sus mediciones y la decisión de D-9, y que el umbral de 1,5× quedó cumplido antes de proponer la etiqueta `v5.1-tesis`.
- [ ] 6.4 DEFERRED to the v5.1-tesis unified run: confirmar en el laboratorio, con la Batería 5 sobre `v5.1-tesis` dentro de la corrida unificada, al menos 95 ev/s como ventana de consumo entre el primer y el último `received_at`, con `FIM_PROFILE_INGEST` según el protocolo de la corrida; registrar el resultado tal como se mida, **sin declarar mejora anticipada**, con referencia cruzada a la Change 61.
