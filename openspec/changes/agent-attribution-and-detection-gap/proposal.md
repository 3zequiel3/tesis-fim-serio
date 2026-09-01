## Why

El agente convierte «no sé» en una afirmación positiva, dos veces, y las dos veces la afirmación
favorece la lectura más tranquilizadora o la más alarmante sin distinguirlas de un hecho verificado.

**Atribución.** `agent/detector.py:98-106` declara `_get_uid(pid) -> int` y devuelve `0` cuando
`open("/proc/<pid>/status")` levanta `OSError`. Ese archivo desaparece en cuanto el proceso termina,
y entre la notificación del kernel y el armado del evento hay hasta 150 ms de reintentos de hash
(`_hash_file_async`), de modo que un editor que escribe y sale, un `install` o un paso de gestor de
paquetes **ya no existe** cuando se lo consulta. El evento resultante dice `process_uid: 0`, que en
el vocabulario del sistema significa **root**. `agent/decision.py:151` es peor: la ruta de
rehidratación del journal escribe `"process_uid": 0` de forma incondicional, y ahí el proceso
original no existe **por definición**, así que todo evento recuperado tras un reinicio del agente se
reporta como hecho por root. Un operador que filtra por `uid = 0` para buscar cambios privilegiados
recibe una lista contaminada, sin ninguna marca que separe la atribución real de la inventada.

**Cobertura.** `agent/_fanotify.py` nunca define la constante `FAN_Q_OVERFLOW` (`0x00004000`) y
`_parse_events` (`agent/_fanotify.py:241-258`) nunca la chequea. Cuando el kernel desborda su propia
cola descarta eventos y sigue; el agente, que nunca los recibe, no tiene forma de inferir que
faltaron. Es el único modo de falla del sistema que es silencioso **por construcción**. Los
contadores existentes no lo cubren: `event_drops` (`agent/detector.py:402-411`, publicado en
`agent/heartbeat.py:103`) mide la `asyncio.Queue` interna del agente —un punto de pérdida
posterior, cuando el evento ya salió del kernel— y `queue_pressure` mide la cola offline de 100 MB
en disco (`agent/queue.py:1-27`), que no tiene relación alguna con la saturación de `fanotify`.

Origen: auditoría externa de la tesis del 2026-08-21, con los hallazgos verificados contra el código
el 2026-08-24. Las tres decisiones que gobiernan esta change ya están cerradas: **D49/RN-143**,
**D50/RN-144** y **D51/RN-145** (`docs/reglas_de_negocio.md:1559,1590,1625`). No se abre ninguna
suposición nueva.

## What Changes

- **`process_uid` nulo cuando la atribución no se resolvió (D49/RN-143).** `_get_uid` pasa a
  `-> int | None`; `FanotifyEvent.uid` (`agent/detector.py:55`) y `DetectedChange.process_uid`
  (`:72`) acompañan el cambio de tipo. La rehidratación del journal (`agent/decision.py:151`) emite
  `process_pid`, `process_uid` y `process_exe` en `null`. `0` pasa a significar exclusivamente
  «el proceso causante corría como root».
- **`FAN_Q_OVERFLOW` deja de ser invisible (D50/RN-144).** Se define la constante en
  `agent/_fanotify.py`, `_parse_events` la reconoce y la propaga, y el hilo lector emite un evento
  sintético `event_type: "detection_gap"` con `path` nulo, causa `fan_q_overflow` y contexto de
  proceso nulo, por el **mismo stream** que la evidencia. Deduplicación **por ventana**: a lo sumo
  un `detection_gap` por ventana de 60 segundos, con la cuenta de desbordamientos suprimidos en el
  propio evento.
- **`event_type` persistido y `path` opcional (D51/RN-145).** Columna `event_type` en `Event` con el
  vocabulario que el agente ya emite (`file_created`, `file_modified`, `file_deleted`,
  `file_absent`, `detection_gap`), en minúsculas snake_case (RN-71), propagada a `EventOut`, a
  `EventListItem` y al tipo del frontend. `Event.path` pasa a nullable y la ingesta deja de degradar
  el nulo a `""` (`backend/app/modules/events/service.py:164`).
- **Un evento sin ruta no participa de la supersesión por path.** `get_pending_event_for_path`
  (`service.py:88-94`) y `compact_chain` (`:244`) se saltean cuando la ruta es nula. Sin esto,
  **todos** los `detection_gap` se supersederían entre sí bajo la clave `""` y cada brecha nueva
  borraría la anterior de la vista del operador.
- **Severidad de un evento sin ruta: `high` fijo.** Excepción acotada a D34/RN-128 —el backend sigue
  siendo la única autoridad y la sigue calculando al ingerir—, disparada por **ausencia de ruta**, no
  por tipo de evento.
- **Un evento sin ruta no ejecuta acción física.** El motor de decisión no puede restaurar ni poner
  en cuarentena algo que no tiene path: el `detection_gap` se emite con `action: "alert_only"` sin
  atravesar `evaluate_and_act`, y el ruleset no se consulta.
- **Frontend.** `EventsTable` y `EventDetail` renderizan una fila sin ruta con el `event_type` como
  discriminador visible, sin guiones ni celdas vacías.
- **Migración `012` en esta change**, no separada: `event_type` NOT NULL con default
  `file_modified` para las filas previas, y `path` relajada a nullable.
- **Limpieza de referencias stale a `pyfanotify`** en `agent/detector.py:2,52,242,279,363` y en los
  docstrings de `agent/tests/test_symlink_hardening.py:22`,
  `agent/tests/test_detector_multi_event.py:39`, `agent/tests/test_scope_filter.py:14,195` y
  `agent/tests/test_agent_config.py:17`. **No** se tocan `agent/requirements.txt:6` ni
  `agent/_fanotify.py:5`: el primero ya declara explícitamente que no se depende de `pyfanotify` y
  el segundo es una referencia legítima al wrapper descartado.

No hay cambios **BREAKING** de contrato: `event_type` es aditivo y tolerante hacia adelante, y
`path` pasa de obligatorio a opcional (relajación, no restricción). El único consumidor que debe
adaptarse es el frontend, que hoy tipa `path: string`.

## Capabilities

### New Capabilities

Ninguna. Las tres decisiones se expresan como cambios de requisito sobre capabilities existentes;
introducir una capability nueva fragmentaría el contrato del evento entre dos archivos sin agregar
cobertura.

### Modified Capabilities

- `agent-fanotify-detector`: la captura de contexto de proceso admite atribución no resuelta
  (`process_uid` nulo); el descarte de eventos con path nulo se acota para no tragarse el
  desbordamiento; se agrega la detección de `FAN_Q_OVERFLOW` y la emisión de `detection_gap` con
  deduplicación por ventana; el léxico de `operation_type` incorpora `detection_gap`.
- `agent-decision-engine`: la rehidratación del journal deja de fabricar contexto de proceso; se fija
  que un evento sin ruta no ejecuta acción física.
- `backend-event-consumer`: la ingesta persiste `event_type`, preserva el `path` nulo sin
  degradarlo a `""`, excluye a los eventos sin ruta de la supersesión y de la compactación de
  cadena, y les asigna severidad `high` fija.
- `backend-events-api`: `EventOut` expone `event_type` y admite `path` nulo en el listado y en el
  detalle.
- `domain-models`: `Event.event_type` (str NOT NULL) y `Event.path` (`str | None`), más la migración
  SQL `012`.
- `frontend-events`: el tipo `EventListItem` incorpora `event_type` y `path: string | null`; la
  tabla y el detalle renderizan un evento sin ruta.

## Impact

**Agente** — `agent/detector.py` (`_get_uid`, `FanotifyEvent`, `DetectedChange`, `_read_loop`),
`agent/_fanotify.py` (constante `FAN_Q_OVERFLOW`, `_parse_events`, `FanEvent`), `agent/decision.py`
(`rehydrate`).

**Backend** — `backend/app/modules/events/models.py` (`Event`),
`backend/app/modules/events/service.py` (`ingest_event`, `get_pending_event_for_path`,
`compact_chain`, severidad), `backend/app/modules/events/router.py` (`EventOut`).
`backend/app/modules/events/consumer.py` **no** requiere cambios: no valida `path` en ninguno de sus
siete pasos de validación.

**Base de datos** — `backend/db/migrations/012_add_event_type_and_nullable_path.sql` (SQL manual
idempotente, misma convención que 005–011; el proyecto no usa Alembic, D3).

**Frontend** — `frontend/src/api/events.ts` (`EventListItem`),
`frontend/src/components/ui/EventsTable.tsx:134`, `frontend/src/pages/EventDetail.tsx:89`.

**Tests** — el cambio en `agent/decision.py:151` hoy **no tiene cobertura**: los tests que ejercen
`engine.rehydrate()` (`agent/tests/test_decision.py:220,364,399,419`) no assertan sobre
`process_uid`. Las fixtures con `process_uid: 0` en `test_decision.py:60-77`,
`test_restore_metadata.py:77` y `test_symlink_hardening.py:565` son helpers `_make_change()` que
representan un proceso root **real** y **no se modifican**.

**Resultados de la tesis** — los datos de `resultados/` corresponden al esquema previo a la
migración `012` y a un agente que atribuía a root la atribución no resuelta. La re-corrida de las
baterías del Capítulo 5 es **condición para reportar**.
