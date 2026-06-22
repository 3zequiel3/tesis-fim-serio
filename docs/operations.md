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

### Requisitos previos

- Linux con systemd (kernel ≥ 5.1 para fanotify con `FAN_OPEN_EXEC_PERM`).
- Python 3.13 y `pyfanotify` 0.3.0 instalados en el host.
- Certificado mTLS firmado por la CA del backend (ver sección PKI).
- Permiso `CAP_SYS_ADMIN` — requerido por fanotify para monitoreo de filesystem (RN-108).

### Unit file de ejemplo

Guardar en `/etc/systemd/system/fim-agent.service`:

```ini
[Unit]
Description=FIM Platform Agent
Documentation=https://github.com/mncrmn2009/tesis-fim-serio
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root

# Ruta al directorio del agente
WorkingDirectory=/opt/fim-agent

# Comando de arranque
ExecStart=/opt/fim-agent/venv/bin/python -m agent.bootstrap.main

# Permisos requeridos
AmbientCapabilities=CAP_SYS_ADMIN
CapabilityBoundingSet=CAP_SYS_ADMIN
NoNewPrivileges=false

# Variables de entorno
EnvironmentFile=/etc/fim-agent/env

# Restart automático
Restart=on-failure
RestartSec=10s
TimeoutStopSec=30s

# Seguridad adicional
ProtectSystem=full
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### Archivo de entorno del agente

Crear `/etc/fim-agent/env` con permisos `600` (solo root):

```bash
# Valkey — conexión al stream de backend
VALKEY_URL=valkey://backend-host:6379

# Identificador único del agente
AGENT_ID=agent-prod-01

# mTLS — certificados firmados por el backend CA
AGENT_CERT_PATH=/etc/fim-agent/certs/agent.crt
AGENT_KEY_PATH=/etc/fim-agent/certs/agent.key
CA_CERT_PATH=/etc/fim-agent/certs/ca.crt

# Paths a monitorear (separados por coma)
WATCH_PATHS=/etc,/usr/bin,/usr/sbin,/lib,/lib64

# Baseline cifrado AES-GCM
BASELINE_PATH=/var/lib/fim-agent/baseline.enc
BASELINE_KEY_PATH=/etc/fim-agent/baseline.key
```

### Comandos de gestión

```bash
# Recargar systemd tras instalar o modificar el unit file
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

### Verificar permisos CAP_SYS_ADMIN

```bash
# El proceso debe mostrar cap_sys_admin en el conjunto de capacidades efectivas
cat /proc/$(systemctl show --property=MainPID fim-agent.service | cut -d= -f2)/status | grep ^Cap
# Decodificar: capsh --decode=<CapEff value>
```

Si `cap_sys_admin` no aparece, fanotify fallará con `EPERM` al intentar registrar el watcher.
Verificar que el unit file tiene `AmbientCapabilities=CAP_SYS_ADMIN` y que el binario de Python
no tiene la capability dropped en su propia imagen.
