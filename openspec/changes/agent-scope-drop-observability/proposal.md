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

## Capabilities

### New Capabilities

- _Ninguna._ Esta change no introduce capabilities: ajusta el comportamiento observable de tres que
  ya existen.

### Modified Capabilities

- `agent-fanotify-detector`: el nivel del log del descarte fuera de scope pasa a `debug` y queda
  fijado como requisito; el contador acumulativo y su publicación en el heartbeat quedan ratificados
  sin cambio.
- `backend-agent-management`: el consumer de heartbeat persiste el contador de descartes fuera de
  scope en una columna nullable y los dos endpoints de agentes lo exponen.
- `frontend-agents`: la tarjeta del agente presenta el contador como informativo, con tratamiento
  neutro distinguible del de los descartes locales, mediante un mapper puro propio.

## Impact

**Agente** (una línea, sin cambio de contrato):
- `agent/detector.py:567-571` — nivel del log.
- `agent/detector.py:723-725`, `agent/heartbeat.py:105` — **no se tocan**; se verifica que sigan
  intactos.
- `agent/tests/test_scope_filter.py` — **no se toca**; la sección "4.2 out_of_scope_drops en el
  heartbeat" debe seguir verde sin modificaciones. Ningún test fija hoy el nivel de ese log.

**Backend**:
- `backend/app/modules/agents/models.py` — `Agent.out_of_scope_drops` y `AgentResponse.out_of_scope_drops`.
- `backend/app/modules/agents/heartbeat_consumer.py` — lectura e ingesta tolerante.
- `backend/app/modules/agents/service.py` — `_agent_to_response`.
- `backend/db/migrations/020_add_agent_out_of_scope_drops.sql` — **nueva**, aditiva e idempotente.

**Frontend**:
- `frontend/src/api/agents.ts` — campo opcional en el tipo `Agent`.
- `frontend/src/utils/` — mapper puro nuevo + su test.
- `frontend/src/components/ui/AgentCard.tsx` — indicador neutro junto a la presión de cola.

**Sin impacto**: contrato del heartbeat, filtro de scope, transporte Valkey, esquema de `events`,
`discarded_events` y su presentación de anomalía. `event_drops` queda deliberadamente fuera de
alcance (ver design, decisión D-6).

Reglas cubiertas: RN-04 (filtro de scope, ratificada sin cambio), RN-71 (léxico snake_case),
RN-92 (estado operacional del agente en la consola). Decisión aplicada: **D69/RN-163**.
