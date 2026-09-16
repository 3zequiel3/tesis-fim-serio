## ADDED Requirements

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
