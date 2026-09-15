## Context

La Tabla 22 de la auditoría V10 deja ocho historias en PARCIAL (riesgo A-4). Este change toma las cinco que se cierran sin decisiones nuevas. El estado verificado en el código es el siguiente:

| Historia | Criterio (texto literal) | Estado actual |
|---|---|---|
| US-27 | "El formulario de cambio pide: password actual, password nuevo (>= 12 caracteres, al menos 1 mayúscula, 1 minúscula, 1 número), confirmación." | `ForcePasswordChange.tsx:17-25` sólo valida largo y confirmación |
| US-27 | "El backend valida la contraseña actual y las reglas de complejidad antes de aceptar." | `users/router.py:56-63` valida la actual fuera del scope `password_change_only`; `:65` sólo exige `len >= 12` |
| US-27 | "La nueva contraseña se hashea con Argon2id con parámetros C9." / "La operación se registra en `audit_log` (W18)." / "Si el admin cierra el navegador sin completar, el próximo login vuelve a exigir el cambio." | Implementado (`security.py:21`, `users/router.py:100`, flag persistido), sin tests dedicados; `rg current_password backend/tests` no devuelve resultados |
| US-29 | "Cuando la tabla `failed_notifications` tiene al menos 1 fila con `retry_count >= 3`, el frontend muestra un banner amarillo en el header: \"Notificaciones pendientes: N alertas no pudieron ser enviadas\"." | `AlertsBanner.tsx:23` muestra el banner con `total > 0` de `GET /alerts?status=failed`, sin umbral y con otro texto |
| US-29 | "El banner incluye un link que abre la vista `/notifications/failed`." | `AlertsBanner.tsx:31` enlaza a `/alerts`; la vista existe en `/alerts/failed` (`App.tsx:61`) |
| US-29 | "La acción (reintentar / descartar) se registra en `audit_log` (W18)." | `backend/app/modules/alerts/*.py` no escribe `audit_log` |
| US-05 | "Si hay notificaciones externas fallidas (`failed_notifications` con `retry_count >= 3`), se muestra banner amarillo persistente (ver US-29)." | Igual que el primer criterio de US-29 |
| US-11 | "…el backend retorna HTTP 409 y el frontend muestra un toast: \"Este evento ya fue resuelto o reemplazado. Refrescando lista...\" (C5)." | `useEventActions.ts:50` muestra "Este evento ya fue resuelto por otro admin"; sin test |
| US-11 | "Si el archivo ya no existe en el filesystem al momento de aprobar, se muestra un warning: \"El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline.\"" / "El admin debe confirmar explícitamente la aprobación de un archivo ausente." | `EventDetail.tsx:136-153` muestra "El archivo no está en el baseline. ¿Confirmar aprobación de ausencia?" con botón Confirmar; sin test de UI |
| US-12 | "El agente escribe journal pre-acción (W2) antes de ejecutar restore o quarantine; al completar actualiza el journal a `completed` o `failed` con detalles." | `agent/commands.py:338-409` y `:460-498` implementan ambas transiciones; sólo hay tests del `JournalManager` aislado y del orden pre-acción |

Datos del modelo que condicionan el diseño:

- `notify_event` (`alerts/service.py:240-272`) escribe `retry_count = attempt` en cada fallo de n8n y, al agotar la cascada, marca `failed_at`. Con `N8N_WEBHOOK_URL` configurada, una alerta en fallo terminal queda con `retry_count = 3`; sin n8n configurado, queda con `retry_count = 0`. `retry_alert` resetea `retry_count = 0` y `failed_at = NULL` antes de reencolar.
- `list_alerts(status="failed")` filtra sólo `failed_at IS NOT NULL` (`service.py:405-406`); `list_failed_alerts` usa la definición completa de D6 (`delivered_at IS NULL AND failed_at IS NOT NULL`).
- `AuditLog` tiene `user_id`, `action`, `target_type`, `target_id`, `detail`. `write_audit_log` (`core/audit.py`) no completa `target_type` / `target_id` y hace commit propio.
- `AlertsBanner` usa la query key `['alerts-failed-count']`, que no cae bajo el prefijo `['alerts']` que `useRetryAlert` / `useDiscardAlert` invalidan (`useAlerts.ts:25-37`).
- El error 422 de `change-password` hoy es un `HTTPException` con `detail` string, y `ForcePasswordChange.tsx:51` muestra ese string tal cual.

## Goals / Non-Goals

**Goals:**

- Que cada criterio listado en el Change 55 tenga un test que lo ejercite contra su texto literal y pase.
- Implementar sólo el comportamiento faltante: complejidad de contraseña, umbral y enlace del banner, `audit_log` en reintento y descarte, y el texto literal de dos mensajes de US-11.
- Mantener la trazabilidad recomputable: cada test nuevo se cita por nombre en `docs/trazabilidad_us_tests.md`.

**Non-Goals:**

- US-21 (Change 48), US-01 y US-23 (correcciones de texto).
- Cambiar D2: el baseline se sigue actualizando con el hash del evento. La divergencia con el criterio "hash actual" de US-11 queda registrada, no se implementa.
- Aplicar la regla de complejidad a `POST /users` (alta de admins). RN-100 la fija para el cambio forzado, y todo admin creado nace con `must_change_password = true`, así que su primera contraseña propia pasa por la regla.
- Endpoint de reintento masivo en el backend. El contrato vigente de `frontend-alerts` ya define el bulk como N llamadas individuales.
- Agregar `ruleset_version` a `restore_file` / `quarantine_file`, pedir la contraseña actual en el cambio forzado, o restituir la rama visual C10 del `RejectModal`. Son divergencias no cerradas (ver Open Questions).

## Decisions

### D-1 — La política de contraseña vive en `core/security.py` y se aplica en el router con 422 de `detail` string

Se agrega `password_policy_error(password: str) -> str | None` en `backend/app/core/security.py`, junto a `hash_password`. Devuelve `None` si la contraseña cumple, o el mensaje del primer requisito incumplido: largo (≥ 12) primero y complejidad después. `change_password` reemplaza el chequeo de `len` por esta función y conserva `HTTPException(422, detail=<string>)`.

- **Alternativa descartada: `field_validator` de Pydantic en `ChangePasswordRequest`.** Produce un 422 con `detail` como lista de errores, que `ForcePasswordChange` mostraría como `[object Object]`, y cambiaría la forma del error que el spec `backend-auth` ya fija para el largo.
- **Clases de carácter:** mayúscula = `str.isupper()`, minúscula = `str.islower()`, número = `str.isdecimal()`, evaluadas por carácter. El frontend usa las clases Unicode equivalentes (`\p{Lu}`, `\p{Ll}`, `\p{Nd}` con flag `u`). Así una contraseña en castellano con `Ñ` o `Á` cuenta como mayúscula en ambos lados. La paridad se fija con los mismos casos de prueba en backend y frontend.

### D-2 — El umbral del banner se resuelve en el backend con un endpoint de conteo dedicado

Nuevo `GET /alerts/failed/count` (admin), que responde `{"count": int}` con `delivered_at IS NULL AND failed_at IS NOT NULL AND retry_count >= 3`. El umbral es una constante de módulo (`DLQ_BANNER_MIN_RETRY_COUNT = 3`) en `alerts/service.py`. `AlertsBanner` hace polling cada 30 s a ese endpoint.

- **Por qué en el backend:** el umbral es parte del estado de la alerta (D6/RN-107), no una preferencia de presentación. Si el frontend filtrara, duplicaría la máquina de estados de `alerts` en la UI.
- **Alternativa descartada: filtrar del lado del cliente sobre `GET /alerts/failed`.** Transfiere la DLQ completa, sin paginar, cada 30 s para mostrar un número.
- **Alternativa descartada: parámetro `min_retry_count` en `GET /alerts`.** `list_alerts(status="failed")` no aplica `delivered_at IS NULL`, así que el conteo no coincidiría con la vista de fallidas, y se ensancharía un endpoint genérico por un único consumidor.
- **Precedente:** W11 (`docs/flujo_de_usuario.md:1100`) ya prescribe un endpoint de conteo para el banner. La ruta se ubica bajo `/alerts/failed` porque D6 unificó la DLQ en `alerts` y `GET /alerts/failed` ya es la vista de datos (`CHANGES.md:370`).
- La ruta `/failed/count` se declara antes de cualquier ruta con `/{alert_id}` para que no la capture un parámetro de path.

### D-3 — La query key del banner pasa a `['alerts', 'failed', 'count']`

`useRetryAlert` y `useDiscardAlert` ya invalidan `['alerts']` y `['alerts', 'failed']`. Con la key bajo ese prefijo, el banner se refresca apenas se reintenta o se descarta, sin esperar el próximo poll. No se toca `useAlerts.ts`.

### D-4 — `audit_log` en la misma transacción que la operación sobre la alerta

`retry_alert(alert_id, session, actor_id)` y `delete_alert(alert_id, session, actor_id)` agregan un `AuditLog(user_id=actor_id, action=..., target_type="alert", target_id=alert_id, detail=f"event_id={alert.event_id}")` a la sesión antes del `commit` que ya hacen: el reset de la DLQ en el reintento, el `DELETE` en el descarte. El router pasa `_admin.id`.

- **Acciones:** `alert_retry` y `alert_discard`, con la convención `<recurso>_<verbo>` ya en uso (`agent_config`, `agent_rescan`, `user_created`).
- **`detail` con `event_id`:** tras un descarte la fila de `alerts` desaparece, y `event_id` es el único vínculo auditable con el evento que originó la notificación.
- **Por qué no `write_audit_log`:** hace su propio `commit` y no completa `target_type` / `target_id`. Con un commit separado podría quedar un reintento sin registro, o un registro sin reintento.
- **Sólo operaciones exitosas:** un 404 o 409 lanza antes del commit y no deja fila.
- **Bulk:** N llamadas producen N filas. Es lo que pide el Done de CHANGES ("cada reintento deja una fila en `audit_log`"), y permite auditar cada alerta por separado.

### D-5 — Los textos de US-11 se alinean con el literal de la historia

El toast del 409 (compartido por approve y reject) pasa a "Este evento ya fue resuelto o reemplazado. Refrescando lista...". El aviso de archivo ausente pasa a "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline.", y conserva los botones Confirmar / Cancelar. No es una decisión nueva: el texto canónico existe y el spec `frontend-events` lo había reemplazado sin decisión que lo respalde. Sin este ajuste, un test sobre el texto actual no cierra el criterio (regla de `docs/trazabilidad_us_tests.md` §2).

### D-6 — US-12 se cierra con tests sobre los handlers reales, no sobre `JournalManager` aislado

Los tests invocan `handle_restore_file` y `handle_quarantine_file` con un `JournalManager` real sobre `tmp_path`, y leen la entrada por `command_id` para verificar `state == "completed"` en el camino feliz, y `state == "failed"` con `error` no vacío en un fallo (sin baseline para restore; store o fuente inválida para quarantine). Los handlers no borran la entrada tras marcarla (a diferencia de `DecisionEngine`), así que el estado final es observable sin espías.

## Risks / Trade-offs

- [El umbral `retry_count >= 3` oculta del banner las alertas en fallo terminal cuando n8n no está configurado (`retry_count = 0`)] → Siguen visibles en `/alerts/failed`. El conflicto con D6/RN-107 queda como Open Question bloqueante antes de `/opsx:apply`.
- [Paridad de clases de carácter entre Python y la regex Unicode del navegador] → Mismos casos de prueba (ASCII, `Ñ`, dígitos) en ambos lados.
- [Colisión con el Change 54 en `alerts/router.py` y en los specs `frontend-shell` / `frontend-events`] → Applies y archives en serie. Los requisitos modificados son distintos, así que el merge de specs no se pisa.
- [Un `audit_log` que falla al insertar ahora aborta el reintento o el descarte] → Es el comportamiento buscado (RN-94 exige el registro). El 500 resultante es visible en la UI.
- [Tests de backend dependientes de Postgres del laboratorio] → Se corren con `TEST_DATABASE_URL` explícita. Sin base, la suite no se considera verde.

## Migration Plan

Sin migraciones de esquema: `audit_log` y `alerts` ya tienen las columnas necesarias. El despliegue es el normal de backend y frontend. Rollback: revertir el commit. El endpoint nuevo no tiene consumidores fuera de `AlertsBanner`.

## Open Questions

Todas requieren cierre en el appendix "Decisiones de implementación" del doc canónico correspondiente antes de `/opsx:apply`. OQ-1 y OQ-2 condicionan requisitos de este change; OQ-3 a OQ-5 condicionan si US-12 y US-27 llegan a COMPLETA.

1. **OQ-1 — Umbral del banner vs D6/RN-107 (bloqueante).** US-29, US-05 y el Done del Change 55 exigen `retry_count >= 3`. El appendix D6 (`docs/arquitectura_stack.md:2088-2091`, `docs/reglas_de_negocio.md:2138`), que prevalece, reemplazó la base del banner de RN-102 por `COUNT(*) WHERE delivered_at IS NULL AND failed_at IS NOT NULL`, sin umbral. En la tabla unificada, `failed_at IS NOT NULL` ya significa fallo terminal, que es lo que `retry_count >= 3` expresaba en `failed_notifications`. Aplicar el umbral literal oculta los fallos terminales sin n8n configurado. Los specs de este change siguen el Done del Change 55; si se cierra a favor de D6, el requisito del conteo y el escenario de umbral se reemplazan por el de fallo terminal.
2. **OQ-2 — Ruta de la vista de fallidas.** US-29 y RN-102 nombran `/notifications/failed`; la vista archivada (`frontend-alerts`) vive en `/alerts/failed` y ninguna decisión formalizó el cambio. Los specs enlazan a `/alerts/failed`. Alternativa: registrar `/notifications/failed` como redirect a `/alerts/failed` para cumplir el literal sin mover la vista.
3. **OQ-3 — `ruleset_version` en los comandos de rechazo (US-12).** RN-26 (`docs/reglas_de_negocio.md:211`), RN-57 y el criterio de US-12 lo incluyen. El spec `backend-approve-reject` (`openspec/specs/backend-approve-reject/spec.md:150`) lo excluye ("No incluye `hash` ni `ruleset_version`"), sin decisión en un appendix. Hasta cerrarlo, este change sólo documenta la divergencia y US-12 no puede declararse COMPLETA por ese criterio.
4. **OQ-4 — Contraseña actual en el cambio forzado (US-27).** US-27 y W20 (`docs/flujo_de_usuario.md:733-752`) piden "password actual" en el formulario, y que el backend la verifique también en el primer login. Los specs `backend-auth` y `frontend-auth` la omiten con scope `password_change_only`, sin decisión que lo respalde. Este change testea la verificación con scope normal, pero no cambia el flujo forzado.
5. **OQ-5 — Criterio visual C10 de US-12.** El criterio pide que el modal oculte las acciones cuando el baseline está `absent`; `RejectModal.tsx:16-18` documenta que esa rama se eliminó en C38 a favor del no-op del servidor (RN-74). Hace falta decidir si se restituye o si se registra la sustitución.
