## 0. Precondiciones

- [ ] 0.1 Cerrar OQ-1 (umbral del banner vs D6/RN-107) y OQ-2 (ruta `/notifications/failed` vs `/alerts/failed`) en el appendix "Decisiones de implementación" antes de tocar código; si el cierre contradice los specs de este change, actualizarlos primero
- [ ] 0.2 Confirmar que el apply del Change 54 (`backend-privacy-hardening`) no está en curso sobre `backend/app/modules/alerts/`; los applies de 54 y 55 se ejecutan en serie
- [ ] 0.3 Registrar el estado base de las suites (backend, frontend, agente) con los comandos de la sección 7, para distinguir fallas preexistentes

## 1. US-27 — Política de contraseña (backend)

- [ ] 1.1 Agregar `password_policy_error(password) -> str | None` en `backend/app/core/security.py`: largo ≥ 12 primero, después al menos una mayúscula (`isupper`), una minúscula (`islower`) y un dígito (`isdecimal`) por carácter
- [ ] 1.2 Reemplazar el chequeo `len(body.new_password) < 12` de `backend/app/modules/users/router.py` por `password_policy_error`, manteniendo `HTTPException(422, detail=<string>)` y evaluándolo antes de modificar el usuario
- [ ] 1.3 Tests unitarios de `password_policy_error`: válida, corta, sin mayúscula, sin minúscula, sin dígito, mayúscula `Ñ` válida
- [ ] 1.4 Test HTTP: `new_password` sin mayúscula / sin minúscula / sin dígito → 422 con `detail` string y `password_hash` sin cambios (tres casos parametrizados)
- [ ] 1.5 Test HTTP: `new_password` de 11 caracteres → 422
- [ ] 1.6 Test HTTP con scope normal: `current_password` incorrecto → 401 y hash sin cambios; `current_password` correcto → 200 y `must_change_password = False`
- [ ] 1.7 Test: tras un cambio exitoso, el `password_hash` persistido empieza con `$argon2id$`, codifica `m=65536,t=3,p=4` y verifica contra el nuevo password y no contra el anterior
- [ ] 1.8 Test: un cambio exitoso deja una fila `audit_log` con `action="change_password"` y el `user_id`
- [ ] 1.9 Test: login del seed, sin completar el cambio, segundo login → `must_change_password: true` y token con scope `password_change_only`

## 2. US-27 — Formulario de cambio forzado (frontend)

- [ ] 2.1 En `frontend/src/pages/ForcePasswordChange.tsx`, extender `validate()` con las reglas de mayúscula (`\p{Lu}`), minúscula (`\p{Ll}`) y número (`\p{Nd}`) con flag `u`, con un mensaje por requisito
- [ ] 2.2 Mostrar en el formulario la lista de requisitos (12 caracteres, 1 mayúscula, 1 minúscula, 1 número) y actualizar el texto descriptivo que hoy sólo menciona 12 caracteres
- [ ] 2.3 Crear `frontend/src/pages/ForcePasswordChange.test.tsx`: password sin mayúscula, sin minúscula y sin número muestran error y `changePasswordApi` no se llama; password corto idem; password válido con `Ñ` llama a `changePasswordApi`; los requisitos se renderizan

## 3. US-29 / US-05 — Conteo y banner de la DLQ

- [ ] 3.1 Agregar `DLQ_BANNER_MIN_RETRY_COUNT = 3` y `count_failed_alerts_over_threshold(session) -> int` en `backend/app/modules/alerts/service.py` con `delivered_at IS NULL AND failed_at IS NOT NULL AND retry_count >= DLQ_BANNER_MIN_RETRY_COUNT`
- [ ] 3.2 Agregar `GET /alerts/failed/count` (admin) en `backend/app/modules/alerts/router.py` que responde `{"count": int}`, declarado antes de las rutas con `/{alert_id}`
- [ ] 3.3 Tests backend en `backend/tests/test_notifications.py`: con alertas entregada, fallida `retry_count=3`, fallida `retry_count=2` y pendiente → `count == 1`; DLQ vacía → `count == 0`; sin token → 401
- [ ] 3.4 Cambiar `AlertsBanner.tsx` para consultar `GET /alerts/failed/count` con query key `['alerts', 'failed', 'count']`, mostrar "Notificaciones pendientes: N alertas no pudieron ser enviadas" (singular "1 alerta no pudo ser enviada") y enlazar a `/alerts/failed`
- [ ] 3.5 Reescribir `frontend/src/components/layout/AlertsBanner.test.tsx` contra el nuevo contrato: `count=0` sin banner; `count=4` con el texto literal de US-29 y clase amarilla; singular; `href="/alerts/failed"`; consulta a `/alerts/failed/count`; banner que desaparece cuando un refetch devuelve `count=0`
- [ ] 3.6 Test de umbral de extremo a extremo del criterio: DLQ con sólo alertas `retry_count < 3` → el endpoint devuelve 0 (backend) y el banner no se muestra con `count=0` (frontend)

## 4. US-29 — `audit_log` en reintento y descarte

- [ ] 4.1 Agregar el parámetro `actor_id` a `retry_alert` y agregar a la sesión un `AuditLog(action="alert_retry", target_type="alert", target_id=alert_id, detail=f"event_id={alert.event_id}")` antes del commit del reset
- [ ] 4.2 Agregar el parámetro `actor_id` a `delete_alert` y agregar a la sesión un `AuditLog(action="alert_discard", ...)` antes del commit de la eliminación
- [ ] 4.3 Pasar `_admin.id` desde `retry_failed_alert` y `discard_alert` en `alerts/router.py`; actualizar los demás llamadores y tests existentes de `retry_alert` / `delete_alert` a la nueva firma
- [ ] 4.4 Test: `POST /alerts/{id}/retry` exitoso deja una fila `alert_retry` con `user_id` del admin, `target_type="alert"`, `target_id` y `detail` con `event_id`
- [ ] 4.5 Test: tres `POST /alerts/{id}/retry` sobre alertas distintas (reintento masivo) dejan tres filas `alert_retry` con los `target_id` correspondientes
- [ ] 4.6 Test: `POST /alerts/{id}/retry` con 404 y con 409 no deja filas en `audit_log`
- [ ] 4.7 Test: `DELETE /alerts/{id}` exitoso deja una fila `alert_discard` con `detail` que contiene el `event_id`; `DELETE` con 404 no deja filas
- [ ] 4.8 Crear `frontend/src/pages/FailedAlerts.test.tsx`: "Reintentar" por fila llama `POST /alerts/{id}/retry`; seleccionar tres filas y el bulk llama `POST /alerts/{id}/retry` una vez por id; "Descartar" confirmado llama `DELETE /alerts/{id}`

## 5. US-11 — Toast 409 y aviso de archivo ausente

- [ ] 5.1 Cambiar el toast 409 de `frontend/src/hooks/useEventActions.ts` a "Este evento ya fue resuelto o reemplazado. Refrescando lista..."
- [ ] 5.2 Cambiar el aviso de `frontend/src/pages/EventDetail.tsx` a "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline.", conservando Confirmar / Cancelar
- [ ] 5.3 Test (`EventDetail.test.tsx` o `useEventActions.test.tsx`): approve con 409 muestra el toast literal e invalida las queries `['event', id]` y `['events']`
- [ ] 5.4 Test: reject con 409 muestra el mismo toast e invalida las queries (criterio 409 de US-12)
- [ ] 5.5 Test: approve con 422 `absent_confirmation_required` muestra el aviso literal; Confirmar reenvía `POST /actions/approve` con `confirm_absent: true`; Cancelar oculta el aviso sin nueva request
- [ ] 5.6 Test: el detalle de un evento `pending` muestra los botones "Aprobar" y "Rechazar"

## 6. US-12 — Estado final del journal de los comandos de rechazo

- [ ] 6.1 Test en `agent/tests/test_commands.py`: `handle_restore_file` exitoso con `JournalManager` real sobre `tmp_path` deja la entrada del `command_id` en `state == "completed"`
- [ ] 6.2 Test: `handle_restore_file` sin baseline deja la entrada en `state == "failed"` con `error == "no_baseline_content"`
- [ ] 6.3 Test: `handle_quarantine_file` exitoso deja la entrada en `state == "completed"`
- [ ] 6.4 Test: `handle_quarantine_file` con fallo del store deja la entrada en `state == "failed"` con `error` no vacío igual al del ack publicado

## 7. Verificación

- [ ] 7.1 Backend (desde `backend/`, con Postgres de laboratorio): `TEST_DATABASE_URL=<url-lab> uv run --no-sync python -m pytest tests/test_auth.py tests/modules/users tests/test_notifications.py -q`, y luego la suite completa `TEST_DATABASE_URL=<url-lab> uv run --no-sync python -m pytest -q`
- [ ] 7.2 Frontend (desde `frontend/`): `pnpm test --run` y `pnpm exec tsc --noEmit`
- [ ] 7.3 Agente (desde la raíz del repo): `PYTHONPATH=backend backend/.venv/bin/python -m pytest agent/tests/test_commands.py -q` y luego `PYTHONPATH=backend backend/.venv/bin/python -m pytest agent/tests -q`
- [ ] 7.4 `openspec validate backlog-partial-stories-completion --strict`

## 8. Trazabilidad y cierre

- [ ] 8.1 Actualizar `docs/trazabilidad_us_tests.md` §5.5, §5.11, §5.12, §5.27 y §5.29 con los nombres exactos de los tests nuevos, y dejar registrado D2 para el criterio "hash actual" de US-11
- [ ] 8.2 Actualizar las filas US-05, US-11, US-12, US-27 y US-29 de `docs/cierre/MATRIZ_TRAZABILIDAD.md`; mantener PARCIAL en US-12 / US-27 mientras OQ-3, OQ-4 u OQ-5 sigan abiertas
- [ ] 8.3 Antes y después de `openspec archive`: `python3 scripts/check_spec_integrity.py` (D47/RN-141); archivar en serie con el Change 54
