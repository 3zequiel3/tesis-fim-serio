# frontend-shell Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: Layout shell con MainLayout y AuthLayout

El sistema SHALL tener `frontend/src/components/layout/MainLayout.tsx` (con Sidebar + Navbar, para rutas autenticadas) y `frontend/src/components/layout/AuthLayout.tsx` (centrado, para login y change-password). `MainLayout` MUST incluir `SystemBanner` y `AlertsBanner` en la parte superior. `Sidebar` MUST incluir navegación a las secciones principales: Eventos, Reglas, Agentes, Dashboard, Alertas.

#### Scenario: Rutas autenticadas usan MainLayout
- **WHEN** el usuario navega a cualquier ruta protegida
- **THEN** se muestra el layout con Sidebar y Navbar visibles

#### Scenario: Rutas de auth usan AuthLayout
- **WHEN** el usuario navega a `/login` o `/change-password`
- **THEN** se muestra el layout centrado sin Sidebar ni Navbar

### Requirement: SystemBanner con polling de /health/components

El sistema SHALL tener `frontend/src/components/layout/SystemBanner.tsx` que hace polling a `GET /health/components` cada 10 segundos (RN-101). Si algún componente devuelve `"down"`, MUST mostrar un banner rojo visible en la parte superior del layout con un mensaje indicando degradación. Si todos están `"ok"` o `"degraded"`, no se muestra el banner rojo (solo se muestra para `"down"`).

#### Scenario: Componente down muestra banner rojo
- **WHEN** `GET /health/components` retorna algún componente con `"down"`
- **THEN** aparece un banner rojo en la parte superior con mensaje de alerta del sistema

#### Scenario: Todos los componentes ok — sin banner
- **WHEN** todos los componentes retornan `"ok"` o `"degraded"`
- **THEN** no se muestra el banner rojo (puede mostrarse amarillo por degraded según criterio de implementación)

#### Scenario: Polling actualiza el estado cada 10 segundos
- **WHEN** un componente pasa de `"ok"` a `"down"` entre polls
- **THEN** el banner aparece en el próximo ciclo de 10 segundos sin recargar la página

### Requirement: AlertsBanner con conteo de alertas fallidas

El sistema SHALL tener `frontend/src/components/layout/AlertsBanner.tsx` que consulta `GET /alerts/failed/count` cada 30 s para conocer cuántas alertas de la DLQ están en fallo terminal (`delivered_at IS NULL AND failed_at IS NOT NULL`, US-29, US-05, RN-102, D6) — **sin** umbral de `retry_count`: una alerta agotada con `retry_count = 0` (n8n sin configurar) cuenta igual que una con `retry_count = 3`. La query MUST usar la key `['alerts', 'failed', 'count']`, para que las invalidaciones de reintento y descarte la refresquen. Si `count > 0`, MUST mostrar un banner amarillo con el texto "Notificaciones pendientes: N alertas no pudieron ser enviadas" (en singular, "1 alerta no pudo ser enviada") y un enlace a la vista de alertas fallidas `/alerts/failed`. El banner MUST desaparecer automáticamente cuando el conteo vuelve a 0.

#### Scenario: DLQ con alertas agotadas muestra banner amarillo
- **WHEN** `GET /alerts/failed/count` retorna `count = 4`
- **THEN** aparece un banner amarillo con el texto "Notificaciones pendientes: 4 alertas no pudieron ser enviadas"

#### Scenario: Singular con una sola alerta
- **WHEN** `GET /alerts/failed/count` retorna `count = 1`
- **THEN** el banner dice "Notificaciones pendientes: 1 alerta no pudo ser enviada"

#### Scenario: Alerta con retry_count = 0 igual muestra el banner
- **WHEN** la DLQ sólo contiene una alerta en fallo terminal con `retry_count = 0` (n8n sin configurar) y `GET /alerts/failed/count` retorna `count = 1`
- **THEN** se muestra el banner amarillo

#### Scenario: DLQ vacía — sin banner amarillo
- **WHEN** `GET /alerts/failed/count` retorna `count = 0`
- **THEN** no se muestra el banner amarillo

#### Scenario: El enlace abre la vista de alertas fallidas
- **WHEN** el banner está visible
- **THEN** contiene un enlace con `href="/alerts/failed"`

#### Scenario: Banner desaparece tras resolver alertas
- **WHEN** todas las alertas fallidas son reintentadas exitosamente y el siguiente fetch retorna `count = 0`
- **THEN** el banner amarillo desaparece sin recargar la página

### Requirement: nginx.conf con headers de seguridad y SPA fallback

El sistema SHALL servir el build estático de Vite con nginx, con `try_files $uri /index.html` para SPA routing y con proxy de `/api/` y `/auth/refresh` hacia `backend:8000` idéntico en todos los modos. Todas las respuestas MUST incluir `Content-Security-Policy` (script-src self), `X-Frame-Options: DENY` y `X-Content-Type-Options: nosniff`. El `Dockerfile` del frontend MUST usar nginx para servir el build en producción y MUST exponer 80 y 443.

El modo de servicio MUST seleccionarse al arrancar el contenedor a partir de `CONSOLE_TLS_MODE` (D55/RN-149):
- `off`: escucha sólo en 80, MUST NOT emitir `Strict-Transport-Security`, y MUST registrar al arrancar una advertencia de que credenciales y tokens viajan en claro.
- `self_signed`: escucha en 443 con el certificado autofirmado que emite `certs-init`.
- `provided`: escucha en 443 con el certificado y la clave indicados por `CONSOLE_TLS_CERT_FILE` y `CONSOLE_TLS_KEY_FILE`, relativos a `CONSOLE_TLS_DIR` montado.

En los dos modos HTTPS, el puerto 80 MUST responder `301` hacia `https://` con el mismo host y URI, y las respuestas servidas por HTTPS MUST incluir `Strict-Transport-Security` con el valor del modo (D60/RN-154): `max-age=63072000; includeSubDomains` en `provided`, y `max-age=300` sin `includeSubDomains` en `self_signed`. Un valor de modo desconocido, o un certificado o clave ausente en un modo HTTPS, MUST terminar el contenedor con exit distinto de 0 y un mensaje que nombre el problema; nginx MUST NOT degradar en silencio a HTTP.

#### Scenario: SPA routing funciona en rutas anidadas
- **WHEN** el usuario navega directamente a `/events` en el browser
- **THEN** nginx sirve `index.html` y React Router maneja la ruta

#### Scenario: Headers de seguridad presentes en respuestas
- **WHEN** se hace cualquier request al frontend en cualquiera de los tres modos
- **THEN** los headers `X-Frame-Options`, `X-Content-Type-Options` y `Content-Security-Policy` están presentes en la respuesta

#### Scenario: Modo HTTP sin HSTS
- **WHEN** `CONSOLE_TLS_MODE=off` y se hace `GET http://<host>/`
- **THEN** la respuesta es 200 y no incluye `Strict-Transport-Security`

#### Scenario: Modo HTTPS con redirección y HSTS
- **WHEN** `CONSOLE_TLS_MODE=self_signed` y se hace `GET http://<host>/events?x=1`
- **THEN** la respuesta es 301 con `Location: https://<host>/events?x=1`
- **AND** `GET https://<host>/` incluye `Strict-Transport-Security`

#### Scenario: Certificado ausente en modo HTTPS
- **WHEN** `CONSOLE_TLS_MODE=provided` y el archivo indicado por `CONSOLE_TLS_CERT_FILE` no existe en el montaje
- **THEN** el contenedor termina con exit distinto de 0 y el log nombra el archivo faltante

#### Scenario: Refresh de sesión operativo en ambos esquemas
- **WHEN** el operador inicia sesión por la consola en modo `off` y, en otro despliegue, en modo `self_signed`, y el access token vence
- **THEN** en ambos casos el navegador conserva la cookie de refresh y `POST /auth/refresh` responde 200

### Requirement: Access log de nginx sin credenciales del stream SSE (D64, RN-158)

La configuración nginx de la consola (`frontend/nginx/`) SHALL declarar, en contexto `http` y compartido por los modos `console-http.conf` y `console-https.conf`, un `map` que derive de `$request` una variable con el valor de los parámetros de query `ticket` y `token` reemplazado por `[REDACTED]`, y un `log_format` que use esa variable en lugar de `$request`, conservando los demás campos del formato `combined`. Todos los bloques `server` de la consola MUST usar ese formato en su `access_log`. Ninguna línea del access log de nginx MUST contener el valor de un ticket SSE. La configuración resultante MUST pasar `nginx -t` en los tres modos de `CONSOLE_TLS_MODE`.

#### Scenario: Ticket redactado en el access log de nginx
- **WHEN** un cliente hace `GET /api/alerts/stream?ticket=abc123&last_event_id=9` contra la consola
- **THEN** la línea del access log contiene `/api/alerts/stream?ticket=[REDACTED]&last_event_id=9`
- **AND** no contiene la string `abc123`

#### Scenario: Requests sin credenciales se registran sin cambios
- **WHEN** un cliente hace `GET /api/events?page=2`
- **THEN** la línea del access log contiene `/api/events?page=2` sin modificaciones

#### Scenario: Configuración válida en todos los modos
- **WHEN** el contenedor de la consola arranca con `CONSOLE_TLS_MODE` en `off`, `self_signed` o `provided`
- **THEN** `nginx -t` finaliza con éxito

