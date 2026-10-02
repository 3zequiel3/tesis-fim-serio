## Why

Poner un archivo en cuarentena destruye la versión aprobada que la cuarentena debía proteger. Tras
una cuarentena automática, el detector llama a `mark_absent` (`agent/detector.py:1158` en la rama
`file_modified` y `:990-992` en la rama `file_created`), y `mark_absent` (`agent/baseline.py:385-401`)
reescribe la entrada con `snapshots=[]`, `content_b64=None` y metadatos nulos. A partir de ese momento
`select_restorable_content` (`agent/baseline.py:207-228`) devuelve `None` y toda restauración posterior
—automática (`agent/decision.py:226-234`) o del operador— falla con `no_restorable_content`. RN-37
afirma lo contrario: «el baseline permanece intacto».

El camino del operador pierde la versión aprobada por otra vía. `handle_quarantine_file`
(`agent/commands.py:422-505`) no toca el baseline —ni siquiera recibe el `BaselineEngine`, aunque
`dispatch` lo tiene (`:110`, `:170-180`)—, pero el `os.unlink` propio de la cuarentena
(`agent/quarantine.py:626`) rebota como `FAN_DELETE`/`FAN_MOVED_FROM`, entra en la rama `file_deleted`
del detector (`agent/detector.py:847-904`) y ejecuta `mark_absent` en `:896`. La prueba
`test_quarantine_still_reports_the_absence` (`agent/tests/test_restore_feedback_loop.py:556-595`) fija
hoy ese comportamiento como correcto. En el camino automático el mismo eco además reevalúa la regla
`quarantine`, reintenta la cuarentena sobre un archivo que ya no existe y publica un evento
`file_deleted` que el backend deriva a `pending` con `action_error="file_not_found"`: cada cuarentena
automática deja un evento espurio en la cola del operador.

Finalmente, la cuarentena está implementada dos veces —`DecisionEngine._quarantine`
(`agent/decision.py:299-311`) y `handle_quarantine_file`— con mapeos de error distintos (el handler
publica `str(exc)`, que puede incluir texto del sistema operativo) e identidades de artefacto
distintas (`event_id` del agente en un camino, `command_id` en el otro). Es el residual §9 de
`docs/residuales_declarados.md`.

Origen: guía de laboratorio de la tesis v29 (ítems L-2…L-9) verificada contra `devel`; exploración
previa en `docs/implementaciones/cuarentena-y-diff-arreglos-como-implementar.md` (sus números de
decisión provisionales D70–D76 no aplican). Base para el candidato `v5.0-tesis` (re-medición única,
Change 61). La decisión que gobierna esta change está cerrada: **D82/RN-176**
(`docs/reglas_de_negocio.md:2729-2739`, fila D82 de `docs/arquitectura_stack.md:2722`, ampliada en
`5aa6887` y ratificada en `453caba`). Dependencia del DAG: Change 63 `agent-restore-verify-from-disk`
(propuesta, no archivada). El orden de apply es **61 → 62 → 63 → 64**: 63 toca `agent/decision.py` y
`agent/commands.py` y la transición `quarantined → present` de esta change se apoya en su
verificación desde disco (D81/RN-175); 62 deja `reconcile_on_start`, al que esta change agrega la
guarda de RN-176.

## What Changes

- **Estado explícito `quarantined` en la entrada de baseline (D82/RN-176, opción A).**
  `BaselineEntry` gana el valor de `status` `"quarantined"` y el campo `quarantine_action_id`.
  `BaselineEngine.mark_quarantined(path, action_id)` conserva `hash`, metadatos, `content_b64`,
  `snapshots` y `approved_event_id` de la entrada previa; sin entrada previa escribe una entrada
  `quarantined` con campos nulos. `mark_absent` queda reservado a ausencias no causadas por el agente.
  La entrada `quarantined` sigue siendo fuente de `select_restorable_content`.
- **Una única implementación: `quarantine_and_record` en `agent/quarantine.py`.** Orden: journal
  `pending` → `QuarantineStore.quarantine` → `mark_quarantined` → resultado al llamador. El paso
  terminal del journal (`completed`/`failed`) queda **en manos del llamador**: el camino automático lo
  cierra después de publicar (`commit_fn`), preservando el replay al reiniciar; el handler lo cierra
  antes del `event_ack`. Un vocabulario único de causas de falla para ambos caminos.
- **`action_id` del artefacto = `event_id` del agente, siempre.** En el camino del operador el
  backend agrega al comando firmado `quarantine_file` el campo `agent_event_id` (`Event.event_id`,
  UUID del agente); el handler lo usa como identidad del artefacto y como clave de journal. Los
  artefactos previos nombrados por `command_id` se declaran no liberables (`artifact_not_found`, que
  implementa la Change 65).
- **Supresión del auto-eco por estado, no por PID.** Un `file_deleted` o un `file_absent` sobre una
  entrada `quarantined` se descarta antes de asignar `event_id`, con traza `decision_suppressed` y
  razón `quarantined_by_agent`: sin reglas, sin journal, sin publicación y sin mutar el baseline.
  Riesgo aceptado por RN-176: crear en esa ruta un archivo con contenido distinto del aprobado y luego
  borrarlo reporta la creación pero no el borrado.
- **Salidas del estado `quarantined`.** Una restauración verificada (automática o del operador), una
  aprobación (`baseline_update`) o un archivo recreado con **exactamente** el hash aprobado (estado
  sano, equivalente a una restauración verificada; ratificación de RN-176 en `453caba`) devuelven la
  entrada a `present`, de modo que un borrado posterior sí se reporta. Un archivo nuevo con otro
  contenido se reporta pero **no** sobrescribe la entrada (`agent/detector.py:993-996` deja de aplicarse a entradas
  `quarantined`); su contenido sólo se adopta por aprobación.
- **Rehidratación.** El reintento de una cuarentena pendiente pasa por `quarantine_and_record`, de
  modo que la ventana de crash entre el `unlink` y el marcado queda cubierta.
- **`quarantine_state` derivado en lectura (backend).** `GET /events` y `GET /events/{id}` exponen
  `quarantine_state ∈ {none, quarantined, released, discarded}`, sin columna en `events`:
  `quarantined` si `status = quarantined`, o si `status = rejected` con un `quarantine_file` `acked`;
  `released`/`discarded` cuando además existe un `release_quarantine` `acked` con modo de restauración
  o `discard` (comando que crea la Change 65; acá sólo se lee). `GET /events` acepta el filtro
  repetible `quarantine_state`, resuelto en SQL. **La máquina de estados de eventos no cambia**: el
  rechazo con cuarentena sigue terminando en `rejected` (RN-11, RN-12 y RN-72 sin enmienda).
- **Frontend.** Badge de `quarantine_state` en la tabla y en el detalle del evento, y filtro
  multi-select sincronizado en la URL, simétrico con `status` y `severity`.
- **Tests obligatorios**, parametrizados sobre los dos caminos de entrada (cuarentena automática por
  `DecisionEngine` y por el operador vía `handle_quarantine_file`): la cuarentena conserva un
  baseline restaurable (`select_restorable_content` no es `None` y devuelve los bytes aprobados); el
  `unlink` propio no produce evento, ni `mark_absent`, ni journal nuevo.
- **Se retira el residual** `docs/residuales_declarados.md` §9.

**BREAKING (rollback del agente):** un agente anterior no lee entradas de baseline con el campo
`quarantine_action_id` (`from_dict` pasa claves desconocidas a `cls(**fields)`,
`agent/baseline.py:90-93`). Limitación declarada por RN-176: volver a la versión anterior exige
borrar esas entradas. Las entradas ya vaciadas por cuarentenas anteriores **no son recuperables** y no
se migran.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `agent-baseline`: tercer estado `quarantined` que conserva contenido; `mark_quarantined`; salidas a
  `present`; un archivo nuevo no sobrescribe la entrada.
- `agent-decision-engine`: la acción `quarantine` y la rehidratación usan `quarantine_and_record` y
  dejan la entrada `quarantined`; vocabulario único de fallas de cuarentena.
- `agent-approve-reject-handler`: el handler `quarantine_file` reescribe su texto desactualizado
  (`<filename>.<timestamp>`, `agent/actions.py`), usa la implementación única con `agent_event_id`;
  `restore_file` devuelve una entrada `quarantined` a `present`; se retira el requisito que fijaba el
  eco como correcto.
- `agent-fanotify-detector`: supresión del eco por estado (`quarantined_by_agent`) y no sobrescritura
  de una entrada `quarantined` en la rama `file_created`.
- `backend-approve-reject`: el comando `quarantine_file` lleva `agent_event_id`.
- `backend-events-api`: campo y filtro `quarantine_state` derivados en lectura.
- `frontend-events`: badge y filtro de `quarantine_state`.

## Impact

- **Agente:** `agent/baseline.py`, `agent/quarantine.py`, `agent/decision.py`, `agent/detector.py`,
  `agent/commands.py`, `agent/journal.py` (método de escritura `pending` que no pisa una entrada
  existente). Tests en `agent/tests/` (nuevo banco parametrizado y actualización de
  `test_restore_feedback_loop.py:556-595` y de las afirmaciones de `mark_absent` tras cuarentena).
- **Backend:** `backend/app/modules/actions/streams.py` (`enqueue_quarantine_file`, campo aditivo en
  un payload firmado), `backend/app/modules/events/router.py` y `service.py` (expresión SQL de
  `quarantine_state`). Sin migración ni columna nueva.
- **Frontend:** `frontend/src/api/events.ts`, `frontend/src/utils/eventFilters.ts`,
  `frontend/src/pages/Events.tsx`, `frontend/src/components/ui/EventsTable.tsx`,
  `frontend/src/pages/EventDetail.tsx`.
- **Docs:** `docs/residuales_declarados.md` §9 (se retira, sin renumerar).
- **Coordinación:** Change 62 `agent-offline-reconcile-on-start` se aplica antes; esta change agrega
  a `reconcile_on_start` la guarda de RN-176 (no reportar `file_deleted` sobre una entrada
  `quarantined`). Change 65 `quarantine-release-command` produce las filas `release_quarantine` que esta
  change sólo lee.
- **Reglas:** RN-176 (implementada), RN-37 (cumplida en su intención), RN-34–RN-36 y RN-37a
  (preservadas), RN-11, RN-12, RN-72 (sin enmienda), RN-73 (deduplicación por `event_id`, de la que
  depende la rehidratación del camino del operador), RN-71 (léxico), D81/RN-175 (dependencia),
  D30/RN-124 (`ack_status` como fuente de verdad del rechazo con cuarentena).
- **Re-medición:** única, sobre `v5.0-tesis`, después de las Changes 61–69.
