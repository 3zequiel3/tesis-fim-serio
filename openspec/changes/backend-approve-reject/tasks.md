## 1. Backend — Schemas y módulo actions

- [x] 1.1 Crear `backend/app/modules/actions/__init__.py`, `schemas.py`, `service.py`, `router.py`
- [x] 1.2 Definir en `schemas.py`: `ApproveRequest` (`event_id`, `version`, `confirm_absent=False`), `RejectAction` enum (`restore`|`quarantine`), `RejectRequest` (`event_id`, `version`, `action`), `ActionResponse`
- [x] 1.3 Definir en `schemas.py`: `BulkApproveItem`, `BulkApproveRequest`, `BulkRejectItem`, `BulkRejectRequest`, `BulkResultResponse` (`succeeded: list[int]`, `failed: list[dict]`)

## 2. Backend — Publicación de comandos HMAC-signed (core/streams.py)

- [x] 2.1 Agregar `publish_baseline_update(session, event, ruleset_version)` en `core/streams.py`: construye payload con `type`, `command_id`, `event_id`, `target_agent_id`, `path`, `hash`, `baseline_status`, `ruleset_version`, `issued_at`; calcula HMAC-SHA256 sobre JSON canónico (claves ordenadas, sin `signature`) con `shared_secret` del agente; publica al stream `commands`
- [x] 2.2 Agregar `publish_restore_file(session, event)` y `publish_quarantine_file(session, event)` con el mismo patrón HMAC (sin `hash` ni `ruleset_version`)
- [x] 2.3 Extraer `shared_secret` del agente desde `agents.shared_secret_hex` en DB (ya persistido en C06)
- [x] 2.4 Incrementar el counter `ruleset_version` de Valkey antes de publicar `baseline_update` (mismo counter de C12)

## 3. Backend — Servicio de approve single

- [x] 3.1 Implementar `_approve_single(db, event_id, version, confirm_absent, user_id)` en `service.py`
- [x] 3.2 UPDATE optimista: `UPDATE events SET status='approved', version=version+1, resolved_at=now(), resolved_by=user_id WHERE id=event_id AND version=<version> AND status='pending'`; si rowcount=0 → raise `ConflictError`
- [x] 3.3 Si `event.hash is None` y `confirm_absent=False` → raise `AbsentConfirmationRequired` (HTTP 422)
- [x] 3.4 Upsert en `baseline_entries`: `hash=event.hash`, `status='absent' if hash is None else 'present'`, `last_updated=now()`, `ruleset_version=new_version`
- [x] 3.5 Llamar a `publish_baseline_update` y registrar en `audit_log` con `action='approve'`

## 4. Backend — Servicio de reject single

- [x] 4.1 Implementar `_reject_single(db, event_id, version, action, user_id)` en `service.py`
- [x] 4.2 UPDATE optimista idéntico al de approve pero con `status='rejected'`; rowcount=0 → `ConflictError`
- [x] 4.3 Si `baseline_entries.status='absent'` para ese `(path, agent_id)` → no-op del comando (log warning); sino publicar `restore_file` o `quarantine_file` según `action`
- [x] 4.4 Registrar en `audit_log` con `action='reject'` y `details.action=<restore|quarantine>`

## 5. Backend — Bulk operations

- [x] 5.1 Implementar `approve_bulk(db, items, user_id)` en `service.py`: loop independiente por ítem, captura excepciones individuales, acumula `succeeded` y `failed`
- [x] 5.2 Implementar `reject_bulk(db, items, user_id)` con la misma estructura; error en un ítem no aborta el resto

## 6. Backend — Router y registro

- [x] 6.1 Implementar los 4 endpoints en `router.py`: `POST /actions/approve`, `POST /actions/reject`, `POST /actions/bulk-approve`, `POST /actions/bulk-reject`; todos requieren JWT admin; mapear `ConflictError` → 409, `AbsentConfirmationRequired` → 422
- [x] 6.2 Registrar el router en `backend/app/main.py` con `prefix="/actions"`, `tags=["actions"]`

## 7. Agente — Módulo commands.py (dispatch y verificación)

- [x] 7.1 Crear `agent/commands.py` con `dispatch(command: dict, *, baseline_engine, state)` que enruta por `command["type"]`
- [x] 7.2 Implementar verificación HMAC-SHA256: recalcular sobre JSON canónico del payload (sin `signature`), comparar con `command["signature"]` usando `hmac.compare_digest`; si falla → log error y return sin ejecutar
- [x] 7.3 Implementar filtro `target_agent_id`: si no es `None` y no coincide con `state.agent_id` → ignorar silenciosamente
- [x] 7.4 Para tipos desconocidos: log warning y return sin excepción

## 8. Agente — Handler baseline_update

- [x] 8.1 Implementar `handle_baseline_update(command, baseline_engine, state)` en `commands.py`
- [x] 8.2 Verificar `command["ruleset_version"] >= state.ruleset_version`; si es menor → log debug y return
- [x] 8.3 Implementar `BaselineEngine.update_from_command(path, hash_value, baseline_status)` en `agent/baseline.py`: misma clave HKDF, nuevo nonce ACM-GCM por escritura, sobreescribe entrada existente si existe
- [x] 8.4 Actualizar `state.ruleset_version = command["ruleset_version"]` y persistir en `state.json`
- [x] 8.5 Publicar `event_ack` al stream `event_ack` de Valkey con `command_id`, `command_type="baseline_update"`, `agent_id`, `status="ok"|"error"`

## 9. Agente — Handler restore_file

- [x] 9.1 Implementar `handle_restore_file(command, baseline_engine, journal)` en `commands.py`
- [x] 9.2 Escribir journal pre-acción en `/var/lib/fim-agent/journal/` antes de cualquier escritura al filesystem
- [x] 9.3 Llamar a la función de restore ya implementada en `agent/actions.py` (C10); capturar excepciones (sin baseline → error)
- [x] 9.4 Escribir journal post-acción con resultado (`success` o `error` con razón)
- [x] 9.5 Publicar `event_ack` con `status="ok"` o `status="error"`

## 10. Agente — Handler quarantine_file

- [x] 10.1 Implementar `handle_quarantine_file(command, journal)` en `commands.py`
- [x] 10.2 Escribir journal pre-acción
- [x] 10.3 Llamar a la función de quarantine ya implementada en `agent/actions.py` (C10); capturar excepciones (archivo inexistente → error)
- [x] 10.4 Escribir journal post-acción con resultado
- [x] 10.5 Publicar `event_ack` con `status="ok"` o `status="error"`

## 11. Agente — Integración con el consumer loop

- [x] 11.1 Modificar `agent/publisher.py` para pasar mensajes del stream `commands` no-`rule_sync` a `commands.dispatch(msg, baseline_engine=..., state=...)`
- [x] 11.2 Asegurar que `dispatch` recibe las instancias correctas de `baseline_engine`, `state` y las funciones de publicación de `event_ack`

## 12. Tests backend

- [ ] 12.1 `test_approve_success` — evento pending aprobado: status→approved, baseline_entries upserted, `baseline_update` publicado
- [ ] 12.2 `test_approve_conflict` — versión incorrecta → 409
- [ ] 12.3 `test_approve_absent_no_confirm` — hash nulo sin `confirm_absent` → 422
- [ ] 12.4 `test_approve_absent_confirmed` — hash nulo con `confirm_absent=True` → 200, baseline_entries con `status='absent'`
- [ ] 12.5 `test_reject_restore` — evento pending rechazado con `action=restore`, `restore_file` publicado, baseline no modificado
- [ ] 12.6 `test_reject_quarantine` — `quarantine_file` publicado
- [ ] 12.7 `test_reject_absent_baseline_noop` — baseline absent → reject OK, sin comando publicado
- [ ] 12.8 `test_bulk_approve_partial` — 3 ítems, 1 con conflicto → succeeded 2, failed 1
- [ ] 12.9 `test_bulk_reject_partial` — misma semántica
- [ ] 12.10 `test_baseline_update_hmac_valid` — payload del comando tiene firma HMAC verificable con `shared_secret` del agente
- [ ] 12.11 `test_no_get_file_hash_published` — ningún flujo de approve/reject publica `get_file_hash`
- [ ] 12.12 `test_audit_log_on_approve` — fila en audit_log con `action='approve'`
- [ ] 12.13 `test_audit_log_on_reject` — fila en audit_log con `action='reject'` y `details.action`

## 13. Tests agente

- [ ] 13.1 `test_dispatch_routes_baseline_update` — tipo correcto llama al handler correcto
- [ ] 13.2 `test_dispatch_unknown_type_no_exception` — sin excepción, log warning
- [ ] 13.3 `test_hmac_invalid_discards_command` — firma incorrecta → handler no llamado
- [ ] 13.4 `test_target_agent_id_filter_other_agent` — comando para otro agente ignorado
- [ ] 13.5 `test_target_agent_id_null_broadcast` — `target_agent_id=null` → procesado
- [ ] 13.6 `test_baseline_update_present_writes_encrypted` — entry cifrada creada/actualizada
- [ ] 13.7 `test_baseline_update_absent_writes_null_hash`
- [ ] 13.8 `test_baseline_update_older_version_ignored`
- [ ] 13.9 `test_restore_handler_success_publishes_ack`
- [ ] 13.10 `test_restore_handler_no_baseline_publishes_error_ack`
- [ ] 13.11 `test_quarantine_handler_success`
- [ ] 13.12 `test_quarantine_handler_file_not_found_publishes_error_ack`
- [ ] 13.13 `test_journal_written_before_filesystem_op` — journal pre-acción existe antes de modificar filesystem
