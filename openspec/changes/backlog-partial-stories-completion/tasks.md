## 0. Precondiciones

- [x] 0.1 Confirmar que el apply del Change 54 (`backend-privacy-hardening`) no está en curso sobre `backend/app/modules/alerts/`; este change (55) se aplica y archiva primero, el Change 54 después, en serie (D-10)
- [x] 0.2 Registrar el estado base de las suites (backend, frontend, agente) con los comandos de la sección 7, para distinguir fallas preexistentes

## 1. US-27 — Política de contraseña y contraseña actual (backend)

- [x] 1.1 Agregar `password_policy_error(password) -> str | None` en `backend/app/core/security.py`: largo ≥ 12 primero, después al menos una mayúscula (`isupper`), una minúscula (`islower`) y un dígito (`isdecimal`) por carácter
- [x] 1.2 Reemplazar el chequeo `len(body.new_password) < 12` de `backend/app/modules/users/router.py` por `password_policy_error`, manteniendo `HTTPException(422, detail=<string>)` y evaluándolo antes de modificar el usuario
- [x] 1.3 Quitar el salteo de verificación de `current_password` para scope `password_change_only` en `backend/app/modules/users/router.py:56-63` (D-2): verificar `current_password` contra el hash actual en ambos scopes; 401 sin modificar `password_hash` si falla o si falta
- [x] 1.4 Tests unitarios de `password_policy_error`: válida, corta, sin mayúscula, sin minúscula, sin dígito, mayúscula `Ñ` válida
- [x] 1.5 Test HTTP: `new_password` sin mayúscula / sin minúscula / sin dígito → 422 con `detail` string y `password_hash` sin cambios (tres casos parametrizados)
- [x] 1.6 Test HTTP: `new_password` de 11 caracteres → 422
- [x] 1.7 Test HTTP con scope normal: `current_password` incorrecto → 401 y hash sin cambios; `current_password` correcto → 200 y `must_change_password = False`
- [x] 1.8 Test HTTP con scope `password_change_only`: `current_password` incorrecto o ausente → 401 y hash sin cambios; `current_password` correcto → 200
- [x] 1.9 Test: tras un cambio exitoso, el `password_hash` persistido empieza con `$argon2id$`, codifica `m=65536,t=3,p=4` y verifica contra el nuevo password y no contra el anterior
- [x] 1.10 Test: un cambio exitoso deja una fila `audit_log` con `action="change_password"` y el `user_id`
- [x] 1.11 Test: login del seed, sin completar el cambio, segundo login → `must_change_password: true` y token con scope `password_change_only`

## 2. US-27 — Formulario de cambio forzado (frontend)

- [x] 2.1 En `frontend/src/pages/ForcePasswordChange.tsx`, agregar el campo "Contraseña actual" (`current_password`), enviado siempre en `POST /users/change-password` sin condicionarlo al scope (D-2)
- [x] 2.2 Extender `validate()` con las reglas de mayúscula (`\p{Lu}`), minúscula (`\p{Ll}`) y número (`\p{Nd}`) con flag `u` sobre `newPassword`, con un mensaje por requisito; agregar validación de `currentPassword` no vacío
- [x] 2.3 Mostrar en el formulario la lista de requisitos (12 caracteres, 1 mayúscula, 1 minúscula, 1 número) y actualizar el texto descriptivo que hoy sólo menciona 12 caracteres
- [x] 2.4 Crear `frontend/src/pages/ForcePasswordChange.test.tsx`: contraseña actual vacía muestra error y `changePasswordApi` no se llama; password nuevo sin mayúscula, sin minúscula y sin número muestran error e idem; password corto idem; password válido con `Ñ` llama a `changePasswordApi` con `current_password` incluido; los requisitos se renderizan; un 401 del backend (contraseña actual incorrecta) muestra el `detail` recibido

## 3. US-29 / US-05 — Conteo y banner de la DLQ (sin umbral, D-3)

- [x] 3.1 Agregar `count_failed_alerts(session) -> int` en `backend/app/modules/alerts/service.py` con `delivered_at IS NULL AND failed_at IS NOT NULL` (misma condición que `list_failed_alerts`, sin filtro de `retry_count`)
- [x] 3.2 Agregar `GET /alerts/failed/count` (admin) en `backend/app/modules/alerts/router.py` que responde `{"count": int}`, declarado antes de las rutas con `/{alert_id}`
- [x] 3.3 Tests backend en `backend/tests/test_notifications.py`: con alertas entregada, fallida `retry_count=3`, fallida `retry_count=0` (n8n sin configurar) y pendiente → `count == 2`; DLQ vacía → `count == 0`; sin token → 401
- [x] 3.4 Cambiar `AlertsBanner.tsx` para consultar `GET /alerts/failed/count` con query key `['alerts', 'failed', 'count']` (D-4), mostrar "Notificaciones pendientes: N alertas no pudieron ser enviadas" (singular "1 alerta no pudo ser enviada") y enlazar a `/alerts/failed`
- [x] 3.5 Reescribir `frontend/src/components/layout/AlertsBanner.test.tsx` contra el nuevo contrato: `count=0` sin banner; `count=4` con el texto literal de US-29 y clase amarilla; singular; `href="/alerts/failed"`; consulta a `/alerts/failed/count`; banner que desaparece cuando un refetch devuelve `count=0`; una alerta con `retry_count=0` sí cuenta (sin umbral)

## 4. US-29 — `audit_log` en reintento y descarte

- [x] 4.1 Agregar el parámetro `actor_id` a `retry_alert` y agregar a la sesión un `AuditLog(action="alert_retry", target_type="alert", target_id=alert_id, detail=f"event_id={alert.event_id}")` antes del commit del reset
- [x] 4.2 Agregar el parámetro `actor_id` a `delete_alert` y agregar a la sesión un `AuditLog(action="alert_discard", ...)` antes del commit de la eliminación
- [x] 4.3 Pasar `_admin.id` desde `retry_failed_alert` y `discard_alert` en `alerts/router.py`; actualizar los demás llamadores y tests existentes de `retry_alert` / `delete_alert` a la nueva firma
- [x] 4.4 Test: `POST /alerts/{id}/retry` exitoso deja una fila `alert_retry` con `user_id` del admin, `target_type="alert"`, `target_id` y `detail` con `event_id`
- [x] 4.5 Test: tres `POST /alerts/{id}/retry` sobre alertas distintas (reintento masivo) dejan tres filas `alert_retry` con los `target_id` correspondientes
- [x] 4.6 Test: `POST /alerts/{id}/retry` con 404 y con 409 no deja filas en `audit_log`
- [x] 4.7 Test: `DELETE /alerts/{id}` exitoso deja una fila `alert_discard` con `detail` que contiene el `event_id`; `DELETE` con 404 no deja filas
- [x] 4.8 Crear `frontend/src/pages/FailedAlerts.test.tsx`: "Reintentar" por fila llama `POST /alerts/{id}/retry`; seleccionar tres filas y el bulk llama `POST /alerts/{id}/retry` una vez por id; "Descartar" confirmado llama `DELETE /alerts/{id}`

## 5. US-11 — Toast 409 y aviso de archivo ausente

- [x] 5.1 Cambiar el toast 409 de `frontend/src/hooks/useEventActions.ts` a "Este evento ya fue resuelto o reemplazado. Refrescando lista..."
- [x] 5.2 Cambiar el aviso de `frontend/src/pages/EventDetail.tsx` a "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline.", conservando Confirmar / Cancelar
- [x] 5.3 Test (`EventDetail.test.tsx` o `useEventActions.test.tsx`): approve con 409 muestra el toast literal e invalida las queries `['event', id]` y `['events']`
- [x] 5.4 Test: reject con 409 muestra el mismo toast e invalida las queries
- [x] 5.5 Test: approve con 422 `absent_confirmation_required` muestra el aviso literal; Confirmar reenvía `POST /actions/approve` con `confirm_absent: true`; Cancelar oculta el aviso sin nueva request
- [x] 5.6 Test: el detalle de un evento `pending` muestra los botones "Aprobar" y "Rechazar"

## 6. US-12 — Journal, `ruleset_version` (D66) y criterio C10 del modal de rechazo

- [x] 6.1 Test en `agent/tests/test_commands.py`: `handle_restore_file` exitoso con `JournalManager` real sobre `tmp_path` deja la entrada del `command_id` en `state == "completed"`
- [x] 6.2 Test: `handle_restore_file` sin baseline deja la entrada en `state == "failed"` con `error == "no_baseline_content"`
- [x] 6.3 Test: `handle_quarantine_file` exitoso deja la entrada en `state == "completed"`
- [x] 6.4 Test: `handle_quarantine_file` con fallo del store deja la entrada en `state == "failed"` con `error` no vacío igual al del ack publicado
- [x] 6.5 Agregar `baseline_status: BaselineStatus | None` a `EventDetailOut` (`backend/app/modules/events/router.py`), resuelto en `get_event` con un `SELECT` a `BaselineEntry` por `(event.path, event.agent_id)`; `None` si `event.path` es `None` o no hay fila (D-8)
- [x] 6.6 Test backend en `backend/tests/test_event_router.py`: `GET /events/{id}` de un evento cuyo path tiene `BaselineEntry.status = absent` responde `baseline_status: "absent"`; con `status = present` responde `"present"`; sin `BaselineEntry` responde `null`
- [x] 6.7 Agregar `baseline_status: 'present' | 'absent' | null` a `EventListItem` en `frontend/src/api/events.ts`
- [x] 6.8 En `frontend/src/components/ui/RejectModal.tsx`, agregar la prop `baselineStatus` (o leerla de `event`); cuando sea `'absent'`, ocultar el `fieldset` de acción correctiva y mostrar "No hay archivo a restaurar (baseline ausente). Confirmar rechazará el evento sin acción en filesystem.", conservando Confirmar / Cancelar; `onConfirm` sigue enviando `action: 'restore'` (D-8)
- [x] 6.9 Test (`RejectModal.test.tsx`, crear si no existe): con `baselineStatus='absent'` no se renderizan los radios de acción y sí el texto literal de C10; con `baselineStatus='present'` o `null` se renderizan los radios como hoy
- [x] 6.10 Cambiar `reject()` en `frontend/src/api/actions.ts` para devolver el cuerpo de la respuesta (`{event_id, status, baseline_absent}`) en vez de descartarlo
- [x] 6.11 En `frontend/src/hooks/useEventActions.ts`, en el `onSuccess` de `rejectMutation`, mostrar un toast informativo ("El baseline ya no tiene archivo: el rechazo no ejecutó ninguna acción.") cuando la respuesta trae `baseline_absent: true`, y el toast de éxito actual en caso contrario
- [x] 6.12 Test (`useEventActions.test.tsx` o `EventDetail.test.tsx`): reject con `baseline_absent: true` en la respuesta muestra el toast informativo; reject sin ese flag muestra el toast de éxito actual
- [x] 6.13 Agregar el requisito `GET /events/{event_id}` con `baseline_status` al spec `backend-events-api` de este change (ya incluido en `specs/backend-events-api/spec.md`); no se toca `GET /events` (listado) ni `POST /actions/bulk-reject` (ver design.md → Non-Goals)
- [x] 6.14 Documentar en `docs/trazabilidad_us_tests.md` §5.12 que el criterio "`ruleset_version` en los comandos de rechazo" queda superado por D66/RN-160 (no se implementa), citando la decisión

## 7. Verificación

- [x] 7.1 Backend (desde `backend/`, con Postgres de laboratorio): `TEST_DATABASE_URL=<url-lab> uv run --no-sync python -m pytest tests/test_auth.py tests/modules/users tests/test_notifications.py tests/test_event_router.py -q`, y luego la suite completa `TEST_DATABASE_URL=<url-lab> uv run --no-sync python -m pytest -q`
- [x] 7.2 Frontend (desde `frontend/`): `pnpm test --run` y `pnpm exec tsc --noEmit`
- [x] 7.3 Agente (desde la raíz del repo): `PYTHONPATH=backend backend/.venv/bin/python -m pytest agent/tests/test_commands.py -q` y luego `PYTHONPATH=backend backend/.venv/bin/python -m pytest agent/tests -q`
- [x] 7.4 `openspec validate backlog-partial-stories-completion --strict`

## 8. Trazabilidad y cierre

- [x] 8.1 Actualizar `docs/trazabilidad_us_tests.md` §5.5, §5.11, §5.12 y §5.29 con los nombres exactos de los tests nuevos, y dejar registrado D2 para el criterio "hash actual" de US-11
- [x] 8.2 Actualizar `docs/trazabilidad_us_tests.md` §5.27 con los tests de contraseña actual en ambos scopes y complejidad
- [x] 8.3 Actualizar `docs/trazabilidad_us_tests.md` §5.1 (US-01): sólo referencia la ruta `/change-password`, ya alineada; sin tests nuevos si ninguno de los tests citados cambia
- [x] 8.4 Actualizar `docs/trazabilidad_us_tests.md` §5.23 (US-23): citar `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/a4-12.6-webhook-email.txt` como evidencia del canal de email de n8n, y dejar explícito que no cubre el fallback SMTP directo del backend
- [x] 8.5 Si el criterio de "SMTP real" de `docs/cierre/MATRIZ_TRAZABILIDAD.md` (fila US-23) exige acreditar también el fallback SMTP directo del backend: levantar un SMTP de captura (Mailpit) en un `docker compose` aislado del laboratorio, forzar el agotamiento de n8n y confirmar la recepción; documentar la evidencia nueva. Si el criterio ya se considera cubierto por el canal de n8n, omitir y dejarlo registrado en §5.23
- [x] 8.6 Actualizar las filas US-01, US-05, US-11, US-12, US-23, US-27 y US-29 de `docs/cierre/MATRIZ_TRAZABILIDAD.md`; US-12 pasa a COMPLETA si C10 y el resto de sus criterios quedan cubiertos por los tests de este change
- [x] 8.8 US-21 (D-11): tests de `ruleset_version` en la vista y del realce de estados no-ok en `frontend/src/components/ui/AgentCard.test.tsx` (6 casos, 25/25 en el archivo), test del intervalo de heartbeat de 10 s en `agent/tests/test_heartbeat_interval.py` (2/2), `tsc --noEmit` limpio; filas US-21 de `docs/trazabilidad_us_tests.md` y `docs/cierre/MATRIZ_TRAZABILIDAD.md` pasan a completa
- [ ] 8.7 Antes y después de `openspec archive`: `python3 scripts/check_spec_integrity.py` (D47/RN-141); archivar este change antes que el Change 54, en serie (D-10)
