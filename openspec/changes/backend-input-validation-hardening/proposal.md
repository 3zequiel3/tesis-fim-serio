## Why

Las revisiones del 2026-11-11 (estática, automática y E2E en navegador real sobre una pila aislada), hechas para la presentación y demo técnica del proyecto, encontraron que el backend acepta entradas del operador que nunca deberían persistirse y que el rate limit del login permite bloquear al `admin` desde cualquier origen con seis pedidos. Verificado contra `devel` `30efcaf`:

- `validate_pattern` (`backend/app/modules/rules/service.py:109`) sólo exige un glob no vacío y compilable por `fnmatch.translate`, que casi nunca falla: se aceptan `relative/path`, `/etc/[`, `../../etc/passwd`, patrones de 5.000 caracteres y saltos de línea (D7 de la revisión).
- `AgentConfigRequest.watch_paths` (`backend/app/modules/agents/models.py:154`) acepta rutas relativas, con `..`, con caracteres de control y la lista vacía, que deja al agente sin vigilar nada (D12).
- `path_prefix` de `GET /events` usa `Event.path.startswith(path_prefix)` sin `autoescape` (`backend/app/modules/events/router.py:169`): `%` devuelve todos los eventos (D9).
- `check_login_rate_limit` (`backend/app/core/rate_limit.py:37-53`) incrementa antes de verificar y cuenta también los logins exitosos; la clave usa `request.client.host` (`backend/app/modules/auth/router.py:99`), que detrás del `nginx` del frontend es la IP de ese contenedor porque uvicorn sólo confía en `X-Forwarded-For` desde `127.0.0.1`. Resultado: seis pedidos de cualquiera bloquean el usuario para todos durante 15 minutos (D5). El README ya promete «5 intentos fallidos».
- `POST /users/change-password` acepta como nueva la contraseña actual —el cambio forzado del seed se completa repitiendo la contraseña expuesta en el `.env`— y responde en inglés (`"Incorrect current password"`, `password_policy_error`).

La memoria de la tesis (Capítulo 5) sigue atada a `v5.1-tesis`; esta change es para la demo y no altera la evaluación.

## What Changes

- **Validación de rutas** en un módulo puro nuevo, `backend/app/core/path_validation.py`, usado por reglas y por la configuración de agentes antes de cualquier escritura, incremento de `ruleset_version` o publicación de comando (D91/RN-185):
  - `pattern` de regla (descontado `!`): absoluto, sin segmento `..`, sin caracteres de control, ≤ 1.024 caracteres, todo `[` cerrado.
  - `watch_paths`: mismas reglas de ruta; entre 1 y 64 entradas; sin duplicados (sin la barra final).
  - **BREAKING** (contrato de API): un `pattern` o `watch_paths` que hoy se acepta pasa a responder `422`. Las filas existentes no se revalidan.
- **`path_prefix` literal**: `%`, `_` y `\` se escapan (D91/RN-185).
- **Rate limit del login sobre intentos fallidos** (D92/RN-186): un login exitoso no incrementa y borra el contador; el bloqueo se evalúa antes de verificar la contraseña; `Retry-After` igual al TTL restante; IP real del cliente resuelta desde `X-Forwarded-For` sólo si el par TCP está en `TRUSTED_PROXY_CIDRS` (setting nuevo, default loopback; los compose lo fijan a los rangos privados de Docker).
- **Cambio de contraseña** (D89/RN-183): rechaza `new_password` igual a la actual con `password_reuse`; mensajes en español; la revocación total de la sesión se conserva (el frontend la consume en la Change 72).
- **Contrato de error** (D90/RN-184): todo error conserva `{"detail": ...}`; los errores nuevos o tocados usan `detail = {code, message}` con `message` en español. Los códigos existentes (`absent_confirmation_required`, `pending_events_exist` + `count`, `release_in_progress`) no cambian.
- **BREAKING** (texto): los `detail` string en inglés de login, cambio de contraseña y reglas pasan a objeto `{code, message}` en español. El único consumidor es el frontend, que se adapta en la Change 72 (`frontend-ux-redesign`).
- README: el aviso del rate limit refleja el mensaje en español y la semántica «fallidos».

## Capabilities

### New Capabilities

Ninguna. Todo cae en capacidades existentes.

### Modified Capabilities

- `backend-rules`: el requisito «Validación de pattern, severity y action» incorpora las reglas de ruta, el glob bien formado y los códigos de error.
- `backend-agent-management`: requisito nuevo de validación de `watch_paths` en `POST /agents/{id}/config`.
- `backend-events-api`: requisito nuevo de `path_prefix` literal.
- `backend-auth`: los requisitos «POST /auth/login» y «POST /users/change-password» cambian (contador de fallidos, IP real, reutilización, mensajes); requisitos nuevos para la resolución de la IP del cliente y el contrato del cuerpo de error.

## Impact

- **Código**: `backend/app/core/path_validation.py` (nuevo), `backend/app/core/client_ip.py` (nuevo), `backend/app/core/rate_limit.py`, `backend/app/core/security.py` (`password_policy_error`), `backend/app/core/config.py` (`trusted_proxy_cidrs`), `backend/app/modules/rules/service.py` y `router.py`, `backend/app/modules/agents/service.py` y `router.py`, `backend/app/modules/events/router.py`, `backend/app/modules/auth/router.py`, `backend/app/modules/users/router.py`.
- **Despliegue**: `docker-compose.yml`, `docker-compose.tls.yml` y los compose de laboratorio fijan `TRUSTED_PROXY_CIDRS`; `.env.example` lo documenta.
- **Tests**: nuevos por cada defecto; se ajustan los tests que asertan los `detail` en inglés o crean reglas relativas vía API. Línea base: 1.106 tests (1.102 pasan, 4 se omiten).
- **Docs**: README (aviso del rate limit).
- **Decisiones**: D89/RN-183, D90/RN-184, D91/RN-185, D92/RN-186. Refina RN-08, RN-58 y W5/RN-88; preserva D36/RN-130, RN-100 y RN-29.
- **DAG**: sin dependencias pendientes; la Change 72 depende de ésta.
