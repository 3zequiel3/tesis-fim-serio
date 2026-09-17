## Why

El filtro de scope del detector descarta, con un `log.warning` **por ruta**, toda escritura del host
que cae fuera de los `watch_paths` (`agent/detector.py:567-571`). Como la marca de fanotify cubre el
filesystem completo en modo FID (D46/RN-140), eso no es un caso de borde: es el caso normal. En el
host del agente el contador llegó a **2.748.492** descartes, con el journal inundado.

El daño es doble. El ruido sepulta los eventos de integridad que el sistema existe para mostrar, y
durante una corrida de medición cronometrada compite por I/O de journal con lo que se está midiendo
—la latencia de detección es justamente uno de los indicadores del Capítulo 5—.

Pero el agregado no debe desaparecer: es la evidencia de que el filtro de scope está funcionando. El
agente **ya** publica `out_of_scope_drops` en cada heartbeat (`agent/heartbeat.py:105`), junto a
`event_drops`; el backend hoy ignora las dos claves —no hay ninguna referencia en
`backend/app/modules/agents/heartbeat_consumer.py` ni columna en `Agent`—, así que el agregado no
llega a ninguna parte. El operador tiene hoy las dos peores mitades: el detalle inunda el journal y
el total no se ve en ningún lado.

La decisión que gobierna esta change ya está cerrada y no se reinterpreta acá: **D69/RN-163**
(`docs/reglas_de_negocio.md:2202`), con su contraparte técnica en la fila D69 de la tabla de
decisiones D63–D65 de `docs/arquitectura_stack.md:2707`. No se abre ninguna suposición nueva.

**Hallazgo posterior (2026-09-17).** El agente con D69/RN-163 se desplegó a las 17:44:05 UTC (tarea
1.8) y el journal siguió inundado: 82 líneas `"level": "debug"` en los primeros 15 segundos. Causa
raíz: `agent/logging.py` nunca filtró la salida de `structlog` por nivel —el nivel sólo llegaba a
`logging.basicConfig`, que no intercepta esa salida—, así que **todo** nivel se imprimía sin
importar `--log-level`/`LOG_LEVEL`. Se cierra con **D73/RN-167**
(`docs/reglas_de_negocio.md`), que esta change también implementa.

**Segundo hallazgo posterior (2026-09-17, tras el redespliegue de D73/RN-167).** Con el filtro de
nivel ya funcionando, el journal siguió mostrando flujo de `detector.event_null_path` a nivel
`warning` (`agent/detector.py:561-564`, emitido cuando `ev.path is None`): 71.833 líneas entre las
13:00 y las 14:44 hora local del 2026-09-17 (~12/s), 135.547 desde el 2026-09-16, y 79 líneas en los
primeros 40 segundos tras un reinicio, concentradas en 3 PIDs. Investigación de causa raíz
(`agent/_fanotify.py:265-337`): el path se reconstruye a partir de los registros FID del evento del
kernel, y falla (`ev.path is None`) cuando `_open_by_handle` no puede resolver el handle contra
ningún fd de montaje abierto —típicamente `ESTALE` porque el objeto referenciado ya fue borrado o
renombrado entre la generación del evento y su procesamiento—. A diferencia de `out_of_scope_drop`,
el chequeo de path nulo corre **antes** del filtro de scope (`agent/detector.py:561` frente a
`:565`), así que un path nulo no confirma que el objeto estuviera fuera de `watch_paths`: puede
esconder un cambio en scope. Se cierra con **D74/RN-168** (`docs/reglas_de_negocio.md`), que esta
change también implementa, con un marco deliberadamente distinto al de D69/RN-163: el log baja a
`debug` igual, pero el contador nuevo (`null_path_drops`) se documenta como posible brecha de
cobertura, no como ruido confirmado, y esta change no lo persiste en el backend ni lo presenta en el
frontend.

## What Changes

- **Agente — el log por ruta baja a `debug` (D69/RN-163).** `detector.out_of_scope_drop`
  (`agent/detector.py:567-571`) pasa de `log.warning` a `log.debug`. El contador
  `self._out_of_scope_drops` y su property pública (`agent/detector.py:723-725`) **no cambian**, y
  `agent/heartbeat.py:105` tampoco: el agente **no cambia su contrato**, sólo el nivel al que habla.
- **Backend — el contador se persiste y se expone.** Columna `out_of_scope_drops` en `Agent`,
  **nullable** (`None` = "nunca reportado", deliberadamente distinto de `0`), con migración aditiva
  idempotente `backend/db/migrations/020_add_agent_out_of_scope_drops.sql` en el mismo estilo que
  `019_add_agent_registered_at.sql` (incluida la nota de que las migraciones se aplican a mano, D3).
  Ingesta en `heartbeat_consumer.py` con el mismo criterio tolerante que ya se aplica a
  `queue_pressure` y `watch_path_status`, y exposición en `AgentResponse` vía `_agent_to_response`
  (`backend/app/modules/agents/service.py:102-118`).
- **Frontend — contador informativo, con tratamiento neutro.** La tarjeta del agente lo muestra
  junto a la presión de cola, con un mapper puro propio en `frontend/src/utils/`. El tratamiento
  visual es **neutro y explícitamente distinto** del de `DiscardedEventsIndicator`
  (`frontend/src/components/ui/AgentCard.tsx:54-64`), que resalta anomalía porque allí un positivo
  **es una detección perdida**. Acá un positivo es esperado. Los tres estados —nunca reportó, cero,
  positivo— se distinguen, igual que en los otros contadores del agente.
- **Restricción de secuencia, no preferencia.** El slice del agente DEBE desplegarse **antes** de
  re-correr las baterías del Capítulo 5 (tarea 12.4 de `agent-attribution-and-detection-gap`). Los
  slices de backend y frontend no tocan el agente, así que pueden desplegarse después de la corrida
  sin invalidarla.
- **Agente — el logging del agente filtra por nivel (D73/RN-167).** `agent/logging.py`
  (`configure_logging`) pasa a `wrapper_class=structlog.make_filtering_bound_logger(...)`, mismo
  mecanismo que ya usa el backend. A nivel `info` (default) ningún log `debug` —incluido
  `detector.out_of_scope_drop`— llega a stdout; esto es lo que hace efectivo el cambio de nivel de
  D69/RN-163. Un nivel desconocido cae a `info` sin romper el arranque.
- **Agente — el log por evento de path nulo baja a `debug` y suma un contador (D74/RN-168).**
  `detector.event_null_path` (`agent/detector.py:561-564`) pasa de `log.warning` a `log.debug`, y se
  agrega el contador acumulativo `null_path_drops` (incrementado antes del log, property pública) que
  viaja en el heartbeat junto a `out_of_scope_drops` y `event_drops`. A diferencia de D69/RN-163, el
  contador se documenta como **posible brecha de cobertura** —el chequeo de path nulo corre antes del
  filtro de scope, así que no hay certeza de que el objeto perdido estuviera fuera de `watch_paths`—,
  no como ruido confirmado. Esta change no persiste el contador en el backend ni lo presenta en el
  frontend: queda para una decisión posterior.

## Capabilities

### New Capabilities

- _Ninguna._ Esta change no introduce capabilities: ajusta el comportamiento observable de tres que
  ya existen.

### Modified Capabilities

- `agent-fanotify-detector`: el nivel del log del descarte fuera de scope pasa a `debug` y queda
  fijado como requisito; el contador acumulativo y su publicación en el heartbeat quedan ratificados
  sin cambio. Se agrega, además, el descarte por path nulo del kernel: el log pasa a `debug` y se
  suma el contador `null_path_drops` (D74/RN-168), documentado como posible brecha de cobertura.
- `backend-agent-management`: el consumer de heartbeat persiste el contador de descartes fuera de
  scope en una columna nullable y los dos endpoints de agentes lo exponen.
- `frontend-agents`: la tarjeta del agente presenta el contador como informativo, con tratamiento
  neutro distinguible del de los descartes locales, mediante un mapper puro propio.

## Impact

**Agente** (una línea, sin cambio de contrato para `out_of_scope_drop`; contrato del heartbeat
extendido de forma aditiva para `null_path_drops`):
- `agent/detector.py:567-571` — nivel del log.
- `agent/detector.py:723-725`, `agent/heartbeat.py:105` — **no se tocan**; se verifica que sigan
  intactos.
- `agent/tests/test_scope_filter.py` — la sección "4.2 out_of_scope_drops en el heartbeat" **no se
  toca** y sigue verde; se agrega una sección "4.3 null_path_drops en el heartbeat" nueva.
- `agent/detector.py:561-564` (D74/RN-168) — `detector.event_null_path` pasa de `log.warning` a
  `log.debug`; se agrega `self._null_path_drops` (incrementado antes del log) y la property pública
  `null_path_drops`.
- `agent/heartbeat.py:105` (D74/RN-168) — se agrega la clave `null_path_drops` al payload, junto a
  `out_of_scope_drops`.
- `agent/tests/test_detector_multi_event.py`, `agent/tests/test_detection_gap.py` — tests existentes
  que referencian `event_null_path`; ver Impact detallado en `design.md` (D-11).

**Backend**:
- `backend/app/modules/agents/models.py` — `Agent.out_of_scope_drops` y `AgentResponse.out_of_scope_drops`.
- `backend/app/modules/agents/heartbeat_consumer.py` — lectura e ingesta tolerante.
- `backend/app/modules/agents/service.py` — `_agent_to_response`.
- `backend/db/migrations/020_add_agent_out_of_scope_drops.sql` — **nueva**, aditiva e idempotente.

**Frontend**:
- `frontend/src/api/agents.ts` — campo opcional en el tipo `Agent`.
- `frontend/src/utils/` — mapper puro nuevo + su test.
- `frontend/src/components/ui/AgentCard.tsx` — indicador neutro junto a la presión de cola.

**Sin impacto**: filtro de scope, transporte Valkey, esquema de `events`, `discarded_events` y su
presentación de anomalía. `event_drops` queda deliberadamente fuera de alcance (ver design, decisión
D-6). Persistencia en backend y presentación en frontend de `null_path_drops` quedan deliberadamente
fuera de alcance de esta change (D74/RN-168, ver design D-11).

Reglas cubiertas: RN-04 (filtro de scope, ratificada sin cambio), RN-71 (léxico snake_case),
RN-92 (estado operacional del agente en la consola). Decisiones aplicadas: **D69/RN-163**,
**D73/RN-167**, **D74/RN-168**.
