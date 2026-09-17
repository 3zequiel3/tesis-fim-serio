## Context

**Estado actual — el agente.** La marca de fanotify es de filesystem completo en modo FID
(`FAN_MARK_FILESYSTEM`, D46/RN-140): el kernel entrega **toda** escritura del host, no sólo las de
los `watch_paths`. El filtro de scope vive en el hilo lector (`agent/detector.py`), justo después
del chequeo de path nulo: si `_path_location_in_scope(ev.path, self._watch_paths_real)` es falso,
incrementa `self._out_of_scope_drops`, emite `log.warning("detector.out_of_scope_drop", path=...,
total_drops=...)` y sigue (`:567-571`). El contador se expone como property pública
(`:723-725`) y viaja en cada heartbeat (`agent/heartbeat.py:105`), al lado de `event_drops`.

El filtro es correcto. Lo que no es correcto es el **nivel**: un `warning` por cada escritura ajena
al alcance del agente convierte el caso normal en una anomalía reportada. En el host del agente el
contador llegó a 2.748.492 con el journal inundado.

**Estado actual — el backend.** `heartbeat_consumer.py` lee `queue_pressure`, `queue_size`,
`shutdown`, `watch_path_status` y `discarded_events`, y **ninguna** de las dos claves de contadores
del detector: ni `event_drops` ni `out_of_scope_drops` aparecen en el módulo. `Agent`
(`backend/app/modules/agents/models.py`) tampoco tiene columna para ellas. El agregado que el agente
publica en cada latido se descarta en la ingesta.

**Estado actual — el frontend.** La tarjeta del agente ya muestra presión de cola, cola local
(`queue_size`) y descartes locales (`discarded_events`) en el mismo bloque
(`frontend/src/components/ui/AgentCard.tsx:141-177`). `DiscardedEventsIndicator` (`:54-64`) consume
`getDiscardedEventsMeta` (`frontend/src/utils/discardedEvents.ts`), un mapper puro de tres estados
—`unknown` / `zero` / `positive`— donde el positivo se pinta en rojo porque **es una detección
perdida**.

**Restricción externa.** La tarea 12.4 de `agent-attribution-and-detection-gap` re-corre las
baterías del Capítulo 5 y regenera `resultados/`. La latencia de detección es uno de los indicadores
medidos, y el ruido del journal compite por el mismo I/O.

**Decisión de gobierno.** D69/RN-163 (`docs/reglas_de_negocio.md:2202`) ya está cerrada y
commiteada. Este design la implementa; no la reinterpreta ni la amplía.

## Goals / Non-Goals

**Goals:**

- Que el journal del agente deje de inundarse, sin perder la capacidad de ver la ruta descartada
  cuando alguien está diagnosticando.
- Que el agregado `out_of_scope_drops` llegue al backend y se vea en la consola, como **contador
  informativo**.
- Que la presentación sea inequívocamente distinta de la de `discarded_events`, de modo que un
  positivo acá no le enseñe al operador a ignorar un indicador rojo allá.
- Que "nunca reportó" siga siendo distinguible de "cero", como en el resto de los contadores.
- Que el slice del agente pueda desplegarse solo, antes de la corrida de medición.

**Non-Goals:**

- **No** se toca el filtro de scope: qué se descarta no cambia (RN-04 intacta).
- **No** se toca el contrato del heartbeat: la clave ya viaja, el agente no cambia lo que publica.
- **No** se persiste ni se presenta `event_drops`, la otra clave que el consumer ignora (ver D-6).
- **No** se agrega retención, agregación por ventana ni serie temporal del contador: es un
  acumulado desde el arranque del proceso, y así se muestra.
- **No** se cambia la presentación de `discarded_events`, `queue_size` ni `queue_pressure`.

## Decisions

**D-1 — El log baja a `debug`, no se elimina.**
Alternativa considerada: borrar el `log` y dejar sólo el contador. Rechazada: cuando alguien
diagnostica por qué un cambio esperado no generó evento, la ruta descartada **es** el dato, y es el
único lugar donde aparece. `debug` la conserva detrás de un nivel que la unidad systemd no persiste
por defecto: el ruido desaparece del journal sin que la información deje de ser obtenible subiendo
el nivel a mano.

**D-2 — Sin rate-limit ni sampling del log.**
Alternativa considerada: mantener `warning` con supresión por ventana, al estilo de la
deduplicación de `detection_gap` (D50/RN-144). Rechazada por dos razones: agrega estado y una
ventana que hay que razonar, y sobre todo **sigue escribiendo** — con 2,7 millones de descartes,
incluso una emisión por minuto es un `warning` recurrente sobre un hecho estructural. La
deduplicación por ventana existe allá porque un `detection_gap` **es** una anomalía; acá no lo es.

**D-3 — Columna nullable, `None` ≠ `0`.**
`Agent.out_of_scope_drops` es `int | None` con `default=None`, mismo criterio que `queue_size`
(US-21) y `discarded_events` (D37/RN-131) y mismo que exige D69/RN-163 explícitamente. `None`
significa "este agente nunca reportó la clave" —agente sin actualizar, o sin heartbeat todavía— y
`0` significa "reportó y no descartó nada". Degradar `None` a `0` afirmaría que el filtro de scope
no descartó nada, que es justamente lo que no sabemos.

**D-4 — Migración aditiva `020`, idempotente, aplicada a mano (D3).**
`backend/db/migrations/020_add_agent_out_of_scope_drops.sql`, en el estilo de
`019_add_agent_registered_at.sql`: comentario de cabecera que explica por qué existe la columna,
`ADD COLUMN IF NOT EXISTS`, y la nota de que las migraciones se aplican a mano con `psql`. A
diferencia de `019`, **no hay backfill ni `SET NOT NULL`**: no existe forma de reconstruir cuántos
descartes acumuló un agente antes de esta columna, y `NULL` es exactamente la respuesta correcta
para esas filas. Eso hace la migración estrictamente aditiva: una sola sentencia, sin `UPDATE`.

**D-5 — Ingesta tolerante, idéntica al precedente.**
Se replica el criterio ya aplicado a `discarded_events` (`heartbeat_consumer.py:147-153`): clave
ausente → **no** se toca el valor guardado (nunca se resetea a cero por un agente viejo); `bool`
rechazado explícitamente con log, porque `isinstance(True, int)` es `True` en Python; cualquier otro
no-numérico se ignora con log y el heartbeat **se procesa igual** —un contador malformado nunca
puede dejar a un agente marcado offline—. No se agrega schema ni allowlist al consumer: la firma
HMAC cubre el dict completo, leer una clave más no altera la verificación.

**D-6 — `event_drops` queda fuera de alcance, y es deliberado.**
El consumer ignora dos claves, no una. `event_drops` se deja afuera a propósito: mide
`asyncio.QueueFull` sobre la cola interna del detector, es decir **eventos perdidos**, con la misma
semántica de anomalía que `discarded_events`. Presentarlo exige la discusión de cómo se resalta y
bajo qué umbral, que D69 no cierra porque no es de lo que habla. Se documenta acá para que la
próxima lectura no lo interprete como un olvido ni lo agregue de contrabando a este change.

**D-7 — Mapper propio, no un flag sobre `getDiscardedEventsMeta`.**
Alternativa considerada: reutilizar `getDiscardedEventsMeta` con un parámetro que cambie el color.
Rechazada: los dos mappers difieren justo en el eje que importa —en uno el positivo es una anomalía,
en el otro es lo esperado—, así que el flag no compartiría lógica, sólo la estructura de tres
estados. Y acoplaría dos presentaciones que D69/RN-163 exige mantener distinguibles: una edición
futura de una rompería la otra en silencio. Se escribe `getOutOfScopeDropsMeta` en
`frontend/src/utils/`, con su propio test de los tres estados, siguiendo el mismo contrato de mapper
puro que ya establecieron `getDiscardedEventsMeta` y `getWatchPathStatusMeta`.

**D-8 — Tratamiento visual neutro y verificable.**
El indicador usa la paleta neutra de la tarjeta (gris), **nunca** rojo ni ámbar, en los tres
estados. El positivo se distingue del cero por el número y por el `title`, no por el color de
alarma. El `title` dice qué significa el número —descartes estructurales del filtro de scope,
esperados— para que un positivo alto no se lea como un problema que hay que atender. El spec fija
esto como escenario, de modo que un futuro cambio de estilo que lo pinte de rojo rompa un test.

**D-9 — El orden de los slices es una restricción, no una preferencia.**
El slice del agente se despliega **antes** de re-correr las baterías del Capítulo 5 (tarea 12.4 de
`agent-attribution-and-detection-gap`); los de backend y frontend pueden ir después. Fundamento: el
ruido compite por I/O de journal con la latencia de detección, que es uno de los indicadores
medidos, y **cualquier** cambio en el agente posterior a la medición invalida los números. Backend y
frontend no tocan `agent/`, así que desplegarlos después no invalida la corrida.

## Risks / Trade-offs

- **[Un operador busca en el journal la ruta que se descartó y ya no la encuentra]** → El contador
  en la tarjeta le dice que el filtro está actuando y cuánto; el detalle vuelve subiendo el nivel a
  `debug` en la unidad systemd, sin recompilar ni redesplegar el agente. Es el trade-off explícito
  de D69/RN-163.
- **[Se despliega el backend y el frontend antes que el agente, y la tarjeta muestra "—" para
  siempre]** → No es un bug: el agente ya publica la clave desde antes de esta change, así que el
  "—" sólo persiste para agentes que nunca latieron. Y si persistiera, `None` = "nunca reportado" es
  la lectura correcta, no una falla de la UI.
- **[Se despliega el slice del agente después de la corrida de medición]** → Invalida los números
  del Capítulo 5. Mitigación: el orden está escrito en este design (D-9) y como tarea explícita y
  verificable en `tasks.md`, no como nota al pie.
- **[El tratamiento neutro se lee como "esto no importa" y se ignora un valor anómalo]** → Riesgo
  aceptado y elegido: D69/RN-163 lo resuelve al revés —el costo de resaltar lo estructural es
  enseñarle al operador a ignorar los indicadores rojos, y eso es exactamente cómo se pierde una
  alerta real—. El `title` del indicador carga la explicación.
- **[La columna nullable se llena de `NULL` en despliegues mixtos]** → Es el estado correcto y
  está especificado; ningún consumidor la degrada a `0`.

## Migration Plan

1. **Slice 1 — agente.** Bajar el nivel del log, correr la suite del agente (la sección
   "4.2 out_of_scope_drops en el heartbeat" de `agent/tests/test_scope_filter.py` debe seguir verde
   **sin tocar el archivo**), desplegar el agente. **Punto de corte**: recién después de este paso
   se re-corren las baterías del Capítulo 5.
2. **Slice 2 — backend.** Aplicar `020_add_agent_out_of_scope_drops.sql` a mano con
   `psql $DATABASE_URL -f` (D3), desplegar el backend. La migración es aditiva: un backend viejo
   contra una base ya migrada funciona igual, porque nadie lee la columna nueva.
3. **Slice 3 — frontend.** Desplegar. El campo es opcional en el tipo `Agent`, así que un frontend
   nuevo contra un backend viejo renderiza el estado "nunca reportó" en vez de romperse.

**Rollback**: revertir el código de cualquier slice es seguro y no requiere revertir la migración —
la columna es nullable y sin default, de modo que queda sin uso y no rompe ningún `INSERT`. Revertir
el slice del agente restaura el `warning` y el ruido, sin pérdida de datos.

## Open Questions

Ninguna. D69/RN-163 cierra el nivel del log, la persistencia, la nulabilidad y el criterio de
presentación. Si durante el apply aparece una suposición que esta decisión no cubre —por ejemplo,
la necesidad de presentar `event_drops` (D-6) o de agregar un umbral de alerta sobre el contador—,
**detener el flujo** y cerrarla en el appendix "Decisiones de implementación — Abril 2026" antes de
continuar.
