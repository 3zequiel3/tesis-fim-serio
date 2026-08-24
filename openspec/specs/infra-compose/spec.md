# infra-compose Specification

## Purpose
TBD - estructura reparada al archivar n8n-contract-and-config. El archivo se había escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar Purpose.

## Requirements

### Requirement: Compose orquesta los servicios del servidor central

El sistema SHALL proveer un archivo `docker-compose.yml` en la raíz del repositorio que declare los servicios `db`, `valkey`, `backend`, `frontend` y `n8n`, sin servicio `db-init` (D3). Los servicios `backend` y `frontend` SHALL existir como placeholders compatibles con `docker compose config` aunque sus imágenes/builds aún no produzcan binarios funcionales en este change. El agente FIM NO SHALL aparecer en el compose (RN-68: se despliega nativo con systemd).

#### Scenario: Compose válido sintácticamente
- **WHEN** se ejecuta `docker compose config` con un `.env` derivado de `.env.example`
- **THEN** el comando termina con exit 0 y emite la composición renderizada sin warnings de variables faltantes
- **AND** el output incluye exactamente los servicios `db`, `valkey`, `backend`, `frontend`, `n8n` y NO incluye `db-init`

#### Scenario: Servicios infra arrancan en aislado
- **WHEN** se ejecuta `docker compose up -d db valkey n8n`
- **THEN** los tres contenedores quedan en estado `running` y sus healthchecks (cuando aplique) reportan `healthy`
- **AND** ningún error aparece en `docker compose logs db valkey n8n` relacionado con configuración faltante

### Requirement: Versiones del stack pinneadas

El compose SHALL fijar las imágenes a las versiones declaradas en `docs/arquitectura_stack.md §Stack`: `postgres:18.3`, `valkey/valkey:9.0.3`, `n8nio/n8n:2.16.1`. SHALL NO usarse el tag `latest` ni rangos abiertos.

#### Scenario: Versiones exactas presentes en compose
- **WHEN** se inspecciona el `docker-compose.yml`
- **THEN** se encuentran textualmente las cadenas `postgres:18.3`, `valkey/valkey:9.0.3` y `n8nio/n8n:2.16.1`
- **AND** no aparece `:latest` en ninguna directiva `image:`

### Requirement: Dos bases de datos en el mismo PostgreSQL (RN-67)

El sistema SHALL inicializar dos bases en la instancia PostgreSQL: `fim` (aplicación) y `fim_n8n` (n8n). La inicialización SHALL ejecutarse mediante un script SQL montado como volumen read-only en `/docker-entrypoint-initdb.d/` del contenedor `db`, sin servicio `db-init` adicional (D3). El usuario aplicativo `fim` SHALL ser owner de ambas bases. El script SHALL ser idempotente respecto al primer arranque (la imagen oficial de PostgreSQL solo lo ejecuta cuando el `pg_data` está vacío).

#### Scenario: Bases creadas en primer arranque
- **WHEN** se levanta `db` por primera vez con `pg_data` vacío
- **THEN** el comando `docker compose exec db psql -U fim -l` lista las bases `fim` y `fim_n8n`
- **AND** ambas bases tienen como owner al usuario `fim`

#### Scenario: Re-arranques no rompen la inicialización
- **WHEN** se reinicia el servicio `db` con un volumen `pg_data` ya inicializado
- **THEN** el contenedor arranca sin volver a ejecutar el script (comportamiento estándar de la imagen oficial)
- **AND** las bases siguen presentes y accesibles

### Requirement: Permisos restringidos para n8n

El usuario `fim` SHALL tener `ALL PRIVILEGES` sobre `fim_n8n` para que n8n pueda crear su propio schema, tablas e índices al arrancar. NO SHALL crearse un usuario PostgreSQL adicional para n8n en este change (la separación lógica RN-67 se sostiene a nivel de base, no de usuario).

#### Scenario: n8n conecta y migra su schema
- **WHEN** se arranca `n8n` apuntando a `fim_n8n` con credenciales del usuario `fim`
- **THEN** los logs de n8n muestran las migraciones internas ejecutándose sin errores de permisos
- **AND** `psql -U fim -d fim_n8n -c "\dt"` lista tablas creadas por n8n

### Requirement: Red interna y exposición de puertos (RN-76, RN-78)

El compose SHALL declarar una red interna `fim_internal` por la que se comunican todos los servicios. `db`, `valkey` y `n8n` NO SHALL exponer puertos al host. El servicio `backend` SHALL declarar (para uso futuro en Change 02 / Change 04) los puertos `8443` (mTLS para agentes, RN-78) y `8000` (API HTTP para frontend); en este change el backend es placeholder y no responde, pero los puertos quedan declarados. El servicio `backend` SHALL estar configurado con `deploy.replicas: 1` (RN-76).

#### Scenario: Puertos internos no accesibles desde el host
- **WHEN** los servicios infra están arriba (`db`, `valkey`, `n8n`)
- **THEN** no hay binding visible en `docker compose ps` para los puertos `5432`, `6379` ni `5678`
- **AND** los servicios resuelven entre sí por nombre (`db`, `valkey`, `n8n`) en la red `fim_internal`

#### Scenario: Backend declarado como single-instance
- **WHEN** se inspecciona el bloque `backend` en `docker-compose.yml`
- **THEN** existe la directiva `deploy.replicas: 1`
- **AND** los puertos `8443:8443` y `8000:8000` están mapeados al host

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

### Requirement: Volúmenes nombrados para persistencia

El compose SHALL declarar volúmenes nombrados `pg_data` (datos de PostgreSQL), `n8n_data` (workflows y credenciales de n8n) y `backend_certs` (placeholder para la CA propia que Change 04 emitirá, RN-78). El volumen `backend_certs` SHALL existir aunque hoy esté vacío, para que el bind del servicio `backend` no falle cuando el binario aparezca.

#### Scenario: Volúmenes creados en primer up
- **WHEN** se ejecuta `docker compose up -d db valkey n8n`
- **THEN** `docker volume ls` muestra volúmenes con nombre derivado del proyecto + `pg_data` y `n8n_data`
- **AND** `pg_data` contiene los archivos de PostgreSQL después del primer arranque

### Requirement: Healthchecks para dependencias críticas

Los servicios `db` y `valkey` SHALL declarar `healthcheck` (con comandos nativos `pg_isready` y `valkey-cli ping` respectivamente) para que en changes posteriores los servicios dependientes puedan usar `depends_on … condition: service_healthy` sin race conditions.

#### Scenario: db reporta healthy tras inicialización
- **WHEN** transcurren los segundos del `start_period` del healthcheck del servicio `db`
- **THEN** `docker compose ps` muestra `db` con estado `healthy`

#### Scenario: valkey reporta healthy tras arranque
- **WHEN** `valkey` está corriendo
- **THEN** `docker compose ps` muestra `valkey` con estado `healthy`

### Requirement: Done criterion del Change 01

La infraestructura SHALL satisfacer el criterio de aceptación declarado en `CHANGES.md` línea 87: `docker compose up db valkey n8n` arranca limpio y `docker compose exec db psql -U fim -c "\l"` muestra las bases `fim` y `fim_n8n`.

#### Scenario: Smoke test reproducible
- **WHEN** un operador clona el repo, copia `.env.example` a `.env` con valores válidos, y ejecuta `docker compose up -d db valkey n8n`
- **THEN** los tres servicios quedan `running` (y `db`/`valkey` `healthy`) en menos de 60 segundos
- **AND** `docker compose exec db psql -U fim -c "\l"` lista `fim` y `fim_n8n`
- **AND** no hay tracebacks ni errores fatales en `docker compose logs`

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
