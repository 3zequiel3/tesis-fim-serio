## 1. FIX-01 — Semántica de `_try_cascade` en la cascada de notificaciones

- [x] 1.1 En `backend/app/modules/alerts/service.py`, función `_try_cascade`: agregar detección de si algún canal primario está configurado (`any_primary_configured = bool(settings.n8n_webhook_url or settings.smtp_host or settings.webhook_fallback_url)`).
- [x] 1.2 Modificar `_try_cascade` para que, después de ejecutar `log_only` (siempre, RN-54), retorne `(False, None)` si `any_primary_configured` es True, o `(True, AlertChannel.log_only)` si ningún canal primario está configurado (D23, RN-120).
- [x] 1.3 Actualizar el docstring de `_try_cascade` para reflejar la nueva semántica de retorno.

## 2. FIX-02 — Publicación Valkey post-commit en approve y reject

- [x] 2.1 En `backend/app/modules/actions/service.py`, función `_approve_single`: mover la llamada a `publish_baseline_update(db, valkey_client, event, new_version)` del paso 5 al paso 9 (después de `db.commit()` y `db.refresh(event)`).
- [x] 2.2 En `backend/app/modules/actions/service.py`, función `_reject_single`: mover las llamadas a `publish_restore_file` y `publish_quarantine_file` del paso 2 al paso 7 (después de `db.commit()` y `db.refresh(event)`).
- [x] 2.3 Verificar que el import de `publish_baseline_update` / `publish_restore_file` / `publish_quarantine_file` (que se hace dentro de la función) siga siendo correcto en la nueva posición.

## 3. FIX-03 — Re-consulta de pending cuando `mark_superseded` falla

- [x] 3.1 En `backend/app/modules/events/service.py`, función `ingest_event`: cuando `mark_superseded` retorna `False`, agregar re-consulta con `get_pending_event_for_path(session, path)`.
- [x] 3.2 Si la re-consulta encuentra un pending activo → retornar `None` (skip legítimo, log de warning sin cambios).
- [x] 3.3 Si la re-consulta retorna `None` (no hay pending) → continuar el flujo normal de inserción del nuevo evento con `parent_event_id = None` (D25, RN-121).

## 4. FIX-04 — Paginación SQL real en `list_events`

- [x] 4.1 En `backend/app/modules/events/router.py`, función `list_events`: agregar import de `func` desde `sqlalchemy`.
- [x] 4.2 Reemplazar `all_events = session.exec(q).all()` / `total = len(all_events)` / slice en Python por: `count_q = select(func.count()).select_from(q.subquery()); total = session.exec(count_q).one()`.
- [x] 4.3 Agregar `items_q = q.order_by(Event.created_at.desc()).offset((page - 1) * page_size).limit(page_size)` y `items = list(session.exec(items_q).all())`.

## 5. FIX-05 — Corrección de `compact_chain` de `.desc()` a `.asc()`

- [x] 5.1 En `backend/app/modules/events/service.py`, función `compact_chain`: cambiar `.order_by(Event.created_at.desc())` por `.order_by(Event.created_at.asc())` en la query de eventos superseded (línea ~100).

## 6. FIX-06, FIX-07, FIX-08 — Consumer: reordenar y agregar validaciones

- [x] 6.1 En `backend/app/modules/events/consumer.py`, función `_handle_message`: mover el bloque de dedup (paso 6 actual) ANTES del bloque de rate limit (paso 5 actual). El nuevo orden de pasos es: schema → agent → HMAC → clock_skew → event_id → dedup → rate_limit.
- [x] 6.2 Agregar validación de `event_id` no-vacío: después del check de clock_skew y antes del dedup, verificar que `event_id` sea una cadena no-vacía. Si `not event_id` → llamar `_reject(... RejectionReason.invalid_schema ...)` y retornar (FIX-07).
- [x] 6.3 En `backend/app/modules/events/consumer.py`, función `_parse_datetime`: asegurar que siempre retorna un datetime UTC-aware o None. Agregar lógica: si el parsed datetime tiene `tzinfo`, usar `astimezone(timezone.utc)`; si es naive, asignar `replace(tzinfo=timezone.utc)` (FIX-08).
- [x] 6.4 En `_handle_message`: separar el rechazo por `detected_at is None` (no parseable → `clock_skew`) del rechazo por fuera de rango. Agregar log diferenciado: `clock_skew.unparseable` vs `clock_skew.out_of_range` (FIX-08).
- [x] 6.5 Para re-entregas detectadas en dedup: verificar que el `_rate_limiter.check(agent_id)` NO se llame para el path de re-entrega (el return ya ocurre antes de llegar al step de rate limit).

## 7. FIX-09 — Reemplazar `datetime.utcnow()` por `datetime.now(timezone.utc)`

- [x] 7.1 En `backend/app/modules/events/service.py`: reemplazar `datetime.utcnow()` por `datetime.now(timezone.utc)` en `retention_task` (línea ~189). Verificar que `timezone` esté en el import.
- [x] 7.2 En `backend/app/modules/actions/service.py`: reemplazar las 3 ocurrencias de `datetime.utcnow()` en `_increment_ruleset_version` (línea 72) y `_upsert_baseline_entry` (líneas 110, 117). Verificar que `timezone` esté en el import.
- [x] 7.3 En `backend/app/modules/rules/service.py`: reemplazar las 2 ocurrencias de `datetime.utcnow()` en `_increment_ruleset_version` (línea 79) y `update_rule` (línea 217). Agregar `timezone` al import `from datetime import datetime, timezone`.

## 8. Tests de regresión

- [x] 8.1 Test para FIX-01: configurar N8N_WEBHOOK_URL con mock que siempre falla; verificar que tras 4 intentos `alerts.failed_at` está poblado, `delivered_at IS NULL`, y que `log_only` fue llamado en cada intento.
- [x] 8.2 Test para FIX-01 (no-primaries): con todos los canales primarios sin configurar (None), verificar que la alerta queda como `delivered` con `channel=log_only`.
- [x] 8.3 Test para FIX-02: en `_approve_single` mockear el publish de Valkey para capturar el momento de llamada; verificar que ocurre después de `db.commit()` (el evento tiene `status=approved` en DB antes del publish).
- [x] 8.4 Test para FIX-02: mismo patrón para `_reject_single` con `publish_restore_file`.
- [x] 8.5 Test para FIX-03: simular una carrera donde `mark_superseded` retorna False y no hay pending activo → verificar que se inserta un nuevo evento con `parent_event_id=None`.
- [x] 8.6 Test para FIX-03: simular una carrera donde `mark_superseded` retorna False y todavía hay un pending → verificar que `ingest_event` retorna `None`.
- [x] 8.7 Test para FIX-04: insertar 120 eventos, hacer `GET /events?page=2&page_size=50`; verificar `total=120`, `len(items)=50`, `page=2`.
- [x] 8.8 Test para FIX-05: insertar 11 eventos superseded para el mismo path; verificar que `compact_chain` elimina el más antiguo (menor `created_at`) y retiene los 10 más recientes.
- [x] 8.9 Test para FIX-06: enviar una re-entrega (event_id ya existente) seguida de un evento nuevo cuando el agent está al límite de rate (99 eventos); verificar que la re-entrega no incrementa el contador y el evento nuevo (evento 100) pasa el rate check.
- [x] 8.10 Test para FIX-07: enviar mensaje al consumer con `event_id = ""`; verificar `rejected_events_audit` con `reason=invalid_schema`.
- [x] 8.11 Test para FIX-08: enviar mensaje al consumer con `detected_at = "not-a-date"`; verificar `rejected_events_audit` con `reason=clock_skew`.
- [x] 8.12 Test para FIX-08: enviar mensaje con `detected_at` como naive datetime ISO8601 (sin `Z` ni offset) dentro del rango de 5 minutos; verificar que el evento se acepta (no lanza TypeError).
- [x] 8.13 Test para FIX-09: verificar que `datetime.utcnow()` no aparece en ningún módulo del backend (búsqueda de texto o import check).

## 9. Verificación final

- [ ] 9.1 Ejecutar la suite completa de tests (`pytest backend/tests/ -x -q`) y confirmar que los 257 tests previos siguen pasando junto con los nuevos (harness C33: TRUNCATE + RESTART IDENTITY CASCADE + reseed admin).
- [ ] 9.2 Revisar que no haya `DeprecationWarning` de `datetime.utcnow()` en los logs de tests.
