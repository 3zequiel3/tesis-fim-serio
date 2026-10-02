## Why

El límite de ingesta por agente es hoy un log de ventana deslizante: `_RateLimiter`
(`backend/app/modules/events/consumer.py:143-227`) guarda un `deque[float]` de marcas por `agent_id`
y rechaza el evento número 101 dentro de cualquier ventana de 60 s, con defaults
`rate_limit_ingest_events=100` y `rate_limit_ingest_window_seconds=60.0`
(`backend/app/core/config.py:100-101`). Ese modelo no distingue una ráfaga legítima de un régimen
sostenido abusivo: el replay de 2.672 eventos de la batería 5 tarda **al menos 26,7 minutos** con
los defaults del producto, de modo que todas las corridas de medición tuvieron que elevar el límite
a 100000/60 mediante `lab/docker-compose.exp.yml:8-9` y declararlo según D38/RN-132. El resultado
es que el producto que se mide no es el producto que se entrega.

Un token bucket separa las dos cosas: conserva el régimen sostenido de 100 ev/min y admite una
ráfaga acotada que cubre el replay medido. Con eso las baterías pueden correr con los defaults del
producto.

Origen: guía de laboratorio de la tesis v29 (ítems L-2…L-9), verificada contra `devel`. La decisión
que gobierna esta change está cerrada: **D85/RN-179** (`docs/reglas_de_negocio.md`, appendix
«Decisiones de implementación»; fila D85 en `docs/arquitectura_stack.md:2725`), con la base de la
ráfaga, la eliminación de los settings anteriores y la consecuencia sobre `retry_after` ya
explicitadas. Relaciona **D38/RN-132** y preserva **D37/RN-131** y **D75/RN-169**. No se abre
ninguna suposición nueva.

## What Changes

- **Token bucket por agente (D85/RN-179).** `_RateLimiter` pasa de ventana deslizante a token
  bucket: cada `agent_id` tiene un balde de capacidad `burst` que se rellena a `rate_per_s` tokens
  por segundo; un evento nuevo consume un token. Un agente nunca visto arranca con el balde lleno.
  Régimen sostenido: 100 ev/min; ráfaga: 3.000 eventos.
- **Settings nuevos.** `rate_limit_ingest_rate_per_s` (default `100/60`) y
  `rate_limit_ingest_burst` (default `3000`), expuestos como `RATE_LIMIT_INGEST_RATE_PER_S` y
  `RATE_LIMIT_INGEST_BURST`.
- **BREAKING (configuración): se eliminan `rate_limit_ingest_events` y
  `rate_limit_ingest_window_seconds`.** No se mapean. Si `RATE_LIMIT_INGEST_EVENTS` o
  `RATE_LIMIT_INGEST_WINDOW_SECONDS` siguen definidas en el entorno del backend, el arranque
  registra una advertencia que nombra las variables ignoradas y sus reemplazos.
- **`retry_after` = tiempo hasta el próximo token.** Con el balde vacío, el `retry_after` del
  `event_nack` de `rate_limited` pasa de «hasta que la marca más vieja salga de la ventana» (hasta
  ~60 s) a `(1 − tokens) / rate_per_s` (≤ 0,6 s a 100 ev/min), con el piso existente
  `_MIN_RETRY_AFTER_S = 0.5`. Consecuencia aceptada por D85/RN-179, compatible con D37/RN-131.
- **Se conservan**: el orden dedup → rate check (las re-entregas no consumen token), el `XACK` +
  auditoría + `event_nack` retenible, la thread-safety introducida por D75/RN-169, el estado en
  memoria que se reinicia con el backend, `reset_rate_limiter()` y el método explícito que expone
  el remanente.
- **Compose y ejemplo de entorno.** `docker-compose.yml:286-291` y `.env.example:118,121` pasan a
  los settings nuevos; el compose sigue reenviando los nombres heredados **sólo** para que la
  advertencia de arranque pueda detectarlos.
- **Laboratorio: las baterías corren con los defaults del producto.** Se elimina
  `lab/docker-compose.exp.yml` y los scripts de `lab/` dejan de aplicarlo; la procedencia que
  registran pasa a los settings nuevos.
- **Documentación operativa.** `README.md` §F.12 (`:1388-1411`) y el comentario de
  `backend/app/core/config.py:209` se reescriben con el modelo nuevo.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `backend-event-consumer`: el requisito «Rate limiting 100 eventos/min por agent_id en el consumer»
  pasa a token bucket con ráfaga; el requisito «retry_after is derived from the live rate limiter
  state» pasa a tiempo hasta el próximo token; se agrega un requisito para la configuración del
  límite y la advertencia por variables heredadas.
- `backend-async-consumer`: el escenario «El limitador de tasa de ingesta tolera el cruce de hilos»
  del requisito «Operaciones DB en consumers ejecutadas en threadpool» deja de hablar de ventana
  deslizante y de «semántica previa».

## Impact

- **Código**: `backend/app/modules/events/consumer.py` (`_RateLimiter`, `:143-232`),
  `backend/app/core/config.py` (`:92-101`, comentario `:209`), `backend/app/main.py` (advertencia
  en el `lifespan`, `:78`).
- **Configuración**: `docker-compose.yml:286-291`, `.env.example:118,121`.
  `docker-compose.tls.yml` y `scripts/prepare_server_env.py` no referencian estas variables.
- **Laboratorio**: `lab/docker-compose.exp.yml` (se elimina); `lab/corrida_unificada.sh`,
  `lab/bateria4.sh`, `lab/bateria5.sh`, `lab/corte_valkey.sh`, `lab/cierre_cap5.sh`,
  `lab/repetir_cap5.sh`, `lab/b5_post_d75.sh`, `lab/rehacer_notif_resil.sh`.
- **Tests**: `backend/tests/test_event_consumer_c11.py:88-210`,
  `backend/tests/test_stream_ack_durability_consumer.py:500-549`,
  `backend/tests/test_ingest_offload_blocking_db.py:452-500`,
  `backend/tests/test_c31_backend_event_correctness.py:519-560`; tests nuevos para ráfaga, régimen
  sostenido, aislamiento por agente y advertencia.
- **Sin cambios**: el agente (`agent/publisher.py` ya acota `retry_after` a `[>0, 60 s]`), el
  contrato del stream `commands`, el esquema de base de datos, el frontend.
- **Fuera de alcance**: la evidencia histórica bajo `tesis/cierre/` y
  `docs/implementaciones/` conserva los nombres viejos porque registra lo que se corrió; el
  rendimiento de la ingesta y la re-corrida del arnés son de Change 69.
