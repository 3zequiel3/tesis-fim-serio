> **Orden de despliegue — restricción, no preferencia (D-9 del design).** El grupo 1 (agente) DEBE
> desplegarse **antes** de re-correr las baterías del Capítulo 5 (tarea 12.4 de
> `agent-attribution-and-detection-gap`): el ruido del journal compite por I/O con la latencia de
> detección, que es uno de los indicadores medidos, y cualquier cambio en el agente **posterior** a
> la medición invalida los números. Los grupos 2 a 7 (backend y frontend) no tocan `agent/`, así que
> pueden desplegarse después de la corrida sin invalidarla.

## 1. Agente — bajar el nivel del log (slice 1, antes de la corrida del Capítulo 5)

- [x] 1.1 En `agent/detector.py:567-571`, cambiar `log.warning("detector.out_of_scope_drop", ...)` por `log.debug(...)`. Los argumentos (`path`, `total_drops`) no cambian: el nombre del evento y su contenido son los mismos, sólo baja el nivel.
- [x] 1.2 Comentar el cambio citando **D69/RN-163** y diciendo por qué: la marca de fanotify es de filesystem completo en modo FID (D46/RN-140), así que el descarte es el caso normal y no una anomalía. Nombrar la magnitud medida (2.748.492 descartes con el journal inundado) para que la próxima lectura no reconstruya el razonamiento desde cero ni "arregle" el nivel de vuelta.
- [x] 1.3 Verificar que `self._out_of_scope_drops += 1` sigue **exactamente donde estaba**, antes del log y del `continue`. El contador no cambia de posición ni de semántica: si el incremento se moviera detrás del log, un cambio futuro de nivel podría dejar de contarlo.
- [x] 1.4 Verificar que la property `out_of_scope_drops` (`agent/detector.py:723-725`) **no se toca**, incluido su docstring que cita RN-04.
- [x] 1.5 Verificar que `agent/heartbeat.py:105` **no se toca**: la clave `out_of_scope_drops` ya viaja en el payload junto a `event_drops`. El agente **no cambia su contrato** en esta change. Si el arreglo parece necesitar tocar el heartbeat, detenerse: el design dice que no hace falta, y esa discrepancia es información.
- [x] 1.6 Verificar con `rg -n "out_of_scope_drop" agent/tests/` que **ningún test fija el nivel** de ese log. `agent/tests/test_scope_filter.py` afirma el contador y su presencia en el payload (sección "4.2 out_of_scope_drops en el heartbeat"): esos tests deben seguir verdes **sin tocar el archivo**. Si alguno fallara, el cambio se pasó de alcance.
- [x] 1.7 Correr la suite del agente completa y dejar el resultado en el reporte de apply. Resultado: `629 passed, 1 skipped in 176.91s` (exit code 0); `agent/tests/test_scope_filter.py` con sus 19 casos en verde sin modificaciones.
- [ ] 1.8 **Punto de corte del despliegue**: desplegar el agente con este cambio **antes** de re-correr las baterías del Capítulo 5. Dejar constancia en el reporte de apply de que el orden se respetó, con la fecha del despliegue del agente y la de la corrida.

## 2. Backend — modelo y migración

- [ ] 2.1 En `backend/app/modules/agents/models.py`, agregar a `Agent` el campo `out_of_scope_drops: int | None = Field(default=None)`, junto a `discarded_events`. Comentar citando **D69/RN-163** con el criterio explícito: `None` = "el agente nunca reportó", distinto de `0` = "reportó y no descartó nada"; y que un positivo es **esperado**, a diferencia de `discarded_events`. Nombrar la migración `020`.
- [ ] 2.2 En el mismo archivo, agregar `out_of_scope_drops: int | None = None` a `AgentResponse`, con el mismo comentario de nulabilidad que llevan `queue_size` y `discarded_events`.
- [ ] 2.3 Crear `backend/db/migrations/020_add_agent_out_of_scope_drops.sql` con el mismo estilo y estructura de comentarios que `019_add_agent_registered_at.sql`: cabecera que explica **por qué** existe la columna (el contador ya viaja en el heartbeat y el backend lo ignoraba), la nota de idempotencia, y la nota de que **las migraciones se aplican a mano (D3)** con la línea `psql $DATABASE_URL -f 020_add_agent_out_of_scope_drops.sql`.
- [ ] 2.4 El cuerpo de la migración es **una sola sentencia**: `ALTER TABLE agents ADD COLUMN IF NOT EXISTS out_of_scope_drops INTEGER;`. **No** lleva `UPDATE` de backfill, **no** lleva `SET DEFAULT` y **no** lleva `SET NOT NULL` — a diferencia de `019`. Documentarlo en el comentario: no hay forma de reconstruir el contador previo, y `NULL` es exactamente la respuesta correcta para las filas existentes. Correrla dos veces no debe producir error.

## 3. Backend — ingesta en el consumer de heartbeat

- [ ] 3.1 En `backend/app/modules/agents/heartbeat_consumer.py`, junto a la lectura de `discarded_events` (`:91`), agregar `out_of_scope_drops = payload.get("out_of_scope_drops")` con un comentario que cite **D69/RN-163** y diga que es el mismo criterio tolerante que `queue_pressure` y `watch_path_status`.
- [ ] 3.2 En el bloque de aplicación (junto a `:147-153`), replicar **exactamente** el patrón de `discarded_events`: si la clave no es `None`, rechazar `bool` con `log.warning("heartbeat_consumer.invalid_out_of_scope_drops", agent_id=agent_id)` —porque `isinstance(True, int)` es `True` en Python—, aceptar `(int, float)` convirtiendo con `int(...)`, y loguear igual para cualquier otro tipo. Una clave ausente **no** toca el valor guardado.
- [ ] 3.3 Verificar que ninguna rama de esta ingesta puede interrumpir el procesamiento del resto del heartbeat: un contador malformado nunca debe dejar a un agente sin actualizar `last_heartbeat` ni sin pasar a `online`.
- [ ] 3.4 Actualizar el docstring del módulo (`:6-8`), que hoy enumera qué persiste el consumer, para incluir el contador nuevo citando D69/RN-163.
- [ ] 3.5 **No** agregar `event_drops` (D-6 del design). Es la otra clave que el consumer ignora, tiene semántica de pérdida y exige la discusión de anomalía que D69 no cierra. Si durante el apply parece natural agregarla, **detenerse**: es una decisión nueva, va al appendix primero.

## 4. Backend — exposición en la API

- [ ] 4.1 En `backend/app/modules/agents/service.py`, agregar `out_of_scope_drops=agent.out_of_scope_drops` a `_agent_to_response` (`:102-118`), con el comentario de nulabilidad al estilo de las líneas vecinas. Esto cubre `GET /agents` y `GET /agents/{id}` a la vez, porque las dos rutas pasan por el mismo mapper.
- [ ] 4.2 Verificar leyendo el diff que el valor viaja **sin transformarlo**: sin `or 0`, sin `int(...)`, sin default. El nulo debe propagarse solo hasta la respuesta.

## 5. Tests del backend

- [ ] 5.1 Test: un heartbeat con `out_of_scope_drops` numérico persiste el valor y los dos endpoints lo exponen.
- [ ] 5.2 Test: un heartbeat **sin** la clave, posterior a uno que reportó un valor, deja el valor guardado intacto (no lo resetea a cero).
- [ ] 5.3 Test: un heartbeat con un valor no numérico deja el valor intacto, registra el log de inválido y **procesa el resto del heartbeat igual** (el agente queda `online` y `last_heartbeat` se actualiza).
- [ ] 5.4 Test: un heartbeat con un valor booleano se rechaza por la misma rama que el no numérico.
- [ ] 5.5 Test: un agente que nunca reportó la clave expone `null`, no `0`, en los dos endpoints.
- [ ] 5.6 Correr la suite del backend completa y dejar el resultado en el reporte de apply.

## 6. Frontend — tipo y mapper neutro

- [ ] 6.1 En `frontend/src/api/agents.ts`, agregar `out_of_scope_drops?: number | null` a la interfaz `Agent`, con el comentario al estilo de los vecinos: cita a **D69/RN-163**, `null`/`undefined` = "nunca reportó" distinto de `0`, y la aclaración de que un positivo es **esperado** (a diferencia de `discarded_events`).
- [ ] 6.2 Crear `frontend/src/utils/outOfScopeDrops.ts` con `getOutOfScopeDropsMeta(count: number | null | undefined)`, mapper **puro** de tres estados (`unknown` / `zero` / `positive`) que nunca lanza, siguiendo el contrato de `frontend/src/utils/discardedEvents.ts`.
- [ ] 6.3 Las clases de los tres estados usan **paleta neutra** (gris), nunca roja ni ámbar — incluido el estado `positive`. Esta es la diferencia deliberada con `getDiscardedEventsMeta`, que pinta el positivo en rojo porque allí es una detección perdida. Comentar el mapper explicando esa asimetría y citando D69/RN-163, para que una futura "unificación de estilos" no la borre.
- [ ] 6.4 El `title` del estado `positive` SHALL explicar que los descartes fuera de scope son esperados y que el contador es la evidencia de que el filtro de scope está funcionando. El del estado `unknown` distingue "nunca reportó" de cero, al estilo del mapper vecino.
- [ ] 6.5 **No** reutilizar `getDiscardedEventsMeta` con un parámetro ni generalizar los dos mappers en uno (D-7 del design). Son módulos separados a propósito.

## 7. Frontend — tarjeta del agente y tests

- [ ] 7.1 En `frontend/src/components/ui/AgentCard.tsx`, agregar un `OutOfScopeDropsIndicator` que consuma `getOutOfScopeDropsMeta`, con la misma forma que `DiscardedEventsIndicator` (`:54-64`) pero sin su tratamiento de anomalía. Etiqueta en prosa de UI, contenido del contador en `tabular-nums` como sus vecinos.
- [ ] 7.2 Ubicarlo en el bloque de presión de cola (`:141-177`), junto a `DiscardedEventsIndicator` (`:147`), de modo que los dos contadores se vean a la vez y su diferencia de tratamiento sea evidente en pantalla.
- [ ] 7.3 Comentar la ubicación citando D69/RN-163 y nombrando explícitamente el contraste con `discarded_events`: los dos están al lado y **deben** verse distintos.
- [ ] 7.4 Test del mapper (`frontend/src/utils/outOfScopeDrops.test.ts`): los tres estados retornan resultados distintos, ninguno lanza, y ninguno usa la paleta de alarma. El test del color es el que impide que un futuro cambio de estilo convierta el contador en un indicador rojo en silencio.
- [ ] 7.5 Test en `AgentCard.test.tsx`: un valor positivo se renderiza con tratamiento neutro; un cero se renderiza como cero; un agente sin el campo muestra el estado desconocido y **no** cero.
- [ ] 7.6 Test en `AgentCard.test.tsx`: con descartes locales positivos y descartes fuera de scope positivos a la vez, los dos indicadores se renderizan y sus tratamientos visuales difieren.
- [ ] 7.7 Verificar que los tests existentes de `AgentCard` y de `discardedEvents` siguen verdes **sin modificarlos**: esta change no altera la presentación de `discarded_events`.
- [ ] 7.8 Correr la suite del frontend completa y dejar el resultado en el reporte de apply.

## 8. Cierre del change

- [ ] 8.1 Verificar que la entrada del Change 56 en `CHANGES.md` refleja lo efectivamente implementado. Si el alcance cambió durante el apply, actualizar la entrada: el roadmap es índice, no historia.
- [ ] 8.2 Correr `python3 scripts/check_spec_integrity.py` antes y después del archive (D47/RN-141, sección MANDATORIA de `CLAUDE.md`).
- [ ] 8.3 Correr `openspec validate agent-scope-drop-observability --strict` y dejar el resultado en el reporte.
- [ ] 8.4 **No tocar** `docs/cierre/**`, `.env.example`, `docs/trazabilidad_us_tests.md` ni `docs/residuales_declarados.md` en esta change: quedan fuera de alcance.
- [ ] 8.5 Documentar en el reporte de apply cualquier suposición que haya aparecido y que D69/RN-163 no cubra —en particular la presentación de `event_drops` (D-6) o un umbral de alerta sobre el contador—. En ese caso **detener el flujo** y cerrar la decisión en el appendix "Decisiones de implementación — Abril 2026" antes de continuar.
