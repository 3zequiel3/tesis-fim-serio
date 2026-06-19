## 1. Dependencias y configuración

- [x] 1.1 Agregar `httpx[asyncio]` y `aiosmtplib` a `backend/requirements.txt` con versiones fijadas
- [x] 1.2 Agregar variables de notificación opcionales a `backend/app/core/config.py`: `N8N_WEBHOOK_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`, `WEBHOOK_FALLBACK_URL`

## 2. Módulo alerts — notifier

- [x] 2.1 Crear `backend/app/modules/alerts/notifier.py` con función `send_n8n(payload, url, timeout)` async usando httpx
- [x] 2.2 Agregar `send_smtp(payload, cfg)` async en `notifier.py` usando aiosmtplib
- [x] 2.3 Agregar `send_webhook_fallback(payload, url, timeout)` async en `notifier.py` usando httpx
- [x] 2.4 Agregar `send_log_only(payload)` que emite log crítico estructurado y retorna siempre éxito

## 3. Módulo alerts — service

- [x] 3.1 Crear `backend/app/modules/alerts/service.py` con `_determine_severity(event, session)` — lookup fnmatch en rules, retorna RuleSeverity max o `low`
- [x] 3.2 Agregar `notify_if_applicable(event)` en `service.py`: skip si severity < high o status == superseded; crear fila Alert en DB; llamar `notify_event(alert, event)`
- [x] 3.3 Implementar `notify_event(alert, event)` con retry loop `RETRY_DELAYS = [5, 30, 120]` y cascada de canales; actualizar `alerts` tras cada intento (delivered_at, failed_at, channel, retry_count)
- [x] 3.4 Agregar `list_failed_alerts(session)`, `retry_alert(alert_id, session)`, `delete_alert(alert_id, session)` en `service.py`

## 4. Módulo alerts — router

- [x] 4.1 Crear `backend/app/modules/alerts/router.py` con `GET /alerts/failed` — requiere JWT admin, retorna `{"items": [...], "total": int}`
- [x] 4.2 Agregar `POST /alerts/{id}/retry` en el router — resetea failed_at/last_error/retry_count y re-llama `notify_event`; 409 si ya entregada, 404 si no existe
- [x] 4.3 Agregar `DELETE /alerts/{id}` en el router — 204 si ok, 404 si no existe
- [x] 4.4 Registrar `alerts_router` en `backend/app/main.py`

## 5. Hook post-ingesta en el event consumer

- [x] 5.1 Modificar `backend/app/modules/events/consumer.py`: después del XACK en el happy path, agregar `asyncio.create_task(notify_if_applicable(event))` si `event is not None`

## 6. Endpoint GET /health/components

- [x] 6.1 Crear `backend/app/core/health.py` con `_last_state: dict` en memoria y `check_components(session, valkey_client, settings)` async que verifica postgres (SELECT 1), valkey (PING), n8n (GET/HEAD), agents (query DB)
- [x] 6.2 Implementar detección de cambio de estado en `health.py`: comparar resultado con `_last_state` y disparar `asyncio.create_task(send_n8n(change_payload, ...))` si hay diferencia
- [x] 6.3 Agregar endpoint `GET /health/components` en `backend/app/main.py` (sin auth JWT, llama `check_components`)

## 7. Tests

- [x] 7.1 Crear `backend/tests/test_notifications.py` con tests unitarios (mock httpx/aiosmtplib): severity determination, notify skip (low/medium/superseded), retry loop 3x, cascada canales, log_only siempre exitoso
- [x] 7.2 Agregar tests de endpoints en `test_notifications.py`: `GET /alerts/failed`, `POST /alerts/{id}/retry` (casos 200/409/404), `DELETE /alerts/{id}` (casos 204/404)
- [x] 7.3 Agregar tests de `GET /health/components` en `test_notifications.py`: todos ok, valkey down, n8n degraded, detección de cambio de estado
