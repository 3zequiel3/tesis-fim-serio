## ADDED Requirements

### Requirement: `N8N_WEBHOOK_URL` sin valor por defecto (D43/RN-137)

El `docker-compose.yml` SHALL pasar `N8N_WEBHOOK_URL` al servicio `backend` **sin default**. SHALL NO usarse la forma `${N8N_WEBHOOK_URL:-<cualquier-valor>}`.

El default vigente hasta este change (`http://n8n:5678/healthz`) apunta el canal principal de notificación a un endpoint de salud que responde `200` a cualquier `POST`. Como consecuencia, `send_n8n` retorna `True` y la alerta se marca `delivered` con `channel="n8n"` sin que ningún receptor haya procesado nada. Un despliegue sin configuración explícita SHALL reportar el canal como **no configurado**, no como sano.

La misma regla SHALL aplicarse a `N8N_HEALTH_URL`, `SMTP_*` y `WEBHOOK_FALLBACK_URL`: ninguna variable de notificación SHALL tener un default que la haga aparentar estar configurada.

#### Scenario: Compose sin N8N_WEBHOOK_URL deja el canal no configurado
- **WHEN** se ejecuta `docker compose config` con un `.env` que no define `N8N_WEBHOOK_URL`
- **THEN** el servicio `backend` recibe `N8N_WEBHOOK_URL` vacío
- **AND** el valor renderizado no contiene `healthz`

#### Scenario: El health check reporta degraded en un deploy limpio
- **WHEN** se levanta el stack sin configurar ninguna variable de notificación
- **AND** se consulta `GET /health/components`
- **THEN** la respuesta contiene `{"n8n": "degraded"}`
- **AND** no contiene `{"n8n": "ok"}`

#### Scenario: Ninguna variable de notificación tiene default en el compose
- **WHEN** se inspecciona el `docker-compose.yml`
- **THEN** ninguna de `N8N_WEBHOOK_URL`, `N8N_HEALTH_URL`, `SMTP_HOST`, `WEBHOOK_FALLBACK_URL` usa la sintaxis `:-` de valor por defecto

## MODIFIED Requirements

### Requirement: Variables de entorno documentadas en `.env.example`

El sistema SHALL incluir un `.env.example` en la raíz que documente, con un comentario explicativo, cada variable que el compose lee: `DB_PASSWORD`, `JWT_SECRET_CURRENT`, `JWT_SECRET_PREVIOUS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `CA_CERT_PATH`, `CA_KEY_PATH`.

El archivo SHALL documentar además las variables del dominio de notificaciones, hoy ausentes: `N8N_WEBHOOK_URL`, `N8N_HEALTH_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`, `SMTP_STARTTLS`, `SMTP_SSL` y `WEBHOOK_FALLBACK_URL`. Cada una SHALL llevar un comentario que indique qué canal habilita y qué ocurre si se deja vacía. Sin esta documentación, configurar un canal de notificación exige editar el `docker-compose.yml` en lugar del `.env`.

El comentario de `N8N_HEALTH_URL` SHALL advertir explícitamente que no debe apuntar a la URL de un webhook productivo.

El archivo `.env` real SHALL NO commitearse — el `.gitignore` SHALL incluirlo.

#### Scenario: Render del compose sin variables huérfanas
- **WHEN** se copia `.env.example` a `.env`, se rellenan los valores y se ejecuta `docker compose config`
- **THEN** no aparece ningún warning del estilo "The X variable is not set"
- **AND** el output renderizado contiene los valores asignados

#### Scenario: `.env` ignorado por git
- **WHEN** se inspecciona `.gitignore`
- **THEN** la entrada `.env` está presente
- **AND** `.env.example` NO está en `.gitignore`

#### Scenario: Las variables de notificación están documentadas
- **WHEN** se inspecciona `.env.example`
- **THEN** las once variables de notificación están presentes, cada una con su comentario
- **AND** configurar el canal n8n no requiere editar `docker-compose.yml`
