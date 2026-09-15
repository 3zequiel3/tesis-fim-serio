## ADDED Requirements

### Requirement: Redacción de credenciales en query strings de los logs (D64, RN-158, RN-89)

El pipeline de logging SHALL incluir un processor `redact_query_credentials`, ubicado después de `sanitize_secrets` tanto en la cadena de structlog como en el `foreign_pre_chain` de los loggers stdlib (incluido `uvicorn.access`), que reemplace por `[REDACTED]` el valor de los parámetros de query `ticket`, `token` y `access_token` (match case-insensitive del nombre) en todo valor string del `event_dict`, incluido el mensaje `event` renderizado desde registros stdlib, recorriendo dicts y listas anidados con la misma profundidad máxima que `sanitize_secrets`. El processor MUST preservar el nombre del parámetro y el resto de la línea, y MUST NOT alterar strings que no contengan esos parámetros. Ninguna línea de log emitida por el backend MUST contener el valor de un ticket SSE.

#### Scenario: Access log de uvicorn con ticket redactado
- **WHEN** uvicorn registra la línea de acceso de `GET /alerts/stream?ticket=abc123&last_event_id=9`
- **THEN** la línea de log JSON contiene `ticket=[REDACTED]&last_event_id=9`
- **AND** no contiene la string `abc123` en ninguna parte

#### Scenario: Token residual en query redactado
- **WHEN** se registra una request a `/alerts/stream?token=eyJhbGciOi.payload.sig`
- **THEN** la línea de log contiene `token=[REDACTED]` y no contiene `eyJhbGciOi`

#### Scenario: String anidado con ticket redactado
- **WHEN** el código ejecuta `log.info("sse.request", ctx={"url": "/alerts/stream?Ticket=abc123"})`
- **THEN** la línea de log contiene `"url": "/alerts/stream?Ticket=[REDACTED]"`

#### Scenario: Strings sin credenciales quedan intactos
- **WHEN** el código ejecuta `log.info("x", url="/events?page=2&size=50")`
- **THEN** la línea de log contiene `"url": "/events?page=2&size=50"` sin modificaciones
