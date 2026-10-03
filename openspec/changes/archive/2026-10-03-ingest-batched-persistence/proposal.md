## Why

El diagnóstico del drenaje sobre `v5.0-tesis` del 2026-10-03
(`tesis/cierre/evidencia/diagnostico-drenaje-v5.0-20261003/`) midió en el laboratorio **76,6 ev/s**
(2.995 eventos en 39,1 s de ventana de consumo), por debajo del mínimo de 95 ev/s de D87/RN-181. La
regla fijada en la Change 69 (`mediciones.md` §5 de
`openspec/changes/archive/2026-10-02-ingest-drain-resilience-and-throughput/`) dice que, si el
laboratorio mide menos de 95 ev/s, se reabre el rendimiento de la ingesta y se etiqueta un
candidato nuevo, `v5.1-tesis`. Esta change es esa reapertura.

El perfilado `consumer.timing` ubica el tiempo en la ingesta transaccional: autenticación 0,02 ms,
validación 0,14 ms e `ingest_ms` 12,27 ms de media por evento (98 %). La primera versión de esta
change atribuía ese costo al `COMMIT` por evento en contención con el carril de notificación y
proponía persistir por lote. **La medición de la tarea 1.7 refutó esa hipótesis** (`mediciones.md`
§1 de esta change). El banco `lab/bench_ingest_consumer.py` con la cadena de notificación sin stub
(`--notify real --paths 600`) reproduce el laboratorio: 62,0 ev/s e `ingest_ms` 15,85 ms, contra
170-178 ev/s y 5,1-5,9 ms con stub. Pero:

- `commit_ms` es 1,085 ms, el 6,8 % de `ingest_ms`;
- `synchronous_commit=off` deja 61,9 ev/s;
- un intervalo de cambio del GIL 50 veces menor deja 59,6 ev/s.

La causa medida es otra. `send_n8n` (`backend/app/modules/alerts/notifier.py:45`) crea un
`httpx.AsyncClient` por entrega, y cada construcción arma un contexto SSL nuevo, con la carga del
bundle de CA, en CPU del proceso. El hilo del executor de ingesta pierde ese tiempo. Con
`verify=False` inyectado, sólo como diagnóstico, el banco da 81,4 ev/s e `ingest_ms` 11,96 ms
(+31 %).

Decisión que gobierna esta change: **ampliación del 2026-10-03 de D87/RN-181, revisada tras la
medición** (`docs/arquitectura_stack.md`, fila D87; `docs/reglas_de_negocio.md`, sección
D87/RN-181), con una enmienda **condicional** de D76/RN-170 dentro de la fase B. Preserva D42/RN-136,
D75/RN-169, D40/RN-134, D41/RN-135, D25/RN-121, RN-11, RN-12, RN-72 y RN-98.

## What Changes

- **Fase A (obligatoria): cliente HTTP de larga vida para las entregas.** `send_n8n` y
  `send_webhook_fallback` dejan de crear un `httpx.AsyncClient` por llamada. Pasan a usar uno solo:
  - creado en el lifespan y cerrado al apagar;
  - verificación TLS activa y contexto SSL construido una vez;
  - mismos timeouts;
  - pool acotado a `notify_max_concurrent_deliveries` conexiones, con keep-alive de 4 s.

  Un reset de conexión o un reinicio de n8n hacen fallar sólo la entrega en curso, que sigue la
  escalera de reintentos durable de D42/RN-136. La entrega siguiente abre una conexión nueva. El
  chequeo de salud de n8n conserva su cliente por llamada.
- **Medición de la fase A** con el banco sin stub. El umbral es al menos 1,5× la línea base sin
  stub, es decir ≥93 ev/s sobre los 62,0 medidos.
- **Fase B (condicional): persistencia por lote.** Sólo si la fase A no alcanza el umbral. Es la
  persistencia en una única transacción por lote de la versión anterior de esta change, sin cambios
  de semántica:
  - dedup en la base y dentro del lote;
  - cadena `superseded` entre eventos del mismo lote;
  - todo el lote en la PEL ante un error transitorio;
  - re-ejecución evento por evento ante `IntegrityError`/`DataError`;
  - devolución de tokens de rate limit;
  - efectos después del `COMMIT`, en orden.

  Dentro de ella, y sólo si tampoco alcanza el umbral, la fila `Alert` se crea en la misma
  transacción (enmienda acotada de D76/RN-170). Si la fase A alcanza el umbral, la fase B no se
  implementa y queda registrada como no necesaria, con su medición.
- **Banco sin stub** (`--notify real`, `--paths`, `commit_ms`): ya hecho en la tarea 1.
- **Batería 5** registra el ritmo como ventana de consumo entre el primer y el último `received_at`.
- **Confirmación de laboratorio diferida** a la corrida unificada de `v5.1-tesis`, sin declarar
  mejora anticipada.

Sin cambios **BREAKING**: el contrato de notificación (D40/RN-134), su `notification_id` (D41/RN-135)
y el protocolo `event_ack`/`event_nack` no cambian.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `backend-notifications`: las entregas HTTP del carril de notificación usan un cliente HTTP de
  larga vida, con verificación TLS activa, pool acotado y recuperación de una conexión rota en la
  entrega siguiente (requisito de envío a n8n).
- `backend-event-consumer`: el requisito de piso de rendimiento pasa de «`INSERT` por lote
  condicional» a las fases A y B, con aceptación en `v5.1-tesis` y en el banco sin stub. Si la fase B
  se adopta, su delta (requisito nuevo de persistencia transaccional por lote y extensión de los de
  ACK por lote y perfilado, redactado en `32d9e5d`) se restaura en la change antes del código; si no,
  ninguna main spec recibe requisitos que no se implementaron.

## Impact

- **Código, fase A**: `backend/app/modules/alerts/notifier.py` (cliente compartido y su ciclo de
  vida), `backend/app/main.py` (creación en el lifespan y cierre al apagar) y
  `backend/tests/conftest.py` (reset del cliente entre tests).
- **Código, fase B si aplica**: `backend/app/modules/events/consumer.py`,
  `backend/app/modules/events/service.py`, `backend/app/modules/rules/service.py` y, en su paso
  condicional, `backend/app/modules/alerts/service.py`.
- **Tests**: nuevos para el cliente compartido. Si la fase B aplica, se reescriben tres tests de
  `backend/tests/test_ingest_drain_resilience.py`. `test_fifo_order_preserved_after_batch_drain` y
  `test_no_duplicate_after_transient_db_error_and_pel_redelivery` no se modifican en ningún caso.
- **Laboratorio**: `lab/bench_ingest_consumer.py` (hecho) y `lab/bateria5.sh`.
- **Sin cambios** de esquema, de compose, de protocolo con el agente ni de frontend.
- **Candidato**: `v5.1-tesis`; la re-corrida unificada repite todas las baterías.
