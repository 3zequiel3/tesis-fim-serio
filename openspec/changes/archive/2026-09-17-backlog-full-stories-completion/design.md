## Context

**Estado de partida.** Corte del 2026-09-16 sobre `devel`, commit `2475de8`
(`docs/cierre/MATRIZ_TRAZABILIDAD.md`): 25 completas, 6 parciales, 0 sin cobertura.

| Historia | Criterio pendiente | Evidencia verificada |
|---|---|---|
| US-07 | Selector con los 7 estados | `Events.tsx:11-18` lista 6; `superseded` sólo se renderiza con el toggle activo (`:107-117`, toggle en `:175-186`) |
| US-11 | Baseline con el hash **actual** | `actions/streams.py:132` usa `event.hash_detected` por D2; `test_actions.py::test_no_get_file_hash_published` asserta lo contrario al texto |
| US-21 | Flag booleano `queue_pressure: true` (W3) | `agent/heartbeat.py:100` publica el float; `AgentCard.tsx:80-83` decide el umbral en el cliente |
| US-22 | Confirmación visual del rescan | `toast.success('Rescan iniciado')` en `Agents.tsx`, sin test; no existe `Agents.test.tsx` |
| US-27 | `audit_log` de `login`/`logout` | `write_audit_log` en `auth/router.py:124,247`, sin aserción |
| US-29 | `last_error`/`retry_count`/`failed_at` en HTTP | Declarados en `AlertResponse`; `test_get_failed_alerts_returns_only_failed` asserta sólo `id` y `total` |

**Ajustes de criterio ya aplicados y no declarados como tales.** `cc73c2d` (2026-09-15) reescribió texto
canónico de US-01, US-05, US-23, US-27 y US-29, y creó D66/RN-160 para US-12. Las decisiones que respaldan
cada ajuste: D6/RN-107 (tabla `alerts` y banner sin umbral, reescritura de RN-102), D66/RN-160
(`ruleset_version` fuera de los comandos de acción) y, desde esta propuesta, D70/RN-164 (ruta
`/change-password`) y D71/RN-165 (hash del evento en el approve).

**Decisiones ya cerradas antes de proponer.** D70/RN-164, D71/RN-165 y D72/RN-166 en los appendices de
`docs/reglas_de_negocio.md` y `docs/arquitectura_stack.md`; criterio 4 de US-11 alineado en
`docs/historias_de_usuario.md`.

**Interacción con el change 56 (`agent-scope-drop-observability`, en apply).** Toca los mismos archivos del
heartbeat de punta a punta y es dueño de la migración `020`. Introduce el patrón de ingesta tolerante y
nullable para `out_of_scope_drops` que este change replica.

**Alcance de D66 sobre US-11 C5.** Verificado: D66/RN-160 se limita a los comandos de **acción** sobre
eventos (`restore_file`, `quarantine_file` y sus reintentos). El `baseline_update` del approve **sí** lleva
`ruleset_version` (`actions/streams.py:145`, incrementado por el caller según D5) y el agente lo rechaza si
es menor al aplicado (`agent/commands.py:250-257`). US-11 C5 no está afectado por D66 y no requiere ajuste.

## Goals / Non-Goals

**Goals:**

- Cerrar US-07 y US-21 cambiando el código para cumplir el texto canónico.
- Cerrar US-22, US-27 y US-29 con un test por criterio.
- Declarar, historia por historia, cada ajuste de criterio con su decisión, fecha y commit, y llevar las dos
  matrices a 31/0/0 con el conteo estricto visible al lado.
- Dos partes independientes: la parte 1 no depende de la parte 2 y cada una se commitea sola.

**Non-Goals:**

- Retirar el float `queue_pressure` o cambiar su cálculo, el límite de 100 MB o la política drop-oldest.
- Cambiar el backend de eventos: la coherencia de `superseded` se resuelve en el frontend.
- Reabrir D2, D6 o D66.
- Producir un nuevo candidato consolidado con cadena de custodia.
- Editar el texto canónico de otras historias fuera de lo que la parte 2 enumera.

## Decisions

### D-1: Dos partes con frontera en el tipo de trabajo

La parte 1 cambia comportamiento y agrega tests; la parte 2 sólo toca documentación de trazabilidad. La
matriz no puede decir 31/0/0 antes de que los tests de la parte 1 existan y pasen, así que la parte 2 va
después y cita los nombres reales de los tests. Alternativa descartada: un único grupo por historia, que
mezclaría commits de código y de documentación y obligaría a reescribir la matriz varias veces.

### D-2: US-07 — coherencia resuelta en el frontend, sin tocar el backend

`GET /events` excluye `superseded` antes de aplicar `status` (`events/router.py:129-133`), así que
`status=superseded` sin `include_superseded=true` devuelve siempre vacío. Se acopla en el cliente:
marcar `superseded` agrega `include_superseded=true`; apagar el toggle quita `superseded` del filtro; y
`parseEventFilters` normaliza una URL con `status=superseded` para que el toggle quede activo.

Alternativa descartada: que el backend incluya `superseded` cuando aparece en `status`. Cambia el contrato
de un endpoint cuya semántica ya está especificada y testeada (`test_list_events_excludes_superseded_by_default`)
para resolver algo que es de presentación. La normalización en el parser mantiene válido el deep-link
(requisito existente de URL como estado reconstruible).

Desmarcar `superseded` **no** apaga el toggle: el toggle tiene sentido propio (ver los reemplazados junto
al resto sin filtrarlos por estado) y apagarlo implícitamente sorprendería al operador.

### D-3: US-21 — flag calculado en el agente a partir de una sola lectura

`_publish` lee `self._queue.queue_pressure` una vez, lo guarda en una variable local y deriva de ella
`queue_pressure` y `queue_pressure_high`. `queue_pressure` es una property que suma el tamaño de los archivos de la
cola: leerla dos veces podría producir un ratio de 0,81 y un flag calculado sobre 0,79 en el mismo mensaje.
El umbral vive como constante en `agent/queue.py` (`QUEUE_PRESSURE_HIGH_THRESHOLD = 0.8`), junto al
límite de 100 MB que define, con comparación estricta (`>`), igual que el cliente actual (`pressurePct > 80`)
y que W3 ("al superar 80%").

Alternativa descartada: una property `queue_pressure_high` en `EventQueue`. Obligaría a una segunda
lectura del directorio o a cachear el ratio dentro de la cola, con un estado nuevo que invalidar.

### D-4: US-21 — ingesta tolerante con booleano estricto

Mismo patrón que `discarded_events` y `out_of_scope_drops`: clave ausente o `null` no toca el valor; un
valor presente se acepta sólo si `isinstance(value, bool)`. A diferencia de los contadores, acá el tipo
válido **es** `bool`, así que `0`/`1` y `"true"`/`"false"` se rechazan con
`log.warning("heartbeat_consumer.invalid_queue_pressure_high", agent_id=...)`. La columna es
`bool | None = Field(default=None)`; `_agent_to_response` la propaga sin transformar (sin `or False`).

La migración es `021_add_agent_queue_pressure_high.sql`, una sola sentencia
`ALTER TABLE agents ADD COLUMN IF NOT EXISTS queue_pressure_high BOOLEAN;`, sin `DEFAULT`, sin `NOT NULL`,
sin backfill, con el encabezado al estilo de `019`/`020`.

### D-5: US-21 — el banner depende sólo del flag; la barra sigue usando el ratio

`showQueuePressureBanner = agent.queue_pressure_high === true`. Sin respaldo por umbral en el cliente
(D72/RN-166). La barra conserva `pressurePct` y sus colores. Consecuencia aceptada: un agente anterior al
flag no muestra banner aunque su ratio supere 0,8; la barra sí lo muestra. En este despliegue todos los
agentes se reinstalan desde el repositorio, así que la ventana es la del propio despliegue.

### D-6: Orden estricto respecto del change 56

El change 56 se archiva antes de aplicar este. Motivos: comparte los siete archivos del heartbeat, es dueño
de la migración `020` y de las líneas de `AgentCard` donde vive la barra de presión, y su delta de
`backend-agent-management` establece el criterio que este replica. Aplicar en paralelo produciría
conflictos de merge en archivos donde el orden de los campos importa para la lectura, y un archive
cruzado sobre la misma main spec. `scripts/check_spec_integrity.py` se corre antes y después de cada
archive.

### D-7: Tests de US-22, US-27 y US-29 en los archivos existentes, salvo US-22

- **US-22**: archivo nuevo `frontend/src/pages/Agents.test.tsx`, porque no existe test de la página; mockea
  `@/api/client` como `Events.test.tsx` y mockea `sonner` (la librería que importa `Agents.tsx`)
  para assertar `'Rescan iniciado'` y `'Rescan forzado iniciado'`.
- **US-27**: dos tests en `backend/tests/test_auth.py`, junto a `test_change_password_deja_fila_en_audit_log`,
  consultando `AuditLog` por `action == "login"` y `"logout"` y el `user_id` correspondiente.
- **US-29**: un test en `backend/tests/test_notifications.py`, junto a
  `test_get_failed_alerts_returns_only_failed`, que siembra una alerta en fallo terminal con valores
  conocidos y asserta los tres campos en la respuesta HTTP (`failed_at` como ISO-8601 con zona).

### D-8: Tabla de ajustes declarados y conteo estricto

Cada matriz gana una tabla "Ajustes de criterio declarados" con columnas: Historia, Criterio, Texto
original, Texto vigente, Decisión, Fecha, Commit. El resumen muestra dos números: **31/0/0** (con ajustes
declarados) y el **conteo estricto** (historias completas cuyo texto canónico no fue ajustado). Las
historias cerradas por cambio de código (US-07, US-21) **no** son ajustes de criterio y cuentan en el
estricto. La etiqueta "D6/RN-102" que usan los textos de US-05 y US-29 se declara como
**D6/RN-107 (reescritura de RN-102)**, porque RN-102 conserva su texto original con `failed_notifications`
y es D6/RN-107 quien lo sustituye (tabla "Reglas modificadas por este appendix").

## Risks / Trade-offs

- **[Riesgo] El conteo estricto depende de un inventario completo de ajustes.** `cc73c2d` tocó también US-27
  (ruta) y US-29 (tabla, banner y ruta `/alerts/failed`), no sólo US-01, US-05, US-12 y US-23. →
  Mitigación: la parte 2 inventaría el diff de `cc73c2d` sobre `docs/historias_de_usuario.md` completo y
  cada línea cambiada tiene fila en la tabla. Con ese inventario el estricto es **24** (31 menos US-01,
  US-05, US-11, US-12, US-23, US-27 y US-29).
- **[Resuelto] La ruta `/alerts/failed` no tenía decisión.** US-29 y US-05 enlazaban a `/alerts/failed`
  desde `cc73c2d` sin respaldo. → Cerrado el 2026-09-17: D70/RN-164 se amplió a ambas rutas y RN-102 se
  reescribió con `alerts` (D6/RN-107) y `/alerts/failed`.
- **[Riesgo] Valor rancio del flag.** Un agente que baja de versión deja de enviar la clave y el backend
  conserva el último valor. → Aceptado: es el mismo comportamiento de todos los campos tolerantes del
  heartbeat; el `last_heartbeat` sigue indicando frescura.
- **[Riesgo] Invalidar la corrida del Capítulo 5.** El slice del agente cambia el payload del heartbeat. →
  Mitigación: desplegarlo antes de re-correr las baterías (tarea 12.4 de
  `agent-attribution-and-detection-gap`), igual que el change 56; dejar las fechas en el reporte de apply.
- **[Trade-off] Sin respaldo en el cliente.** Un agente viejo no muestra banner. → Aceptado por D72/RN-166.

## Migration Plan

1. Archivar el change 56 (con `check_spec_integrity.py` antes y después).
2. Parte 1: agente → backend (`psql $DATABASE_URL -f backend/db/migrations/021_add_agent_queue_pressure_high.sql`,
   D3) → frontend. El orden garantiza que el backend acepte la clave antes de que la UI la consuma; el
   backend nuevo con agentes viejos lee `null`.
3. Desplegar el agente antes de la corrida del Capítulo 5.
4. Parte 2: matrices.

**Rollback**: la columna nullable puede quedar sin uso; revertir el frontend vuelve al umbral en el
cliente y revertir el agente deja de emitir la clave sin romper el consumer.

## Open Questions

- Ninguna bloqueante. La ruta `/alerts/failed` quedó cubierta por la ampliación de D70/RN-164 y la
  etiqueta de US-05 y US-29 se corrigió a "D6/RN-107, reescritura de RN-102" (tareas 7.1 y 7.2, cerradas
  el 2026-09-17).
