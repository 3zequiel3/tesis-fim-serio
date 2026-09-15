## Why

La auditoría V10 de la tesis (riesgo **A-4**, Tabla 22) recomputa el backlog en **23 COMPLETA / 8 PARCIAL / 0 SIN COBERTURA**: el criterio 31/31 no se alcanza. De las ocho historias parciales, siete se cierran en este change: US-27 no exige la complejidad de contraseña ni la contraseña actual que su criterio pide en el flujo de primer login, US-29 y US-05 muestran el banner de la DLQ con el enlace equivocado y sin `audit_log` en los reintentos, US-11 carece de tests dedicados de criterios ya implementados, US-12 carece de esos mismos tests y además el modal de rechazo no implementa el criterio C10 (ocultar las opciones correctivas ante baseline `absent`), y US-01 / US-23 sólo necesitan su fila de trazabilidad corregida — la divergencia de ruta de US-01 y la de tabla de US-05/US-29 ya fueron alineadas por el equipo de documentación. Este change corresponde al **Change 55** de `CHANGES.md`.

## What Changes

- **US-27 — complejidad y contraseña actual.** `POST /users/change-password` rechaza con 422 un `new_password` sin al menos una mayúscula, una minúscula y un número, además del mínimo de 12 caracteres ya vigente (RN-100). El endpoint MUST exigir y verificar `current_password` también con scope `password_change_only` (hoy sólo se verifica con scope normal): el admin conoce su contraseña de seed, que es justamente la que el primer login usó. `ForcePasswordChange.tsx` agrega el campo "Contraseña actual", valida la misma regla de complejidad antes de enviar y muestra los requisitos. Se agregan tests de contraseña actual (401 y 200) en ambos scopes, largo, complejidad, Argon2id con parámetros C9, `audit_log` y re-exigencia del cambio en un login posterior.
- **US-29 / US-05 — banner de la DLQ.** Nuevo `GET /alerts/failed/count` que cuenta las alertas en fallo terminal según la definición unificada de D6/RN-102 (`delivered_at IS NULL AND failed_at IS NOT NULL`), **sin** umbral adicional de `retry_count`: con n8n sin configurar una alerta agotada queda con `retry_count = 0` y debe seguir contando. `AlertsBanner` consume ese conteo, muestra el texto del criterio ("Notificaciones pendientes: N alertas no pudieron ser enviadas") y enlaza a `/alerts/failed`.
- **US-29 — `audit_log` en la DLQ.** `POST /alerts/{id}/retry` y `DELETE /alerts/{id}` escriben una fila en `audit_log` (`alert_retry`, `alert_discard`) en la misma transacción que la operación. El reintento masivo, que el frontend ya resuelve como N llamadas individuales (`FailedAlerts.tsx:60-78`), deja N filas.
- **US-11 — tests dedicados.** Tests del toast ante 409 en approve y reject, y del aviso y la confirmación de archivo ausente en approve. El texto del toast 409 y del aviso de archivo ausente se alinean con el literal de US-11: hoy difieren (`useEventActions.ts:50`, `EventDetail.tsx:138`), y un test sobre el texto actual no cerraría el criterio.
- **US-12 — criterio C10 del modal de rechazo y tests del journal.** `GET /events/{event_id}` agrega `baseline_status: "present" | "absent" | null`, leído de `baseline_entries` por `(path, agent_id)`. `RejectModal` oculta las opciones "Restaurar" / "Poner en cuarentena" y muestra "No hay archivo a restaurar (baseline ausente). Confirmar rechazará el evento sin acción en filesystem." cuando `baseline_status === "absent"` (C10); el hook de acciones además muestra un toast informativo si, por una condición de carrera, el backend responde `baseline_absent: true` sobre un evento cuyo modal mostró las opciones. `ruleset_version` **no** se agrega a los comandos de rechazo — D66/RN-160 (nueva, 2026-09-15) cerró esa divergencia declarando que ese contador es exclusivo de `update_config`. Se agregan tests del estado final `completed` / `failed` del journal en los handlers `restore_file` y `quarantine_file`.
- **US-01 / US-23 — trazabilidad.** Sin cambios de comportamiento. Se actualizan las filas de `docs/trazabilidad_us_tests.md` y `docs/cierre/MATRIZ_TRAZABILIDAD.md`: US-01 referencia la ruta `/change-password` (ya alineada en la historia); US-05 y US-29 referencian la tabla `alerts` (D6); US-23 cita la entrega real de email vía n8n con Gmail SMTP (`docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/a4-12.6-webhook-email.txt`) y deja explícito que esa evidencia cubre el canal de email de n8n, no el fallback SMTP directo del backend — si el criterio de "SMTP real" exige también ese fallback, se agrega una verificación con un SMTP de captura (Mailpit) en un compose aislado.
- Actualización de la trazabilidad (`docs/trazabilidad_us_tests.md`, `docs/cierre/MATRIZ_TRAZABILIDAD.md`) con los tests nuevos y las siete historias.

US-21 se incorporó el 2026-09-15 como ítem de trazabilidad y tests: `queue_size`, el webhook al pasar a `dead` y el banner W3 ya estaban implementados desde el 2026-09-12 (`7f62348`, `1226ed9`); faltaban tests de `ruleset_version` en la vista, del realce de estados no-ok y del intervalo de heartbeat de 10 s. La cascada y la DLQ de esa notificación siguen en el Change 48. La divergencia de US-11 sobre el "hash actual" está cerrada por D2 y sólo se deja registrada. Extender `POST /actions/bulk-reject` para exponer `baseline_absent` por ítem queda fuera: el bulk reject ya documenta (`actions/service.py:401-402`, RN-74) la decisión de no exponerlo como representación paralela, y sólo el flujo individual implementa C10 (ver design.md → Decisions).

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `backend-auth`: `POST /users/change-password` agrega la regla de complejidad (mayúscula, minúscula, número) con 422, y exige `current_password` también con scope `password_change_only`.
- `frontend-auth`: `ForcePasswordChange` agrega el campo de contraseña actual y valida/muestra la regla de complejidad antes de enviar.
- `frontend-shell`: `AlertsBanner` usa el conteo de fallo terminal de D6/RN-102 (sin umbral de `retry_count`), el texto del criterio y el enlace a `/alerts/failed`.
- `backend-notifications`: nuevo `GET /alerts/failed/count`; `POST /alerts/{id}/retry` y `DELETE /alerts/{id}` registran la acción en `audit_log`.
- `backend-events-api`: `GET /events/{event_id}` agrega `baseline_status`.
- `frontend-events`: el toast ante 409 y el aviso de archivo ausente usan el texto literal de US-11; `RejectModal` implementa C10.

## Impact

- **Historias**: US-27, US-29, US-05, US-11, US-12, US-01, US-23 (`docs/historias_de_usuario.md`).
- **Reglas y decisiones**: RN-94 (W18, `audit_log`), RN-102 (visibilidad de la DLQ), RN-62 y RN-100 (seed y cambio forzado), RN-26, RN-74 y RN-83 (rechazo, no-op de baseline absent y journal), RN-77 (409), D2 (hash del evento en approve), D6/RN-107 (tabla unificada `alerts`), D66/RN-160 (nueva — `ruleset_version` fuera de los comandos de acción).
- **Backend**: `backend/app/core/security.py`, `backend/app/modules/users/router.py`, `backend/app/modules/alerts/{router,service}.py`, `backend/app/modules/events/router.py`; tests en `backend/tests/test_auth.py`, `backend/tests/modules/users/`, `backend/tests/test_notifications.py`, `backend/tests/test_event_router.py`.
- **Frontend**: `frontend/src/pages/ForcePasswordChange.tsx`, `frontend/src/components/layout/AlertsBanner.tsx`, `frontend/src/hooks/useEventActions.ts`, `frontend/src/pages/EventDetail.tsx`, `frontend/src/components/ui/RejectModal.tsx`, `frontend/src/api/{actions,events}.ts`; tests nuevos o ampliados junto a cada archivo, y `FailedAlerts.test.tsx`.
- **Agente**: sólo tests en `agent/tests/test_commands.py`; sin cambios de código.
- **API**: endpoint nuevo `GET /alerts/failed/count`; `GET /events/{event_id}` agrega el campo `baseline_status`. Sin cambios incompatibles.
- **Dependencias del DAG**: 15 (`backend-notifications`) y 17 (`frontend-shell-auth`), ambas archivadas.
- **Coordinación**: el Change 54 (`backend-privacy-hardening`) también modifica `backend/app/modules/alerts/router.py` y los specs `frontend-shell` y `frontend-events` (requisitos distintos). Este change se aplica y archiva primero; el Change 54 sigue después, en serie (ver design.md).
