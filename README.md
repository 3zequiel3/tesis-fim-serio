# FIM Platform — Guía de instalación

Plataforma de **File Integrity Monitoring (FIM)** para hosts Linux: un servidor
central (backend FastAPI, PostgreSQL, Valkey, n8n y consola web) y uno o más
**agentes nativos** instalados en los anfitriones cuyo filesystem se vigila.

Esta guía es un procedimiento paso a paso para dejar la plataforma funcionando
desde un clon limpio del repositorio. Todos los comandos están verificados
contra archivos de este repositorio; los que no se pudieron verificar están
declarados como tales en [Limitaciones de esta guía](#16-limitaciones-de-esta-guía).

**El caso que importa es el de la [Parte C](#parte-c--anfitrión-monitoreado-distinto-del-servidor):
el anfitrión monitoreado es una máquina distinta del servidor.** La Parte B deja
el servidor central listo; la Parte C enrola el anfitrión remoto.

---

## Índice

- [0. Antes de empezar: las tres reglas que evitan la mayoría de los problemas](#0-antes-de-empezar-las-tres-reglas-que-evitan-la-mayoría-de-los-problemas)
- [Parte A — Requisitos previos](#parte-a--requisitos-previos)
  - [1. Requisitos del servidor](#1-requisitos-del-servidor)
  - [2. Requisitos del anfitrión monitoreado](#2-requisitos-del-anfitrión-monitoreado)
  - [3. Topología y puertos](#3-topología-y-puertos)
- [Parte B — Instalación del servidor central](#parte-b--instalación-del-servidor-central)
  - [Paso 1. Clonar el repositorio](#paso-1-clonar-el-repositorio)
  - [Paso 2. Crear el archivo `.env`](#paso-2-crear-el-archivo-env)
  - [Paso 3. Elegir el modo TLS de la consola](#paso-3-elegir-el-modo-tls-de-la-consola)
  - [Paso 4. Validar la interpolación del `.env`](#paso-4-validar-la-interpolación-del-env)
  - [Paso 5. Levantar el stack](#paso-5-levantar-el-stack)
  - [Paso 6. Verificar `certs-init`](#paso-6-verificar-certs-init)
  - [Paso 7. Verificar la salud de los servicios](#paso-7-verificar-la-salud-de-los-servicios)
  - [Paso 8. Primer ingreso a la consola](#paso-8-primer-ingreso-a-la-consola)
  - [Paso 9. Aplicar migraciones (solo sobre una base preexistente)](#paso-9-aplicar-migraciones-solo-sobre-una-base-preexistente)
  - [Paso 10. Restringir el acceso a los puertos publicados](#paso-10-restringir-el-acceso-a-los-puertos-publicados)
- [Parte C — Anfitrión monitoreado distinto del servidor](#parte-c--anfitrión-monitoreado-distinto-del-servidor)
  - [11. Qué se instala de cada lado](#11-qué-se-instala-de-cada-lado)
  - [12. Conectividad requerida, puerto por puerto](#12-conectividad-requerida-puerto-por-puerto)
  - [Paso 13. Registrar el agente en el servidor](#paso-13-registrar-el-agente-en-el-servidor)
  - [Paso 14. Transferir la CA, la huella y el secreto al anfitrión](#paso-14-transferir-la-ca-la-huella-y-el-secreto-al-anfitrión)
  - [Paso 15. Preparar el directorio vigilado](#paso-15-preparar-el-directorio-vigilado)
  - [Paso 16. Instalar el agente](#paso-16-instalar-el-agente)
  - [Paso 17. Verificar el transporte TLS desde el anfitrión monitoreado](#paso-17-verificar-el-transporte-tls-desde-el-anfitrión-monitoreado)
  - [Paso 18. Crear las reglas de decisión](#paso-18-crear-las-reglas-de-decisión)
- [Parte D — PKI: cómo se generan y distribuyen los certificados](#parte-d--pki-cómo-se-generan-y-distribuyen-los-certificados)
- [Parte E — Verificación final](#parte-e--verificación-final)
- [Parte F — Problemas frecuentes](#parte-f--problemas-frecuentes)
- [Parte G — Operación posterior](#parte-g--operación-posterior)
- [16. Limitaciones de esta guía](#16-limitaciones-de-esta-guía)
- [17. Documentación relacionada](#17-documentación-relacionada)

---

## 0. Antes de empezar: las tres reglas que evitan la mayoría de los problemas

### Regla 1 — Siempre los dos archivos de Compose

> **Todo** comando de Docker Compose de este proyecto se ejecuta con los dos
> archivos:
>
> ```bash
> docker compose -f docker-compose.yml -f docker-compose.tls.yml <subcomando>
> ```
>
> El override `docker-compose.tls.yml` es el único lugar donde Valkey publica el
> puerto **6380** y donde se habilita TLS/mTLS en el canal agente ↔ backend.
> Omitirlo en **cualquier** comando que recree servicios (`up`, `restart` de un
> servicio recreado, `down` + `up`) deja el stack **sin TLS**: Valkey vuelve a
> escuchar únicamente en 6379 dentro de la red interna, el 6380 deja de estar
> publicado y el agente pierde el transporte con un error de conexión rechazada
> (`errno 111` / `Connection refused`).
>
> Esto no es una nota al pie: es la causa más frecuente de un agente que "dejó de
> andar solo" después de un comando de mantenimiento aparentemente inocuo.

Referencia: los bloques `ports: - "6380:6380"` y `command: valkey-server --port 0
--tls-port 6380 ...` existen **únicamente** en `docker-compose.tls.yml`.

Para no repetirlo, conviene exportar el prefijo una vez por sesión:

```bash
cd /ruta/al/repositorio/tesis-fim-serio
alias fimc='docker compose -f docker-compose.yml -f docker-compose.tls.yml'
```

A lo largo de la guía los comandos se escriben completos, para que se puedan
copiar sin depender del alias.

### Regla 2 — El archivo `.env` no existe en el clon y es obligatorio

El repositorio versiona `.env.example` (el contrato de configuración), nunca
`.env`. Sin `.env`, la composición **falla**: `docker-compose.yml` declara
`N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY:?set N8N_ENCRYPTION_KEY in .env — see .env.example}`,
que aborta el comando si la variable no está definida. Ver
[Paso 2](#paso-2-crear-el-archivo-env).

### Regla 3 — Docker Compose interpola `$` dentro del `.env`

Compose interpola el contenido del `.env` contra sí mismo. Un `$` literal sin
escapar se interpreta como referencia a variable y **se reemplaza por una cadena
vacía, sin error**. Un hash bcrypt (`$2a$10$...`) es exactamente ese caso: se
trunca en silencio y el login de n8n falla sin mensaje explicativo.

> **Todo `$` literal dentro de un valor del `.env` se escribe `$$`.**

Esto está implementado en `scripts/prepare_server_env.py` (`_escape_dollar`),
que escapa cada `$` de cada valor antes de escribir el archivo; su comentario
documenta la verificación empírica contra Docker Compose v5.5.0 (2026‑09‑13).
Si el `.env` se genera con ese script, el escapado ya está hecho. Si se escribe
a mano, es responsabilidad del operador.

---

## Parte A — Requisitos previos

### 1. Requisitos del servidor

| Requisito | Valor | Verificado en |
|---|---|---|
| Docker Engine | Instalado y corriendo | `docs/despliegue_servidor_remoto.md` §1 |
| Docker Compose | **v2** como plugin (`docker compose`, no `docker-compose`) | `docker-compose.yml` (encabezado: "Compose v2, sin directiva `version:`") |
| Python 3 | Solo para `scripts/prepare_server_env.py` (usa exclusivamente la biblioteca estándar) | `scripts/prepare_server_env.py` |
| Puertos publicables | Consola (80 y/o 443 según el modo TLS), **8443**, **8444**, **6380** | `docker-compose.yml`, `docker-compose.tls.yml` |
| Identidad pública | Una IP pública, un nombre DNS, o ambos. No hace falta un dominio | `docs/despliegue_servidor_remoto.md` §1 |
| `openssl` | Para generar secretos, si el `.env` se escribe a mano | `.env.example` |

Comprobación:

```bash
docker version
docker compose version
python3 --version
```

Se espera ver: versión de Docker Engine, una versión de Compose que empiece en
`v2` o superior, y una versión de Python 3.

Las imágenes están pinneadas en `docker-compose.yml`: PostgreSQL `18.3`, Valkey
`9.0.3`, n8n `2.17.8`. El backend y el frontend se construyen localmente desde
`./backend` y `./frontend`.

### 2. Requisitos del anfitrión monitoreado

| Requisito | Valor | Verificado en |
|---|---|---|
| Sistema | Linux con systemd | `agent/deploy/fim-agent.service` |
| Kernel | ≥ 5.1 (fanotify en modo FID) | `docs/operations.md` §"Requisitos previos" |
| Python | **Exactamente 3.13** (ni 3.12 ni 3.14) | `agent/install.sh` (`REQUIRED_PYTHON_MAJOR=3`, `REQUIRED_PYTHON_MINOR=13`) |
| Privilegios | `root` para instalar el servicio | `agent/install.sh` |
| Capabilities otorgables | `CAP_SYS_ADMIN`, `CAP_DAC_READ_SEARCH`, `CAP_DAC_OVERRIDE`, `CAP_FOWNER`, `CAP_CHOWN` | `agent/deploy/fim-agent.service` |
| Conectividad saliente | Hacia el servidor en **8444**, **6380** (y **8443** para la renovación de certificados) | `agent/installer.py` (`SCOPE_CHECK_PORTS`, `derive_urls`) |
| Red | Acceso a Internet para que `pip` instale las dependencias del agente | `agent/install.sh` (`pip install -r requirements.txt`) |

`agent/install.sh` valida la versión de Python **antes** de crear el entorno
virtual y aborta con un mensaje claro si no coincide. Si el `python3` del sistema
es otra versión, instalar 3.13 y apuntar al intérprete:

```bash
uv python install 3.13
sudo bash agent/install.sh --python "$(uv python find 3.13)" ...
```

`--python` solo afecta al intérprete con el que se crea el venv; sobre un venv ya
creado la validación no se repite.

El agente **no abre ningún puerto TCP** en el anfitrión monitoreado (RN‑108/D8):
no hay nada que habilitar en el firewall de entrada. Todo el tráfico es saliente.

### 3. Topología y puertos

```
Servidor (host Docker)                                Anfitrión monitoreado (1..N)
──────────────────────────────────────────            ──────────────────────────────
docker-compose.yml + docker-compose.tls.yml           agente nativo (systemd)
perfil `app`, valores sólo en `.env`                  instalado con agent/install.sh
certs-init: CA → backend → Valkey → cliente
  Valkey → consola (sólo self_signed)

  consola  :80 (HTTP) | :443 (HTTPS)  ◄────────────── navegador del operador
  backend  :8444 bootstrap TLS server-auth ◄───────── agente (primer arranque)
  backend  :8443 mTLS                      ◄───────── agente (renovación de cert.)
  valkey   :6380 mTLS                      ◄───────── agente (eventos, heartbeat)
  no publicados al exterior: 8000, 5432, 6379, 5678
```

(Reproducido de `docs/arquitectura_stack.md` §Topología.)

| Puerto | Servicio | Publicación | Configurable |
|---|---|---|---|
| `8443` | backend, listener mTLS para agentes (exige certificado de cliente) | `0.0.0.0:8443` | **No** — valor fijo en `backend/app/core/pki.py::start_mtls_server` y en `docker-compose.yml` |
| `8444` | backend, listener de bootstrap (TLS server-auth, sin certificado de cliente) | `0.0.0.0:8444` | **No** — valor fijo en `backend/app/core/pki.py::start_bootstrap_server` y en `docker-compose.yml` |
| `6380` | Valkey sobre TLS con `--tls-auth-clients yes` | `0.0.0.0:6380` | **No** — valor fijo en `docker-compose.tls.yml` |
| `8000` | API HTTP del backend, en claro, solo diagnóstico | `127.0.0.1:8000` | No |
| `80` / `443` | consola web (nginx) | `${CONSOLE_HTTP_PORT:-80}` / `${CONSOLE_HTTPS_PORT:-443}` | **Sí**, por `.env` |
| `5432` | PostgreSQL | no publicado | — |
| `6379` | Valkey en claro | no publicado (y con el override TLS, apagado: `--port 0`) | — |
| `5678` | UI de n8n | no publicado; solo por la red interna | — |

`agent/installer.py::derive_urls` deriva las tres URLs del agente a partir de un
único `--server-host`, con esos mismos puertos fijos:

```
backend_url      = https://<host>:8444
mtls_backend_url = https://<host>:8443
valkey_url       = valkeys://<host>:6380
```

---

## Parte B — Instalación del servidor central

### Paso 1. Clonar el repositorio

```bash
git clone <url-del-repositorio> tesis-fim-serio
cd tesis-fim-serio
```

**Se espera ver:** el repositorio clonado, con `docker-compose.yml`,
`docker-compose.tls.yml` y `.env.example` en la raíz. **No hay `.env`**: eso es
correcto.

### Paso 2. Crear el archivo `.env`

Hay dos caminos. El generador es el recomendado porque resuelve solo los tres
problemas que más cuestan a mano: el escapado de `$`, el hash bcrypt de n8n y la
derivación de `CORS_ALLOWED_ORIGINS`.

#### Opción A (recomendada) — generador

```bash
python3 scripts/prepare_server_env.py \
  --fim-public-hosts <ip-o-dominio-publico>[,<otro-host>...] \
  --console-tls-mode off
```

**Se espera ver:**

```
Wrote /ruta/.env (mode 0600).

Initial admin password (shown once, never logged):
  <contraseña generada>

Initial n8n owner password (shown once, never logged):
  <contraseña generada>
```

Puntos críticos:

- **Las dos contraseñas se muestran una sola vez.** Guardarlas antes de cerrar la
  terminal: no quedan en ningún log; el owner de n8n queda solo como hash bcrypt.
- **Nunca sobrescribe un `.env` existente.** El archivo se crea con
  `os.O_CREAT | os.O_EXCL` y modo `0600`; si ya existe, el script termina con
  error sin tocarlo. Para generar uno de referencia y fusionar a mano:
  `--output .env.new`.
- Requiere **Docker** disponible: calcula el hash bcrypt del owner de n8n con un
  contenedor efímero de la misma imagen pinneada (`n8nio/n8n:2.17.8`), usando el
  `bcryptjs` que la propia imagen trae. La contraseña viaja por stdin, nunca como
  argumento.
- Cada entrada de `--fim-public-hosts` se valida con la misma regla que el backend
  usa para el SAN (IP, o nombre DNS RFC 1123 sin comodines). Una entrada inválida
  aborta sin escribir nada.
- Los valores que no se pasen por flag se preguntan de forma interactiva
  (`--admin-username`, `--n8n-owner-email`, `--n8n-owner-first-name`,
  `--n8n-owner-last-name`).

El generador **no** escribe las variables de canales de n8n
(`N8N_FIM_CHANNELS`, `N8N_EMAIL_*`, `N8N_SLACK_*`, `N8N_JIRA_*`,
`N8N_LINEAR_*`): se agregan a mano después. Sin ningún canal habilitado el stack
levanta igual y el enrutador de alertas responde `channel_disabled` — es un modo
válido para la primera instalación.

#### Opción B — a mano, desde la plantilla

```bash
umask 077
cp .env.example .env
${EDITOR:-vi} .env
```

Variables que **hay que completar sí o sí** (las demás tienen un valor por
defecto utilizable en `.env.example` o en el compose):

| Variable | Por qué es obligatoria | Cómo generarla |
|---|---|---|
| `DB_PASSWORD` | La leen `db` (`POSTGRES_PASSWORD`), `n8n` (`DB_POSTGRESDB_PASSWORD`) y el backend (`DATABASE_URL`) | `openssl rand -base64 24` — **ver aviso abajo** |
| `JWT_SECRET_CURRENT` | Firma de los JWT (HS256). Sin ella el backend aborta con `ValidationError` | `openssl rand -hex 32` |
| `ADMIN_USERNAME` | Usuario del primer admin (`.env.example` trae `admin`) | — |
| `ADMIN_PASSWORD` | Contraseña inicial del primer admin | `openssl rand -base64 16` |
| `N8N_ENCRYPTION_KEY` | **La composición falla si falta** (`:?` en `docker-compose.yml`) | `openssl rand -hex 32` |
| `CA_CERT_PATH`, `CA_KEY_PATH`, `BACKEND_CERT_PATH`, `BACKEND_KEY_PATH` | Se pasan tal cual a `certs-init` y al backend; vacías rompen la emisión de certificados | Usar los valores de `.env.example`: `/certs/ca.pem`, `/certs/ca-key.pem`, `/certs/backend.pem`, `/certs/backend-key.pem` |
| `FIM_PUBLIC_HOSTS` | IPs y/o nombres DNS por los que los agentes remotos alcanzan el servidor. **Vacía ⇒ los certificados solo cubren los nombres internos del compose y el agente remoto falla la verificación de hostname** | Lista separada por comas |
| `CORS_ALLOWED_ORIGINS` | El navegador envía `Origin` en todo POST. Sin el origen exacto del host público, el login responde **403** | Incluir el origen público con su esquema y puerto |
| `CONSOLE_TLS_MODE` | `off` \| `self_signed` \| `provided`. Un valor fuera de ese dominio aborta el arranque del backend | Ver [Paso 3](#paso-3-elegir-el-modo-tls-de-la-consola) |
| `N8N_INSTANCE_OWNER_EMAIL`, `_FIRST_NAME`, `_LAST_NAME`, `_PASSWORD_HASH` | Sin el owner declarativo, la primera vez que alguien abre la UI de n8n queda pendiente un wizard de setup manual | Ver abajo |
| `N8N_WEBHOOK_URL`, `N8N_HEALTH_URL` | Sin ellas el canal n8n queda **no configurado** y `GET /health/components` reporta `n8n: degraded` | `http://n8n:5678/webhook/fim-alert` y `http://n8n:5678/healthz` |

> **Aviso sobre `DB_PASSWORD`.** `.env.example` sugiere `openssl rand -base64 24`
> y advierte en el mismo comentario que no se deben usar caracteres que rompan la
> URL de conexión (`@`, `/`, `#`, `:`) sin encodearlos. `base64` puede producir
> `/` y `+`. Si se genera así, verificar el valor y regenerarlo hasta obtener uno
> limpio, o usar la Opción A: `prepare_server_env.py` genera contraseñas
> estrictamente alfanuméricas justamente por este motivo
> (`generate_password`, comentario: "no characters that break a Postgres
> connection URL").

> **`N8N_INSTANCE_OWNER_PASSWORD_HASH` es un hash bcrypt, no la contraseña.**
> Un texto plano ahí rompe el login de n8n sin error explícito. Cálculo manual
> documentado en `.env.example`:
>
> ```bash
> htpasswd -nbBC 10 "" '<password>'
> ```
>
> y quedarse con la parte posterior a `:`. **Al pegarlo en el `.env`, duplicar
> cada `$`:** un hash `$2y$10$abc...` se escribe `$$2y$$10$$abc...`
> ([Regla 3](#regla-3--docker-compose-interpola--dentro-del-env)).

> **`N8N_HEALTH_URL` nunca debe apuntar a un webhook productivo.** El health
> check hace `GET` cada 10 s, y un `GET` contra la URL de un webhook **dispara el
> workflow**: el chequeo de salud se convertiría en un emisor de notificaciones
> espurias. Por eso son dos variables distintas y ninguna se deriva de la otra.

Permisos del archivo:

```bash
chmod 600 .env
```

### Paso 3. Elegir el modo TLS de la consola

`CONSOLE_TLS_MODE` decide cómo sirve la consola web y si la cookie de refresh
viaja con el atributo `Secure`:

| Modo | Cuándo usarlo | Puertos | HSTS |
|---|---|---|---|
| `off` | Solo IP, sin dominio, o una primera prueba | 80 (HTTP) | ninguno |
| `self_signed` | Hay dominio o IP fija, pero no un certificado emitido por una CA pública | 80 → 301 a 443, HTTPS autofirmado | `max-age=300` (corto a propósito) |
| `provided` | Hay un certificado real (Let's Encrypt u otro) | 80 → 301 a 443, HTTPS con ese certificado | `max-age=63072000; includeSubDomains` |

> **Advertencia del modo `off`.** El login y el refresh de sesión viajan en texto
> plano: cualquiera en la misma red puede capturar las credenciales del
> administrador. El arranque del backend deja un `warning`
> (`backend.console_tls_mode`) recordándolo. Usarlo solo detrás de una red ya
> confiable (VPN, túnel SSH) o mientras se define el nombre público definitivo.

En modo `provided`, montar el **directorio completo** que contiene el certificado
en `CONSOLE_TLS_DIR` (por defecto `./deploy/console-tls`), no archivos sueltos:
así funciona un árbol estilo `/etc/letsencrypt`, donde `live/<dominio>/*.pem` son
enlaces relativos a `archive/`. `CONSOLE_TLS_CERT_FILE` y `CONSOLE_TLS_KEY_FILE`
son rutas **relativas** a ese directorio.

En modo `self_signed`, `certs-init` imprime en su log la huella SHA‑256 del
certificado autofirmado (`certs_init.step.done step=console`); compararla contra
la que muestra el navegador antes de aceptar la excepción de seguridad.

> En `CONSOLE_TLS_MODE=off` el contenedor `frontend` publica igual el puerto 443,
> pero nada escucha ahí dentro del contenedor y la conexión se rechaza. Es
> deliberado (evita editar YAML al cambiar de modo), no una falla.

### Paso 4. Validar la interpolación del `.env`

Antes de levantar nada, verificar que Compose resuelve todo y que ningún valor se
truncó:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml config > /tmp/fim-compose-config.txt
rg 'N8N_INSTANCE_OWNER_PASSWORD_HASH' /tmp/fim-compose-config.txt
```

**Se espera ver:** el comando `config` termina con exit 0 y la línea del hash
muestra el valor **completo** (`$2y$10$...`, con un solo `$` — Compose ya
resolvió el `$$`). Si aparece truncado o vacío, faltó el escapado de la
[Regla 3](#regla-3--docker-compose-interpola--dentro-del-env).

Si falta `N8N_ENCRYPTION_KEY`, el comando falla con exit distinto de 0 y el
mensaje nombra la variable.

Borrar el volcado cuando se termine: contiene los secretos ya resueltos.

```bash
rm -f /tmp/fim-compose-config.txt
```

### Paso 5. Levantar el stack

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d --build
```

**Se espera ver:** la construcción de las imágenes `fim-backend:dev` y
`fim-frontend:dev`, y luego los contenedores `db`, `valkey`, `n8n`,
`certs-init`, `backend` y `frontend` creados.

Notas sobre los perfiles:

- `--profile app` habilita `backend` y `frontend`, que de otro modo no arrancan.
- `certs-init` **no** tiene perfil: corre siempre, antes de `valkey`, `backend` y
  `frontend`, que dependen de él con `service_completed_successfully`.
- El servicio `agent` del compose pertenece al perfil **`lab`**, no a `app`: es un
  agente de laboratorio con secreto por defecto, pensado para probar todo en una
  sola máquina. **En un servidor real no se levanta.** Un anfitrión monitoreado
  usa el agente nativo de la [Parte C](#parte-c--anfitrión-monitoreado-distinto-del-servidor).

### Paso 6. Verificar `certs-init`

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app ps
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app logs certs-init
```

**Se espera ver:** en `ps`, `certs-init` con estado **`Exited (0)`** — es un
servicio one‑shot, ese es el resultado correcto, **no una falla**. En sus logs,
la secuencia:

```
certs_init.step.start step=ca_and_backend
certs_init.step.done  step=ca_and_backend
certs_init.step.start step=valkey_server
certs_init.step.done  step=valkey_server
certs_init.step.start step=backend_valkey_client
certs_init.step.done  step=backend_valkey_client
certs_init.step.skipped step=console console_tls_mode=off     # o step=console con sha256_fingerprint
certs_init.done
```

Si termina con `certs_init.failed`, el campo `reason` nombra la causa (por
ejemplo, una entrada inválida en `FIM_PUBLIC_HOSTS`).

### Paso 7. Verificar la salud de los servicios

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app ps
```

**Se espera ver:** `db`, `valkey` y `n8n` en `Up (healthy)`; `backend` y
`frontend` en `Up`; `certs-init` en `Exited (0)`.

`backend` depende de `n8n` con `condition: service_healthy`, y el healthcheck de
`n8n` solo pasa después de que su entrypoint completó el provisioning de
workflows. Si `n8n` no llega a `healthy`, el backend no arranca; los logs de
`n8n` nombran el workflow que no quedó activo:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app logs n8n
```

Chequeos puntuales:

```bash
# Backend (API HTTP en claro, solo desde el propio servidor)
curl -fsS http://127.0.0.1:8000/health

# Componentes: postgres, valkey, n8n, agents
curl -fsS http://127.0.0.1:8000/health/components
```

**Se espera ver:** `{"status":"ok"}` en el primero; en el segundo, un JSON con
`postgres`, `valkey`, `n8n` y `agents`. `agents: "degraded"` es lo correcto
mientras no haya ningún agente `online` todavía.

### Paso 8. Primer ingreso a la consola

Abrir en el navegador:

- `CONSOLE_TLS_MODE=off` → `http://<host>:<CONSOLE_HTTP_PORT>/` (por defecto el 80)
- `self_signed` / `provided` → `https://<host>:<CONSOLE_HTTPS_PORT>/` (por defecto el 443)

Ingresar con `ADMIN_USERNAME` y `ADMIN_PASSWORD` del `.env`. El sistema exige
cambiar la contraseña en el primer login.

> **Hay rate limit en el login y es comportamiento esperado.** Tras **5 intentos
> fallidos** dentro de una ventana de **900 segundos** (15 minutos), el backend
> responde **429** con `Too many login attempts. Try again later.` (valores por
> defecto `rate_limit_login_attempts` / `rate_limit_login_window_seconds` en
> `backend/app/core/config.py`). No es una falla de la instalación: hay que
> esperar a que la ventana se libere. Evitar probar contraseñas a repetición
> mientras se diagnostica otra cosa, porque bloquea el diagnóstico real.

> Si la consola se abre por el nombre o IP público y el login responde **403**,
> el problema es `CORS_ALLOWED_ORIGINS`, no las credenciales. Ver
> [Parte F](#parte-f--problemas-frecuentes).

### Paso 9. Aplicar migraciones (solo sobre una base preexistente)

Sobre una base **limpia** no hay que hacer nada: el `lifespan` del backend
ejecuta `SQLModel.metadata.create_all(engine)` y crea el esquema completo desde
los modelos.

Sobre una base que **ya tenía datos de una versión anterior**, las migraciones de
`backend/db/migrations/` se aplican **a mano** — no hay un runner automático ni
en el backend ni en el compose. Las migraciones declaran ese contrato en su
propio encabezado: *"Migrations are applied by hand (D3)"*. Son idempotentes
(`ADD COLUMN IF NOT EXISTS`).

```bash
while IFS= read -r migration; do
  echo "aplicando $migration"
  docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
    exec -T db psql -v ON_ERROR_STOP=1 -U fim -d fim < "backend/db/migrations/$migration"
done < <(fd -t f -e sql . backend/db/migrations -x basename | sort)
```

**Se espera ver:** una línea `ALTER TABLE` / `CREATE INDEX` por migración, sin
errores. Correr el bucle una segunda vez debe ser un no-op (comprobación de
idempotencia).

### Paso 10. Restringir el acceso a los puertos publicados

Docker escribe sus propias reglas de `iptables`/`nftables` para los puertos
publicados, y **esas reglas se evalúan antes que las de `ufw`**: un
`ufw deny 8443` no bloquea nada si Docker ya aceptó la conexión. Hay que filtrar
en la cadena `DOCKER-USER`, que Docker respeta:

```bash
sudo iptables -I DOCKER-USER -p tcp --dport 8443 -s <ip-o-subred-confiable> -j ACCEPT
sudo iptables -I DOCKER-USER -p tcp --dport 8444 -s <ip-o-subred-confiable> -j ACCEPT
sudo iptables -I DOCKER-USER -p tcp --dport 6380 -s <ip-o-subred-confiable> -j ACCEPT
sudo iptables -I DOCKER-USER -p tcp --dport 8443 -j DROP
sudo iptables -I DOCKER-USER -p tcp --dport 8444 -j DROP
sudo iptables -I DOCKER-USER -p tcp --dport 6380 -j DROP
```

`-I` inserta al principio, así que el orden importa: los `ACCEPT` específicos
deben quedar por delante de los `DROP` generales. El puerto 8000 no necesita
regla: ya publica solo en `127.0.0.1`. La consola (80/443) queda abierta a
propósito: es la interfaz pública del producto.

---

## Parte C — Anfitrión monitoreado distinto del servidor

Este es el caso real: el servidor corre el stack Docker y el anfitrión
monitoreado es otra máquina, en otra red, con el agente nativo instalado como
servicio systemd.

### 11. Qué se instala de cada lado

| | Servidor | Anfitrión monitoreado |
|---|---|---|
| **Software** | Docker Engine + Compose v2; el stack completo (`db`, `valkey`, `n8n`, `certs-init`, `backend`, `frontend`) | Agente nativo en `/opt/fim-agent`, servicio systemd `fim-agent` |
| **Se instala con** | `docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d --build` | `sudo bash agent/install.sh ...` |
| **Necesita del repositorio** | El repositorio completo | El directorio `agent/` (clonar el repo o copiar solo `agent/`) |
| **Archivos de configuración** | `.env` en la raíz del repositorio | `/etc/fim-agent/config.yaml`, `/etc/fim-agent/env`, `/etc/fim-agent/certs/ca.pem` |
| **Material criptográfico** | CA propia y clave privada de la CA, en el volumen `backend_certs` | Solo el **certificado público** de la CA (`ca.pem`) + su propio certificado emitido en el bootstrap |
| **Puertos escuchando** | 80/443, 8443, 8444, 6380 | **Ninguno** (RN‑108/D8: el agente no expone servidor HTTP) |

El contenedor `agent` del compose (perfil `lab`) **no** se usa aquí: es el modo
todo‑en‑una‑máquina, con un secreto de bootstrap por defecto. Levantarlo en un
servidor real arrancaría un agente de laboratorio en bucle de reinicios.

### 12. Conectividad requerida, puerto por puerto

Todo el tráfico es **saliente desde el anfitrión monitoreado hacia el servidor**.
El servidor nunca inicia una conexión hacia el anfitrión.

| Origen | Destino | Puerto | Protocolo | Para qué | Cuándo |
|---|---|---|---|---|---|
| Anfitrión monitoreado | Servidor | **8444/tcp** | TLS 1.3, server-auth (sin certificado de cliente) | `POST /agents/bootstrap`: el agente entrega su CSR y recibe su certificado, el `shared_secret` y el `master_secret` | Primer arranque, y cada vez que se re-enrola |
| Anfitrión monitoreado | Servidor | **8443/tcp** | mTLS 1.3 (`CERT_REQUIRED`) | `POST /agents/renew`: renovación del certificado del agente | Durante toda la vida del agente |
| Anfitrión monitoreado | Servidor | **6380/tcp** | TLS 1.3 con `--tls-auth-clients yes` (mTLS) | Valkey Streams: publicación de eventos, heartbeats, recepción de comandos | Permanente |
| Navegador del operador | Servidor | **80** y/o **443/tcp** | HTTP / HTTPS según `CONSOLE_TLS_MODE` | Consola web | Cuando se opera |
| Servidor | Anfitrión monitoreado | — | — | **Nada.** No hay conexión en esta dirección | Nunca |

`agent/install.sh` verifica, antes de habilitar el servicio, que **8444 y 6380**
sean alcanzables, con TLS verificado contra la CA y con el hostname cubierto por
el SAN del certificado. Si falla, no habilita nada y termina con **exit 3**
indicando qué puerto falló y por qué (DNS, conexión rechazada, timeout, o
verificación TLS/hostname).

El puerto 8443 no entra en esa verificación previa porque exige un certificado de
cliente que el agente todavía no tiene; se ejercita después del bootstrap.

### Paso 13. Registrar el agente en el servidor

**En el servidor**, con el stack arriba:

```bash
scripts/register-agent.sh <agent_id>
```

**Se espera ver:**

```
[register-agent] Registering '<agent_id>' against the running backend...
agent_id: <agent_id>
hosts: <contenido de FIM_PUBLIC_HOSTS>
ca_fingerprint_sha256: <64 caracteres hexadecimales>
bootstrap_secret: <32 caracteres hexadecimales>

Suggested install command (run on the monitored host; the secret is
deliberately omitted — read it from the line above):
  sudo bash agent/install.sh --non-interactive --server-host <host> \
    --agent-id <agent_id> --watch-path <path> --ca-cert ./fim-ca.pem \
    --ca-fingerprint <huella> --bootstrap-secret-file <path-to-secret-file>

[register-agent] Exporting the CA certificate to ./fim-ca.pem ...
[register-agent] Done.
```

Qué hace: genera un secreto de bootstrap con `secrets.token_hex(16)`, registra el
agente con la misma lógica de servicio que `POST /agents/register` (hash Argon2id),
imprime los datos de enrolamiento y exporta `./fim-ca.pem` al directorio actual.
No pide la contraseña del administrador: tener acceso a Docker en el servidor ya
es un privilegio mayor.

> **El secreto de bootstrap es de un solo uso.** Un bootstrap exitoso pone
> `bootstrap_secret_hash = None` en la fila del agente
> (`backend/app/modules/agents/service.py::bootstrap_agent`), así que **cualquier
> reintento posterior con ese mismo secreto devuelve 401 `invalid credentials`**.
> Y volver a correr `scripts/register-agent.sh` con el mismo `agent_id` devuelve
> **409 `agent '<id>' already registered`**: no emite un secreto nuevo.
> Consecuencia práctica: si se pierde el secreto **antes** de completar el primer
> bootstrap, hay que enrolar bajo un `agent_id` distinto (ver
> [Limitaciones](#16-limitaciones-de-esta-guía)).
>
> Una vez que el agente tiene su certificado, el secreto ya no hace falta: se lo
> puede borrar del anfitrión y las reinstalaciones posteriores no lo piden.

### Paso 14. Transferir la CA, la huella y el secreto al anfitrión

Hay que llevar tres cosas al anfitrión monitoreado, por un canal que el operador
considere seguro:

1. **`fim-ca.pem`** — el certificado público de la CA. No es secreto, pero su
   integridad importa: es lo que el agente usa para verificar al servidor.
2. **La huella SHA‑256 de la CA** (`ca_fingerprint_sha256`) — se transmite por un
   canal distinto al del archivo si es posible. El instalador compara la huella
   del archivo contra este valor y **aborta antes de escribir nada en
   `/etc/fim-agent`** si no coinciden, mostrando ambas huellas.
3. **El secreto de bootstrap**, en un archivo. El instalador **nunca** lo acepta
   como argumento de línea de comandos (`--bootstrap-secret` se rechaza
   explícitamente antes de escribir nada) ni como variable de entorno: solo por
   `--bootstrap-secret-file` o por un prompt oculto. Debe tener al menos 16
   caracteres.

Por ejemplo, desde el servidor:

```bash
scp ./fim-ca.pem <usuario>@<anfitrion>:/tmp/fim-ca.pem
```

Y en el anfitrión, escribir el secreto en un archivo con permisos restrictivos:

```bash
umask 077
printf '%s' '<secreto-de-bootstrap>' > /root/fim-bootstrap-secret
```

**El certificado de la CA termina en `/etc/fim-agent/certs/ca.pem`**, con modo
`0644` y dueño `root:root`. **Eso lo hace el instalador**, no el operador: se le
pasa la ruta del archivo copiado con `--ca-cert` y él lo verifica y lo deposita
en su destino final (`agent/installer.py::apply_config`,
`DEFAULT_CA_CERT_DEST = "/etc/fim-agent/certs/ca.pem"`).

Borrar el archivo del secreto después de la instalación.

### Paso 15. Preparar el directorio vigilado

> **Las reglas de decisión y la ruta de vigilancia NO son lo mismo.** Es la
> confusión que más tiempo cuesta, porque el síntoma no apunta a la causa.
>
> | | Qué acepta | Ejemplo válido | Dónde se configura |
> |---|---|---|---|
> | **Ruta de vigilancia** (`watch_path`) | Un **directorio existente**, ruta absoluta. **Sin globs** | `/srv/fim-watch` | `--watch-path` de `agent/install.sh`; después, desde la consola |
> | **Regla de decisión** (`pattern`) | Un **glob** evaluado con `fnmatch` sobre la ruta del evento; `*` cruza barras | `/srv/fim-watch/*`, `/srv/fim-watch/critico/*` | Consola web, o `POST /rules` |
>
> Poner un glob como ruta de vigilancia produce
> **`fanotify_mark: No such file or directory`** y el agente no detecta nada.
> `agent/installer.py::validate_watch_paths` exige que cada ruta sea absoluta y
> que **exista** (`os.path.exists`), por lo que el instalador rechaza un glob de
> entrada; pero una ruta inyectada a mano en `config.yaml` o empujada desde el
> backend llega directo a `fanotify_mark(2)` y falla ahí.

Crear el directorio **antes** de instalar, porque el instalador valida su
existencia:

```bash
sudo mkdir -p /srv/fim-watch
```

**Se espera ver:** el comando termina sin salida y `/srv/fim-watch` existe.

Un `watch_path` agregado **en caliente** desde la consola queda monitoreado pero
**no remediable** hasta que se re-ejecute `agent/install.sh` en el anfitrión: el
`ReadWritePaths` de systemd se resuelve al arrancar el servicio, y el instalador
es quien regenera el drop-in `/etc/systemd/system/fim-agent.service.d/10-watchpaths.conf`.
El agente lo hace visible: la tarjeta del agente en la consola muestra ese path
como solo‑detección (`read_only_mount`).

### Paso 16. Instalar el agente

**En el anfitrión monitoreado**, con el directorio `agent/` disponible y desde la
raíz del repositorio:

```bash
sudo bash agent/install.sh --non-interactive \
  --server-host <host-o-ip-del-servidor> \
  --agent-id <agent_id> \
  --watch-path /srv/fim-watch \
  --ca-cert /tmp/fim-ca.pem \
  --ca-fingerprint <huella-sha256-impresa-por-register-agent.sh> \
  --bootstrap-secret-file /root/fim-bootstrap-secret
```

`--watch-path` se puede repetir para vigilar varias rutas
(`--watch-path /etc --watch-path /usr/bin ...`).

Sin `--non-interactive`, el instalador pregunta por cualquier valor faltante; el
secreto siempre por un prompt oculto que no lo muestra en pantalla.

**Se espera ver**, en orden:

```
[fim-agent] Installing FIM Agent from /ruta/agent
[fim-agent] Created system user: fim-agent
[fim-agent] Created /var/lib/fim-agent/ layout with 0700
[fim-agent] Created /var/log/fim-agent/ and /etc/fim-agent/
[fim-agent] Using /usr/bin/python3 (Python 3.13)
[fim-agent] Created venv at /opt/fim-agent/venv
[fim-agent] Installed Python dependencies into /opt/fim-agent/venv
installer.py: plan
  agent_id=<agent_id>
  backend_url=https://<host>:8444
  mtls_backend_url=https://<host>:8443
  valkey_url=valkeys://<host>:6380
  watch_paths=['/srv/fim-watch']
  bootstrap secret: provided (not shown)
[fim-agent] Plan validated
[fim-agent] Replaced installed code at /opt/fim-agent/agent
[fim-agent] Installed fim-agent.service
[fim-agent] Applied configuration
[fim-agent] Generated /etc/systemd/system/fim-agent.service.d/10-watchpaths.conf ...
[fim-agent] Reloaded systemd
installer.py: scope check <host>:8444 -> OK (ok): <host>:8444 reachable and trusted
installer.py: scope check <host>:6380 -> OK (ok): <host>:6380 reachable and trusted (client cert required, as expected)
[fim-agent] Applied ownership: ...
[fim-agent] Enabled fim-agent.service
[fim-agent] Started fim-agent.service (bootstrap secret provided, no certificate yet)

[fim-agent] Installation complete.
  systemctl status fim-agent
```

Puntos importantes:

- El mensaje `client cert required, as expected` en el chequeo de 6380 **es el
  resultado correcto**: Valkey exige certificado de cliente y el agente todavía
  no tiene el suyo; que el rechazo llegue *después* de una verificación TLS
  exitosa es justamente lo que se quería comprobar.
- Si el chequeo de alcance falla, el script aplica igual la propiedad de los
  archivos (para dejar el host consistente) pero **no habilita el servicio** y
  termina con **exit 3**.
- El instalador es **idempotente** y **reemplaza** el código instalado en vez de
  fusionarlo. Sin `--reconfigure`, `config.yaml` y `/etc/fim-agent/env` quedan
  byte a byte intactos.
- Una ruta relativa en `--ca-cert` o `--bootstrap-secret-file` se resuelve contra
  el directorio desde el que se invocó `install.sh`, no contra `/opt/fim-agent`.

Borrar el archivo del secreto:

```bash
sudo shred -u /root/fim-bootstrap-secret
```

### Paso 17. Verificar el transporte TLS desde el anfitrión monitoreado

#### 17.1 — El servicio está activo

```bash
sudo systemctl status fim-agent
```

**Se espera ver:** `Active: active (running)`.

Si queda en `failed` con código de salida **78**, es un error de **configuración**
(secreto de bootstrap ausente, `shared_secret` ausente, `config.yaml` ausente o
inválido): el unit declara `RestartPreventExitStatus=78` justamente para que el
mensaje se lea una sola vez en lugar de repetirse en bucle cada 5 segundos.

#### 17.2 — El bootstrap se completó

```bash
sudo journalctl -u fim-agent -n 200 --no-pager
```

**Se espera ver:** el bootstrap contra `https://<host>:8444` completado sin
errores y, a continuación, la conexión a `valkeys://<host>:6380` establecida. El
certificado propio del agente queda en `/var/lib/fim-agent/certs/`:

```bash
sudo ls -l /var/lib/fim-agent/certs/
```

**Se espera ver:** `agent-cert.pem` (y su clave privada) presentes. Su existencia
es lo que hace que una reinstalación posterior ya no exija el secreto de
bootstrap.

#### 17.3 — Re-ejecutar la verificación de alcance sin tocar el servicio

El instalador expone su chequeo de red como subcomando independiente, así que se
puede repetir en cualquier momento sin reinstalar:

```bash
cd /opt/fim-agent && sudo ./venv/bin/python -m agent.installer check \
  --non-interactive --server-host <host-o-ip-del-servidor>
```

**Se espera ver:**

```
installer.py: scope check <host>:8444 -> OK (ok): <host>:8444 reachable and trusted
installer.py: scope check <host>:6380 -> OK (ok): <host>:6380 reachable and trusted (client cert required, as expected)
```

Este chequeo hace lo que hay que hacer: resuelve el nombre, abre la conexión TCP,
completa el handshake TLS verificando el certificado del servidor **contra
`/etc/fim-agent/certs/ca.pem`** y comprueba que el SAN cubra el host configurado.
Un fallo indica exactamente en qué etapa (`dns`, `tcp_refused`, `tcp_timeout`,
`tls_verify`, `hostname_mismatch`).

#### 17.4 — El agente aparece en el servidor

**En el servidor:**

```bash
curl -fsS http://127.0.0.1:8000/health/components
```

**Se espera ver:** el `agent_id` recién enrolado en la lista `agents`, y el
agregado pasar a `"ok"` en cuanto el agente esté `online`.

#### 17.5 — Las capabilities están completas

```bash
pid="$(systemctl show --property=MainPID --value fim-agent.service)"
rg '^Cap' "/proc/$pid/status"
```

**Se espera ver:** los conjuntos de capabilities del proceso. Decodificar con
`capsh --decode=<valor de CapEff>`; deben aparecer las cinco:
`cap_sys_admin`, `cap_dac_read_search`, `cap_dac_override`, `cap_fowner`,
`cap_chown`. Sin `cap_sys_admin`, fanotify falla con `EPERM`; sin las tres
últimas, `auto_restore` y `quarantine` fallan siempre con `permission_denied`.

### Paso 18. Crear las reglas de decisión

Un evento solo genera una alerta si su severidad es `high` o `critical`
(RN‑52), y la severidad la asigna una **regla** que hace `fnmatch` sobre la ruta
del evento. Sin reglas, el agente detecta pero no se genera ninguna alerta.

Las reglas se crean desde la consola web, o por API (`POST /rules`). El script de
laboratorio `scripts/seed-reglas-lab.sh` muestra el patrón canónico:

```
<WATCH_PREFIX>/*                     severidad high      acción alert_only
<WATCH_PREFIX>/<subdir>/*            severidad critical  acción alert_only
```

Con `WATCH_PREFIX=/srv/fim-watch`, las reglas serían `/srv/fim-watch/*` y
`/srv/fim-watch/critico/*`. `*` cruza barras, así que `/srv/fim-watch/*` cubre
también los subdirectorios; gana la severidad más alta entre las reglas que
coinciden.

**Recordar la distinción del [Paso 15](#paso-15-preparar-el-directorio-vigilado):**
el glob va en la **regla**; la **ruta de vigilancia** es el directorio
`/srv/fim-watch`, sin `/*`.

---

## Parte D — PKI: cómo se generan y distribuyen los certificados

Nadie ejecuta comandos de OpenSSL a mano. Toda la cadena la emite el servicio
one‑shot `certs-init` (`backend/app/core/certs_init.py`, imagen del backend),
antes de que arranque ningún servicio que la necesite.

### D.1 — Qué emite `certs-init`, en qué orden y dónde

| Paso | Qué emite | Volumen | Ruta dentro del contenedor | Dueño final |
|---|---|---|---|---|
| 1 | **CA propia** (`ca.pem` + `ca-key.pem`) y **certificado de servidor del backend** (`backend.pem` + `backend-key.pem`) | `backend_certs` | `/certs` | uid `10001` (usuario `app` del backend) |
| 2 | **Certificado de servidor de Valkey** (`valkey.pem` + `valkey-key.pem`) y una **copia de `ca.pem`** | `valkey_tls` | `/valkey-certs` | uid `999` (usuario `valkey`) |
| 3 | **Certificado de cliente del backend ante Valkey** (`backend-valkey.pem`, `CN=fim-backend-valkey`) | `backend_certs` | `/certs` | uid `10001` |
| 4 | Solo con `CONSOLE_TLS_MODE=self_signed`: **certificado autofirmado de la consola** (ECDSA P‑256, **no** firmado por la CA propia) | `console_tls_generated` | `/console-certs` | `root` |

`certs-init` corre como `root` (`user: "0:0"`) precisamente para fijar dueño y
modo por archivo en los tres volúmenes. **La clave privada de la CA
(`ca-key.pem`) nunca sale de `backend_certs`**: los volúmenes `valkey_tls` y
`console_tls_generated` reciben, como mucho, una copia del certificado público.

### D.2 — SAN: por qué `FIM_PUBLIC_HOSTS` es decisivo

El SAN de los certificados del backend y de Valkey se calcula como
**nombres internos ∪ `FIM_PUBLIC_HOSTS`**:

- Nombres internos del backend: `backend`, `fim-backend`, `localhost`.
- Nombres internos de Valkey: `valkey`, `localhost`.
- Cada entrada de `FIM_PUBLIC_HOSTS` que parsea como IP se emite como
  `IPAddress`; el resto, como `DNSName`.

Si `FIM_PUBLIC_HOSTS` está vacía, los certificados **no cubren la IP ni el
nombre público**, y el agente remoto falla la verificación de hostname
(`hostname_mismatch` en el chequeo de alcance). Esta es una de las causas más
comunes de una instalación remota que no arranca.

La reemisión es **idempotente**: si el certificado existente cubre el conjunto
requerido y le quedan al menos 15 días de vigencia, no se toca. Agregar un host a
`FIM_PUBLIC_HOSTS` y volver a levantar el stack reemite lo necesario.

### D.3 — Cómo llega la CA al anfitrión monitoreado

```
servidor: backend_certs:/certs/ca.pem
   │
   │  scripts/register-agent.sh  →  docker compose cp backend:/certs/ca.pem ./fim-ca.pem
   ▼
servidor: ./fim-ca.pem   +   huella SHA-256 (impresa por register-agent.sh)
   │
   │  transferencia por canal seguro (scp, gestor de secretos, etc.)
   ▼
anfitrión: /tmp/fim-ca.pem
   │
   │  agent/install.sh --ca-cert /tmp/fim-ca.pem --ca-fingerprint <huella>
   │     └─ installer.py::load_and_verify_ca:
   │          - valida que sea PEM
   │          - valida que sea CA (BasicConstraints ca=True)
   │          - compara SHA-256(DER) contra la huella esperada
   │          - si no coincide, ABORTA antes de escribir nada, mostrando ambas
   ▼
anfitrión: /etc/fim-agent/certs/ca.pem   (0644, root:root)
```

La huella se normaliza sin distinguir mayúsculas y ignorando `:` y espacios
(`normalize_fingerprint`), así que se puede pegar en el formato que imprime
OpenSSL.

### D.4 — Cómo obtiene el agente su propio certificado

1. El agente genera un CSR localmente.
2. Lo envía por `POST /agents/bootstrap` al **puerto 8444** (TLS 1.3, el agente
   verifica el certificado del servidor contra `ca.pem`; el servidor **no** exige
   certificado de cliente, porque el agente todavía no tiene uno).
3. El backend verifica el secreto de bootstrap (Argon2id), valida el CSR, emite
   el certificado firmado por la CA propia y responde con el certificado, la CA,
   un `shared_secret` y un `master_secret`.
4. El backend **anula el hash del secreto de bootstrap**: es de un solo uso.
5. El agente guarda su certificado en `/var/lib/fim-agent/certs/` y a partir de
   ahí usa mTLS: **8443** para renovar su certificado y **6380** para Valkey.

El puerto 8444 existe precisamente porque el listener de 8443 usa
`ssl.CERT_REQUIRED` y un agente recién instalado no podría completar ese
handshake. Ambos listeners fijan **TLS 1.3 como piso**.

### D.5 — Renovación

- **Backend y Valkey:** `certs-init` reemite automáticamente en cada `up` o
  reinicio del stack cuando al certificado le quedan menos de **15 días**. No
  requiere acción manual, siempre que el stack se reinicie con cierta
  regularidad (recomendado: antes del día 75 de cada certificado de 90 días).
  **La CA no se rota.**
- **Consola en modo `provided`:** renovar con la herramienta correspondiente
  (por ejemplo `certbot renew`) apuntando al mismo directorio montado en
  `CONSOLE_TLS_DIR`, y después reiniciar el frontend — nginx no relee el
  certificado en caliente:

  ```bash
  docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app restart frontend
  ```
- **Agente:** renueva su propio certificado por `POST /agents/renew` sobre el
  puerto 8443.

> ⚠️ **No borrar el volumen `backend_certs`.** Ahí vive la clave privada de la CA.
> Si se elimina (por ejemplo con `docker compose down -v`), `certs-init` emite una
> **CA nueva**: cambia la huella SHA‑256, los certificados de todos los agentes ya
> enrolados dejan de ser válidos, y hay que volver a distribuir `ca.pem` y
> re‑enrolar cada anfitrión.

---

## Parte E — Verificación final

Ejecutar en orden. Cada punto tiene un comando y una salida esperada.

### E.1 — Servicios del servidor

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app ps
```

**Se espera ver:** `db` `Up (healthy)`, `valkey` `Up (healthy)`, `n8n`
`Up (healthy)`, `backend` `Up`, `frontend` `Up`, `certs-init` `Exited (0)`.

### E.2 — PostgreSQL

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  exec db pg_isready -U fim -d fim
```

**Se espera ver:** `accepting connections`.

Ambas bases deben existir (`fim` para la aplicación, `fim_n8n` para n8n,
creada por `db/init/01-create-databases.sql` en el primer arranque):

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  exec db psql -U fim -d fim -c '\l'
```

**Se espera ver:** `fim` y `fim_n8n` en el listado, ambas con owner `fim`.

### E.3 — Valkey sobre TLS

Este es el comando exacto del healthcheck de `docker-compose.tls.yml`:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  exec valkey valkey-cli --tls -p 6380 \
    --cert /certs/valkey.pem --key /certs/valkey-key.pem --cacert /certs/ca.pem ping
```

**Se espera ver:** `PONG`.

Si esto responde pero el agente no conecta, revisar el filtro de `DOCKER-USER`
del [Paso 10](#paso-10-restringir-el-acceso-a-los-puertos-publicados).

### E.4 — n8n

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  exec n8n wget -q -O - http://127.0.0.1:5678/healthz
```

**Se espera ver:** una respuesta de estado correcta de n8n (es el mismo comando
del healthcheck del servicio).

### E.5 — Backend

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/health/components
```

**Se espera ver:** `{"status":"ok"}`; y luego un JSON con `postgres: "ok"`,
`valkey: "ok"`, `n8n: "ok"` (si `N8N_HEALTH_URL` está configurada) y `agents`.

> `n8n: "ok"` confirma únicamente que n8n responde en `/healthz`. **No** confirma
> que una alerta se vaya a entregar: sin ningún canal en `N8N_FIM_CHANNELS`, el
> enrutador responde `channel_disabled` (502) a cualquier `POST`, y eso es el
> comportamiento correcto.

### E.6 — Listeners TLS del backend

```bash
curl -k https://<host-publico>:8444/
```

**Se espera ver:** cualquier respuesta HTTP, incluido un **404**. Eso ya confirma
que el listener TLS de bootstrap está arriba. El 8444 solo expone
`POST /agents/bootstrap`, así que un 404 en `/` es lo normal.

```bash
curl -k https://<host-publico>:8443/
```

**Se espera ver:** un **fallo de handshake TLS**. Es el comportamiento correcto:
8443 exige certificado de cliente (`CERT_REQUIRED`) y `curl` no lo presenta. No
es una falla del backend.

### E.7 — Consola web

```bash
curl -fsSI http://<host-publico>:<CONSOLE_HTTP_PORT>/
```

**Se espera ver:** en `CONSOLE_TLS_MODE=off`, un `200 OK` sirviendo la SPA. En
`self_signed` o `provided`, un `301` redirigiendo a HTTPS.

El proxy de la consola hacia el backend está en `/api/`, así que también:

```bash
curl -fsS http://<host-publico>:<CONSOLE_HTTP_PORT>/api/health
```

**Se espera ver:** `{"status":"ok"}`. Si esto funciona pero el login da 403, el
problema es `CORS_ALLOWED_ORIGINS`.

### E.8 — Agente

**En el anfitrión monitoreado:**

```bash
sudo systemctl status fim-agent
```

**Se espera ver:** `Active: active (running)`.

**Prueba funcional de punta a punta:** modificar un archivo dentro de un
`watch_path` y confirmar que el evento aparece en la consola en el orden de los
segundos:

```bash
sudo touch /srv/fim-watch/prueba.txt
echo "cambio" | sudo tee -a /srv/fim-watch/prueba.txt
```

**Se espera ver:** un evento nuevo en la consola para ese path. Si la regla
correspondiente asigna severidad `high` o `critical`, además se genera una
alerta.

---

## Parte F — Problemas frecuentes

### F.1 — El agente no conecta: `Connection refused` / `Error 111` contra el 6380

**Síntoma.** El agente estaba andando y de golpe no publica más eventos; el log
muestra conexión rechazada al puerto 6380. `docker compose ps` parece normal.

**Causa.** Algún comando de Compose se ejecutó **sin** `-f docker-compose.tls.yml`
y recreó `valkey` con la configuración base: sin TLS, sin `--tls-port 6380` y sin
publicar el 6380 al host. El puerto simplemente ya no existe.

**Solución.** Volver a levantar con los dos archivos:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d
```

Y confirmar que el 6380 está publicado:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app port valkey 6380
```

**Prevención.** [Regla 1](#regla-1--siempre-los-dos-archivos-de-compose).

### F.2 — `docker compose` falla antes de arrancar nada

**Síntoma.** Cualquier subcomando termina con exit distinto de 0 y el mensaje
nombra `N8N_ENCRYPTION_KEY`.

**Causa.** Falta el `.env`, o la variable está vacía. `docker-compose.yml` la
declara con `:?`, que aborta la composición.

**Solución.** Crear el `.env` ([Paso 2](#paso-2-crear-el-archivo-env)).

### F.3 — El login de n8n falla sin ningún mensaje claro

**Síntoma.** n8n arranca, `/healthz` responde, pero no se puede entrar a su UI con
la contraseña del owner.

**Causa.** El hash bcrypt de `N8N_INSTANCE_OWNER_PASSWORD_HASH` llegó **truncado**:
Docker Compose interpoló los `$` del hash como referencias a variables y los
reemplazó por cadena vacía, sin emitir ningún error.

**Solución.** Escribir el hash con `$$` en lugar de cada `$`, y verificar el valor
resuelto:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml config | rg N8N_INSTANCE_OWNER_PASSWORD_HASH
```

El valor debe verse completo, con un solo `$` (Compose ya resolvió el `$$`).
Después: `docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d n8n`.

**Causa alternativa.** Se puso la contraseña en claro en lugar del hash. La
variable **es** un hash bcrypt.

### F.4 — n8n no arranca tras reinstalar sobre volúmenes viejos

**Síntoma.** El contenedor `n8n` no llega a `healthy` después de recrear el stack
con un `.env` nuevo; las credenciales guardadas dejan de funcionar.

**Causa.** La clave de cifrado de n8n queda **guardada dentro de su propio
volumen** (`n8n_data`, montado en `/home/node/.n8n`). Si el volumen sobrevivió a
una instalación previa y `N8N_ENCRYPTION_KEY` del `.env` no coincide con la
almacenada, n8n no puede descifrar sus credenciales. Como documenta
`docs/n8n_estado_y_requisitos.md` §188‑189: sin `N8N_ENCRYPTION_KEY` explícita las
credenciales quedan atadas a una clave autogenerada dentro del volumen, y recrear
el volumen las invalida **en silencio**.

**Solución A — reutilizar la clave que ya está en el volumen.** Inspeccionar el
contenido de la configuración persistida de n8n y recuperar de ahí la clave, para
escribirla en el `.env`:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  exec n8n ls -la /home/node/.n8n
```

(Ese es el punto de montaje declarado en `docker-compose.yml`:
`n8n_data:/home/node/.n8n`.) La ubicación exacta del campo dentro de esa
configuración no está fijada por este repositorio; ver
[Limitaciones](#16-limitaciones-de-esta-guía).

**Solución B — empezar limpio.** Eliminar únicamente el volumen de n8n y dejar
que se reinicialice con la clave del `.env`:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app stop n8n
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app rm -f n8n
docker volume rm "$(basename "$PWD")_n8n_data"
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d n8n
```

> ⚠️ Esto **borra** los workflows y credenciales que n8n tuviera guardados. Los
> workflows de la plataforma se re‑provisionan solos desde `n8n/workflows/` en el
> entrypoint del contenedor; las credenciales configuradas a mano en la UI de n8n,
> no.
>
> ⚠️ **Nunca usar `docker compose down -v` para esto:** ese comando borra *todos*
> los volúmenes, incluido `backend_certs` con la clave privada de la CA. Ver
> [Parte D.5](#d5--renovación).

### F.5 — `password authentication failed for user "fim"`

**Síntoma.** El backend (o n8n) no conecta a PostgreSQL; el log de `db` muestra
`password authentication failed for user "fim"`.

**Causa.** `DB_PASSWORD` del `.env` no coincide con la contraseña que quedó grabada
en el volumen `pg_data` cuando la base se inicializó. La imagen de PostgreSQL
**no** re‑ejecuta los scripts de init ni actualiza la contraseña cuando cambia la
variable de entorno: `POSTGRES_PASSWORD` solo tiene efecto en el primer arranque
sobre un volumen vacío. Está documentado en el propio `.env.example`.

**Solución A — alinear la base al `.env` (conserva los datos):**

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  exec db psql -U fim -d fim -c "ALTER USER fim WITH PASSWORD '<valor-de-DB_PASSWORD>';"
```

Después, reiniciar el backend y n8n para que reconecten con la contraseña nueva.

> Si el usuario `fim` ya no puede autenticarse ni siquiera para correr el
> `ALTER USER`, hay que entrar por otra vía (por ejemplo, un `psql` local dentro
> del contenedor mediante el socket Unix, que por defecto confía en el usuario del
> sistema) o recurrir a la Solución B.

**Solución B — base limpia (BORRA TODOS LOS DATOS):**

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app down -v
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d --build
```

> ⚠️ **`down -v` borra todos los volúmenes del proyecto:** `pg_data` (eventos,
> alertas, auditoría), `valkey_data`, `n8n_data` y **`backend_certs` — que
> contiene la clave privada de la CA**. Al volver a levantar, `certs-init` emite
> una **CA nueva**: todos los agentes enrolados quedan con certificados inválidos
> y hay que re‑enrolarlos con la nueva `ca.pem` y su nueva huella. No es un
> "reinicio limpio": es una instalación nueva.

### F.6 — El login de la consola devuelve 429

**Síntoma.** Después de varios intentos, el login responde `429` con
`Too many login attempts. Try again later.`

**Causa.** **Es comportamiento esperado, no una falla de la instalación.** El
backend limita a **5 intentos** de login por ventana de **900 segundos**
(`rate_limit_login_attempts` / `rate_limit_login_window_seconds` en
`backend/app/core/config.py`).

**Solución.** Esperar a que la ventana se libere. Si se está diagnosticando otra
cosa, dejar de probar credenciales: cada intento extiende el bloqueo y oculta el
problema real.

### F.7 — El login de la consola devuelve 403

**Síntoma.** Credenciales correctas, pero el POST de login responde `403`.

**Causa.** El origen desde el que se abre la consola no está en
`CORS_ALLOWED_ORIGINS`. El navegador envía el header `Origin` en todo POST,
**incluso same-origin detrás de un proxy**; sin el origen exacto del host público
en esa lista, `CORSOriginMiddleware` rechaza la petición.

Es el caso típico de un `.env` copiado a mano de `.env.example`, cuyo valor por
defecto es `http://localhost,http://localhost:80,http://127.0.0.1`: sirve para
probar en la propia máquina, no para entrar por la IP pública.

**Solución.** Agregar el origen exacto (esquema + host + puerto si no es el
default del esquema) a `CORS_ALLOWED_ORIGINS` en el `.env` y recrear el backend.
`scripts/prepare_server_env.py` lo deriva automáticamente de
`FIM_PUBLIC_HOSTS ∪ {localhost}` con **ambos** esquemas (`http` y `https`),
justamente para que cambiar `CONSOLE_TLS_MODE` no obligue a editarlo a mano.

### F.8 — `agent/install.sh` termina con exit 3

**Síntoma.** La instalación llega hasta el final, aplica la propiedad de los
archivos, y termina con:

```
[fim-agent] Scope check failed (see diagnostics above) — service NOT enabled.
```

**Causa.** La verificación previa de alcance a 8444 y/o 6380 falló. La línea
anterior nombra la etapa exacta:

| Etapa | Qué significa | Dónde mirar |
|---|---|---|
| `dns` | El nombre del servidor no resuelve desde el anfitrión | DNS / `/etc/hosts` del anfitrión |
| `tcp_refused` | Nada escucha en ese puerto, o un firewall lo rechaza | Que el stack esté arriba **con los dos archivos de compose**; reglas de `DOCKER-USER` |
| `tcp_timeout` | El paquete se pierde | Firewall intermedio, grupo de seguridad del proveedor |
| `tls_verify` | El certificado del servidor no valida contra la `ca.pem` instalada | Que la `ca.pem` sea la del servidor actual (¿se regeneró la CA?) |
| `hostname_mismatch` | El certificado no cubre el host configurado | **`FIM_PUBLIC_HOSTS` no incluye ese host.** Agregarlo y volver a levantar el stack para que `certs-init` reemita |

**Solución.** Corregir la causa y re‑ejecutar `agent/install.sh` (es idempotente),
o solo el chequeo con `python -m agent.installer check` ([Paso 17.3](#173--re-ejecutar-la-verificación-de-alcance-sin-tocar-el-servicio)).

### F.9 — `CA fingerprint mismatch`

**Síntoma.** El instalador aborta **antes** de escribir nada:

```
installer.py: CA fingerprint mismatch: expected <a>, got <b>
```

**Causa.** El `fim-ca.pem` copiado no es el del servidor actual, o la huella se
pegó de otra corrida. Casi siempre: se regeneró la CA en el servidor (volumen
`backend_certs` borrado) y se está usando una huella vieja, o al revés.

**Solución.** Volver a exportar la CA y su huella desde el servidor con
`scripts/register-agent.sh` y usar ese par. Es una verificación deliberada: no
tiene bypass, y así debe ser.

### F.10 — El agente arranca pero no detecta nada: `fanotify_mark: No such file or directory`

**Síntoma.** El servicio está `active (running)`, pero ningún cambio en el
directorio produce eventos. El log muestra un error de `fanotify_mark`.

**Causa.** Un **glob** quedó configurado como ruta de vigilancia
(`/srv/fim-watch/*` en lugar de `/srv/fim-watch`). `fanotify_mark(2)` necesita un
directorio real, no un patrón. Los globs son para las **reglas**, no para los
`watch_paths`.

**Solución.** Corregir el `watch_path` a un directorio existente:

```bash
sudo bash agent/install.sh --non-interactive --reconfigure \
  --server-host <host> --agent-id <agent_id> \
  --watch-path /srv/fim-watch \
  --ca-cert /tmp/fim-ca.pem --ca-fingerprint <huella> \
  --bootstrap-secret-file <archivo>
```

> `--reconfigure` reescribe `config.yaml` y `env`, guardando una copia
> `.bak-<timestamp>`. Tras el primer bootstrap exitoso la configuración
> autoritativa vive en el backend y se administra desde la consola: el
> `watch_path` conviene corregirlo ahí y luego re‑ejecutar `install.sh` **sin**
> `--reconfigure` para regenerar el drop-in de `ReadWritePaths`.

Ver también [Paso 15](#paso-15-preparar-el-directorio-vigilado).

### F.11 — El bootstrap falla con 401 al reintentar

**Síntoma.** El primer bootstrap parecía haber fallado; al reintentar con el mismo
secreto, el backend responde `401 invalid credentials`.

**Causa.** **El secreto de bootstrap es de un solo uso.** Si el bootstrap llegó a
completarse del lado del servidor (aunque el agente no lo haya registrado como
éxito), `bootstrap_secret_hash` ya fue anulado y ningún reintento va a funcionar.

**Cómo distinguir los casos:**

```bash
sudo ls -l /var/lib/fim-agent/certs/
```

- **Si `agent-cert.pem` existe**, el bootstrap sí se completó: el agente ya está
  enrolado y no necesita el secreto. Reinstalar sin `--bootstrap-secret-file` y
  sin `--reconfigure`.
- **Si no existe**, el bootstrap no llegó a guardar nada localmente pero el
  secreto pudo consumirse igual.

**Solución.** Re‑ejecutar `scripts/register-agent.sh` con el **mismo** `agent_id`
devuelve `409 agent '<id>' already registered` y **no** emite un secreto nuevo.
Este repositorio no expone un comando ni un endpoint para reemitir el secreto de
bootstrap de un `agent_id` ya registrado; ver
[Limitaciones](#16-limitaciones-de-esta-guía). La salida practicable es registrar
el anfitrión bajo un `agent_id` nuevo:

```bash
scripts/register-agent.sh <agent_id>-2
```

### F.12 — Se pierden eventos en una ráfaga grande

**Síntoma.** Una modificación masiva (un despliegue, un `apt upgrade`, una
restauración de backup) genera muchos más eventos de los que llegan a la consola
de inmediato.

**Causa.** El consumer del stream `events` aplica un rate limit por ventana
deslizante **por `agent_id`**: por defecto **`RATE_LIMIT_INGEST_EVENTS=100` cada
`RATE_LIMIT_INGEST_WINDOW_SECONDS=60`**. Los eventos que exceden el presupuesto
no se descartan: reciben un `event_nack` de tipo `rate_limited` con un
`retry_after` derivado de esa misma ventana, y el agente los **reintenta** cuando
se libera cupo.

**Qué significa en la práctica.** Una ráfaga de, por ejemplo, 3.000 eventos no se
pierde, pero tarda: a 100 por minuto, el drenaje completo se extiende por unos 30
minutos. Mientras tanto los eventos se acumulan en la cola local del agente
(`/var/lib/fim-agent/queue`, con un tope de 100 MB y política drop‑oldest). Un
evento que agota `publisher.max_publish_attempts` (20 por defecto, con reintentos
cada ~60 s ≈ 20 horas) termina en `/var/lib/fim-agent/discarded` con razón
`max_attempts_exceeded` — ahí sí hay pérdida, y el contenido de ese directorio es
evidencia de una detección perdida, no datos descartables.

**Solución.** Si se espera una ráfaga legítima (una batería de medición, una
migración), subir `RATE_LIMIT_INGEST_EVENTS` en el `.env` y recrear el backend.
Los valores por defecto son los de producción; subirlos permanentemente cambia el
perfil de protección contra un agente comprometido o en bucle.

### F.13 — `ADMIN_PASSWORD` del `.env` no se aplica

**Síntoma.** Se cambió `ADMIN_PASSWORD` en el `.env`, se reinició el stack, y el
login sigue pidiendo la contraseña vieja. El log del backend muestra un `warning`
`seed_admin.env_password_ignored`.

**Causa.** Es deliberado: si el usuario admin ya existe, aplicar el valor del
entorno en cada arranque dejaría que un `.env` viejo o filtrado sobrescriba una
contraseña que el operador ya cambió a mano.

**Solución.** Aplicarlo explícitamente:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app \
  exec backend python -m app.modules.auth.cli reset-admin-password
```

Esto hashea la contraseña con Argon2id, fuerza `must_change_password=True` (el
próximo login exige elegir una nueva) y deja registro en `audit_log` con
`action="reset_admin_password_cli"`.

### F.14 — Un `watch_path` aparece como solo‑detección en la consola

**Síntoma.** La tarjeta del agente marca un path como `read_only_mount` o
`permission_denied`: se detectan cambios pero `auto_restore` y `quarantine`
fallan.

**Causa y solución.**

1. `read_only_mount` → falta el drop-in de `ReadWritePaths` para ese path. Ocurre
   siempre que se agrega un `watch_path` en caliente desde la consola. Confirmar
   con `systemctl cat fim-agent.service` que `10-watchpaths.conf` lo incluye; si
   no, re‑ejecutar `agent/install.sh` (sin `--reconfigure`) y
   `sudo systemctl restart fim-agent`.
2. `permission_denied` con el path ya en el drop-in → revisar las capabilities
   antes que los permisos del filesystem ([Paso 17.5](#175--las-capabilities-están-completas)).
   `CAP_DAC_OVERRIDE` cubre la mayoría de los casos DAC, así que su ausencia es la
   causa más común.
3. `missing` → el path configurado no existe en el anfitrión.

### F.15 — El servicio `fim-agent` queda en `failed` y no reintenta

**Síntoma.** `systemctl status fim-agent` muestra `failed` con código de salida
**78** y el servicio no vuelve a intentar arrancar.

**Causa.** Es intencional. El unit declara `RestartPreventExitStatus=78`
(`78 = EX_CONFIG`): los fallos de **configuración** del arranque (secreto de
bootstrap ausente, `shared_secret` ausente, `config.yaml` ausente o inválido)
salen con ese código para que el error se lea una sola vez, en lugar de repetirse
cada 5 segundos en un bucle indefinido. Los fallos transitorios (Valkey caído,
red) usan otros códigos y sí se reintentan.

**Solución.** Leer el mensaje en `journalctl -u fim-agent`, corregir la
configuración, y `sudo systemctl start fim-agent`.

---

## Parte G — Operación posterior

### G.1 — Actualizar el código del agente

`agent/install.sh` es idempotente y **reemplaza** el árbol de código instalado en
lugar de fusionarlo (`/opt/fim-agent/agent` queda idéntico a la fuente, sin
archivos viejos sobrantes). Si el servicio estaba activo, lo reinicia.

Si el agente **ya se enroló**, `--bootstrap-secret-file` ya no es obligatorio:

```bash
sudo bash agent/install.sh --non-interactive \
  --server-host <host> --agent-id <agent_id> \
  --watch-path /srv/fim-watch --ca-cert ./fim-ca.pem --ca-fingerprint <huella>
```

Sin `--reconfigure`, `config.yaml` y `/etc/fim-agent/env` quedan byte a byte
intactos.

### G.2 — Habilitar canales de notificación en n8n

Las variables de canal (`N8N_FIM_CHANNELS` y las específicas de email, Slack,
Jira o Linear) se completan a mano en el `.env`. Cambiarlas **sí** dispara la
recreación del contenedor `n8n` en la próxima `up -d`, que es exactamente lo que
hace falta para que el canal nuevo quede provisionado (el provisioning corre en
el entrypoint de `n8n`, antes de que arranque el proceso).

Ejemplo verificado, canal de email con Gmail (requiere una
[contraseña de aplicación](https://myaccount.google.com/apppasswords), porque
Gmail rechaza la contraseña de la cuenta para SMTP de terceros):

```bash
N8N_FIM_CHANNELS=email
N8N_EMAIL_FROM=tu-cuenta@gmail.com
N8N_EMAIL_TO=destino@ejemplo.org
N8N_EMAIL_SMTP_HOST=smtp.gmail.com
N8N_EMAIL_SMTP_PORT=587
N8N_EMAIL_SMTP_USER=tu-cuenta@gmail.com
N8N_EMAIL_SMTP_PASSWORD=<contraseña-de-aplicación-de-16-caracteres>
N8N_EMAIL_SMTP_SECURE=false
```

`N8N_EMAIL_SMTP_SECURE=false` con el puerto 587 significa **STARTTLS**, no una
conexión sin cifrar: es la combinación que Gmail espera en 587. `secure=true` es
para el 465 (TLS implícito).

Luego:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml --profile app up -d
```

### G.3 — Levantar el laboratorio todo‑en‑una‑máquina

Solo para desarrollo o pruebas, nunca en un servidor real. El servicio `agent`
del compose usa un secreto de bootstrap por defecto:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml \
  --profile app --profile lab up -d
scripts/setup-agent.sh <password-actual-del-admin>
```

`scripts/setup-agent.sh` registra el agente `docker-agent` vía la API HTTP
(`http://localhost:8000`) con el secreto `docker-bootstrap-secret` y reinicia el
contenedor para que haga bootstrap. Los archivos vigilados se editan en
`./fim-watch` del host, que el contenedor ve como `/watch`.

### G.4 — Verificar la integridad de las especificaciones (desarrollo)

```bash
python3 scripts/check_spec_integrity.py
```

Sin dependencias; exit 1 si falla. Correr antes y después de cada
`openspec archive`.

---

## 16. Limitaciones de esta guía

Lo siguiente **no** se pudo verificar contra un archivo de este repositorio y por
lo tanto **no** se documenta como comando ejecutable:

1. **Lectura de la clave de cifrado existente de n8n desde su volumen.** Se
   verificó que el volumen es `n8n_data` montado en `/home/node/.n8n`
   (`docker-compose.yml`) y que la clave queda atada a ese volumen
   (`docs/n8n_estado_y_requisitos.md` §188‑189, `CHANGES.md`). El **nombre del
   archivo y el campo exactos** donde n8n persiste esa clave no están fijados por
   ningún archivo de este repositorio, así que la [Solución A de F.4](#f4--n8n-no-arranca-tras-reinstalar-sobre-volúmenes-viejos)
   indica inspeccionar el directorio en lugar de dar una ruta inventada. La
   Solución B (empezar limpio) sí está completamente verificada.

2. **Reemisión de un secreto de bootstrap para un `agent_id` ya registrado.**
   `backend/app/modules/agents/cli.py` solo expone `register`, que falla con 409
   si el agente existe; `backend/app/modules/agents/router.py` no expone ningún
   endpoint de reemisión ni de baja de agentes. **No existe un camino soportado
   para reemitir el secreto**: la guía propone registrar un `agent_id` nuevo, que
   es la única salida verificable.

3. **Recuperación cuando el usuario `fim` de PostgreSQL no puede autenticarse.**
   La [Solución A de F.5](#f5--password-authentication-failed-for-user-fim)
   (`ALTER USER`) requiere una sesión `psql` que funcione. El camino alternativo
   (entrar por el socket Unix dentro del contenedor, que por defecto usa
   autenticación `trust`/`peer` local) es comportamiento estándar de la imagen de
   PostgreSQL, **no** algo configurado por este repositorio: se menciona como
   orientación, sin comando.

4. **Versiones mínimas exactas de Docker Engine y Docker Compose.** El repositorio
   exige Compose **v2** (por el uso de `profiles`, la ausencia de `version:` y el
   plugin `docker compose`) y `scripts/prepare_server_env.py` documenta una
   verificación empírica contra Compose v5.5.0. **No hay una versión mínima
   declarada** en ningún archivo, así que esta guía no la afirma.

5. **Distribución del secreto de bootstrap y de la CA entre máquinas.** Los
   comandos `scp` del [Paso 14](#paso-14-transferir-la-ca-la-huella-y-el-secreto-al-anfitrión)
   son una sugerencia genérica de transferencia, no un procedimiento de este
   repositorio: `docs/despliegue_servidor_remoto.md` §6 dice "por un canal que el
   operador considere seguro" sin fijar ninguno.

6. **Discrepancia documental detectada.** `docs/despliegue_servidor_remoto.md` §4
   describe `GET /health/components` como un endpoint **autenticado**. El código
   dice lo contrario: `backend/app/main.py` lo declara con el comentario
   *"Sin auth JWT (RN-101 — monitoreo sin login). Siempre retorna 200."* Esta guía
   sigue el código, y por eso los comandos de verificación usan `curl` sin token.
   La discrepancia queda señalada aquí para que se corrija en el documento
   correspondiente.

---

## 17. Documentación relacionada

- [docs/despliegue_servidor_remoto.md](docs/despliegue_servidor_remoto.md) — guía
  de producto del despliegue remoto: `.env`, modos de consola, registro e
  instalación del agente, verificación, reset de admin, renovación de certificados.
- [docs/operations.md](docs/operations.md) — guía operativa: variables de entorno,
  formato de logs, retención, instalación del agente como unit de systemd,
  diagnóstico de capabilities y de paths no remediables, directorio de descarte.
- [docs/arquitectura_stack.md](docs/arquitectura_stack.md) — stack, modelo de
  eventos, decision engine, baseline cifrado AES‑GCM, mTLS, máquina de estados,
  topología y puertos.
- [docs/flujo_de_usuario.md](docs/flujo_de_usuario.md) — flujos de UI/UX por pantalla.
- [docs/historias_de_usuario.md](docs/historias_de_usuario.md) — historias priorizadas.
- [docs/reglas_de_negocio.md](docs/reglas_de_negocio.md) — reglas de negocio.
- [docs/n8n_estado_y_requisitos.md](docs/n8n_estado_y_requisitos.md) — estado y
  requisitos del componente de notificaciones.
- [tesis/cierre/REPRODUCIR.md](tesis/cierre/REPRODUCIR.md) — procedimiento de
  reproducción de la validación de cierre.
- [CHANGES.md](CHANGES.md) — roadmap de changes (M1 → M4).
- [CLAUDE.md](CLAUDE.md) — convenciones del proyecto y workflow de implementación.
