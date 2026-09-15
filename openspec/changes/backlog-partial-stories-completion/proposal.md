## Why

La auditoría V10 de la tesis (riesgo **A-4**, Tabla 22) recomputa el backlog en **23 COMPLETA / 8 PARCIAL / 0 SIN COBERTURA**: el criterio 31/31 no se alcanza. De las ocho historias parciales, cinco se cierran con código ya existente más una cantidad acotada de comportamiento y tests: US-27 no exige la complejidad de contraseña que su criterio pide, US-29 y US-05 muestran el banner de la DLQ sin el umbral `retry_count >= 3`, con el enlace equivocado y sin `audit_log` en los reintentos, y US-11 y US-12 carecen de tests dedicados de criterios ya implementados. Este change corresponde al **Change 55** de `CHANGES.md`.

## What Changes

- **US-27 — complejidad de contraseña.** `POST /users/change-password` rechaza con 422 un `new_password` sin al menos una mayúscula, una minúscula y un número, además del mínimo de 12 caracteres ya vigente (RN-100). `ForcePasswordChange.tsx` valida la misma regla antes de enviar y muestra los requisitos. Se agregan tests de contraseña actual (401 y 200), largo, complejidad, Argon2id con parámetros C9, `audit_log` y re-exigencia del cambio en un login posterior.
- **US-29 / US-05 — banner de la DLQ.** Nuevo `GET /alerts/failed/count` que cuenta las alertas en fallo terminal con `retry_count >= 3`. `AlertsBanner` consume ese conteo, muestra el texto del criterio ("Notificaciones pendientes: N alertas no pudieron ser enviadas") y enlaza a la vista de alertas fallidas en lugar de `/alerts`.
- **US-29 — `audit_log` en la DLQ.** `POST /alerts/{id}/retry` y `DELETE /alerts/{id}` escriben una fila en `audit_log` (`alert_retry`, `alert_discard`) en la misma transacción que la operación. El reintento masivo, que el frontend ya resuelve como N llamadas individuales (`FailedAlerts.tsx:60-78`), deja N filas.
- **US-11 / US-12 — tests dedicados.** Tests del toast ante 409 en approve y reject, del aviso y la confirmación de archivo ausente, y del estado final `completed` / `failed` del journal en los handlers `restore_file` y `quarantine_file`. El texto del toast 409 y del aviso de archivo ausente se alinean con el literal de US-11: hoy difieren (`useEventActions.ts:50`, `EventDetail.tsx:138`), y un test sobre el texto actual no cerraría el criterio.
- Actualización de la trazabilidad (`docs/trazabilidad_us_tests.md`, `docs/cierre/MATRIZ_TRAZABILIDAD.md`) con los tests nuevos.

Fuera de alcance: US-21 (webhook al pasar a `dead`, `queue_size` en UI) queda en el Change 48; US-01 y US-23 son correcciones de texto. La divergencia de US-11 sobre el "hash actual" está cerrada por D2 y sólo se deja registrada.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `backend-auth`: `POST /users/change-password` agrega la regla de complejidad (mayúscula, minúscula, número) con 422.
- `frontend-auth`: `ForcePasswordChange` valida y muestra la regla de complejidad antes de enviar.
- `frontend-shell`: `AlertsBanner` usa el conteo con umbral `retry_count >= 3`, el texto del criterio y el enlace a la vista de alertas fallidas.
- `backend-notifications`: nuevo `GET /alerts/failed/count`; `POST /alerts/{id}/retry` y `DELETE /alerts/{id}` registran la acción en `audit_log`.
- `frontend-events`: el toast ante 409 y el aviso de archivo ausente usan el texto literal de US-11.

## Impact

- **Historias**: US-27, US-29, US-05, US-11, US-12 (`docs/historias_de_usuario.md`).
- **Reglas y decisiones**: RN-94 (W18, `audit_log`), RN-102 (visibilidad de la DLQ), RN-62 y RN-100 (seed y cambio forzado), RN-26 y RN-83 (rechazo y journal), RN-77 (409), D2 (hash del evento en approve), D6/RN-107 (tabla unificada `alerts`). Decisiones nuevas: ninguna; las divergencias no cerradas se listan en `design.md` → Open Questions.
- **Backend**: `backend/app/core/security.py`, `backend/app/modules/users/router.py`, `backend/app/modules/alerts/{router,service}.py`; tests en `backend/tests/test_auth.py`, `backend/tests/modules/users/`, `backend/tests/test_notifications.py`.
- **Frontend**: `frontend/src/pages/ForcePasswordChange.tsx`, `frontend/src/components/layout/AlertsBanner.tsx`, `frontend/src/hooks/useEventActions.ts`, `frontend/src/pages/EventDetail.tsx`; tests nuevos o ampliados junto a cada archivo, y `FailedAlerts.test.tsx`.
- **Agente**: sólo tests en `agent/tests/test_commands.py`; sin cambios de código.
- **API**: endpoint nuevo `GET /alerts/failed/count`. Sin cambios incompatibles.
- **Dependencias del DAG**: 15 (`backend-notifications`) y 17 (`frontend-shell-auth`), ambas archivadas.
- **Coordinación**: el Change 54 (`backend-privacy-hardening`) también modifica `backend/app/modules/alerts/router.py` y los specs `frontend-shell` y `frontend-events` (requisitos distintos). Los applies y los archives de 54 y 55 deben ejecutarse en serie.
