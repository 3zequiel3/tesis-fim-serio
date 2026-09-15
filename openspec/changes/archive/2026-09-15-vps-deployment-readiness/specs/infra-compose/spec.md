## MODIFIED Requirements

### Requirement: Compose orquesta los servicios del servidor central

El sistema SHALL proveer un archivo `docker-compose.yml` en la raíz del repositorio que declare los servicios de larga vida `db`, `valkey`, `backend`, `frontend` y `n8n`, y el servicio one-shot `certs-init` (emisión de certificados, D53/RN-147), sin servicio `db-init` (D3). Los servicios `backend` y `frontend` SHALL pertenecer al perfil `app`.

*(Revisado el 2026-09-15 tras la aceptación en VPS — hallazgo 14.5, D58/RN-152 revisada)* NO SHALL existir un servicio `n8n-provision` separado: el provisioning de workflows y credenciales de n8n (D44/RN-138) corre dentro del propio entrypoint del servicio `n8n`, antes de que arranque el proceso `n8n` — ver el requisito "Provisioning idempotente de workflows de n8n" más abajo.

El compose MAY declarar un servicio `agent`, exclusivamente bajo el perfil `lab`. Ese servicio es de laboratorio: SHALL NOT arrancar con `--profile app` y SHALL NOT ser el mecanismo para monitorear hosts, que se monitorean con el agente nativo instalado por `agent/install.sh` (RN-68, D54/RN-148, D56/RN-150).

#### Scenario: Compose válido sintácticamente
- **WHEN** se ejecuta `docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app config` con un `.env` completo derivado de `.env.example`
- **THEN** el comando termina con exit 0 y emite la composición renderizada sin warnings de variables faltantes
- **AND** el output incluye los servicios `db`, `valkey`, `backend`, `frontend`, `n8n` y `certs-init`, y NO incluye `db-init` ni `n8n-provision`

#### Scenario: Servicios infra arrancan en aislado
- **WHEN** se ejecuta `docker compose up -d db valkey n8n`
- **THEN** los tres contenedores de larga vida quedan en estado `running` y sus healthchecks reportan `healthy`
- **AND** `n8n` no reporta `healthy` hasta que su entrypoint completó el provisioning de workflows (si el provisioning falla, `n8n` no llega a arrancar y el contenedor termina en error, nunca en `healthy`)
- **AND** ningún error aparece en `docker compose logs db valkey n8n` relacionado con configuración faltante

#### Scenario: El agente de laboratorio no arranca con el perfil de servidor
- **WHEN** se ejecuta `docker compose --profile app config --services`
- **THEN** la lista no incluye `agent`
- **AND** con `--profile app --profile lab` la lista sí lo incluye

### Requirement: Versiones del stack pinneadas

El compose SHALL fijar las imágenes a las versiones declaradas en `docs/arquitectura_stack.md §Stack`: `postgres:18.3`, `valkey/valkey:9.0.3`, `n8nio/n8n:2.17.8` (D45/RN-139). SHALL NO usarse el tag `latest` ni rangos abiertos.

#### Scenario: Versiones exactas presentes en compose
- **WHEN** se inspecciona el `docker-compose.yml`
- **THEN** se encuentran textualmente las cadenas `postgres:18.3`, `valkey/valkey:9.0.3` y `n8nio/n8n:2.17.8`
- **AND** no aparece `n8nio/n8n:2.16.1`
- **AND** no aparece `:latest` en ninguna directiva `image:`

### Requirement: Red interna y exposición de puertos (RN-76, RN-78)

El compose SHALL declarar una red interna `fim_internal` por la que se comunican todos los servicios. En la topología de servidor (`docker-compose.yml` + `docker-compose.tls.yml` + perfil `app`, D54/RN-148) los puertos publicados SHALL ser exactamente:

- los de la consola web, publicados por `frontend`: `${CONSOLE_HTTP_PORT}` → 80 y `${CONSOLE_HTTPS_PORT}` → 443, con defaults 80 y 443 (D55/RN-149);
- `8443` (mTLS para agentes, RN-78) y `8444` (bootstrap de agentes por TLS server-auth, D52/RN-146), publicados por `backend`;
- `6380` (Valkey TLS), publicado sólo por `docker-compose.tls.yml`.

`8000` (API HTTP en claro) SHALL NOT publicarse en una interfaz distinta de loopback: la consola la alcanza por la red interna, y MAY publicarse como `127.0.0.1:8000` para diagnóstico. `5432`, `6379` y `5678` SHALL NOT publicarse en ningún archivo de la topología de servidor (D-04). El servicio `backend` SHALL estar configurado con `deploy.replicas: 1` (RN-76).

#### Scenario: Puertos internos no accesibles desde el host
- **WHEN** se renderiza `docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app config`
- **THEN** no hay mapeo publicado para los puertos `5432`, `6379` ni `5678`
- **AND** los servicios resuelven entre sí por nombre (`db`, `valkey`, `n8n`, `backend`) en la red `fim_internal`

#### Scenario: Backend declarado como single-instance y puertos de agentes publicados
- **WHEN** se inspecciona el bloque `backend` en la composición renderizada
- **THEN** existe la directiva `deploy.replicas: 1`
- **AND** los puertos `8443` y `8444` están mapeados al host
- **AND** el único mapeo del puerto `8000`, si existe, tiene `host_ip: 127.0.0.1`

#### Scenario: Superficie alcanzable desde fuera del servidor
- **WHEN** el stack corre con los dos archivos de compose y el perfil `app`, y se sondea el servidor desde otro host de la red
- **THEN** los puertos `8000`, `5432`, `6379` y `5678` no aceptan conexiones
- **AND** los puertos de la consola, `8443`, `8444` y `6380` aceptan conexiones

### Requirement: Variables de entorno documentadas en `.env.example`

El sistema SHALL incluir un `.env.example` en la raíz que documente, con un comentario explicativo, cada variable que el compose lee: `DB_PASSWORD`, `JWT_SECRET_CURRENT`, `JWT_SECRET_PREVIOUS`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `CA_CERT_PATH`, `CA_KEY_PATH`, `BACKEND_CERT_PATH`, `BACKEND_KEY_PATH` y `CORS_ALLOWED_ORIGINS`.

El archivo SHALL documentar además las variables del dominio de notificaciones: `N8N_WEBHOOK_URL`, `N8N_HEALTH_URL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO`, `SMTP_STARTTLS`, `SMTP_SSL` y `WEBHOOK_FALLBACK_URL`. Cada una SHALL llevar un comentario que indique qué canal habilita y qué ocurre si se deja vacía. Sin esta documentación, configurar un canal de notificación exige editar el `docker-compose.yml` en lugar del `.env`.

El comentario de `N8N_HEALTH_URL` SHALL advertir explícitamente que no debe apuntar a la URL de un webhook productivo.

El archivo SHALL documentar las variables del despliegue remoto (D53/RN-147, D55/RN-149): `FIM_PUBLIC_HOSTS`, `CONSOLE_TLS_MODE`, `CONSOLE_HTTP_PORT`, `CONSOLE_HTTPS_PORT`, `CONSOLE_TLS_DIR`, `CONSOLE_TLS_CERT_FILE` y `CONSOLE_TLS_KEY_FILE`; y las de operación de n8n (D45/RN-139): `N8N_ENCRYPTION_KEY`, `N8N_INSTANCE_OWNER_EMAIL`, `N8N_INSTANCE_OWNER_FIRST_NAME`, `N8N_INSTANCE_OWNER_LAST_NAME` y `N8N_INSTANCE_OWNER_PASSWORD_HASH`. El comentario de `N8N_INSTANCE_OWNER_PASSWORD_HASH` SHALL advertir que el valor es un hash bcrypt y que un texto plano rompe el login sin error explícito. El comentario de `CONSOLE_TLS_MODE` SHALL advertir que con `off` las credenciales y los tokens viajan en claro.

El archivo `.env` real SHALL NO commitearse — el `.gitignore` SHALL incluirlo.

#### Scenario: Render del compose sin variables huérfanas
- **WHEN** se copia `.env.example` a `.env`, se rellenan los valores y se ejecuta `docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app config`
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

#### Scenario: Las variables de despliegue remoto y de n8n están documentadas
- **WHEN** se inspecciona `.env.example`
- **THEN** `FIM_PUBLIC_HOSTS`, las seis variables `CONSOLE_*`, `N8N_ENCRYPTION_KEY` y las cuatro `N8N_INSTANCE_OWNER_*` están presentes, cada una con su comentario

## ADDED Requirements

### Requirement: Override TLS de Valkey para agentes remotos (D53/RN-147, D54/RN-148)

`docker-compose.tls.yml` SHALL configurar Valkey para escuchar sólo TLS en `6380` (`--port 0`, `--tls-port 6380`) con certificado de cliente obligatorio (`--tls-auth-clients yes`), SHALL publicar `6380:6380`, y SHALL hacer depender a `valkey` de `certs-init` con `condition: service_completed_successfully`. Valkey SHALL montar un volumen que contiene únicamente su propio material TLS (certificado, clave y `ca.pem`); SHALL NOT tener acceso a la clave privada de la CA.

El override SHALL configurar `VALKEY_URL` del `backend` con esquema `valkeys://`, el certificado y la clave de cliente del backend ante Valkey (`CN=fim-backend-valkey`), `ssl_ca_certs` apuntando a la CA propia y `ssl_check_hostname=true`. Levantar el backend autenticado ante Valkey SHALL NOT requerir ningún paso manual ni ejecutar comandos dentro de contenedores. Los compose de laboratorio de aceptación conservan su configuración propia.

#### Scenario: El override publica 6380 y configura la identidad de cliente del backend
- **WHEN** se renderiza la composición con `docker-compose.tls.yml`
- **THEN** `valkey` publica `6380`
- **AND** el `VALKEY_URL` del `backend` usa `valkeys://valkey:6380` e incluye `ssl_certfile`, `ssl_keyfile`, `ssl_ca_certs` y `ssl_check_hostname=true`

#### Scenario: Arranque limpio sin pasos manuales
- **WHEN** se levanta el stack con los dos archivos de compose y el perfil `app` sobre volúmenes vacíos, sin ejecutar ningún comando dentro de contenedores
- **THEN** `GET /health/components` reporta `valkey: ok`

#### Scenario: Valkey no ve la clave de la CA
- **WHEN** se lista el contenido montado en el contenedor `valkey`
- **THEN** no existe ningún archivo con la clave privada de la CA

### Requirement: Emisión de certificados previa al arranque (`certs-init`, D53/RN-147)

El servicio one-shot `certs-init` SHALL usar la imagen del backend y SHALL ejecutar, en este orden: asegurar la CA (crearla si falta, validar su perfil si existe), asegurar el certificado de servidor del backend, asegurar el certificado de servidor de Valkey, asegurar el certificado de cliente del backend ante Valkey, y —sólo con `CONSOLE_TLS_MODE=self_signed`— asegurar el certificado autofirmado de la consola. Los requisitos de cada certificado viven en la spec `backend-pki`.

`backend` y `frontend` SHALL depender de `certs-init` con `condition: service_completed_successfully`. Si `certs-init` falla, ningún dependiente SHALL arrancar y el log de `certs-init` SHALL nombrar la causa. `valkey` SHALL recrearse cuando cambia `FIM_PUBLIC_HOSTS`, de modo que cargue el certificado reemitido.

#### Scenario: Volúmenes vacíos
- **WHEN** se ejecuta `up` con volúmenes vacíos
- **THEN** `certs-init` termina con exit 0 antes de que `valkey` y `backend` arranquen
- **AND** existen la CA, el certificado del backend, el de Valkey y el de cliente del backend ante Valkey

#### Scenario: Segundo arranque sin cambios
- **WHEN** se ejecuta `up` por segunda vez sin cambiar `.env`
- **THEN** `certs-init` termina con exit 0 sin reescribir ningún certificado (mismos números de serie)

#### Scenario: Entrada inválida en `FIM_PUBLIC_HOSTS`
- **WHEN** `FIM_PUBLIC_HOSTS` contiene una entrada que no es IP ni nombre DNS válido
- **THEN** `certs-init` termina con exit distinto de 0 y su log nombra la entrada inválida
- **AND** `valkey` (con el override TLS) y `backend` no arrancan

### Requirement: Servicio n8n operable (D45/RN-139, D43/RN-137)

El servicio `n8n` SHALL declarar `N8N_ENCRYPTION_KEY` como obligatoria (la composición falla si falta), el owner declarativo (`N8N_INSTANCE_OWNER_MANAGED_BY_ENV=true` más `N8N_INSTANCE_OWNER_EMAIL`, `_FIRST_NAME`, `_LAST_NAME` y `_PASSWORD_HASH` en bcrypt), `WEBHOOK_URL=http://n8n:5678/`, `N8N_HOST=n8n` y `N8N_PROTOCOL=http`. SHALL declarar un healthcheck contra `GET /healthz`. `backend` SHALL depender de `n8n` con `condition: service_healthy`. El puerto `5678` SHALL permanecer sin publicar (D-04).

#### Scenario: Composición sin clave de cifrado
- **WHEN** se ejecuta `docker compose config` con un `.env` que no define `N8N_ENCRYPTION_KEY`
- **THEN** el comando termina con exit distinto de 0 y el mensaje nombra `N8N_ENCRYPTION_KEY`

#### Scenario: n8n saludable antes que el backend
- **WHEN** se levanta el stack con el perfil `app`
- **THEN** `n8n` reporta `healthy` antes de que `backend` arranque

#### Scenario: Salud del canal con URLs productivas
- **WHEN** `.env` define `N8N_HEALTH_URL=http://n8n:5678/healthz` y el stack está arriba
- **THEN** `GET /health/components` reporta `n8n: ok`

#### Scenario: Owner establecido sin UI
- **WHEN** n8n arranca por primera vez con el owner declarado por variables de entorno
- **THEN** el owner existe con el correo configurado y no queda pendiente ningún setup de owner

### Requirement: Provisioning idempotente de workflows de n8n (D44/RN-138, D58/RN-152 revisada)

*(Revisado el 2026-09-15 tras la aceptación en VPS — hallazgo 14.5)* El provisioning SHALL correr dentro del entrypoint del propio contenedor `n8n` (`n8n/provision/entrypoint.sh`, montado junto con `./n8n/workflows` en solo lectura), **antes** de que se ejecute el proceso `n8n`, y SHALL importar cada workflow por su `id` estable, de modo que re-ejecutarlo actualice las entradas existentes en lugar de duplicarlas. SHALL publicar/activar el enrutador y los sub-flujos y SHALL verificar el estado de activación de cada workflow esperado, terminando el contenedor con exit distinto de 0 (sin llegar a iniciar `n8n`) si alguno no quedó activo — esa verificación es una lectura de la base de datos vía la CLI de n8n y no requiere que el proceso `n8n` esté corriendo. La activación no se asume: un workflow importado inactivo sólo responde en `/webhook-test/...`.

NO SHALL existir un camino en el que el provisioning modifique workflows o credenciales de una instancia de `n8n` que ya está corriendo: al vivir en el entrypoint, sólo corre cuando el contenedor `n8n` arranca (creación o recreación), nunca contra un proceso ya activo — una segunda `docker compose up -d` que no cambia la configuración de `n8n` deja el contenedor (y por lo tanto el entrypoint) sin re-ejecutar.

#### Scenario: Despliegue limpio
- **WHEN** se levanta el stack sobre una base `fim_n8n` vacía
- **THEN** el enrutador `fim-alert` y los tres sub-flujos quedan importados y activos

#### Scenario: Re-ejecución sin duplicados
- **WHEN** se recrea el contenedor `n8n` (por ejemplo, tras cambiar una variable de canal en `.env`)
- **THEN** la cantidad de workflows en n8n no cambia y cada `id` aparece una sola vez

#### Scenario: Activación no verificada
- **WHEN** algún workflow esperado no queda activo tras el provisioning
- **THEN** el contenedor `n8n` termina con exit distinto de 0 nombrando el workflow
- **AND** el proceso `n8n` nunca llega a iniciar

#### Scenario: El webhook productivo responde
- **WHEN** desde la red `fim_internal` se hace `POST http://n8n:5678/webhook/fim-alert` con un payload válido de `notification-payload-contract`
- **THEN** la respuesta no es 404 y el enrutador registra una ejecución

#### Scenario: Segunda `up -d` con n8n ya activo no deja el webhook sin registrar
- **WHEN** se ejecuta `docker compose up -d` una segunda vez, sin cambios en la configuración de `n8n`, mientras `n8n` ya está `healthy`
- **THEN** el contenedor `n8n` no se recrea y su entrypoint no se re-ejecuta
- **AND** un `POST http://n8n:5678/webhook/fim-alert` inmediatamente después sigue respondiendo (no 404), sin necesidad de `restart n8n`

### Requirement: Modos TLS de la consola en el compose (D55/RN-149)

`CONSOLE_TLS_MODE` SHALL leerse de `.env` y pasarse, desde la misma variable y con default `off`, a `frontend` y a `backend`, de modo que el esquema servido por nginx y el atributo `Secure` de la cookie de refresh no puedan divergir. `frontend` SHALL montar en solo lectura `${CONSOLE_TLS_DIR}` (para el modo `provided`) y el volumen donde `certs-init` deja el certificado autofirmado (para el modo `self_signed`). Cambiar de modo SHALL NOT requerir editar YAML.

#### Scenario: Mismo modo en los dos servicios
- **WHEN** `.env` define `CONSOLE_TLS_MODE=self_signed` y se renderiza la composición
- **THEN** `frontend` y `backend` reciben `CONSOLE_TLS_MODE=self_signed`

#### Scenario: Default sin TLS
- **WHEN** `.env` no define `CONSOLE_TLS_MODE`
- **THEN** `frontend` y `backend` reciben `CONSOLE_TLS_MODE=off`

#### Scenario: Certificado provisto con enlaces simbólicos relativos
- **WHEN** `CONSOLE_TLS_DIR=/etc/letsencrypt` y `CONSOLE_TLS_CERT_FILE=live/<dominio>/fullchain.pem`, cuyos archivos son enlaces relativos a `archive/`
- **THEN** nginx lee el certificado y la clave desde el montaje sin error
