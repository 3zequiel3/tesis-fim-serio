## 0. Precondiciones

- [x] 0.1 Verificar con `openspec list --json` / `openspec status --change agent-restore-verify-from-disk --json` que la Change 63 está aplicada (tareas completas) o archivada. Si no lo está, **detenerse**: esta change se apoya en el helper de verificación desde disco de D81/RN-175 y toca los mismos archivos (`agent/decision.py`, `agent/commands.py`).
- [x] 0.2 Correr `python3 scripts/check_spec_integrity.py` y registrar el resultado base. Correr la suite del agente y anotar los fallos preexistentes, si los hay, para no atribuirlos a esta change.
- [x] 0.3 Re-verificar las citas `archivo:línea` del design contra el árbol actual (Change 63 desplaza líneas en `decision.py` y `commands.py`). Corregir las citas de los comentarios nuevos, no el design.

## 1. Agente — baseline (D82/RN-176, D-1, D-2)

- [x] 1.1 En `agent/baseline.py`, documentar `status: str  # "present" | "absent" | "quarantined"` y agregar `quarantine_action_id: str | None = None` después de `approved_event_id`, con comentario que cite D82/RN-176 y la limitación de rollback (un agente anterior no lee la clave).
- [x] 1.2 Implementar `BaselineEngine.mark_quarantined(path, action_id)` junto a `mark_absent`: lee la entrada; si existe, `dataclasses.replace` cambiando sólo `status="quarantined"`, `quarantine_action_id` y `captured_at`; si no existe, entrada `quarantined` con campos nulos y `snapshots=[]`. Escritura con `_encrypt_entry` + `_atomic_write`. Devuelve la entrada.
- [x] 1.3 Implementar `BaselineEngine.clear_quarantine(path)`: si la entrada es `quarantined`, la reescribe con `status="present"` y `quarantine_action_id=None`, sin re-hashear ni leer el disco; si no lo es, no hace nada. Docstring que explique por qué no se usa `write_entry` (D-2).
- [x] 1.4 Confirmar leyendo el código que `write_entry`, `write_symlink_entry`, `mark_absent` y `update_from_command` construyen entradas nuevas y dejan `quarantine_action_id=None`; que `add_snapshot` (guarda `status == "absent" or hash is None`) opera sobre `quarantined`; y que `init_scan`/`run_scan` no tocan una ruta `quarantined` cuyo archivo no existe. Si alguna afirmación es falsa, detenerse y reportarlo.
- [x] 1.5 Dejar `mark_absent` sin cambios de código; agregar en su docstring que está reservado a ausencias no causadas por el agente (D82/RN-176).

## 2. Agente — journal

- [x] 2.1 En `agent/journal.py`, agregar `JournalManager.ensure_pending(event_id, path, action)`: si existe una entrada para la clave no la toca; si no existe, delega en `write_pending`. Mismo HMAC y misma escritura. Test unitario: no altera `created_at` de una entrada existente y crea una nueva cuando falta.

## 3. Agente — implementación única de cuarentena (D-3, D-5)

- [x] 3.1 En `agent/quarantine.py`, agregar el dataclass inmutable `QuarantineOutcome(artifact: QuarantineArtifact | None, error: str | None)` y la función `quarantine_and_record(*, store, baseline, journal, action_id, path)` con el orden de D-3: `ensure_pending` → `store.quarantine` → `mark_quarantined` → outcome. Sin paso terminal de journal.
- [x] 3.2 Mapeo de fallas dentro de la función, en este orden: `QuarantineError` → `exc.reason`; `OSError` → `action_error_from_oserror(exc, fallback="move_failed")` (import diferido desde `agent.decision` para evitar ciclo); otra excepción → `quarantine_failed`; excepción en `mark_quarantined` → `baseline_mark_failed` (el artefacto se conserva). Log estructurado con errno/tipo, nunca la ruta en la causa.
- [x] 3.3 En `agent/decision.py`, reescribir `DecisionEngine._quarantine` para delegar en `quarantine_and_record` con `self._quarantine_store`, `self._baseline`, `self._journal` y `action_id=event_id`; sin almacén → `_ActionFailed("quarantine_store_unavailable")` como hoy; `outcome.error` → `_ActionFailed(outcome.error)`; éxito → `payload["quarantine_path"]`. El terminal sigue en `commit_fn` (no tocar `evaluate_and_act`).
- [x] 3.4 Verificar que la rehidratación (`rehydrate`) hereda el cambio por llamar a `_quarantine` con `entry.event_id`, y que sigue cerrando el journal sólo después de publicar.
- [x] 3.5 En `agent/commands.py`, `dispatch` pasa `baseline_engine=baseline_engine` a `handle_quarantine_file`, y el handler gana el parámetro.
- [x] 3.6 En `handle_quarantine_file`: tras las validaciones de ruta existentes, leer `agent_event_id`; si falta o es vacío, publicar `event_ack` con `ok=False, error="quarantine_identity_missing"` y retornar sin journal ni acción. Usarlo como `journal_key` y `action_id` (reemplaza `command_id or uuid4()`).
- [x] 3.7 En `handle_quarantine_file`: conservar la construcción perezosa del almacén con su mapeo a `quarantine_store_unavailable` (journal `failed` + ack); luego llamar a `quarantine_and_record`; cerrar `journal.mark_completed`/`mark_failed(outcome.error)` y publicar el ack. Eliminar los `except` que producían `str(exc)`.
- [x] 3.8 Actualizar el docstring del handler y el de `_quarantine` citando D82/RN-176 y el residual §9 cerrado.

## 4. Agente — transición a present tras restauración verificada

- [x] 4.1 En `handle_restore_file`, después de la verificación desde disco exitosa (helper de la Change 63) y antes del `event_ack`, si la entrada leída al inicio era `quarantined`, llamar a `baseline_engine.clear_quarantine(path)`. En cualquier falla, no tocar la entrada.

## 5. Agente — detector (D-6, D-7)

- [x] 5.1 En `_process_event`, rama `file_deleted`: como primera instrucción, si `entry is not None and entry.status == "quarantined"`, registrar `_trace_record("decision_suppressed", path=..., operation="file_deleted", baseline_status="quarantined", decision="suppress", reason="quarantined_by_agent", outcome="dropped")` y retornar, antes de `uuid.uuid4()`.
- [x] 5.2 En la rama genérica, inmediatamente después de calcular `current_hash` y antes de cualquier asignación de `event_id`: si `current_hash is None` y la entrada es `quarantined`, misma traza con `operation="file_absent"` y retorno.
- [x] 5.3 Rama `file_created`: quitar el `mark_absent` posterior a una cuarentena exitosa; si la entrada previa era `quarantined`, no llamar `write_entry`/`write_symlink_entry`. Comentario citando D82/RN-176 y el riesgo de sobrescribir el contenido aprobado.
- [x] 5.4 Rama genérica `file_modified`: quitar el `mark_absent` posterior a una cuarentena exitosa; con `auto_restore` exitoso y entrada previa `quarantined`, llamar `clear_quarantine(path)`; el `add_snapshot` del resto no cambia.
- [x] 5.5 Descartes por igualdad de hash (D-10): en la rama `file_created` (descarte con mismo hash y mismo tipo de objeto) y en la rama genérica (`matches_active_baseline`), si la entrada es `quarantined`, llamar a `clear_quarantine(path)` antes del `return`; el evento sigue sin publicarse. Comentario que cite la ratificación de RN-176 y por qué no se usa `write_entry`.
- [x] 5.6 Verificar leyendo el diff que no queda ninguna llamada a `mark_absent` alcanzable después de una cuarentena exitosa (`rg -n mark_absent agent/`), y que las dos supresiones no tocan `_pending` ni `_event_to_path`.

## 6. Agente — coordinación con la Change 62 (D80/RN-174)

- [x] 6.1 En `reconcile_on_start` (Change 62, aplicada antes por el orden 61 → 62 → 63 → 64; si no existe, **detenerse**): agregar la guarda que omite toda entrada `quarantined` cuyo archivo no existe —sin `file_deleted`, sin `file_absent`, sin mutar la entrada— y un test que lo verifique, más uno que confirme que una entrada `present` con archivo faltante sigue emitiendo `file_deleted`.

## 7. Tests del agente

- [x] 7.1 Crear `agent/tests/test_quarantine_baseline_preservation.py` con un banco real (patrón de `test_restore_feedback_loop.py`: `BaselineEngine`, `DecisionEngine`, `JournalManager` y `QuarantineStore` reales sobre `tmp_path`, publisher colector, inyección vía `_process_event`, sin `MagicMock` para baseline, filesystem ni motor). El `DecisionEngine` recibe un `QuarantineStore` real (el parámetro `quarantine_dir` del constructor no construye uno).
- [x] 7.2 Fixture parametrizada `entry_path ∈ {"automatic", "operator"}`: `automatic` = regla `quarantine` + modificación inyectada como `FAN_CLOSE_WRITE`; `operator` = `handle_quarantine_file` con `agent_event_id` igual al UUID del evento. Ambos parten de la misma versión aprobada.
- [x] 7.3 Test parametrizado (ambos caminos): la cuarentena conserva un baseline restaurable. Afirmar primero que la acción ocurrió (artefacto presente direccionado por el `event_id` del agente, origen ausente, journal `completed`) y después: entrada `quarantined`, `content_b64`, `hash`, metadatos y `snapshots` iguales a los previos, y `select_restorable_content(entry)` no es `None` y devuelve exactamente los bytes aprobados.
- [x] 7.4 Test parametrizado (ambos caminos): supresión del eco. Tras 7.3, inyectar `FAN_DELETE` y, en otro caso del parámetro, `FAN_MOVED_FROM`: cero payloads nuevos (camino automático: sólo el payload de la cuarentena), ningún journal nuevo, ninguna invocación de `mark_absent` (espía que delega en el método real), entrada intacta, traza `quarantined_by_agent` registrada.
- [x] 7.5 Test parametrizado (ambos caminos) con regla `auto_restore` sobre la ruta al momento del eco: el archivo sigue ausente, no hay restauración ni evento.
- [x] 7.6 Test parametrizado (ambos caminos): `restore_file` del operador posterior a la cuarentena deja el archivo byte a byte igual al aprobado con `mode`/`uid`/`gid`, entrada `present`, `quarantine_action_id` nulo y ningún evento por el `FAN_MOVED_TO`.
- [x] 7.7 Ventana de crash: journal `pending` de `quarantine`, artefacto presente, origen ausente, entrada `present` → `rehydrate` deja la entrada `quarantined` con contenido, no crea artefacto nuevo, publica y cierra el journal. Un segundo caso: la publicación falla → journal sigue `pending`.
- [x] 7.8 Cuarentena sin entrada previa (rama `file_created`, ruta nueva): entrada `quarantined` con nulos; `select_restorable_content` devuelve `None`.
- [x] 7.9 Archivo nuevo con contenido distinto en una ruta `quarantined`: se publica un evento y la entrada conserva `hash`/`content_b64` aprobados. Crear y luego borrar: la creación produce evento y el borrado se descarta (riesgo aceptado de RN-176, fijado por test).
- [x] 7.10 Recreación idéntica (D-10): con la entrada `quarantined`, recrear el archivo con exactamente el contenido aprobado (casos `FAN_CREATE` y `FAN_CLOSE_WRITE`): cero payloads, entrada `present` con metadatos aprobados y `quarantine_action_id` nulo; luego borrar el archivo e inyectar `FAN_DELETE`: se publica exactamente un `file_deleted` (no se suprime). Caso negativo: un symlink cuyo target hashea igual no produce la transición en la rama `file_created`.
- [x] 7.11 Cuarentena → la regla cambia a `auto_restore` → el archivo reaparece alterado: exactamente un evento `auto_restore` sin falla, archivo restaurado, entrada `present`, dentro del techo de iteraciones.
- [x] 7.12 Ausencia genuina sin cambios: `FAN_DELETE` sobre una entrada `present` con `alert_only` sigue publicando `file_deleted` y marcando `absent`.
- [x] 7.13 `baseline_mark_failed`: forzar que `mark_quarantined` levante (subclase del motor real que falla sólo ese método) → causa `baseline_mark_failed` en el payload/ack, artefacto conservado, journal `failed`.
- [x] 7.14 Vocabulario: comando sin `agent_event_id` → ack `quarantine_identity_missing`, archivo intacto, sin journal; excepción inesperada cuyo mensaje contiene la ruta → `quarantine_failed` en ack y journal, sin la ruta; hardlink → `hardlink_not_isolatable` en ambos caminos.
- [x] 7.15 Unitarios de `BaselineEngine`: `mark_quarantined` preserva snapshots y contenido; una segunda cuarentena actualiza sólo `quarantine_action_id`; `clear_quarantine`; `update_from_command` desde `quarantined` deja `present` y `quarantine_action_id` nulo; lectura de una entrada cifrada sin la clave nueva.
- [x] 7.16 Reescribir `test_quarantine_still_reports_the_absence` (`agent/tests/test_restore_feedback_loop.py`) para afirmar cero payloads y entrada `quarantined` con contenido, renombrándolo y citando el requisito eliminado; actualizar las afirmaciones de `mark_absent` tras cuarentena en `agent/tests/test_audit_fixes.py` (~`:801-869`) y cualquier otra que `rg -n "quarantin" agent/tests` revele dependiente del comportamiento anterior (incluido `command_id` como identidad de artefacto en `test_commands.py`).
- [x] 7.17 Correr completas `test_restore_feedback_loop.py`, `test_decision.py`, `test_baseline_restore.py`, `test_detector_multi_event.py`, `test_audit_fixes.py`, `test_commands.py`, `test_quarantine.py`, `test_journal_state_after_action_handlers.py` y luego la suite entera del agente.

## 8. Backend — comando quarantine_file (D-4)

- [x] 8.1 En `backend/app/modules/actions/streams.py::enqueue_quarantine_file`, agregar `"agent_event_id": event.event_id` al payload antes de firmar. Docstring actualizado (lista de campos, D82/RN-176). `restore_file` no cambia.
- [x] 8.2 Test: el payload de `quarantine_file` contiene `agent_event_id == Event.event_id` y la firma verifica con el `shared_secret`; el de `restore_file` no lo contiene; el evento queda `rejected`.

## 9. Backend — quarantine_state (D-8)

- [x] 9.1 Definir `QuarantineState(str, Enum)` con `none`, `quarantined`, `released`, `discarded` en el módulo de eventos.
- [x] 9.2 Implementar `quarantine_state_expr()` en `backend/app/modules/events/service.py` según D-8 (`sa.case` con `EXISTS` correlacionados sobre `published_commands`; modo leído con `cast(payload, JSONB)["mode"].astext` sólo para `command_type = "release_quarantine"`).
- [x] 9.3 Agregar `quarantine_state: QuarantineState = QuarantineState.none` a `EventOut`. En `list_events`, seleccionar la expresión etiquetada junto con `Event`, poblar el campo y aceptar el filtro repetible `quarantine_state` (`Annotated[list[QuarantineState], Query(alias="quarantine_state")]`) aplicado con `expr.in_(...)` antes del conteo. Poblarlo también en `get_event` y en la cadena.
- [x] 9.4 Tests contra Postgres (arnés existente): los siete escenarios del requisito ADDED de `backend-events-api` (automática; rechazo `acked`; rechazo `pending`/`failed`/`timeout`; rechazo con `restore_file`; `discarded` y `released` sembrando filas `release_quarantine` a mano; filtro con `total` correcto y paginación; 422). Más: una fila de otro tipo con payload vacío no rompe la expresión.
- [x] 9.5 Verificar que ningún camino escribe `Event.status` a partir de `quarantine_state` y que las pruebas existentes de la máquina de estados siguen verdes.

## 10. Frontend (D-9)

- [x] 10.1 En `frontend/src/api/events.ts`, tipo `QuarantineState` y `quarantine_state?: QuarantineState` en `EventListItem`; `quarantine_state?: string[]` en `EventFilters` y serialización repetida en `getEvents`.
- [x] 10.2 En `frontend/src/utils/eventFilters.ts`, parseo y serialización de `quarantine_state` simétricos con `severity`.
- [x] 10.3 Helper puro `getQuarantineStateMeta` (patrón de `frontend/src/utils/ackStatus.ts`) con su test: `null` para `none`/ausente, etiqueta en minúsculas y estilo distinto del badge de `status`.
- [x] 10.4 Badge en `EventsTable.tsx` y en `EventDetail.tsx` (junto a `AckStatusBadge`), y filtro multi-select en `frontend/src/pages/Events.tsx` con el mismo patrón que `handleSeverityToggle`.
- [x] 10.5 Tests (vitest): fila `rejected` + `quarantined` muestra los dos badges; `none` y campo ausente no muestran badge; el filtro escribe y restaura `quarantine_state` repetido en la URL y la petición lo lleva repetido.

## 11. Documentación y cierre

- [x] 11.1 Retirar el residual §9 de `docs/residuales_declarados.md` sin renumerar las demás entradas (dejar una línea que remita a D82/RN-176 y a esta change).
- [x] 11.2 Correr las suites de agente, backend y frontend; registrar conteos y cualquier fallo preexistente.
- [x] 11.3 Correr `python3 scripts/check_spec_integrity.py` antes y después de `openspec archive`; (corrida previa al archive: OK; la posterior corresponde a la fase de archive); el REMOVED de `agent-approve-reject-handler` no debe producir pérdida inesperada.
- [x] 11.4 Verificar que `reconcile_on_start` conserva la guarda de 6.1 y que la suite del agente la cubre.
