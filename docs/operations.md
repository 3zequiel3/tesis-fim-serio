# FIM Platform — Guía Operativa

Referencia de operación para desplegar y mantener la FIM Platform en producción.

---

## Variables de entorno requeridas

El backend usa `pydantic-settings` para leer todas sus variables de entorno (o un archivo `.env`).
Si falta alguna variable **obligatoria**, el proceso falla al arranque con un `ValidationError`
(fail-fast — no acepta conexiones con configuración incompleta).

### Obligatorias (sin default)

| Variable | Tipo | Descripción |
|----------|------|-------------|
| `DATABASE_URL` | `PostgresDsn` | Cadena de conexión a PostgreSQL 18.3. Ej: `postgresql+psycopg://fim:password@db:5432/fim` |
| `VALKEY_URL` | `str` | URL del servidor Valkey 9.0.3. Ej: `valkey://valkey:6379` |
| `JWT_SECRET_CURRENT` | `str` | Clave de firma JWT activa (mínimo 32 caracteres). Rotar con `JWT_SECRET_PREVIOUS`. |

### Auth

| Variable | Tipo | Default | Descripción |
|----------|------|---------|-------------|
| `JWT_SECRET_PREVIOUS` | `str` | `""` | Clave JWT anterior. Permite rotación sin invalidar tokens existentes. |
| `ADMIN_USERNAME` | `str` | `""` | Email/username del primer admin (creado por `seed_admin` al arranque). |
| `ADMIN_PASSWORD` | `SecretStr` | `""` | Password del primer admin. Mínimo 12 caracteres. |

### CORS

| Variable | Tipo | Default | Descripción |
|----------|------|---------|-------------|
| `CORS_ALLOWED_ORIGINS` | `str` | `""` | Lista de origins permitidos separados por coma. Ej: `http://localhost:5173,https://fim.example.com` |

### PKI / mTLS

| Variable | Tipo | Default | Descripción |
|----------|------|---------|-------------|
| `CA_CERT_PATH` | `str` | `""` | Path al certificado de la CA raíz para mTLS agente↔backend. |
| `CA_KEY_PATH` | `str` | `""` | Path a la clave privada de la CA. |
| `BACKEND_CERT_PATH` | `str` | `""` | Path al certificado TLS del backend. |
| `BACKEND_KEY_PATH` | `str` | `""` | Path a la clave privada del backend. |

### Comportamiento del backend

| Variable | Tipo | Default | Descripción |
|----------|------|---------|-------------|
| `ENVIRONMENT` | `str` | `dev` | Entorno de ejecución. Usado en logs y trazas. Valores típicos: `dev`, `staging`, `prod`. |
| `LOG_LEVEL` | `str` | `INFO` | Nivel de log. Valores: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

### Rate limiting (C20)

| Variable | Tipo | Default | Descripción |
|----------|------|---------|-------------|
| `RATE_LIMIT_LOGIN_ATTEMPTS` | `int` | `5` | Intentos de login máximos antes de bloquear por ventana. |
| `RATE_LIMIT_LOGIN_WINDOW_SECONDS` | `int` | `900` | Duración de la ventana de rate limit de login (segundos). Default: 15 min. |
| `RATE_LIMIT_API_PER_MINUTE` | `int` | `100` | Requests por minuto permitidos por `user_id` autenticado. |

### Notificaciones

Todas opcionales. Si no se configuran, el canal correspondiente se omite silenciosamente.

| Variable | Tipo | Default | Descripción |
|----------|------|---------|-------------|
| `N8N_WEBHOOK_URL` | `str` | `""` | URL del webhook n8n para fan-out de alertas. |
| `SMTP_HOST` | `str` | `""` | Host SMTP para notificaciones por email. |
| `SMTP_PORT` | `int` | `587` | Puerto SMTP. |
| `SMTP_USER` | `str` | `""` | Usuario SMTP. |
| `SMTP_PASSWORD` | `str` | `""` | Password SMTP. |
| `SMTP_FROM` | `str` | `""` | Dirección `From` para emails. |
| `SMTP_TO` | `str` | `""` | Dirección `To` para emails de alerta. |
| `WEBHOOK_FALLBACK_URL` | `str` | `""` | URL de webhook de fallback si n8n no está disponible. |

---

## Formato de logs estructurados

El backend emite logs en JSON estructurado via `structlog`. Cada línea de log es un objeto JSON
con los siguientes campos fijos:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `timestamp` | `str` (ISO 8601) | Fecha y hora UTC del evento de log. |
| `level` | `str` | Nivel del log: `debug`, `info`, `warning`, `error`, `critical`. |
| `trace_id` | `str` | UUID de la request HTTP que originó el evento (inyectado por `TraceIdMiddleware`). Ausente en eventos de background. |
| `module` | `str` | Módulo o componente que emitió el log (ej: `service.ingest`, `auth.login`). |
| `message` | `str` | Descripción del evento. |
| `event` | `str` | Identificador de evento machine-readable en `snake_case`. |

### Ejemplo de log JSON

```json
{
  "timestamp": "2026-06-21T14:32:05.123456Z",
  "level": "info",
  "trace_id": "a3f2b1c4-d5e6-7890-abcd-ef1234567890",
  "module": "events.service",
  "event": "service.ingest_ok",
  "message": "Event ingested successfully",
  "path": "/etc/passwd",
  "agent_id": "agent-prod-01",
  "event_id": "eid-abc123"
}
```

### Nivel de log configurable

El nivel de log se controla con la variable de entorno `LOG_LEVEL` (default: `INFO`).

En producción se recomienda `INFO`. Para debugging de rate limiting o flujos de agentes, usar `DEBUG`.

Los logs se emiten a stdout. En Docker Compose, el collector de logs del host los captura.
Se recomienda redirigir stdout hacia un sistema de logs centralizado (Loki, CloudWatch, etc.)
en entornos de producción.

---

## Retención de datos

### Política (RN-98)

- Los eventos con estado **terminal** (`approved`, `rejected`, `auto_restored`, `quarantined`,
  `alert_only`, `superseded`) son elegibles para eliminación automática tras **30 días**.
- Los eventos **referenciados en `audit_log`** (`target_type = "event"`) son **preservados
  indefinidamente**, independientemente de su antigüedad.
- Los eventos con estado `pending` nunca son eliminados por la tarea de retención.

### Implementación

La tarea `retention_task()` en `backend/app/modules/events/service.py` corre como una
corutina asyncio en background (registrada en el lifespan de FastAPI). Ejecuta cada **1 hora**
y elimina en batch los eventos elegibles.

La compactación de cadenas (`compact_chain()`) corre en la misma transacción que la ingestión
de eventos: si un path acumula más de **10 eventos superseded**, elimina los más antiguos
que no estén protegidos por `audit_log`.

### Configuración del job

La retención es automática — no requiere configuración adicional. Los parámetros internos son:

| Parámetro | Valor | Ubicación |
|-----------|-------|-----------|
| Intervalo entre runs | 3600 segundos (1 hora) | `service.py: retention_task()` |
| Días de retención | 30 | `service.py: _RETENTION_DAYS = 30` |
| Máximo cadena superseded | 10 | `service.py: _MAX_CHAIN = 10` |

Para modificar estos valores, editar las constantes en `backend/app/modules/events/service.py`
y reiniciar el backend.

---

## Instalación del agente FIM como systemd unit

> Esta sección se corrigió el 2026-08-14 (D36/RN-130) porque estaba desfasada
> en cuatro puntos independientes respecto del código real: dependía de
> `pyfanotify` (el agente usa un backend propio sobre syscalls crudas, ver
> abajo), corría como `User=root` (corre como `fim-agent`), declaraba
> `ProtectSystem=full` (es `strict`, con `ReadWritePaths` derivado por
> drop-in) y documentaba un entrypoint `-m agent.bootstrap.main` que no
> existe (el real es `-m agent`, leyendo `/etc/fim-agent/config.yaml`). La
> corrección va del unit real (`agent/deploy/fim-agent.service`) hacia este
> documento, nunca al revés.

### Requisitos previos

- Linux con systemd (kernel ≥ 5.1 para fanotify en modo FID).
- Python 3.13 instalado en el host. El detector **no** depende de `pyfanotify`:
  usa un backend propio sobre syscalls crudas vía `ctypes` (`agent/_fanotify.py`),
  en modo `FAN_REPORT_DFID_NAME` — la API pública de `pyfanotify` es incompatible
  con el hilo lector bloqueante del detector y no entrega eventos de
  creación/borrado/renombrado en modo fd (ver el comentario de cabecera de
  `agent/requirements.txt`).
- CA cert pre-provisionado (`ca_cert_path` en `config.yaml`) — el bootstrap
  del agente lo requiere para verificar la respuesta del backend.
- El host debe poder otorgar `CAP_SYS_ADMIN` + `CAP_DAC_READ_SEARCH` +
  `CAP_DAC_OVERRIDE` + `CAP_FOWNER` + `CAP_CHOWN` al proceso del servicio
  (RN-108, D36/RN-130) — ninguna es opcional: sin las tres últimas,
  `auto_restore`/`quarantine` (RN-30 a RN-37) fallan en el 100% de los casos.

### Instalación recomendada: `agent/install.sh`

El script es la fuente de verdad operativa — instala el unit, el usuario de
servicio, el árbol de `/var/lib/fim-agent`, copia `config.yaml.example` si no
hay config, genera el drop-in de `ReadWritePaths` a partir de los
`watch_paths` configurados, y aplica la propiedad correcta (D36/RN-130 D-11):

```bash
sudo bash agent/install.sh
# Editar /etc/fim-agent/config.yaml (agent_id, watch_paths) antes de arrancar
sudo systemctl start fim-agent
sudo systemctl status fim-agent
```

Es idempotente: correrlo de nuevo no pisa un `config.yaml` ya editado, y
regenera el drop-in desde el `config.yaml` vigente — por eso también es el
procedimiento para aplicar un cambio de `watch_paths` hecho en caliente
(ver "Regenerar el drop-in tras cambiar watch_paths" más abajo).

### Unit file real (`agent/deploy/fim-agent.service`)

```ini
[Unit]
Description=FIM Agent — File Integrity Monitor
Documentation=https://github.com/mncrmn2009/tesis-fim-serio
After=network.target

[Service]
Type=simple
User=fim-agent
Group=fim-agent
WorkingDirectory=/opt/fim-agent

ExecStart=/opt/fim-agent/venv/bin/python -m agent --config /etc/fim-agent/config.yaml

EnvironmentFile=-/etc/fim-agent/env

AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN
CapabilityBoundingSet=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN

ProtectSystem=strict
NoNewPrivileges=true
PrivateTmp=true
ReadWritePaths=/var/lib/fim-agent /var/log/fim-agent

Restart=on-failure
RestartSec=5s
RestartPreventExitStatus=78

StandardOutput=journal
StandardError=journal
SyslogIdentifier=fim-agent

[Install]
WantedBy=multi-user.target
```

`install.sh` además genera `/etc/systemd/system/fim-agent.service.d/10-watchpaths.conf`
(drop-in aditivo, unit base sin editar) con una línea `ReadWritePaths=` por
`watch_path` configurado, más `/etc/fim-agent` siempre incluido — ver
"Arquitectura → Despliegue del agente" en `arquitectura_stack.md` para el
detalle de por qué cada capability está y cómo se deriva el drop-in.

### Archivo de entorno del agente

`/etc/fim-agent/env`, permisos `0600` propiedad `root:root` (systemd lo lee
como root antes de bajar privilegios; el usuario del servicio no necesita
acceso). `install.sh` instala una plantilla desde `agent/deploy/env.example`
**solo si el archivo no existe**. La única variable que va acá es el secreto
de bootstrap — todo lo demás (`agent_id`, `watch_paths`, `valkey_url`, rutas
de certificados) vive en `/etc/fim-agent/config.yaml`, no en el environment:

```bash
# /etc/fim-agent/env — de un solo uso, se recomienda borrar tras el primer
# arranque exitoso (EnvironmentFile=- en el unit tolera su ausencia).
FIM_BOOTSTRAP_SECRET=<secreto entregado por el operador del backend>
```

### Comandos de gestión

```bash
# Recargar systemd tras instalar o modificar el unit file o el drop-in
sudo systemctl daemon-reload

# Habilitar arranque automático al boot
sudo systemctl enable fim-agent.service

# Iniciar el agente
sudo systemctl start fim-agent.service

# Ver estado y últimas líneas de log
sudo systemctl status fim-agent.service

# Ver logs completos
sudo journalctl -u fim-agent.service -f

# Detener el agente
sudo systemctl stop fim-agent.service

# Reiniciar (ej: tras cambio de certificados)
sudo systemctl restart fim-agent.service
```

### Regenerar el drop-in tras cambiar `watch_paths` (D36/RN-130)

`ReadWritePaths` se materializa en el momento de la instalación; un comando
`update_config` emitido desde la interfaz cambia los `watch_paths` **en
caliente**, pero un path agregado así queda **monitoreado y no remediable**
hasta que el operador re-ejecute la configuración privilegiada en el
anfitrión — esto es inherente a que systemd resuelve `ReadWritePaths` en el
namespace de montaje al arrancar el servicio, no un defecto de
implementación. El agente lo hace visible: el preflight de escritura
clasifica ese path como `read_only_mount` y la tarjeta del agente en el
frontend lo muestra como solo-detección dentro de un heartbeat (≤10 s).

Para habilitar remediación sobre el path nuevo:

```bash
# config.yaml ya refleja los watch_paths nuevos (el agente los persiste solo
# tras un update_config exitoso) — install.sh regenera el drop-in desde ahí.
sudo bash agent/install.sh
sudo systemctl daemon-reload
sudo systemctl restart fim-agent
```

### Verificar permisos (capabilities)

```bash
# El proceso debe mostrar las cinco capabilities en el conjunto efectivo/ambient
cat /proc/$(systemctl show --property=MainPID fim-agent.service | cut -d= -f2)/status | grep ^Cap
# Decodificar: capsh --decode=<CapEff value>
```

Si falta alguna de `cap_sys_admin`, `cap_dac_read_search`, `cap_dac_override`,
`cap_fowner` o `cap_chown`:

- `cap_sys_admin` ausente → fanotify fallará con `EPERM` al registrar el watcher.
- `cap_dac_override` / `cap_fowner` / `cap_chown` ausentes → `auto_restore` y
  `quarantine` fallarán con `permission_denied` sobre paths que el preflight
  reporta como `writable` (mount correcto, capability faltante) — comparar
  contra `AmbientCapabilities` **y** `CapabilityBoundingSet` en el unit: una
  capability ausente del bounding set se descarta en silencio aunque figure
  en `AmbientCapabilities` (D36/RN-130).

### Diagnosticar un path no remediable

Si la tarjeta del agente muestra un `watch_path` como solo-detección
(`read_only_mount` o `permission_denied`):

1. `read_only_mount` → falta el drop-in para ese path. Confirmar con
   `systemctl cat fim-agent.service` que `10-watchpaths.conf` lo incluye; si
   no, regenerar (sección anterior).
2. `permission_denied` con el path ya en el drop-in → revisar las
   capabilities (sección anterior) antes que los permisos del filesystem:
   `CAP_DAC_OVERRIDE` cubre la mayoría de los casos DAC, así que su ausencia
   es la causa más común.
3. `missing` → el path configurado no existe en el host. Antes de D36/RN-130
   este caso se aceptaba sin ningún reporte.

## Directorio de descarte del agente (D37/RN-131)

**Ubicación**: `/var/lib/fim-agent/discard/`, junto a la cola. Permisos `0700`, owner `fim-agent`.

**Qué contiene**: eventos que el agente dejó de intentar publicar, cada uno con el motivo del descarte. Los motivos posibles son:

| Motivo | Significado |
|---|---|
| `invalid_schema` | el backend consideró el payload ilegible |
| `clock_skew` | el desfase entre `sent_at` y la hora del backend excedió los 5 minutos |
| `max_attempts_exceeded` | se agotó el techo de intentos sin recibir respuesta de ningún tipo |

**Esto es evidencia, no basura.** Cada archivo es un cambio de integridad detectado en el host que **nunca llegó al backend**. Un directorio de descarte con contenido es una anomalía a investigar, no un residuo a limpiar por rutina.

Cómo leer cada motivo:

- `max_attempts_exceeded` es el más grave: significa que el agente publicó y no obtuvo ni ack ni nack. Las causas típicas son un `agent_id` desconocido para el backend (el agente fue dado de baja o su registro se perdió) o un `shared_secret` desincronizado, porque ninguno de esos dos casos genera respuesta a propósito. Verificar el registro del agente antes que la red.
- `clock_skew` con `sent_at` apunta a un reloj adulterado o a NTP caído en el host, no a una cola vieja: la ventana se evalúa sobre el momento del envío, así que una cola que sobrevivió un corte largo **no** produce este motivo. Si aparece, el reloj es sospechoso.
- `invalid_schema` en un despliegue estable indica corrupción del payload o versiones incompatibles entre agente y backend.

**Cota**: 1000 archivos con drop-oldest. Al llegar al tope se pierden los descartes más antiguos, de modo que un directorio exactamente en 1000 puede estar ocultando descartes previos — revisarlo antes de que llegue ahí.

**Contador**: `discarded_events` viaja en el heartbeat (acumulativo desde el arranque del proceso) y el backend lo persiste y lo muestra en la tarjeta del agente. Un contador que crece es la señal temprana; el directorio es la evidencia.

**No se purga automáticamente.** La retención de RN-98 no lo toca: es material forense y su borrado es una decisión del operador.
