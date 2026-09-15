## Context

La Tabla 22 de la auditoría V10 deja ocho historias en PARCIAL (riesgo A-4). Este change toma las siete que se cierran con código ya existente más una cantidad acotada de comportamiento y tests, o con corrección de trazabilidad. El estado verificado en el código es el siguiente:

| Historia | Criterio (texto literal) | Estado actual |
|---|---|---|
| US-27 | "El formulario de cambio pide: password actual, password nuevo (>= 12 caracteres, al menos 1 mayúscula, 1 minúscula, 1 número), confirmación." | `ForcePasswordChange.tsx:17-25` sólo valida largo y confirmación; no hay campo de contraseña actual |
| US-27 | "El backend valida la contraseña actual y las reglas de complejidad antes de aceptar." | `users/router.py:56-63` valida la actual sólo fuera del scope `password_change_only`; `:65` sólo exige `len >= 12` |
| US-27 | "La nueva contraseña se hashea con Argon2id con parámetros C9." / "La operación se registra en `audit_log` (W18)." / "Si el admin cierra el navegador sin completar, el próximo login vuelve a exigir el cambio." | Implementado (`security.py:21`, `users/router.py:100`, flag persistido), sin tests dedicados; `rg current_password backend/tests` no devuelve resultados |
| US-29 | "Cuando la tabla `failed_notifications` tiene al menos 1 fila con `retry_count >= 3`, el frontend muestra un banner amarillo en el header: \"Notificaciones pendientes: N alertas no pudieron ser enviadas\"." | `AlertsBanner.tsx:23` muestra el banner con `total > 0` de `GET /alerts?status=failed`, con otro texto; `list_alerts(status="failed")` no aplica `delivered_at IS NULL` |
| US-29 | "El banner incluye un link que abre la vista `/notifications/failed`." | `AlertsBanner.tsx:31` enlaza a `/alerts`; la vista existe en `/alerts/failed` (`App.tsx:61`) |
| US-29 | "La acción (reintentar / descartar) se registra en `audit_log` (W18)." | `backend/app/modules/alerts/*.py` no escribe `audit_log` |
| US-05 | "Si hay notificaciones externas fallidas (`failed_notifications` con `retry_count >= 3`), se muestra banner amarillo persistente (ver US-29)." | Igual que el primer criterio de US-29; la historia ya fue corregida por el equipo de documentación a la definición D6/RN-102 (fallo terminal, sin umbral) |
| US-11 | "…el backend retorna HTTP 409 y el frontend muestra un toast: \"Este evento ya fue resuelto o reemplazado. Refrescando lista...\" (C5)." | `useEventActions.ts:50` muestra "Este evento ya fue resuelto por otro admin"; sin test |
| US-11 | "Si el archivo ya no existe en el filesystem al momento de aprobar, se muestra un warning: \"El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline.\"" / "El admin debe confirmar explícitamente la aprobación de un archivo ausente." | `EventDetail.tsx:136-153` muestra "El archivo no está en el baseline. ¿Confirmar aprobación de ausencia?" con botón Confirmar; sin test de UI |
| US-12 | "El agente escribe journal pre-acción (W2) antes de ejecutar restore o quarantine; al completar actualiza el journal a `completed` o `failed` con detalles." | `agent/commands.py:338-409` y `:460-498` implementan ambas transiciones; sólo hay tests del `JournalManager` aislado y del orden pre-acción |
| US-12 | "Si el baseline del path está en `status: absent`, el modal de rechazo oculta las opciones de acción correctiva y muestra: 'No hay archivo a restaurar (baseline ausente). Confirmar rechazará el evento sin acción en filesystem.' — C10." | `RejectModal.tsx:16` documenta la rama como código muerto eliminado en C38 y siempre muestra ambas opciones; el backend ya resuelve el no-op (`actions/service.py:309-339`, `baseline_absent` en la respuesta de `POST /actions/reject`), pero el frontend no expone `baseline_status` antes de enviar ni usa `baseline_absent` en la respuesta — es un gap real, no una divergencia superada |
| US-01 | Ruta `/change-password` (W20) | Ya coincide en código (`App.tsx`) y en la historia (corregida por el equipo de documentación); sólo falta la fila de trazabilidad |
| US-23 | Tabla `alerts` unificada (D6/RN-107), fallback SMTP directo | El código y la historia ya coinciden; falta citar evidencia de entrega real en la trazabilidad |

Datos del modelo que condicionan el diseño:

- `notify_event` (`alerts/service.py:240-272`) escribe `retry_count = attempt` en cada fallo de n8n y, al agotar la cascada, marca `failed_at`. Con `N8N_WEBHOOK_URL` configurada, una alerta en fallo terminal queda con `retry_count = 3`; sin n8n configurado, queda con `retry_count = 0`. `retry_alert` resetea `retry_count = 0` y `failed_at = NULL` antes de reencolar.
- `list_alerts(status="failed")` filtra sólo `failed_at IS NOT NULL` (`service.py:405-406`); `list_failed_alerts` usa la definición completa de D6 (`delivered_at IS NULL AND failed_at IS NOT NULL`), que es también la que define `GET /alerts/failed/count`.
- `AuditLog` tiene `user_id`, `action`, `target_type`, `target_id`, `detail`. `write_audit_log` (`core/audit.py`) no completa `target_type` / `target_id` y hace commit propio.
- `AlertsBanner` usa la query key `['alerts-failed-count']`, que no cae bajo el prefijo `['alerts']` que `useRetryAlert` / `useDiscardAlert` invalidan (`useAlerts.ts:25-37`).
- El error 422 de `change-password` hoy es un `HTTPException` con `detail` string, y `ForcePasswordChange.tsx:51` muestra ese string tal cual.
- `baseline_entries` (`agents/models.py:145`, único índice por `(path, agent_id)`) tiene `status: BaselineStatus` (`present` | `absent`). `GET /events/{event_id}` responde con `EventDetailOut` (`events/router.py:70`), que extiende `EventOut` sin ese dato.
- `POST /actions/reject` ya responde `{event_id, status, baseline_absent}` (`actions/router.py:81-94`), y el no-op sobre baseline `absent` está cubierto por `test_reject_absent_baseline_noop` (`test_actions.py:334`) y `test_reject_with_absent_baseline_reports_the_noop` (`test_actions_router.py:310`). `reject_bulk` (`actions/service.py:391-427`) trata ese no-op como éxito sin exponerlo por ítem — comentario explícito (`:401-402`) de no duplicar esa representación en el bulk.

## Goals / Non-Goals

**Goals:**

- Que cada criterio listado en el Change 55 tenga un test que lo ejercite contra su texto literal y pase.
- Implementar sólo el comportamiento faltante: complejidad y contraseña actual en el cambio forzado, texto y enlace del banner sin umbral adicional, `audit_log` en reintento y descarte, el texto literal de dos mensajes de US-11, y el criterio C10 del modal de rechazo.
- Que US-01 y US-23 reflejen en `docs/trazabilidad_us_tests.md` y `docs/cierre/MATRIZ_TRAZABILIDAD.md` el estado ya alineado del código, sin cambios de comportamiento.
- Mantener la trazabilidad recomputable: cada test nuevo se cita por nombre en `docs/trazabilidad_us_tests.md`.

**Non-Goals:**

- La cascada, los reintentos y la DLQ de la notificación de agente `dead`, y su ruta propia en el enrutador de n8n (Change 48). US-21 en sí entra por trazabilidad y tests (D-11).
- Cambiar D2: el baseline se sigue actualizando con el hash del evento. La divergencia con el criterio "hash actual" de US-11 queda registrada, no se implementa.
- Aplicar la regla de complejidad a `POST /users` (alta de admins). RN-100 la fija para el cambio forzado, y todo admin creado nace con `must_change_password = true`, así que su primera contraseña propia pasa por la regla.
- Endpoint de reintento masivo en el backend. El contrato vigente de `frontend-alerts` ya define el bulk como N llamadas individuales.
- Agregar `ruleset_version` a `restore_file` / `quarantine_file`. D66/RN-160 (2026-09-15) cerró esta divergencia: ese contador queda reservado a `update_config`, no se implementa.
- Exponer `baseline_absent` por ítem en `POST /actions/bulk-reject`. El bulk reject ya trata el no-op como éxito uniforme (RN-74, `actions/service.py:401-402`); revertir esa representación requeriría una decisión nueva que este change no abre. C10 se implementa sólo en el flujo individual (`RejectModal`, disparado desde `EventDetail`); la tabla de eventos y el bulk reject no invocan `RejectModal` hoy y no cambian.

## Decisions

### D-1 — La política de contraseña vive en `core/security.py` y se aplica en el router con 422 de `detail` string

Se agrega `password_policy_error(password: str) -> str | None` en `backend/app/core/security.py`, junto a `hash_password`. Devuelve `None` si la contraseña cumple, o el mensaje del primer requisito incumplido: largo (≥ 12) primero y complejidad después. `change_password` reemplaza el chequeo de `len` por esta función y conserva `HTTPException(422, detail=<string>)`.

- **Alternativa descartada: `field_validator` de Pydantic en `ChangePasswordRequest`.** Produce un 422 con `detail` como lista de errores, que `ForcePasswordChange` mostraría como `[object Object]`, y cambiaría la forma del error que el spec `backend-auth` ya fija para el largo.
- **Clases de carácter:** mayúscula = `str.isupper()`, minúscula = `str.islower()`, número = `str.isdecimal()`, evaluadas por carácter. El frontend usa las clases Unicode equivalentes (`\p{Lu}`, `\p{Ll}`, `\p{Nd}` con flag `u`). Así una contraseña en castellano con `Ñ` o `Á` cuenta como mayúscula en ambos lados. La paridad se fija con los mismos casos de prueba en backend y frontend.

### D-2 — `current_password` se exige también con scope `password_change_only`

`change_password` (`users/router.py:54-63`) deja de saltear la verificación de `current_password` cuando `scope == "password_change_only"`. El admin de seed conoce su contraseña actual: es la que usó para loguearse y obtener ese scope. El literal de US-27 ("El formulario de cambio pide: password actual...") y W20 no distinguen el flujo forzado del voluntario en este punto.

- **Alternativa descartada: mantener el salteo y sólo documentarlo.** Deja el criterio de US-27 sin cerrar — el formulario forzado seguiría sin el campo que la historia pide.
- **Compatibilidad:** el seed emite su password inicial por variable de entorno; el admin la conoce en el momento del primer login. No hay caso legítimo en el que el scope `password_change_only` exista sin que el admin haya podido loguearse con la password vigente.
- `ForcePasswordChange.tsx` agrega el campo "Contraseña actual" y lo envía siempre, sin condicionarlo al scope — el frontend no necesita distinguir el scope para este campo.

### D-3 — El endpoint del banner cuenta fallo terminal según D6/RN-102, sin umbral de `retry_count`

Nuevo `GET /alerts/failed/count` (admin), que responde `{"count": int}` con `delivered_at IS NULL AND failed_at IS NOT NULL` — la misma definición que `list_failed_alerts`. **No** se agrega un umbral `retry_count >= 3`: el appendix D6 (`docs/arquitectura_stack.md:2088-2091`, `docs/reglas_de_negocio.md:2138`), que prevalece sobre el literal original de US-29/RN-102, reemplazó la base del banner por esa condición sin umbral. Con n8n sin configurar, una alerta agotada queda con `retry_count = 0` y el criterio exige que igual cuente: un umbral la ocultaría. `AlertsBanner` hace polling cada 30 s a ese endpoint.

- **Por qué en el backend:** el estado de fallo terminal es parte de la máquina de estados de `alerts` (D6/RN-107), no una preferencia de presentación. Si el frontend filtrara, duplicaría esa lógica en la UI.
- **Alternativa descartada: filtrar del lado del cliente sobre `GET /alerts/failed`.** Transfiere la DLQ completa, sin paginar, cada 30 s para mostrar un número.
- **Alternativa descartada: parámetro en `GET /alerts`.** `list_alerts(status="failed")` no aplica `delivered_at IS NULL`, así que el conteo no coincidiría con la vista de fallidas, y se ensancharía un endpoint genérico por un único consumidor.
- **Precedente:** W11 (`docs/flujo_de_usuario.md:1100`) ya prescribe un endpoint de conteo para el banner. La ruta se ubica bajo `/alerts/failed` porque D6 unificó la DLQ en `alerts` y `GET /alerts/failed` ya es la vista de datos (`CHANGES.md:370`).
- La ruta `/failed/count` se declara antes de cualquier ruta con `/{alert_id}` para que no la capture un parámetro de path.

### D-4 — La query key del banner pasa a `['alerts', 'failed', 'count']`

`useRetryAlert` y `useDiscardAlert` ya invalidan `['alerts']` y `['alerts', 'failed']`. Con la key bajo ese prefijo, el banner se refresca apenas se reintenta o se descarta, sin esperar el próximo poll. No se toca `useAlerts.ts`.

### D-5 — `audit_log` en la misma transacción que la operación sobre la alerta

`retry_alert(alert_id, session, actor_id)` y `delete_alert(alert_id, session, actor_id)` agregan un `AuditLog(user_id=actor_id, action=..., target_type="alert", target_id=alert_id, detail=f"event_id={alert.event_id}")` a la sesión antes del `commit` que ya hacen: el reset de la DLQ en el reintento, el `DELETE` en el descarte. El router pasa `_admin.id`.

- **Acciones:** `alert_retry` y `alert_discard`, con la convención `<recurso>_<verbo>` ya en uso (`agent_config`, `agent_rescan`, `user_created`).
- **`detail` con `event_id`:** tras un descarte la fila de `alerts` desaparece, y `event_id` es el único vínculo auditable con el evento que originó la notificación.
- **Por qué no `write_audit_log`:** hace su propio `commit` y no completa `target_type` / `target_id`. Con un commit separado podría quedar un reintento sin registro, o un registro sin reintento.
- **Sólo operaciones exitosas:** un 404 o 409 lanza antes del commit y no deja fila.
- **Bulk:** N llamadas producen N filas. Es lo que pide el Done de CHANGES ("cada reintento deja una fila en `audit_log`"), y permite auditar cada alerta por separado.

### D-6 — Los textos de US-11 se alinean con el literal de la historia

El toast del 409 (compartido por approve y reject) pasa a "Este evento ya fue resuelto o reemplazado. Refrescando lista...". El aviso de archivo ausente pasa a "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline.", y conserva los botones Confirmar / Cancelar. No es una decisión nueva: el texto canónico existe y el spec `frontend-events` lo había reemplazado sin decisión que lo respalde. Sin este ajuste, un test sobre el texto actual no cierra el criterio (regla de `docs/trazabilidad_us_tests.md` §2).

### D-7 — US-12 se cierra con tests sobre los handlers reales, no sobre `JournalManager` aislado; `ruleset_version` queda excluido por D66

Los tests invocan `handle_restore_file` y `handle_quarantine_file` con un `JournalManager` real sobre `tmp_path`, y leen la entrada por `command_id` para verificar `state == "completed"` en el camino feliz, y `state == "failed"` con `error` no vacío en un fallo (sin baseline para restore; store o fuente inválida para quarantine). Los handlers no borran la entrada tras marcarla (a diferencia de `DecisionEngine`), así que el estado final es observable sin espías. El criterio de US-12 que pedía `ruleset_version` en los comandos de rechazo queda cerrado como superado por D66/RN-160 (2026-09-15, `docs/reglas_de_negocio.md:2123`): ese contador es exclusivo de `update_config`; no se agrega código, y la divergencia se cita con la decisión en la trazabilidad, no como huella abierta.

### D-8 — C10 del `RejectModal` se implementa con `baseline_status` expuesto en `GET /events/{event_id}`

El frontend no tiene hoy ninguna fuente para saber, antes de enviar el rechazo, si el baseline del path está `absent`. `EventDetailOut` (`events/router.py:70`, capability `backend-events-api`) agrega `baseline_status: "present" | "absent" | null`, resuelto con una consulta a `baseline_entries` por `(event.path, event.agent_id)` — `null` cuando el evento no tiene `path` (p. ej. `detection_gap`, D50/RN-144) o el path nunca fue baselineado. `RejectModal` recibe ese valor desde `EventDetail` y, cuando es `"absent"`, oculta el `fieldset` de "Restaurar" / "Poner en cuarentena" y muestra el texto literal de C10 en su lugar, conservando Confirmar / Cancelar; el `onConfirm` sigue enviando `action: "restore"` (valor sin efecto en el backend cuando el baseline está `absent`, ver `actions/service.py:309-339`) para no introducir una tercera forma de payload.

- **Por qué en `GET /events/{event_id}` y no en `GET /events` (listado):** `RejectModal` sólo se abre desde `EventDetail`, que ya consulta el detalle por id; la tabla y el bulk reject no lo invocan. Agregar el campo al listado ensancharía una respuesta paginada por un único consumidor de detalle.
- **Alternativa descartada: que el frontend infiera "ausente" de `hash_detected` vacío.** `hash_detected` vacío significa "archivo borrado en el evento" (comentario `EventDetail.tsx:205-211`), un dato del evento, no del baseline; un archivo puede estar borrado en el evento y el baseline seguir `present` (caso típico de "hash actual", ver D2), o viceversa. Usar esa señal para C10 mezclaría dos conceptos distintos.
- **Condición de carrera:** entre el fetch del detalle y el envío del rechazo, el baseline puede cambiar. `useEventActions` ya recibe `baseline_absent` en la respuesta de `POST /actions/reject`; si viene `true` sobre un evento cuyo modal mostraba las opciones (porque `baseline_status` todavía no reflejaba el cambio), el hook muestra un toast informativo ("El baseline ya no tiene archivo: el rechazo no ejecutó ninguna acción.") en lugar de asumir que la acción correctiva se ejecutó.
- **Bulk reject y tabla de eventos quedan fuera** (ver Non-Goals): ninguno de los dos invoca `RejectModal` hoy, y extender `BulkResultResponse` para exponer `baseline_absent` por ítem reabriría una decisión ya tomada (RN-74, `actions/service.py:401-402`) que este change no toca.

### D-9 — US-01 y US-23 se cierran como trazabilidad pura

Ninguna de las dos historias tiene divergencia de comportamiento pendiente en este change: la ruta `/change-password` de US-01 y la tabla `alerts` de US-05/US-29 ya están alineadas en `docs/historias_de_usuario.md` (editado por el equipo de documentación en paralelo a este change), y el código ya las implementa. Lo único pendiente es que `docs/trazabilidad_us_tests.md` y `docs/cierre/MATRIZ_TRAZABILIDAD.md` reflejen ese estado y, para US-23, citen evidencia de entrega real:

- **US-23 — evidencia SMTP/email:** `docs/cierre/evidencia/a4-vps-acceptance-20260915T153824Z/a4-12.6-webhook-email.txt` registra una entrega 2xx con `{"channel":"email","delivered":true}` a través del router n8n con Gmail SMTP configurado como canal de salida. Esa evidencia cubre el canal de email de n8n, **no** el fallback SMTP directo del backend (el segundo escalón de la cascada de `docs/reglas_de_negocio.md`, tras agotar n8n). Si el criterio de "SMTP real" de la matriz exige acreditar también ese fallback, se agrega una verificación separada con un servidor SMTP de captura (p. ej. Mailpit) en un `docker compose` aislado del laboratorio, forzando el agotamiento de n8n y confirmando la recepción del mensaje en el capturador; el resultado se documenta como evidencia nueva, no se reescribe la ya citada.
- **Sin cambios de código:** ambas historias sólo mueven filas de trazabilidad.

### D-10 — Orden de aplicación: este change antes que el Change 54

El Change 54 (`backend-privacy-hardening`) también modifica `backend/app/modules/alerts/router.py` y los specs `frontend-shell` y `frontend-events`, con requisitos distintos a los de este change. Para evitar un merge de specs que se pise y un conflicto de líneas en `alerts/router.py`, este change (55) se aplica y archiva primero; el Change 54 se aplica y archiva después, en serie. Ningún apply de 54 puede estar en curso sobre `backend/app/modules/alerts/` mientras este change lo modifica (ver tasks.md → Precondiciones).

## Risks / Trade-offs

- [Paridad de clases de carácter entre Python y la regex Unicode del navegador] → Mismos casos de prueba (ASCII, `Ñ`, dígitos) en ambos lados.
- [Colisión con el Change 54 en `alerts/router.py` y en los specs `frontend-shell` / `frontend-events`] → Applies y archives en serie (D-10). Los requisitos modificados son distintos, así que el merge de specs no se pisa.
- [Un `audit_log` que falla al insertar ahora aborta el reintento o el descarte] → Es el comportamiento buscado (RN-94 exige el registro). El 500 resultante es visible en la UI.
- [La consulta a `baseline_entries` en `GET /events/{event_id}` agrega un `SELECT` por request de detalle] → El índice único `(path, agent_id)` ya existe; costo despreciable frente al resto del endpoint (diff, hex dump).
- [Condición de carrera entre el `baseline_status` leído al abrir el modal y el estado real al confirmar] → Cubierta por el toast informativo sobre `baseline_absent` en la respuesta (D-8); no se bloquea el flujo, se informa después del hecho.
- [Tests de backend dependientes de Postgres del laboratorio] → Se corren con `TEST_DATABASE_URL` explícita. Sin base, la suite no se considera verde.

## Migration Plan

Sin migraciones de esquema: `audit_log`, `alerts` y `baseline_entries` ya tienen las columnas necesarias — `baseline_status` es una lectura nueva sobre una tabla existente. El despliegue es el normal de backend y frontend. Rollback: revertir el commit. El endpoint nuevo (`GET /alerts/failed/count`) no tiene consumidores fuera de `AlertsBanner`; el campo nuevo (`baseline_status`) no rompe consumidores existentes de `GET /events/{event_id}` (campo adicional, no removido).

## Resolved (2026-09-15)

Las siguientes preguntas quedaron abiertas en una versión anterior de este design y se resolvieron el 2026-09-15 con aprobación explícita del usuario antes de `/opsx:apply`:

1. **Umbral del banner vs D6/RN-107 — resuelto sin umbral.** Se descarta `retry_count >= 3`: el banner cuenta fallo terminal puro (`delivered_at IS NULL AND failed_at IS NOT NULL`), igual que `list_failed_alerts`. Ver D-3.
2. **Ruta de la vista de fallidas — resuelto a `/alerts/failed`.** No se registra un redirect desde `/notifications/failed`; la historia ya fue corregida para nombrar la ruta real.
3. **`ruleset_version` en los comandos de rechazo — resuelto por D66/RN-160 (2026-09-15).** Queda excluido; el criterio de US-12 se documenta como superado por esa decisión, no se implementa. Ver D-7 y Non-Goals.
4. **Contraseña actual en el cambio forzado — resuelto: se implementa.** `current_password` se exige también con scope `password_change_only`. Ver D-2.
5. **Criterio visual C10 de US-12 — resuelto: es un gap real, se implementa.** Una primera revisión sugirió que la rama había sido eliminada por el Change 38 y sustituida por el no-op server-side (RN-74); una segunda verificación mostró que RN-74 sólo cubre el no-op, no el requisito de UI de C10 (ocultar opciones y mostrar el texto literal antes de enviar), que seguía sin implementar porque el frontend no tenía acceso a `baseline_status`. Se implementa con `GET /events/{event_id}.baseline_status` (D-8).

Además, se incorporó al alcance original (que sólo cubría cinco historias) el cierre de US-01 y US-23 como ítems de trazabilidad pura (D-9), y el 2026-09-15 se incorporó US-21 como ítem de trazabilidad y tests (D-11).

### D-11. US-21 por trazabilidad y tests (2026-09-15)

La auditoría V10 marcó US-21 como parcial sobre el candidato `7a7ee50`. Los commits `7f62348` y `1226ed9` (2026-09-12) implementaron después `queue_size` persistido y visible, el webhook n8n por agente al pasar a `dead` y el banner de `queue_pressure` por encima del 80 %, con tests en `backend/tests/test_heartbeat_consumer.py` y `frontend/src/components/ui/AgentCard.test.tsx`. Quedaban sin prueba tres criterios cuyo comportamiento ya existía: `ruleset_version` en la vista, el realce de estados no-ok y el intervalo de heartbeat de 10 s. Este change agrega esos tests y actualiza la trazabilidad; no cambia código de producción.

Fuera de US-21 queda registrado para el Change 48: `_notify_agent_dead` envía directo a n8n con `send_n8n` (sin cascada, reintentos, fila en `alerts` ni DLQ), y el enrutador de n8n decide por `type === 'health_change' ? 1 : 0`, de modo que un payload `agent_dead` se procesa por la rama de alerta.

