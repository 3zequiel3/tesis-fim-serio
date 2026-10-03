## Why

El diagnóstico del drenaje sobre `v5.0-tesis` del 2026-10-03
(`tesis/cierre/evidencia/diagnostico-drenaje-v5.0-20261003/`) midió en el laboratorio **76,6 ev/s**
(2.995 eventos en 39,1 s de ventana de consumo), por debajo del mínimo de 95 ev/s de D87/RN-181. La
regla fijada en la Change 69 (`mediciones.md` §5 de
`openspec/changes/archive/2026-10-02-ingest-drain-resilience-and-throughput/`) dice que, si el
laboratorio mide menos de 95 ev/s, se reabre el grupo 7 (`INSERT` por lote) y se etiqueta un
candidato nuevo, `v5.1-tesis`. Esta change es esa reapertura.

El perfilado `consumer.timing` de la Change 69 deja poco margen de duda sobre **dónde** está el
tiempo: autenticación 0,02 ms, validación 0,14 ms e **ingesta transaccional 12,27 ms de media por
evento** (98 % del tiempo; mediana 10,3 ms, mínimo 4,9 ms). El flush de ACK por lote suma 0,4 s en
64 lotes y el lag del grupo de consumidores sube de 20 a 581 en 8 s: el backend es el cuello, no el
broker ni el agente.

**Qué cubre `ingest_ms`.** Es el tiempo de pared de `run_in_executor(_ingest)`
(`backend/app/modules/events/consumer.py:547-551`), que ejecuta `_ingest_event_outcome`
(`backend/app/modules/events/service.py:354-536`) con **una `Session` y un `COMMIT` por evento**.
Por evento nuevo sin cadena, eso son ~7 viajes a PostgreSQL —`SELECT 1` de `pool_pre_ping`
(`backend/app/core/database.py:38-45`), `BEGIN`, `SELECT` de dedup (`service.py:429-431`),
`SELECT` del `pending` de la ruta (`get_pending_event_for_path`, `:290-296`), `SELECT * FROM rules`
(`determine_severity_for_path`, `backend/app/modules/rules/service.py:75`), `INSERT … RETURNING`
(`session.flush()`, `:520`) y `COMMIT` (`:535`)— más un `UPDATE` de supersesión y una o dos
consultas de compactación cuando hay cadena. El `COMMIT` vacía el WAL a disco: el compose no fija
`synchronous_commit` y rige el default `on`. En el laboratorio, además, cada evento alerta: el
carril de notificación agrega por evento dos `COMMIT` más (`_create_alert_row`,
`backend/app/modules/alerts/service.py:169-187`, y `_mark_delivered`, `:498-533`) y n8n persiste su
ejecución en la base `fim_n8n` **de la misma instancia** de PostgreSQL (`docker-compose.yml`,
servicio `n8n`, `DB_POSTGRESDB_HOST: db`). El banco de desarrollo de la Change 69 reemplazaba la
notificación por un no-op (`lab/bench_ingest_consumer.py:164-183`) y usaba rutas únicas: midió
~5,7 ms de ingesta, cerca del mínimo del laboratorio (4,9 ms). La atribución a la contención de
`COMMIT` es una hipótesis fundada en el código; esta change la confirma con un banco sin stub
**antes** de tocar la ingesta.

Decisión que gobierna esta change: **ampliación del 2026-10-03 de D87/RN-181**
(`docs/arquitectura_stack.md`, fila D87; `docs/reglas_de_negocio.md`, sección D87/RN-181), con una
enmienda **condicional** de D76/RN-170. Preserva D75/RN-169, D40/RN-134, D41/RN-135, D25/RN-121,
RN-11, RN-12, RN-72 y RN-98.

## What Changes

- **Persistencia por lote.** Dentro de `_process_batch`, los eventos que superan la validación
  (pasos 1–5) se acumulan como candidatos y se persisten en **una sola transacción por lote**, en
  una única salida al executor de ingesta y en el orden del stream. Un único `COMMIT` por lote
  reemplaza los ~50 `COMMIT` actuales.
- **Semántica por evento dentro del lote.** Dedup en bloque contra la base y dentro del lote;
  `pending` de las rutas del lote precargado y mantenido en memoria, de modo que dos eventos de la
  misma ruta en un lote forman cadena `superseded`; `UPDATE` optimista y re-consulta ante carrera
  (D25/RN-121) por evento; reglas leídas una vez por lote; compactación (RN-98) por evento dentro de
  la misma transacción; rate limit por evento y en orden.
- **Efectos después del `COMMIT` del lote, en orden del stream.** `event_ack` + `XACK` (acumulador
  de la Change 69), rechazos `rate_limited`, camino de `InvalidTransitionError` y agendado de la
  notificación por evento. Los rechazos de validación (pasos 1–5) siguen siendo inmediatos.
- **Fallas.** Un error transitorio de base de datos revierte el lote y deja **todos** sus
  candidatos en la PEL, sin `XACK` ni respuesta, y devuelve los tokens de rate limit consumidos. Un
  `IntegrityError`/`DataError` revierte y re-ejecuta los candidatos uno por uno por el camino por
  evento actual, para aislar un evento envenenado.
- **`_handle_message` conserva su firma** y, invocado fuera de un lote, el camino por evento actual.
- **Perfilado.** `consumer.timing` por lote suma `candidates`, `ingest_db_ms` y `commit_ms`; el
  `ingest_ms` por evento pasa a ser la porción de ese evento dentro de la transacción del lote.
- **Paso condicional (enmienda acotada de D76/RN-170).** Sólo si el banco sin stub no alcanza 1,5×
  su línea base con lo anterior, la fila `Alert` se crea en la misma transacción del lote. Su delta
  de spec se escribe antes del código, como addendum.
- **Banco sin stub.** `lab/bench_ingest_consumer.py` gana un modo con la cadena de notificación real
  (reglas `high`, sumidero HTTP local que persiste una fila por pedido en otra base de la misma
  instancia, rutas repetidas como el generador de carga) y registra antes y después en
  `mediciones.md` de esta change.
- **Batería 5** registra el ritmo como ventana de consumo entre el primer y el último `received_at`.
- **Confirmación de laboratorio diferida** a la corrida unificada de `v5.1-tesis`, sin declarar
  mejora anticipada.

Sin cambios **BREAKING** de contrato: `event_ack`/`event_nack` no cambian de forma; cambia el
instante de emisión dentro del lote, que el agente resuelve por `event_id` con una ventana de 60 s.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `backend-event-consumer`: nuevo requisito de persistencia transaccional por lote (dedup intra-lote,
  cadena `superseded` intra-lote, rollback del lote completo, re-ejecución ante error determinista,
  devolución de tokens, efectos post-`COMMIT` en orden); se modifican los requisitos de ACK por lote
  (el `commit` de referencia es el del lote y un error transitorio deja todo el lote en la PEL), de
  perfilado (campos por lote) y de piso de rendimiento (el `INSERT` por lote queda adoptado, con
  aceptación en `v5.1-tesis` y el banco sin stub).

## Impact

- **Código**: `backend/app/modules/events/consumer.py` (`_process_batch`, `_handle_message`,
  limitador), `backend/app/modules/events/service.py` (núcleo de ingesta reutilizable con una
  `Session` dada y contexto de lote), `backend/app/modules/rules/service.py` (cálculo de severidad
  puro sobre una lista de reglas). Condicional: `backend/app/modules/alerts/service.py`.
- **Tests**: nuevos en `backend/tests/`; se reescriben, bajo la ampliación de RN-181, tres tests de
  `backend/tests/test_ingest_drain_resilience.py` que fijaban granularidad por evento dentro del
  lote. `test_fifo_order_preserved_after_batch_drain` y
  `test_no_duplicate_after_transient_db_error_and_pel_redelivery` no se modifican.
- **Laboratorio**: `lab/bench_ingest_consumer.py`, `lab/bateria5.sh`.
- **Sin cambios** de esquema, de compose, de protocolo con el agente ni de frontend.
- **Candidato**: `v5.1-tesis`; la re-corrida unificada repite todas las baterías.
