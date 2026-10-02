## Why

El agente no reporta nada de lo que ocurre en el filesystem mientras está detenido. Es un defecto de
**seguridad**: detener el servicio, modificar o borrar un archivo vigilado y volver a arrancarlo
alcanza para que el cambio no aparezca nunca en la plataforma.

La causa está en la secuencia de arranque. `agent/__main__.py:258` ejecuta `engine.init_scan(...)`,
y `init_scan` (`agent/baseline.py:463`) es idempotente por construcción: omite todo path que ya tiene
entrada (`:480-482` para symlinks, `:497-499` para archivos regulares) y sólo da de alta los que no
la tienen, **en silencio**. `verify_entry` (`:565`) existe pero no se invoca al arrancar, y aunque se
invocara sólo verifica la etiqueta GCM del blob, no el archivo. Después de `init_scan` el detector
recién instala las marcas de fanotify (`agent/detector.py:1187`) y sólo ve lo que ocurre desde ese
momento. El resultado:

- Un archivo **modificado** offline nunca produce `file_modified`: el hash del baseline queda
  distinto del disco sin que nadie lo compare.
- Un archivo **eliminado** offline nunca produce `file_deleted` y su entrada conserva
  `status: present` con el hash anterior. Si después alguien lo **recrea con el mismo contenido**,
  la rama `file_created` del detector (`detector.py:945-951`) compara contra ese hash, lo encuentra
  igual y descarta el evento como «sin cambio real». La eliminación y la recreación quedan ambas
  invisibles.
- Un archivo **creado** offline en una raíz ya vigilada lo absorbe `init_scan` como baseline sin
  emitir evento: queda aprobado sin revisión.

Es la causa de los 17 «falsos negativos» y de las 328–329 operaciones no encoladas medidos sobre
`v4.0-tesis`; esta change invalida ese candidato y la re-medición única se hace sobre `v5.0-tesis`
(ver Change 61).

Las decisiones que gobiernan la change están cerradas: **D80/RN-174**
(`docs/arquitectura_stack.md:2720`, `docs/reglas_de_negocio.md:2707-2715`), incluida su ampliación
del 2026-10-02 (commit `1c308d5`) que cierra el alcance de `file_created` para archivos sin entrada
(`initialized_roots`) y la no re-emisión de una modificación ya reportada. No se abre ninguna
suposición nueva.

## What Changes

- **`initialized_roots` en `state.json`.** `AgentState` (`agent/state.py:17-24`) y `save_state`
  (`:57-75`) ganan el conjunto de raíces vigiladas que completaron un primer escaneo. Ausente en un
  `state.json` previo → conjunto vacío.
- **`init_scan` sólo da de alta en silencio raíces no inicializadas.** En el primer arranque o ante
  un `watch_path` nuevo, `init_scan` escanea la raíz como hoy, la marca en `initialized_roots` y no
  emite eventos. Una raíz ya inicializada **no** se recorre en `init_scan`: sus archivos sin entrada
  quedan para el reconcile. `handle_update_config` (`agent/commands.py:578`) marca también las raíces
  que agrega con `run_scan`.
- **`BaselineEngine.reconcile_on_start()`** (`agent/baseline.py`) compara el baseline contra el
  filesystem de cada raíz inicializada y produce hallazgos:
  - entrada `present` y path inexistente → `file_deleted`;
  - entrada `present` y hash distinto (o cambio de tipo symlink ↔ regular) → `file_modified`,
    **salvo** que el candidato de aprobación del path (`stage_approval_candidate`,
    `baseline.py:662`) ya tenga ese mismo hash: la modificación ya fue reportada y no se re-emite;
  - entrada `absent`, o path sin entrada, y archivo existente → `file_created`.
- **Emisión por el camino normal del detector.** Cada hallazgo entra a
  `FanotifyDetector._process_event` con la clase forzada y `detected_offline=True`, y recorre
  exactamente `_stage_approval_candidate` → `DecisionEngine.evaluate_and_act` → actualización del
  baseline → `publisher.publish` → `commit_fn` (`detector.py:1123-1172` y sus pares en `:871-900`
  y `:976-1000`). El reconcile **nunca** publica por separado.
- **Campo `detected_offline`.** `DetectedChange` (`detector.py:78-112`) agrega
  `detected_offline: bool = False`, presente en todo payload. Los eventos del reconcile llevan
  `true`, `process_pid`/`process_uid`/`process_exe` en `null` (precedente D49/RN-143) y
  `detected_at` igual al instante del reconcile. `FanotifyEvent.pid` y `DetectedChange.process_pid`
  pasan a `int | None`. **Sin** cambio de `schema_version`.
- **Orden de arranque.** El reconcile corre en `agent/__main__.py` después de
  `decision_engine.rehydrate(publisher)` (`:380`) y antes del `asyncio.gather` (`:381`), es decir
  antes de que el detector arranque. Log `baseline.reconcile.complete` con los conteos.
- **Backend.** Migración aditiva `023_add_event_detected_offline.sql` (columna `BOOLEAN` anulable, sin
  backfill ni índice); `Event.detected_offline: bool | None`; ingesta tolerante (clave ausente →
  `NULL`, no booleano → ignorado con log); `EventOut.detected_offline` aditivo.
- **Frontend.** `EventListItem.detected_offline` en `frontend/src/api/events.ts` y un indicador en el
  encabezado de `EventDetail` (`frontend/src/pages/EventDetail.tsx:119-122`) cuando vale `true`.

No hay cambios **BREAKING**: el campo es opcional en el contrato, un backend anterior lo ignora y un
agente anterior produce `NULL`.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `agent-baseline`: `init_scan` deja de absorber en silencio archivos nuevos de raíces ya
  inicializadas; nuevo requisito de reconciliación al arrancar (D80/RN-174).
- `agent-core`: `state.json` persiste `initialized_roots`; el arranque ejecuta el reconcile después
  de la rehidratación del journal y antes del detector.
- `agent-fanotify-detector`: los hallazgos offline se emiten por el camino normal del detector con
  `detected_offline: true` y contexto de proceso nulo.
- `domain-models`: `Event` gana la columna anulable `detected_offline` (migración `023`).
- `backend-event-consumer`: la ingesta persiste `detected_offline` con tolerancia hacia adelante.
- `backend-events-api`: `EventOut` expone `detected_offline`.
- `frontend-events`: el detalle del evento muestra la marca de detección offline.

## Impact

- **Agente**: `agent/state.py`, `agent/baseline.py` (`init_scan`, `reconcile_on_start`, lectura del
  candidato de aprobación), `agent/detector.py` (`FanotifyEvent`, `DetectedChange`,
  `_process_event`), `agent/commands.py` (`handle_update_config`), `agent/__main__.py`.
- **Backend**: `backend/db/migrations/023_add_event_detected_offline.sql`,
  `backend/app/modules/events/models.py`, `backend/app/modules/events/service.py`
  (`_ingest_event_outcome`, `:402-428`), `backend/app/modules/events/router.py` (`EventOut`).
- **Frontend**: `frontend/src/api/events.ts`, `frontend/src/pages/EventDetail.tsx` y su test.
- **Dependencias del DAG**: Change 61 (`agent-publisher-fifo-reconnect`, D79/RN-173) define el orden
  FIFO del publisher con el que viaja la ráfaga del reconcile. El **apply** de esta change espera a
  que 61 esté archivada. Change 66 (D84/RN-178) introducirá `schema_migrations` (`000`) y registrará
  `023`; esta change no depende de ella.
- **Reglas**: RN-174 (nueva). Preserva D49/RN-143 (atribución nula), D14 (decidir antes de mutar el
  baseline), BUG-03 (el hash activo no se reemplaza por contenido no aprobado), RN-83 (rehidratación
  antes del detector), D33/RN-127 (symlink como objeto).
