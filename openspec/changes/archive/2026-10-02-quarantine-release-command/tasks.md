## 0. Precondiciones (bloqueantes)

- [x] 0.1 Verificar con `openspec list --json` y `eza openspec/changes/archive` que `agent-restore-verify-from-disk` (Change 63) y `quarantine-baseline-preservation` (Change 64) están **archivadas**. Si no, detenerse: esta change no se aplica antes.
- [x] 0.2 Localizar en el código ya integrado de la Change 64: `quarantine_and_record`, `BaselineEngine.mark_quarantined`, el estado de baseline `"quarantined"` con `quarantine_action_id`, el helper de derivación de `quarantine_state` del backend y su exposición en `EventOut`/`EventDetailOut` y en `frontend/src/api/events.ts`. Anotar los nombres reales; las tareas siguientes los usan.
- [x] 0.3 Localizar el helper de relectura desde disco de la Change 63 (D81/RN-175) y confirmar su firma y sus códigos (`verify_failed`, `hash_mismatch_after_restore`).
- [x] 0.4 Resolver la Open Question 1 de `design.md`: escribir primero el test 4.9 (eco de `restore_baseline` sobre una entrada `quarantined`) contra el detector de la Change 64. Si falla, detenerse y escalar antes de cambiar el orden de D-7.
- [x] 0.5 Correr `python3 scripts/check_spec_integrity.py` y registrar que pasa en la base.

## 1. Agente — almacén de cuarentena

- [x] 1.1 En `agent/quarantine.py`, agregar `QuarantineStore.load_for_release(action_id, source_path, expected_sha256) -> QuarantineArtifact`: resuelve `artifact_path`, traduce inexistente a `QuarantineError("artifact_not_found")`, `QuarantineIntegrityError` a `artifact_integrity_failed`, identidad distinta a `artifact_identity_mismatch` y `sha256` distinto a `artifact_hash_mismatch`. Usa `read_artifact` (`:497`), hoy sin llamadores.
- [x] 1.2 Agregar `QuarantineStore.remove_artifact(action_id, source_path, expected_sha256) -> None` (D-8): bajo `self._lock`, re-lee sin contenido, revalida identidad y hash, `unlink` y `_fsync_directory`. Nunca borra un archivo que no autentique.
- [x] 1.3 Tests unitarios de 1.1 y 1.2: artefacto válido, inexistente, alterado (byte cambiado), identidad ajena, hash distinto, artefacto heredado nombrado por `command_id`.

## 2. Agente — registro de comandos ejecutados

- [x] 2.1 Crear `agent/executed_commands.py` con `ExecutedCommandRegistry(path)`: `get(command_id)`, `record(command_id, type, ok, error)` con escritura temporal + `fsync` + `os.replace` + `fsync` del directorio, modo `0600`; poda de entradas con `executed_at` más viejo que `quarantine_retention_days` al escribir (D-9).
- [x] 2.2 Tolerancia: un archivo ilegible o corrupto se registra con `log.error("executed_commands.load_failed")` y se trata como vacío; nunca lanza hacia el dispatcher.
- [x] 2.3 Tests: registro y lectura, persistencia entre instancias, poda, archivo corrupto.

## 3. Agente — handler `release_quarantine`

- [x] 3.1 En `agent/commands.py`, agregar una primitiva privada de publicación sin sobrescritura (D-5): temporal `<path>.fim_restore_tmp` con `O_CREAT|O_EXCL`, `write`, `fsync`, `fchown` antes que `fchmod`, `os.link(tmp, path)` (`FileExistsError` → `path_occupied`), `unlink(tmp)` siempre, `fsync` del directorio; otros `OSError` vía `action_error_from_oserror`.
- [x] 3.2 Implementar `handle_release_quarantine(command, *, baseline_engine, state, journal, quarantine_store, registry, valkey_client, config)`: consulta el registro (re-publica el ack registrado si existe), valida `mode`, contención en `watch_paths` (D18/RN-116), journal `pending` con clave `command_id` y acción `release_quarantine`.
- [x] 3.3 Modo `restore_original` en el orden de D-6: guarda `stale_ruleset_version`; `load_for_release`; `kind == "symlink"` → `unsupported_file_type`; `lstat` → `path_occupied`; adopción del baseline `present` con contenido/hash/metadata del artefacto y modo sin `S_ISUID|S_ISGID`, guardando la entrada previa; publicación 3.1; verificación con el helper de D81; `remove_artifact`; `state.ruleset_version = cmd_version` + `save_state`. Cualquier fallo posterior a la adopción restaura la entrada previa y conserva el artefacto.
- [x] 3.4 Modo `restore_baseline` (D-7): `load_for_release`; `lstat` → `path_occupied`; `select_restorable_content` sobre la entrada `quarantined` → `no_restorable_content`; metadata de la entrada (`parse_baseline_mode`, `uid`, `gid`; `no_baseline_metadata` si falta); publicación 3.1; verificación D81; entrada a `present`; `remove_artifact`. No toca `state.ruleset_version`.
- [x] 3.5 Modo `discard` (D-7): `load_for_release` y `remove_artifact`. Baseline y path intactos.
- [x] 3.6 Re-ejecución tras caída (D-9): en los modos de restauración, si `load_for_release` da `artifact_not_found`, el path existe con el hash objetivo y la entrada está `present` con ese hash, responder `ok` sin escribir.
- [x] 3.7 Cierre: journal `completed`/`failed`, `registry.record(...)` y recién después `_publish_ack(..., "release_quarantine", event_id, ...)`. Logs estructurados `commands.release_quarantine.{done,failed}` con `mode`, `command_id`, `event_id` y código; sin contenido del archivo.
- [x] 3.8 En `commands.dispatch` (`agent/commands.py:107-202`), agregar la rama `release_quarantine` (journal o store ausentes → `log.error` y retorno, como `quarantine_file`) y aceptar el registro como dependencia.
- [x] 3.9 En `agent/publisher.py:574-577`, agregar `"release_quarantine"` a la tupla y pasar el registro a `commands.dispatch`; instanciarlo y registrarlo en `register_command_handlers` desde `agent/__main__.py`.
- [x] 3.10 En `DecisionEngine.rehydrate` (`agent/decision.py:135-221`), omitir las entradas con acción `release_quarantine`: ni publicar ni terminalizar (D-9). Comentar citando D83/RN-177.
- [x] 3.11 Actualizar el docstring de módulo de `agent/commands.py` con el nuevo handler.

## 4. Agente — tests

- [x] 4.1 `restore_original` exitoso: contenido, `uid`/`gid`, bits setuid/setgid quitados (artefacto con `0o4755` → archivo `0o755`), entrada `present` con `expected_sha256`, artefacto eliminado, `state.ruleset_version` avanzado, ack `ok`.
- [x] 4.2 `restore_original` con path ocupado antes del `lstat` y con path creado entre `lstat` y `link` (monkeypatch): archivo existente intacto, artefacto conservado, entrada `quarantined`, ack `path_occupied`, sin temporal huérfano.
- [x] 4.3 `restore_original` obsoleto → `stale_ruleset_version` sin efectos; artefacto `symlink` → `unsupported_file_type`.
- [x] 4.4 `restore_original` con relectura que no coincide (inyectada) → `hash_mismatch_after_restore`, baseline revertido, artefacto conservado.
- [x] 4.5 `restore_baseline` exitoso y con path ocupado; sin contenido restaurable → `no_restorable_content`.
- [x] 4.6 `discard` exitoso: artefacto eliminado, entrada `quarantined`, path ausente.
- [x] 4.7 Errores de artefacto por modo: `artifact_not_found` (vencido y heredado por `command_id`), `artifact_integrity_failed`, `artifact_hash_mismatch`; en ningún caso hay escritura en el path.
- [x] 4.8 Idempotencia: misma entrega dos veces → un solo efecto y dos acks idénticos; caída simulada entre `remove_artifact` y `registry.record` → la re-entrega responde `ok` sin reescribir; `rehydrate` con entrada `release_quarantine` no publica.
- [x] 4.9 Eco: con el detector real de la Change 64, `restore_original` y `restore_baseline` exitosos no publican eventos de integridad (patrón de `agent/tests/test_restore_feedback_loop.py`).
- [x] 4.10 Dispatch: `release_quarantine` firmado llega al handler; firma inválida y `target_agent_id` ajeno no producen efectos.

## 5. Backend — comando, servicio y endpoint

- [x] 5.1 En `backend/app/modules/actions/schemas.py`, agregar `ReleaseMode` (`restore_original`, `restore_baseline`, `discard`), `ReleaseQuarantineRequest {mode, reason}` con `extra="forbid"` y validación de `reason` (strip, 1–500), y `ReleaseQuarantineResponse {event_id, command_id, mode, ack_status}`.
- [x] 5.2 En `backend/app/modules/actions/streams.py`, agregar `enqueue_release_quarantine(session, event, mode, ruleset_version | None) -> str` con el payload de D-1 firmado y `_record_published_command(..., "release_quarantine", ..., event_id=event.id, ruleset_version=...)`; retorna el `command_id`. Sin `XADD` ni commit propio (D37/RN-131).
- [x] 5.3 En `backend/app/modules/actions/service.py`, agregar `release_quarantine_single(db, valkey_client, event_id, mode, reason, user_id)`: `SELECT … FOR UPDATE`; `quarantine_state` con el helper de la Change 64; `hash_detected` vacío → no liberable; búsqueda de `release_quarantine` `pending|acked`; `increment_ruleset_version` sólo en `restore_original`; `enqueue_release_quarantine`; `_write_audit(db, user_id, "quarantine_release", event_id, {mode, reason, command_id})`; commit; `publish_pending_commands`. Excepciones propias `QuarantineNotReleasable` y `ReleaseInProgress`. No toca el evento.
- [x] 5.4 En `backend/app/modules/events/router.py`, agregar `POST /{event_id}/quarantine/release` con `require_admin`, `status_code=202`, `404` si no existe y `409` con `code` según excepción.
- [x] 5.5 (already in place from Change 64: `quarantine_state_expr` carries the `discarded`/`released` branches; this change adds the tests, see `backend/tests/test_quarantine_release.py`) Extender la derivación de `quarantine_state` de la Change 64 con las ramas `discarded`/`released` de D-4 (`CAST(payload AS JSONB)->>'mode'`), antes de `quarantined`, en la expresión SQL usada por el filtro y por la serialización.
- [x] 5.6 En `backend/app/modules/agents/command_ack_consumer.py`, en `ok` de `release_quarantine` leer `mode` del payload de la fila: `restore_original` → `_reconcile_baseline_entry(session, event_id, cmd.ruleset_version)` y `_advance_ruleset_version_applied`. Verificar que `release_quarantine` entra al barrido de timeout sin cambios.

## 6. Backend — tests

- [x] 6.1 Endpoint, un test por modo: `202`, fila `PublishedCommand` con `command_id` del cuerpo, payload firmado verificable con el secreto del agente, `mode` y `expected_sha256` correctos; `ruleset_version` sólo en `restore_original`.
- [x] 6.2 Autorización: sin token `401`, no admin `403`, `must_change_password` `403`.
- [x] 6.3 Validación: `reason` vacío o de sólo espacios, `reason` de 501 caracteres, `mode` inválido, campo extra → `422` sin filas nuevas.
- [x] 6.4 Elegibilidad: evento sin cuarentena, `hash_detected` vacío, liberación `acked` → `quarantine_not_releasable`; liberación `pending` → `release_in_progress`; liberación `failed`/`timeout` previa → `202`.
- [x] 6.5 Concurrencia: dos pedidos en sesiones paralelas sobre el mismo evento → un `202` y un `409`, un solo comando.
- [x] 6.6 Auditoría: exactamente una entrada `quarantine_release` con `mode`, `reason` y `command_id`; el payload del comando no contiene `reason`; sin secreto del agente → ni comando ni auditoría.
- [x] 6.7 Estado del evento: `status`, `version`, `resolved_at`, `resolved_by` intactos tras el `202` y tras el ack, para eventos `quarantined` y `rejected` con cuarentena.
- [x] 6.8 Ack: `ok` de `restore_original` reconcilia `baseline_entries` y avanza `ruleset_version_applied`; `ok` de `restore_baseline`/`discard` no toca `baseline_entries`; `error` deja `failed` sin reconciliar.
- [x] 6.9 `quarantine_state`: `released` y `discarded` tras ack `ok`; `quarantined` con `pending`/`failed`; filtro `GET /events?quarantine_state=released`.

## 7. Frontend

- [x] 7.1 En `frontend/src/api/actions.ts`, agregar `ReleaseMode`, `ReleaseQuarantineParams` y `releaseQuarantine(eventId, {mode, reason})` contra `POST /events/{id}/quarantine/release`.
- [x] 7.2 En `frontend/src/hooks/useEventActions.ts`, agregar `releaseQuarantineMutation` con toasts para `202` y para cada `code` de `409`, e invalidación del evento y de la lista.
- [x] 7.3 Crear `frontend/src/components/ui/ReleaseQuarantineModal.tsx` (presentacional): tres opciones con su consecuencia, advertencia de aprobación en `restore_original`, `textarea` de motivo obligatoria, confirmación deshabilitada sin modo o sin motivo.
- [x] 7.4 En `frontend/src/pages/EventDetail.tsx`, botón «Liberar cuarentena» condicionado a `quarantine_state === 'quarantined'`, deshabilitado con `ack_status === 'pending'`, que abre el modal.
- [x] 7.5 Tests: `ReleaseQuarantineModal.test.tsx` (motivo obligatorio, payload por modo, advertencia); `EventDetail.test.tsx` (visible para `quarantined` y para `rejected` con cuarentena; oculto para `none`/`released`/`discarded`; deshabilitado con ack `pending`; `409 release_in_progress`); `actions` API (ruta y cuerpo).

## 8. Cierre

- [x] 8.1 Correr las suites de agente, backend y frontend completas; registrar resultados.
- [x] 8.2 (before-archive run: OK, 56 main specs / 426 requirements; the after-`openspec archive` run belongs to the archive step) Correr `python3 scripts/check_spec_integrity.py` antes y después de `openspec archive` (D47/RN-141).
- [x] 8.3 Verificar con `rg` que `read_artifact` tiene llamador, que `release_quarantine` figura en `agent/publisher.py` y en `commands.dispatch`, y que ningún log del handler incluye contenido de archivo ni el `reason`.
