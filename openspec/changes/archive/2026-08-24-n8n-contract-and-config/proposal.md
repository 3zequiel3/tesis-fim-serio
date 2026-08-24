## Why

El backend **afirma haber entregado notificaciones que nunca salieron**, y el payload que emite incumple RN-53. Ambos defectos tienen la misma causa raíz a nivel de spec: `backend-notifications` define retry, cascada y DLQ, pero **no define el payload**, así que el contrato con n8n pudo divergir sin romper ninguna aserción.

Dos mecanismos concretos:

1. `docker-compose.yml:138` apunta `N8N_WEBHOOK_URL` a `${N8N_WEBHOOK_URL:-http://n8n:5678/healthz}`. Ese endpoint responde `200` a cualquier `POST`, así que `send_n8n` retorna `True` y la alerta se marca `delivered` con `channel="n8n"` sin que nadie reciba nada. Es el camino que produjo miles de filas falsamente entregadas con el contenedor de n8n apagado.
2. `_build_payload` emite 7 campos y omite la **acción tomada**, el **contexto de proceso** (`process_pid`, `process_uid`, `process_exe`) y `received_at`. El contexto de proceso es el dato de mayor valor forense de un FIM y hoy nunca sale del sistema.

El hallazgo que abarata la corrección: **`Event` ya persiste todos los campos faltantes**. Ampliar el payload es leer columnas existentes — cero cambios en el agente, cero migración de datos.

## What Changes

- **Payload completo según RN-53, con sobre plano (D40/RN-134).** `schema_version`, `notification_id` y `type` son **hermanos** de los campos de datos, nunca anidados bajo `data`. La forma anidada se descarta por evidencia: `scripts/receptor_webhook.py` lee `alert_id`/`event_id`/`severity`/`path` al tope del objeto y los tres workflows leen `$json.body.<campo>`.
- **`notification_id`** (uuid v4) estable a lo largo de toda la escalera de reintentos de una misma notificación. Es la clave de deduplicación que consume D41/RN-135 en el change 47.
- **`type`** discrimina `"alert"` de `"health_change"` — las dos formas comparten hoy una única URL de webhook y n8n no puede distinguirlas.
- **Test de contrato workflows ↔ payload**: extrae por expresión regular toda referencia `$json.body.X` de `n8n/workflows/*.json` y afirma que `X` existe en el payload emitido. Con caso negativo obligatorio.
- **BREAKING (configuración)**: se elimina el default `/healthz` de `docker-compose.yml:138`. Sin `N8N_WEBHOOK_URL` explícito el canal queda **no configurado**, no falsamente sano.
- **`n8n_health_url`** separada del webhook. `_check_n8n` deja de emitir requests contra la URL del webhook — hoy su fallback a `GET` puede disparar el workflow, cosa que el propio docstring del código admite y difiere.
- **`smtp_starttls` / `smtp_ssl`** en `Settings`. `notifier.py:70` fuerza `start_tls=True` incondicional: un relay en 465 (SMTPS implícito) o uno interno sin STARTTLS falla siempre.
- Las variables de notificación se declaran en `.env.example`.

**Fuera de alcance**: workflows de n8n, provisioning y compose del servicio `n8n` (change 47); durabilidad de la escalera, `retry_count` acumulativo, `last_error` por canal, `POST /alerts/test`, RN-92 per-agent (change 48). **No se altera** la semántica de D23/RN-120.

## Capabilities

### New Capabilities
- `notification-payload-contract`: la forma canónica del payload de notificación (sobre plano, campos de RN-53, `path` como nombre canónico) y el test de contrato que verifica que los workflows de n8n sólo lean campos que el backend efectivamente emite.

### Modified Capabilities
- `backend-notifications`: adopta el contrato de payload de D40/RN-134 en `_build_payload` (hoy la spec no dice nada del payload — esa omisión es la causa raíz de la divergencia) y admite configuración explícita de TLS para SMTP.
- `backend-health`: el check de n8n usa `n8n_health_url` en lugar de `N8N_WEBHOOK_URL`. La spec vigente prescribe textualmente `GET/HEAD {N8N_WEBHOOK_URL}`, así que el defecto está en el requisito, no sólo en el código.
- `backend-core`: `Settings` incorpora `n8n_health_url`, `smtp_starttls` y `smtp_ssl`.
- `infra-compose`: `N8N_WEBHOOK_URL` deja de tener default; las variables de notificación se declaran en `.env.example`.

## Impact

**Código**: `backend/app/modules/alerts/service.py` (`_build_payload`, propagación de `notification_id`), `backend/app/modules/alerts/notifier.py` (`send_smtp`), `backend/app/core/health.py` (`_check_n8n`, payload de `health_change`), `backend/app/core/config.py` (`Settings`).

**Configuración**: `docker-compose.yml` (servicio `backend`), `.env.example`.

**Tests**: suite nueva de contrato en `backend/tests/`, que lee `n8n/workflows/*.json` como fixture.

**Sin impacto**: agente FIM (ningún cambio), esquema de base de datos (ninguna migración), API pública (ningún endpoint cambia forma), frontend.

**Nota de despliegue**: tras este change, un deploy sin `N8N_WEBHOOK_URL` reportará `n8n: degraded` en `GET /health/components` y el frontend mostrará el banner de RN-101. Es el comportamiento correcto — el canal efectivamente no está configurado — pero cambia el estado por defecto del dashboard respecto de lo que muestran las capturas previas.

**Reglas cubiertas**: RN-52, RN-53, RN-86 (parcial — el resto en el change 48), RN-87, RN-101. **Decisiones aplicadas**: D40/RN-134, D43/RN-137, D41/RN-135 (sólo el campo `notification_id`; su consumo es del change 47). D23/RN-120 se respeta sin cambios.
