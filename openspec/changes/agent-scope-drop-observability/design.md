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

**Hallazgo posterior al despliegue (2026-09-17).** El agente con D69/RN-163 aplicado (`bfe2c57`) se
desplegó el 2026-09-17 17:44:05 UTC (tarea 1.8) y el journal siguió inundado: 82 líneas
`"level": "debug"` en los primeros 15 segundos. Causa raíz: `agent/logging.py`
(`configure_logging`) nunca filtró la salida de `structlog` por nivel —
`wrapper_class=structlog.stdlib.BoundLogger` junto con
`logger_factory=structlog.PrintLoggerFactory(sys.stdout)` imprime **todo** nivel, y el nivel
configurado sólo llegaba a `logging.basicConfig`, que no intercepta esa salida—, así que bajar
`detector.out_of_scope_drop` a `debug` no tuvo efecto real. **D73/RN-167**
(`docs/reglas_de_negocio.md`) cierra este hallazgo: el agente SHALL filtrar por nivel con
`structlog.make_filtering_bound_logger`, mismo mecanismo que ya usa el backend
(`backend/app/core/logging.py:245`). Este design incorpora esa decisión como D-10.

**Segundo hallazgo posterior al despliegue (2026-09-17, D73/RN-167 ya redesplegado 17:57:16 UTC, 0
líneas `debug` en el journal del proceso nuevo).** Con el filtro de nivel funcionando, el journal
mostró un flujo distinto: `detector.event_null_path` (`agent/detector.py:561-564`, `log.warning`
cuando `ev.path is None`), 71.833 líneas entre las 13:00 y las 14:44 hora local del 2026-09-17
(~12/s), 135.547 desde el 2026-09-16, 79 en los primeros 40 s tras un reinicio, concentradas en 3
PIDs. Investigación de causa raíz (`agent/_fanotify.py`): el path de cada evento se reconstruye a
partir de sus registros FID (`_resolve_path`, `:265-311`), y la resolución final pasa por
`_open_by_handle` (`:324-337`), que prueba `open_by_handle_at` contra cada fd de montaje abierto —uno
por `watch_path` (`_open_mount_fd`, `:224-236`)— y devuelve `None` si **todos** fallan, típicamente
`ESTALE` cuando el directorio referenciado ya fue borrado o renombrado entre la generación del
evento en el kernel y su procesamiento en el hilo lector.

A diferencia de `out_of_scope_drop`, este descarte **no** es estructuralmente seguro: el chequeo de
path nulo (`:561`) corre **antes** del filtro de scope (`:565`) precisamente porque
`_path_location_in_scope` necesita un path para decidir, así que un evento sin path puede
corresponder a un cambio dentro de `watch_paths` tanto como a uno fuera. **D74/RN-168**
(`docs/reglas_de_negocio.md`) cierra este hallazgo con un marco distinto al de D69/RN-163: el log
baja a `debug` igual (el ruido por evento es inútil en cualquier caso), pero el contador nuevo se
documenta como **posible brecha de cobertura**, no como ruido confirmado, y queda estrictamente del
lado del agente — sin persistencia en el backend ni presentación en el frontend, que una decisión
posterior deberá cerrar. Este design incorpora esa decisión como D-11.

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
- Que el descarte por path nulo del kernel (`detector.event_null_path`) también deje de inundar el
  journal, y que su magnitud quede visible en el heartbeat sin afirmar que es ruido confirmado
  cuando no hay evidencia de eso (D74/RN-168).

**Non-Goals:**

- **No** se toca el filtro de scope: qué se descarta no cambia (RN-04 intacta).
- **No** se toca el contrato del heartbeat para `out_of_scope_drops`: la clave ya viaja, el agente
  no cambia lo que publica. `null_path_drops` (D74/RN-168) sí es una clave nueva, pero aditiva: un
  backend anterior a esta change simplemente la ignora, igual que ignoraba `out_of_scope_drops`
  antes de esta change.
- **No** se persiste ni se presenta `event_drops`, la otra clave que el consumer ignora (ver D-6).
- **No** se persiste `null_path_drops` en el backend ni se presenta en el frontend en esta change
  (D-11): es estrictamente agente — contador, property y clave de heartbeat. Presentación queda
  para una decisión posterior, precisamente porque su semántica de riesgo (posible brecha de
  cobertura) exige una discusión propia, no la reutilización del criterio "informativo" de D69.
- **No** se agrega retención, agregación por ventana ni serie temporal de ningún contador: son
  acumulados desde el arranque del proceso, y así se muestran/publican.
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
el slice del agente restaura el `warning` y el ruido, sin pérdida de datos. Revertir D-10 restaura
el filtrado ausente y, con él, el flood — el `warning`-a-`debug` de D-1 volvería a imprimirse igual
que antes de esta change. Revertir D-11 restaura el `warning` de `detector.event_null_path` y retira
`null_path_drops` del payload del heartbeat; un backend/frontend que nunca leyó esa clave no se ve
afectado, porque es aditiva.

**D-10 — El agente filtra su salida de `structlog` por nivel (D73/RN-167).**
`configure_logging` pasa a `wrapper_class=structlog.make_filtering_bound_logger(log_level_int)`, el
mismo mecanismo que `backend/app/core/logging.py:245`. Alternativa considerada: agregar un processor
manual que descarte el evento si su nivel es menor al configurado. Rechazada: reimplementaría, con
más código y peor mantenido, lo que `make_filtering_bound_logger` ya resuelve en el wrapper — y lo
haría *después* de que el evento pasara por el resto de la cadena de processors, en vez de antes,
perdiendo la ventaja de no ejecutar `sanitize_logs`/el renderer para líneas que igual se descartan.
Un nivel desconocido o mal formado (typo en `--log-level`, valor inesperado en `LOG_LEVEL`) SHALL
resolverse a `INFO` y no debe impedir el arranque del agente — un fallo de parseo del nivel no es
motivo para que el agente no levante. `structlog.stdlib.add_log_level` se reemplaza por
`structlog.processors.add_log_level`: son el mismo objeto desde structlog 20.2 (verificado en la
instancia instalada, 25.1.0), pero el segundo nombre no sugiere una dependencia del wrapper
`stdlib.BoundLogger` que este cambio retira. El resto del contrato de logging del agente —formato
JSON/consola, `sanitize_logs`, `TimeStamper`, salida por `sys.stdout`— no cambia.

**D-11 — El descarte por path nulo baja a `debug` y suma un contador con un marco distinto al de
D-1 (D74/RN-168).**
`detector.event_null_path` (`agent/detector.py:561-564`) pasa de `log.warning` a `log.debug`, igual
mecanismo que D-1 aplicó a `out_of_scope_drop`. La diferencia está en lo que el contador nuevo,
`null_path_drops`, afirma: causa raíz investigada en `agent/_fanotify.py:265-337` — `_open_by_handle`
devuelve `None` cuando `open_by_handle_at` falla (típicamente `ESTALE`) contra todos los fds de
montaje abiertos, y el chequeo de path nulo corre **antes** del filtro de scope (`:561` frente a
`:565`) porque ese filtro necesita el path para decidir. No hay, entonces, forma de saber si el
objeto perdido estaba dentro de `watch_paths`. Alternativa considerada: presentarlo con el mismo
marco "informativo" que D69/RN-163 le da a `out_of_scope_drops`, por similitud superficial (los dos
son descartes en el mismo hilo lector). Rechazada: allí el path se conoce y su exterioridad está
confirmada; acá no hay path, así que no hay confirmación posible, y llamarlo "esperado" afirmaría
una certeza que no existe. El contador se documenta como posible brecha de cobertura, comparable en
ese sentido a `discarded_events` (D37/RN-131), aunque sin la certeza de pérdida que ese contador sí
tiene.

Se evaluó, además, agregar un resumen periódico acotado (`info`/`warning` a lo sumo una vez por
intervalo de heartbeat, con el delta), al estilo de la deduplicación de `detection_gap` (D50/RN-144).
Rechazada por el mismo motivo que D-2 rechazó esa alternativa para `out_of_scope_drop`: agrega estado
y una ventana que hay que razonar, y el contador acumulativo ya viaja en cada heartbeat — un segundo
canal agregado no suma información. `debug` por evento más el contador es la respuesta proporcional
también acá.

Alcance deliberadamente estrecho: esta decisión NO persiste `null_path_drops` en el backend ni lo
presenta en el frontend (ver Non-Goals). Es una clave aditiva nueva en el payload del heartbeat —un
backend anterior a esta change la ignora sin romperse, con el mismo criterio tolerante que ya aplica
a claves desconocidas—, pero decidir su persistencia y su tratamiento visual (¿neutro como
`out_of_scope_drops`, o con alguna forma de alerta como `discarded_events`, dado que puede esconder
una pérdida?) es una discusión propia que esta decisión no cierra a propósito.

## Open Questions

D69/RN-163 cierra el nivel del log, la persistencia, la nulabilidad y el criterio de presentación de
`out_of_scope_drops`; D73/RN-167 cierra el filtrado por nivel que D69/RN-163 daba por sentado y que
no existía; D74/RN-168 cierra el nivel del log y el contador de `event_null_path`, pero
**deliberadamente no cierra** su persistencia en el backend ni su presentación en el frontend —queda
abierta para una decisión posterior, que deberá decidir si el tratamiento visual es neutro (como
`out_of_scope_drops`) o de alerta (como `discarded_events`), dado que un valor positivo puede
esconder una detección perdida. Si durante el apply aparece una suposición que estas decisiones no
cubren —por ejemplo, la necesidad de presentar `event_drops` (D-6), de agregar un umbral de alerta
sobre cualquiera de los contadores, o de persistir/presentar `null_path_drops`—,
**detener el flujo** y cerrarla en el appendix "Decisiones de implementación — Abril 2026" antes de
continuar.
