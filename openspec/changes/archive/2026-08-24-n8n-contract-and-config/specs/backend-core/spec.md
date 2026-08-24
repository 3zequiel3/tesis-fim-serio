## MODIFIED Requirements

### Requirement: Configuración tipada vía pydantic-settings

El sistema SHALL exponer un objeto `settings: Settings` en `app/core/config.py` que herede de `pydantic_settings.BaseSettings`. La clase SHALL leer variables de entorno y opcionalmente un archivo `.env`. Las variables `DATABASE_URL` y `VALKEY_URL` SHALL ser obligatorias (sin default). Las variables `JWT_SECRET_CURRENT`, `JWT_SECRET_PREVIOUS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `CA_CERT_PATH`, `CA_KEY_PATH` SHALL existir como atributos del modelo, pueden tener default vacío en este change y serán requeridas por los changes que las consumen (04, 06). El modelo SHALL configurarse con `extra="ignore"` para tolerar variables del compose que el backend no usa.

`Settings` SHALL exponer además las siguientes variables del dominio de notificaciones:

| Atributo | Tipo | Default | Propósito |
|---|---|---|---|
| `n8n_webhook_url` | `str` | `""` | canal principal de notificación |
| `n8n_health_url` | `str` | `""` | endpoint de salud de n8n (D43/RN-137) — **distinto** del webhook |
| `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `smtp_to` | — | — | canal `smtp_fallback` |
| `smtp_starttls` | `bool` | `True` | usar `STARTTLS` |
| `smtp_ssl` | `bool` | `False` | usar TLS implícito (SMTPS) |
| `webhook_fallback_url` | `str` | `""` | canal `webhook_fallback` |

`n8n_health_url` SHALL ser un atributo independiente y SHALL NO derivarse automáticamente de `n8n_webhook_url`: la separación es precisamente el objeto de D43/RN-137.

#### Scenario: DATABASE_URL ausente al arrancar
- **WHEN** se intenta importar `app.core.config` sin `DATABASE_URL` en el environment
- **THEN** se lanza `pydantic.ValidationError`
- **AND** el mensaje menciona el campo `DATABASE_URL`

#### Scenario: Variables extra son ignoradas
- **WHEN** el environment incluye `DB_PASSWORD=foo` (variable de otro servicio)
- **AND** se importa `app.core.config`
- **THEN** la importación termina sin error
- **AND** el objeto `settings` no tiene atributo `db_password`

#### Scenario: Variables de notificación con default vacío
- **WHEN** se importa `app.core.config` sin ninguna variable de notificación en el environment
- **THEN** `settings.n8n_webhook_url` y `settings.n8n_health_url` son cadena vacía
- **AND** la importación no falla

#### Scenario: `n8n_health_url` no se deriva del webhook
- **WHEN** `N8N_WEBHOOK_URL` está configurado y `N8N_HEALTH_URL` no
- **THEN** `settings.n8n_health_url` es cadena vacía
- **AND** no toma el valor de `settings.n8n_webhook_url`

#### Scenario: Defaults de TLS para SMTP
- **WHEN** se importa `app.core.config` sin `SMTP_STARTTLS` ni `SMTP_SSL`
- **THEN** `settings.smtp_starttls is True` y `settings.smtp_ssl is False`
