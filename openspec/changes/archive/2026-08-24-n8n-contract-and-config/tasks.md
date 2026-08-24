## 1. Configuración (`Settings`)

- [x] 1.1 Agregar `n8n_health_url: str = ""` a `Settings` en `backend/app/core/config.py`, junto a `n8n_webhook_url`. No derivarlo del webhook (D-3 del design).
- [x] 1.2 Agregar `smtp_starttls: bool = True` y `smtp_ssl: bool = False` a `Settings`.
- [x] 1.3 Agregar test en `backend/tests/` que verifique los defaults: `n8n_health_url == ""` con `N8N_WEBHOOK_URL` seteado, `smtp_starttls is True`, `smtp_ssl is False`.

## 2. Contrato del payload

- [x] 2.1 Definir el módulo del contrato con la constante `SCHEMA_VERSION = 1` y la lista canónica de campos, para que el test de contrato y `_build_payload` lean de una sola fuente.
- [x] 2.2 Ampliar `_build_payload` en `backend/app/modules/alerts/service.py` con los campos de RN-53 leídos del `Event`: `status`, `action_taken`, `action_failed`, `is_symlink`, `process_pid`, `process_uid`, `process_exe`, `received_at`.
- [x] 2.3 Agregar al payload el sobre plano: `schema_version`, `notification_id` (uuid4) y `type="alert"`, como claves de nivel superior. NO anidar bajo `data`.
- [x] 2.4 Verificar que `notification_id` se genera una sola vez por notificación y se reutiliza en todos los reintentos del bucle de `notify_event`.
- [x] 2.5 Test: el payload de una alerta contiene los 18 campos del contrato, con `path` presente y `file_path` ausente.
- [x] 2.6 Test: `process_pid`/`process_uid`/`process_exe` en `None` se emiten como claves presentes con valor `null`, no se omiten.
- [x] 2.7 Test: dos payloads de alertas distintas tienen `notification_id` distintos; los reintentos de una misma notificación comparten el valor.

## 3. Test de contrato workflows ↔ payload

- [x] 3.1 Escribir el helper que carga `n8n/workflows/*.json` y extrae por regex toda referencia `$json.body.<campo>`, devolviendo el conjunto de campos con el archivo de origen de cada uno.
- [x] 3.2 Test principal: cada campo extraído existe en el payload que produce `_build_payload`. El mensaje de fallo nombra el campo y el archivo de workflow.
- [x] 3.3 **Caso negativo obligatorio**: si la extracción devuelve el conjunto vacío, el test falla indicando que el fixture no produjo referencias. Sin esto el test pasa vacuamente al vaciarse el fixture.
- [x] 3.4 Verificar en verde y en rojo: agregar temporalmente `$json.body.campo_inexistente` a un workflow, confirmar que el test falla, y revertir.

## 4. Health check con URL propia

- [x] 4.1 Cambiar `_check_n8n` en `backend/app/core/health.py` para que reciba y use `settings.n8n_health_url`.
- [x] 4.2 Eliminar el fallback a `GET` sobre la URL del webhook y la nota del docstring que lo difería; el check ahora usa un endpoint de salud real.
- [x] 4.3 `n8n_health_url` vacío → `degraded`, igual que antes con el webhook vacío.
- [x] 4.4 Test: con `n8n_webhook_url` y `n8n_health_url` distintas y ambas configuradas, el check emite exactamente un request a `n8n_health_url` y **ninguno** a `n8n_webhook_url`.
- [x] 4.5 Adoptar el sobre plano en el payload de `health_change` (`schema_version`, `notification_id`, `type="health_change"`), conservando `event` por compatibilidad.
- [x] 4.6 Test: el webhook de cambio de estado incluye `type="health_change"`.

## 5. TLS de SMTP

- [x] 5.1 Cambiar `send_smtp` en `backend/app/modules/alerts/notifier.py` para que respete `smtp_starttls` / `smtp_ssl` en lugar de forzar `start_tls=True`.
- [x] 5.2 Registrar error de configuración si ambos flags son `true`.
- [x] 5.3 Tests de los cuatro casos: SMTPS implícito, STARTTLS (default), sin cifrado, y la combinación inválida.
- [x] 5.4 Verificar que el payload que viaja por `smtp_fallback` es el mismo contrato ampliado, no una versión reducida.

## 6. Compose y `.env.example`

- [x] 6.1 Eliminar el default de `docker-compose.yml:138`: `N8N_WEBHOOK_URL: ${N8N_WEBHOOK_URL}` sin `:-http://n8n:5678/healthz`.
- [x] 6.2 Agregar `N8N_HEALTH_URL`, `SMTP_STARTTLS` y `SMTP_SSL` al servicio `backend`, todas sin default.
- [x] 6.3 Documentar las once variables de notificación en `.env.example`, cada una con un comentario que diga qué canal habilita y qué pasa si queda vacía.
- [x] 6.4 En el comentario de `N8N_HEALTH_URL`, advertir explícitamente que no debe apuntar a un webhook productivo.
- [x] 6.5 Verificar que `docker compose config` con un `.env` derivado de `.env.example` no emite warnings de variables faltantes.
- [x] 6.6 Verificar que un stack levantado sin configurar notificaciones reporta `{"n8n": "degraded"}` en `GET /health/components`. **Verificado por tests, NO contra el stack vivo**: `test_health_n8n_degraded_when_not_configured` (nivel `check_components`) y `test_n8n_degraded_when_not_configured` (nivel `_check_n8n`) cubren el comportamiento. No se reinició el backend en ejecución —3 días de uptime, agente conectado, dataset de la tesis— porque esa es una decisión de despliegue del autor, no del apply. Confirmar contra el stack real en el próximo redeploy.

## 7. Cierre

- [x] 7.1 Correr la suite completa del backend y confirmar que no hay regresiones en los tests de cascada y DLQ (la semántica de D23/RN-120 no cambia).
- [x] 7.2 Confirmar el criterio Done de CHANGES.md § Change 46, punto por punto.
- [x] 7.3 Registrar en el proposal la nota de despliegue sobre el cambio de estado por defecto del dashboard, para que se tenga en cuenta antes de sacar capturas nuevas del Cap. 5.
