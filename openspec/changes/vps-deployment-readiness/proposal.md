## Why

**El sistema funciona entre dos equipos, pero sólo con pasos que no están en el producto.** El ensayo multi-host A-3 (2026-09-12) lo demostró y dejó registrado el costo:

- Los SAN de los certificados están fijos en código (`backend/app/core/pki.py:161` → `backend, fim-backend, localhost`; `scripts/emitir_cert_valkey.py:72` → `valkey, localhost`). Un agente que apunta a la IP o al dominio del servidor falla la verificación de hostname, y hubo que mapear nombres en `/etc/hosts` del host monitoreado.
- El puerto 6380 sólo se publica en un override de evidencia; el certificado de cliente del backend ante Valkey (`CN=fim-backend-valkey`) se emitió con un script de la carpeta de evidencia; el certificado de Valkey se emite a mano dentro del contenedor.
- El compose publica 8000 en `0.0.0.0`, con lo que la API queda expuesta salteando el proxy de la consola.
- `agent/install.sh` no recibe ningún valor, obliga a editar `config.yaml` a mano, y re-ejecutarlo anida el código nuevo en `/opt/fim-agent/agent/agent/` mientras el servicio sigue corriendo el anterior. El registro del agente usó un script ad hoc.
- `secure=settings.environment != "dev"` (`auth/router.py:66`) acopla la cookie de refresh a una variable que no dice nada sobre el esquema real; nginx emite HSTS sobre HTTP.
- n8n arranca con **0 workflows**, sin `N8N_ENCRYPTION_KEY`, sin owner y sin healthcheck; `N8N_HEALTH_URL` vacía hace que `GET /health/components` lo reporte `degraded` —correctamente, por D43— y ninguna alerta sale por ese canal.

La tesis tiene que poder reproducirse en un servidor remoto sin dominio y sin conocimiento fuera de banda. Las decisiones D53–D56 (RN-147 a RN-150) cerraron el qué; este change lo implementa.

## What Changes

- **SAN configurable (D53/RN-147)**: `FIM_PUBLIC_HOSTS` en `.env` extiende el SAN del certificado del backend (8443/8444) y del de Valkey (6380), IP como `IPAddress` y nombre como `DNSName`, con reemisión idempotente. Un servicio one-shot `certs-init` emite la CA (si falta), el certificado del backend, el de servidor de Valkey y el de cliente del backend ante Valkey **antes** de que Valkey y el backend arranquen. Ningún operador ejecuta scripts dentro de contenedores.
- **Topología de servidor sin editar YAML (D54/RN-148)**: `docker-compose.yml` + `docker-compose.tls.yml` + perfil `app`. El override TLS publica 6380 y configura la identidad de cliente del backend ante Valkey. **BREAKING**: 8000 deja de publicarse en `0.0.0.0` (queda en loopback para diagnóstico). **BREAKING**: el servicio `agent` del compose pasa al perfil `lab` y deja de arrancar con `--profile app`. Un script de preparación genera `.env` completo sin sobrescribir uno existente.
- **Consola con HTTPS opcional (D55/RN-149)**: `CONSOLE_TLS_MODE` = `off` | `self_signed` | `provided`. Con HTTPS, 80 redirige a 443 y se emite HSTS; en `off` no se emite HSTS y el arranque advierte que las credenciales viajan en claro. **BREAKING**: el atributo `Secure` de la cookie de refresh se deriva de `CONSOLE_TLS_MODE` y deja de derivarse de `ENVIRONMENT`.
- **Instalador del agente parametrizable (D56/RN-150)**: flags o variables de entorno con prompts para lo faltante; secreto de bootstrap sólo por prompt oculto o archivo; huella SHA-256 de la CA verificada; no sobrescribe configuración existente sin `--reconfigure`; la reinstalación reemplaza el código; verificación de alcance a 8444 y 6380 antes de habilitar. Del lado del servidor, un paso único registra el agente y entrega host, huella de la CA y secreto de un solo uso.
- **n8n operable (absorbe el change 47 completo)**: pin a `n8nio/n8n:2.17.8` con owner declarativo en bcrypt (D45/RN-139), `N8N_ENCRYPTION_KEY`, `WEBHOOK_URL`/`N8N_HOST`/`N8N_PROTOCOL`, healthcheck y `depends_on: service_healthy` en el backend; provisioning one-shot idempotente por `id` estable con activación verificada; enrutador único `fim-alert` con sub-flujos por `Execute Workflow Trigger` (D44/RN-138); expresiones corregidas; search-before-create en ticketing (D41/RN-135).
- **Specs desactualizadas**: se corrige el desvío registrado en A-3 sobre el bootstrap en 8444 (D52/RN-146) en `backend-agents`, `agent-bootstrap` y `backend-pki`.
- **Guía de despliegue de producto** en `docs/` (fuera de `docs/cierre/evidencia/`), enlazada desde `README.md`; coherencia de la cita de versión de n8n en `docs/entrega_valores_cap5.md` sin tocar valores medidos.

## Capabilities

### New Capabilities
- `remote-deployment`: script de preparación del `.env` del servidor, paso único de registro de agente del lado del servidor, y guía de despliegue de producto.
- `n8n-alert-routing`: contenido y semántica de los workflows de n8n — enrutador `fim-alert`, sub-flujos invocados, expresiones válidas, respuesta al backend y search-before-create en ticketing.

### Modified Capabilities
- `infra-compose`: servicios one-shot (`certs-init`, `n8n-provision`), `agent` como laboratorio, pin de n8n 2.17.8, exposición de puertos (8444, 6380 por override, 8000 en loopback, puertos de consola), variables nuevas en `.env.example`, override TLS para agentes remotos, n8n operable y provisioning, modos TLS de la consola.
- `backend-pki`: SAN del backend desde `FIM_PUBLIC_HOSTS`, emisión automática de los certificados de Valkey (servidor) y del backend ante Valkey (cliente), listener de bootstrap 8444 y alcance real del listener 8443.
- `agent-valkey-transport`: verificación de hostname contra el SAN para el host de `valkey_url`.
- `agent-bootstrap`: bootstrap exclusivamente por `https` contra el listener 8444, con verificación del servidor contra `ca_cert_path` y hostname.
- `backend-agents`: `POST /agents/bootstrap` servido sólo por el listener 8444 (D52).
- `agent-core`: contrato del instalador (parámetros, secreto, huella de CA, no sobrescritura, reemplazo de código, verificación de alcance).
- `backend-auth`: `Secure` de la cookie de refresh atado a `CONSOLE_TLS_MODE`.
- `frontend-shell`: nginx con modos HTTP/HTTPS y HSTS sólo sobre HTTPS.
- `notification-payload-contract`: el test de contrato cubre también los sub-flujos invocados y fija las formas de acceso aceptadas.

## Impact

**Código**: `backend/app/core/{pki.py,config.py}`, nuevo módulo de emisión one-shot en el backend, `backend/app/modules/auth/router.py`, `backend/app/modules/agents/` (CLI de registro), `backend/app/main.py` (log de modo de consola), `agent/install.sh`, nuevo `agent/installer.py`, `frontend/{nginx.conf,Dockerfile}` y entrypoint de selección de modo, `docker-compose.yml`, `docker-compose.tls.yml`, `.env.example`, `n8n/workflows/*.json`, provisioning de n8n, `scripts/` (preparación del servidor, registro de agente), `scripts/setup-agent.sh` (perfil `lab`).

**Docs**: guía de despliegue nueva en `docs/`, `README.md`, `docs/operations.md`, `docs/arquitectura_stack.md` (nombres definitivos de variables de D55), `docs/entrega_valores_cap5.md:214` (cita).

**Operación**: quien use `--profile app` para el agente de laboratorio debe agregar `--profile lab`; quien acceda a la API por `http://<host>:8000` desde otra máquina debe usar la consola (`/api/`) o loopback.

**Dependencias del DAG**: D52/RN-146 implementado (`f9a536a`). El change 41 (`agent-deployment-caps`) tiene su implementación de `install.sh` presente en el código (drop-in y propiedad) pero **no está archivado** (79/88 tareas; las pendientes son verificaciones en host). Este change compone con ese layout sin redefinirlo; la coordinación está en `design.md`. Coordina con el change 50 (`backend-agent-cert-renewal`, en curso) sobre `backend/app/core/pki.py`.

**Restricción**: `docs/cierre/evidencia/**` es inmutable (`SHA256SUMS`). Los helpers del ensayo A-3 se productizan como archivos nuevos, nunca editando la evidencia.

**Reglas cubiertas**: RN-52, RN-53, RN-76, RN-78, RN-95, RN-114, RN-115, RN-146, RN-147, RN-148, RN-149, RN-150, D-04. **Decisiones aplicadas**: D53/RN-147, D54/RN-148, D55/RN-149, D56/RN-150, D52/RN-146, D41/RN-135, D43/RN-137, D44/RN-138, D45/RN-139, D36/RN-130 (sin modificar).
