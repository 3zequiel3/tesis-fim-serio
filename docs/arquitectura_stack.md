# 🛡️ FIM Platform 2026 – Spec-Driven Architecture

> Última actualización: 23 de abril de 2026
> Estado: Documentación de diseño detallado — sin implementación. La construcción del código y la ejecución del protocolo experimental se proyectan para la fase inmediata siguiente y se entregarán en una adenda formal.

## 🎯 Objetivo

Definir una arquitectura profesional para un sistema FIM (File Integrity Monitoring) con:

* 🧠 Agente autónomo y resiliente sobre detección reactiva del núcleo Linux
* 🔁 Restauración automática confiable con journal de acciones
* 📊 Capacidades forenses (diffs, cadena de eventos, audit_log de retención ilimitada)
* ⚙️ Backend modular (FastAPI) con máquina de estados explícita y optimistic locking
* 🌐 Frontend moderno (React + TypeScript) con hardening web
* ⚡ Infraestructura desacoplada (Valkey + n8n como enrutador acotado)
* 🐳 Servidor central contenedorizado (Docker Compose); agente como servicio nativo del anfitrión

---

# 🧠 Principios Clave

* Agent-first (desacoplado, proceso nativo en el anfitrión)
* Event-driven (notificación reactiva del kernel, no encuestamiento)
* Snapshot + Diff (estrategia híbrida: snapshot para restaurar, diff para auditar)
* Forensic-ready (cadena `superseded`, audit_log, journal de acciones)
* Resiliencia offline (cola local del agente con confirmación bidireccional)
* Defensa en profundidad (mTLS en canal + HMAC en mensaje + AES-GCM en reposo)

---

# 📋 Stack Tecnológico

## Versiones validadas — Abril 2026

| Capa | Tecnología | Versión | Rol |
|------|-----------|---------|-----|
| **Agente** | Python + pyfanotify | 0.3.0 | Monitoreo filesystem reactivo sobre `fanotify` (kernel Linux ≥ 5.1) |
| **Backend** | FastAPI | 0.136.0 | API REST modular, SSE para alertas real-time |
| **ORM** | SQLModel | latest | Modelos + queries, integración nativa con FastAPI y Pydantic |
| **DB Driver** | psycopg (psycopg3) | latest | Driver PostgreSQL async-capable para Python |
| **Base de datos** | PostgreSQL | 18.3 | Almacenamiento persistente de eventos, reglas, alertas, acciones, audit_log |
| **Migraciones** | SQL manual + db-init | — | Scripts SQL versionados. Tablas creadas por SQLModel al iniciar |
| **Streams + Cache** | Valkey | 9.0.3 | Cola de eventos agent→backend, commands backend→agent, cache de reglas |
| **Notificaciones** | n8n | 2.16.1 | Enrutador de notificaciones externas (email, mensajería, SIEM) |
| **Auth** | python-jose + JWT | latest | Autenticación stateless con tokens JWT |
| **Hashing Passwords** | argon2-cffi | latest | Hashing de contraseñas con Argon2id (ganador de PHC) |
| **Auth Agente** | mTLS (certificados) | — | Autenticación mutua agente↔backend con certificados TLS 1.3 |
| **Frontend** | React + TypeScript | React 19 | SPA moderna |
| **Bundler** | Vite | latest | Build y dev server |
| **Data fetching** | TanStack Query | v5 | Cache, refetch, mutations |
| **HTTP Client** | Axios | latest | Requests al backend |
| **State** | Zustand | latest | Estado global del frontend |
| **Estilos** | Tailwind CSS + @tailwindcss/vite | 4.2.2 | Utility-first CSS, integración directa con Vite (sin PostCSS) |
| **Package Manager** | pnpm | latest | Gestor de paquetes rápido, eficiente en disco (symlinks) |
| **Logging** | structlog | latest | Logging estructurado JSON, trace_id por request |
| **Containerización** | Docker + Docker Compose | latest | Orquestación del servidor central (backend, db, valkey, n8n, frontend) |
| **CI/CD** | GitHub Actions | — | Pipeline de integración y despliegue continuo |

### Notas sobre elecciones

* **pyfanotify sobre watchdog/inotify**: `fanotify` (kernel Linux ≥ 5.1) es superior a `inotify` para el caso de uso FIM por tres razones: (1) provee contexto del proceso causante (PID, UID, path del ejecutable), no solo el evento sobre el archivo; (2) soporta marcado a nivel de sistema de archivos completo con `FAN_MARK_FILESYSTEM`, eliminando el race de tener que registrar watchers por cada subdirectorio nuevo; (3) opera en modo notificación pura o con contenido previo (puede bloquear la escritura para inspección antes de que se persista). El costo es que requiere la capability `CAP_SYS_ADMIN`, lo que motiva el despliegue nativo del agente (ver sección correspondiente). Se adopta el wrapper **pyfanotify 0.3.0** (licencia MIT, mantenido) y no el `python-fanotify` de Google porque ese repositorio está archivado.
* **SQLModel** sobre SQLAlchemy puro: creado por el mismo autor de FastAPI (tiangolo), comparte modelos entre ORM y API schemas (Pydantic + SQLAlchemy en uno).
* **psycopg3** (paquete `psycopg`) sobre `asyncpg`: compatible con SQLModel/SQLAlchemy, soporta sync y async, es el driver oficial recomendado para PostgreSQL moderno.
* **python-jose** sobre PyJWT: soporta JWS, JWE, JWK — más completo para manejo de JWT.
* **structlog** sobre loguru: salida JSON nativa, procesadores encadenables, ideal para logs parseables en producción. Se integra bien con `trace_id` por request vía middleware.
* **Tailwind CSS v4** sobre v3: v4 es un rewrite completo. NO usa `tailwind.config.js` — la configuración es CSS-first con `@theme`. Se instala como plugin de Vite (`@tailwindcss/vite`), no como plugin de PostCSS. En el CSS solo se pone `@import "tailwindcss";` (no más `@tailwind base/components/utilities`). Soporta Vite 8.
* **n8n como enrutador acotado**: n8n está delimitado al rol de enrutador de notificaciones externas (recibe webhooks del backend y los reencamina a correo, mensajería corporativa, SIEM). **No** asume el rol de coordinador central del playbook, porque n8n no ejecuta comandos nativos del sistema operativo; toda la lógica de decisión y orquestación de respuesta vive en el backend propio. La licencia es Sustainable Use License (fair-code), no OSS puro: aceptable para uso académico y self-hosted, no apta para reventa comercial. La política de fallbacks automáticos (ver sección correspondiente) garantiza que la indisponibilidad de n8n no comprometa la continuidad del alertado.
* **Migraciones**: SQLModel crea las tablas al iniciar (`SQLModel.metadata.create_all(engine)`). En desarrollo, se reinicia el contenedor. En producción futura, se pueden agregar migraciones SQL versionadas.
* **argon2-cffi** sobre bcrypt: Argon2id es el ganador de la Password Hashing Competition (PHC). Resistente a ataques GPU y side-channel. Configurable en memoria y paralelismo. Es la recomendación actual de OWASP.
* **mTLS para autenticación del agente**: Autenticación mutua con certificados TLS 1.3. El agente presenta su certificado al backend y viceversa, ambos verifican contra una CA compartida. Más seguro que API keys — no requiere secretos en plaintext, resistente a replay attacks, y permite identificación criptográfica del agente.

---

# 🏗️ Arquitectura General

```
┌──────────────────────────────────────────┐
│ ANFITRIÓN MONITOREADO (Linux, kernel ≥5.1) │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ fanotify (kernel)                  │  │
│  │ requiere CAP_SYS_ADMIN             │  │
│  └──────────────┬─────────────────────┘  │
│                 │                        │
│  ┌──────────────▼─────────────────────┐  │
│  │ Agente FIM (Python + pyfanotify)   │  │
│  │ · Servicio systemd nativo          │  │
│  │ · Motor de decisión (4 niveles)    │  │
│  │ · Baseline cifrada (AES-256-GCM)   │  │
│  │ · Cola local offline (JSON)        │  │
│  │ · Journal pre-acción               │  │
│  │ · Heartbeat cada 10 s              │  │
│  └──────────────┬─────────────────────┘  │
└─────────────────┼────────────────────────┘
                  │
                  │ mTLS 1.3 · HMAC-SHA256 por mensaje
                  │ timestamps dobles (anti-replay 5 min)
                  │
┌─────────────────▼────────────────────────┐
│ SERVIDOR CENTRAL — Docker Compose        │
│                                          │
│  [ Valkey 9.0.3 ]                        │
│    streams: events, commands, heartbeat  │
│                ▲                         │
│                │                         │
│  [ Backend FastAPI 0.136 ]               │
│    · Clean Architecture (UoW + Repo)     │
│    · Máquina de estados explícita        │
│    · Optimistic locking (column version) │
│    · JWT con rotación + blacklist        │
│                ▲                         │
│                │                         │
│  [ PostgreSQL 18.3 ]                     │
│    · events, rules, actions, alerts      │
│    · users, agents, ruleset_version      │
│    · audit_log (retención ilimitada)     │
│    · failed_notifications                │
│                                          │
│  [ n8n 2.16.1 ] ── webhook ──► canales   │
│    enrutador de notificaciones           │
│    (fair-code, fallbacks a SMTP/log/DLQ) │
│                                          │
│  [ Frontend React 19 + nginx ]           │
│    · CSP, HSTS, SameSite=Strict          │
│    · SSE para alertas real-time          │
│                                          │
│  [ db-init ] init-container              │
│    · schema + seed del primer admin      │
└──────────────────────────────────────────┘
```

### Servicios Docker Compose (solo el servidor central)

```yaml
services:
  backend:      # FastAPI + SQLModel
  frontend:     # React (Vite build → nginx)
  db:           # PostgreSQL 18.3
  valkey:       # Valkey 9.0.3
  n8n:          # n8n 2.16.1 (enrutador acotado)
  db-init:      # init-container, corre una vez
```

> **Importante**: el agente **no** está en Docker Compose. Se despliega como servicio nativo con systemd en cada anfitrión monitoreado porque `fanotify` requiere `CAP_SYS_ADMIN`, capability incompatible con aislamiento estándar de contenedores. Ver sección "Despliegue del agente".

---

# 🧩 FIM Agent

## Tecnologías del agente

| Componente | Tecnología | Detalle |
|------------|-----------|---------|
| Runtime | Python 3.12+ | Compatible con pyfanotify 0.3.0 |
| Monitoreo FS | pyfanotify 0.3.0 sobre `fanotify` (kernel) | Detección reactiva con contexto de proceso |
| Hashing | hashlib (stdlib) | SHA-256 para integridad |
| Cola offline | Archivos JSON en disco | Resiliencia sin DB embebida |
| Conexión backend | Valkey Streams (via valkey-py) | Publicación async de eventos |
| Cifrado de baseline | cryptography (stdlib ext.) | AES-256-GCM con clave derivada HKDF-SHA256 |
| Servicio | systemd unit nativa | Corre con CAP_SYS_ADMIN; hardening vía systemd (ver Anexo E de la tesis) |

### Por qué `fanotify` y no `inotify`

| Criterio | `inotify` (vía watchdog) | `fanotify` (vía pyfanotify) |
|----------|--------------------------|------------------------------|
| Contexto de proceso | ❌ No informa qué proceso hizo el cambio | ✅ PID, UID, path del ejecutable causante |
| Marcado a nivel de FS | ❌ Hay que registrar watcher por subdirectorio (race con `mkdir`) | ✅ `FAN_MARK_FILESYSTEM` monta el FS entero |
| Bloqueo pre-escritura | ❌ Solo notifica después del write | ✅ Modos de permisos permiten inspeccionar antes |
| Límite de watchers | `fs.inotify.max_user_watches` (agotable) | No aplica al marcado de FS |
| Eventos sobre dispositivos de bloque | ❌ | Limitado (igual que inotify, pero con contexto) |
| Madurez en kernels actuales | ≥ 2.6.13 | ≥ 5.1 con features modernas |
| Capability requerida | Ninguna | `CAP_SYS_ADMIN` |

El agente prioriza la calidad forense del evento (qué proceso tocó qué archivo) y la cobertura completa del FS sobre la simplicidad operativa. El costo — requerir `CAP_SYS_ADMIN` y por tanto deployment nativo — se asume explícitamente como decisión arquitectónica.

### Despliegue del agente (nativo, no Docker)

El agente se instala como servicio de `systemd`:

```ini
# /etc/systemd/system/fim-agent.service
[Unit]
Description=FIM Agent — detección reactiva fanotify
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=fim-agent
Group=fim-agent
AmbientCapabilities=CAP_SYS_ADMIN
CapabilityBoundingSet=CAP_SYS_ADMIN
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/fim-agent /var/log/fim-agent
PrivateTmp=true
ExecStart=/opt/fim-agent/bin/fim-agent --config /etc/fim-agent/config.yaml
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

* `AmbientCapabilities=CAP_SYS_ADMIN`: requerido por `fanotify` para marcar FS completo y leer metadata de proceso causante.
* `ProtectSystem=strict` + `ReadWritePaths`: el agente solo puede escribir en sus propios directorios (baseline cifrada, cola, journal, certs, logs).
* `NoNewPrivileges`: impide escalación posterior.
* `PrivateTmp`: aísla `/tmp`.

> El contenedor del agente fue descartado: otorgar `CAP_SYS_ADMIN` a un contenedor rompe el aislamiento estándar y `fanotify` sobre un mount bind no ve operaciones del anfitrión, solo las del namespace del contenedor.

### Cola offline del agente

El agente NO usa una base de datos embebida. Cuando no puede conectar con Valkey/backend:

1. Serializa el evento a JSON.
2. Escribe en `/var/lib/fim-agent/queue/` con nombre `{timestamp}_{event_id_uuid}.json` (escritura atómica: `write + rename`).
3. Al reconectar, procesa **primero** los comandos pendientes del stream `commands` (ver W4 en appendix) y **después** envía los eventos encolados en orden FIFO.
4. Elimina el archivo JSON tras recibir el `event_ack` correspondiente (ver C3 en appendix).

Esto es más simple que SQLite, no requiere driver extra, y cumple el requisito de resiliencia offline. Límite: 100 MB con política drop-oldest (ver W3 en appendix).

### Inicialización del baseline

El baseline se genera de forma híbrida:

```
Primera ejecución del agente:
  1. Leer lista de paths monitoreados (configuración)
  2. Escanear todos los archivos
  3. Calcular hash SHA-256 de cada uno
  4. Guardar copia completa en /var/lib/fim-agent/baseline/ (cifrada AES-256-GCM)
  5. Registrar metadata (path, hash, timestamp, permisos)
  6. Asumir estado actual como "sano" (baseline inicial)
```

**Re-scan manual** (admin desde frontend):

```
POST /agents/{id}/rescan { paths: ["/var/www", "/etc"] }
  │
  ▼
Backend envía comando via Valkey:
  { "type": "rescan_baseline",
    "paths": ["/var/www", "/etc"],
    "ruleset_version": 47,
    "signature": "<HMAC-SHA256>" }
  │
  ▼
Agente:
  1. Verifica firma HMAC del comando
  2. Verifica ruleset_version >= último aplicado
  3. Escanea paths indicados
  4. Regenera baseline COMPLETO para esos paths (re-cifrado AES-GCM)
  5. Confirma via Valkey
```

¿Cuándo usar re-scan? Después de un deploy legítimo masivo, una migración, o cuando se necesita resetear el baseline sin aprobar eventos uno por uno.

**⚠️ Impacto en eventos `pending`:**

Antes de ejecutar el re-scan, el frontend muestra un diálogo de confirmación:

```
"Los siguientes eventos pending para los paths seleccionados
 serán marcados como superseded:

 - /var/www/index.html (pending desde 2026-04-15)
 - /etc/nginx/nginx.conf (pending desde 2026-04-16)

 ¿Confirmar re-scan?"
```

El admin debe confirmar explícitamente. Al confirmar:
1. Todos los eventos `pending` para los paths seleccionados → `superseded`
2. Se envía comando `rescan_baseline` al agente via Valkey
3. El agente regenera baseline para esos paths

### Regla default (sin match)

Si un archivo cambia y NO matchea ningún patrón de regla configurado, el agente aplica **`alert_only`** como comportamiento default. Esto garantiza que:

* Ningún cambio pasa desapercibido
* No se ejecutan acciones destructivas sin regla explícita
* El admin puede crear reglas retroactivamente al revisar alertas

### Configuración del agente (lifecycle)

La configuración del agente sigue un ciclo de vida de dos fases:

**Fase 1 — Bootstrap (arranque inicial via `/etc/fim-agent/config.yaml` + variables systemd):**

```yaml
# /etc/fim-agent/config.yaml
agent_id: agent-prod-01
backend:
  valkey_url: valkey://backend-host:6379
  ca_cert_path: /etc/fim-agent/certs/ca.pem
watch_paths:
  - /etc
  - /var/www
  - /opt/app
storage:
  baseline_dir: /var/lib/fim-agent/baseline
  queue_dir: /var/lib/fim-agent/queue
  journal_dir: /var/lib/fim-agent/journal
```

El agente lee los paths a monitorear desde el archivo de configuración local al arrancar. Esto define el estado inicial.

**Fase 2 — Runtime (gestión en caliente desde frontend):**

```
Admin agrega path /opt/newservice desde el frontend
       │
       ▼
Backend: POST /agents/{id}/config
       │
       ▼
Backend publica en Valkey Stream (commands):
  { "type": "update_config",
    "watch_paths": [..., "/opt/newservice"],
    "ruleset_version": 48,
    "signature": "<HMAC-SHA256>" }
       │
       ▼
Agente:
  1. Verifica firma HMAC
  2. Verifica ruleset_version monotónica
  3. Recarga paths monitoreados SIN reiniciar el proceso
  4. Ejecuta baseline scan para los paths nuevos
```

La configuración de paths se persiste en PostgreSQL. El `config.yaml` define solo el estado de bootstrap — a partir del primer arranque, el admin gestiona todo desde el frontend y los cambios se sincronizan via Valkey.

## Sistema híbrido de restauración y análisis

## 🔹 Estrategia de Integridad (Core del sistema)

```
Baseline (snapshot completo, cifrado AES-256-GCM)
        +
Diffs (para auditoría, solo texto)
```

---

# 📦 1. Baseline (Snapshot completo)

## ✔ Qué es

Copia completa del archivo en estado "sano", cifrada en reposo.

## 📁 Ubicación

```
/var/lib/fim-agent/baseline/
```

## ✔ Contenido (por entrada)

* archivo completo (cifrado AES-256-GCM)
* hash SHA-256 (del contenido claro)
* metadata (path, permisos, timestamp, tamaño)
* nonce GCM (96 bits, único por archivo)

## 🔐 Cifrado del baseline (W10)

* Algoritmo: **AES-256-GCM** (cifrado autenticado, estándar NIST)
* Derivación de clave: `HKDF-SHA256(ikm=master_secret, salt=AGENT_ID, info="baseline-v1")`
* `master_secret`: entregado al agente en el bootstrap (payload mTLS), persistido con permisos `0400` en `/var/lib/fim-agent/secrets/master_secret`
* Un compromiso del volumen (lectura offline del disco) no revela el baseline sin el `master_secret`

---

## 🔐 Uso

* restauración automática (descifrar → escribir al FS)
* validación de integridad (descifrar → rehashear → comparar)

---

# 🔍 2. Diffs (Análisis forense)

## ✔ Qué es

Diferencia entre versión anterior y nueva, generada al momento del evento.

## 📁 Ubicación

```
/var/lib/fim-agent/diffs/
```

---

## ✔ Uso

* auditoría
* análisis de cambios
* visualización en frontend

---

## ⚠️ Limitaciones

* solo archivos de texto (para binarios: comparación de hash + hex dump parcial)
* no confiable para restauración (puede perderse contexto)

---

# 🧠 Regla de Oro

```
Snapshot = restauración
Diff = análisis
```

---

# ⚙️ Flujo de Procesamiento en el Agente (Motor de Decisión)

## Ciclo de vida del cambio

```
detected -> analyzed -> action -> (auto_restored | quarantined | pending | alert_only)
```

El agente no solo detecta — también **decide y actúa** en base a reglas cacheadas localmente.

## Reglas del agente

Las reglas se sincronizan desde el backend y se cachean en el agente. Cada regla define un patrón, severidad y acción:

```json
{
  "pattern": "/etc/passwd",
  "severity": "critical",
  "action": "auto_restore"
}
```

```json
{
  "pattern": "/var/www/**",
  "severity": "medium",
  "action": "manual_review"
}
```

```json
{
  "pattern": "/var/log/**",
  "severity": "low",
  "action": "alert_only"
}
```

### Acciones posibles (4 niveles)

| Acción | Quién decide | Cuándo | Qué hace el agente |
|--------|-------------|--------|---------------------|
| `auto_restore` | Sistema (automático) | Inmediato | Restaura desde baseline, envía evento |
| `quarantine` | Sistema (automático) | Inmediato | Mueve archivo a cuarentena, envía evento |
| `manual_review` | Humano (admin) | Después | NO restaura, marca como `pending`, envía evento |
| `alert_only` | Nadie | Inmediato | Solo registra y envía evento |

### Patrones glob con negación

Las reglas soportan patrones glob estándar con negación usando el prefijo `!`:

```json
{ "pattern": "/etc/**", "severity": "critical", "action": "auto_restore" }
{ "pattern": "!/etc/motd", "severity": "low", "action": "alert_only" }
```

**Orden de evaluación:**

1. Se evalúan TODAS las reglas que matchean el path (inclusión y exclusión)
2. Las reglas con `!` excluyen paths del match de reglas más amplias
3. Si un path matchea una regla inclusiva Y una exclusiva, la exclusiva gana
4. Si no matchea ninguna regla, se aplica `alert_only` (default)

**Ejemplo:**

```
Regla 1: /etc/**        → auto_restore   (todo /etc/ se restaura)
Regla 2: !/etc/motd     → alert_only     (excepto motd)
Regla 3: !/etc/hostname → alert_only     (excepto hostname)

Resultado:
  /etc/passwd   → auto_restore (matchea regla 1, no excluida)
  /etc/motd     → alert_only   (excluida por regla 2)
  /etc/hostname → alert_only   (excluida por regla 3)
  /etc/shadow   → auto_restore (matchea regla 1, no excluida)
```

## Flujo completo del agente

```
Evento detectado (fanotify vía pyfanotify)
   ├── Contexto recibido: path, pid, uid, exe del proceso causante
   │
   ├── Calcular hash SHA-256 del archivo actual
   ├── Descifrar entrada de baseline (AES-GCM) y comparar hash
   │
   ├── Si NO cambió → ignorar
   │
   ├── Si CAMBIÓ:
   │       │
   │       ├── Generar snapshot (cifrado AES-GCM, si corresponde)
   │       ├── Generar diff (si texto)
   │       │
   │       ├── Consultar regla (cacheada)
   │       │
   │       ├── SIN REGLA (ningún patrón matchea)
   │       │       → DEFAULT: enviar evento (status: alert_only)
   │       │
   │       ├── action = auto_restore
   │       │       → Escribir journal: {event_id, path, action, state: "pending"}
   │       │       → restaurar archivo desde baseline (descifrar + escribir)
   │       │       → verificar hash post-restauración
   │       │       → Actualizar journal: {state: "completed"}
   │       │       → enviar evento (status: auto_restored)
   │       │
   │       ├── action = quarantine
   │       │       → Escribir journal: {event_id, path, action, state: "pending"}
   │       │       → mover archivo a /var/lib/fim-agent/quarantine/
   │       │       → Actualizar journal: {state: "completed"}
   │       │       → enviar evento (status: quarantined)
   │       │
   │       ├── action = manual_review
   │       │       → NO tocar el archivo
   │       │       → enviar evento (status: pending)
   │       │
   │       └── action = alert_only
   │               → enviar evento (status: alert_only)
   │
   └── Publicar en Valkey Stream (o encolar en cola local si offline)
       Payload incluye: event_id (UUID v4), detected_at, schema_version,
                         signature HMAC, contexto de proceso
```

---

# 🧪 Sistema de Respuesta del Agente

## 🔹 1. Auto-restauración (solo reglas críticas)

**Condición**: `action = auto_restore` en la regla.

```
1. Detectar cambio
2. Validar que baseline existe y tiene archivo completo
3. Escribir entrada de journal (W2): state = "pending"
4. Descifrar archivo del baseline (AES-GCM)
5. Restaurar archivo original sobre el FS
6. Verificar hash post-restauración
7. Actualizar journal: state = "completed"
8. Enviar evento (status: auto_restored)
```

> Restauración ≠ Aprobación. La restauración es inmediata y automática. La aprobación es humana y posterior.
>
> El journal pre-acción (W2) garantiza que si el agente muere mid-action, al reiniciar puede rehidratar entradas marcadas como `pending` y reintentar o reportar.

## 🔹 2. Cuarentena

**Condición**: `action = quarantine` en la regla.

```
/var/lib/fim-agent/quarantine/
```

* Escribir journal pre-acción
* Mover archivo sospechoso
* Renombrar con timestamp/hash
* Permisos restringidos (`0400`, owner `fim-agent`)
* Actualizar journal
* Enviar evento (status: quarantined)

## 🔹 3. Revisión manual (pending)

**Condición**: `action = manual_review` en la regla.

* El agente NO toca el archivo
* Envía evento con `status: pending`
* El admin decide desde el frontend (approve / reject)

## 🔹 4. Solo alerta

**Condición**: `action = alert_only` en la regla.

* El agente NO toca el archivo
* Envía evento con `status: alert_only`
* Solo se registra para auditoría

---

## ⚠️ Requisito clave

👉 El baseline DEBE contener el archivo completo (cifrado), no solo hash

---

# 🧠 Clasificación Inteligente de Archivos

## 🔹 Críticos

Ej:

* `/etc/passwd`
* binarios del sistema

✔ snapshot obligatorio (cifrado)
✔ restauración automática

---

## 🔹 Configuración

✔ snapshot + diff

---

## 🔹 No críticos

✔ opcional / ignorar

---

# 💾 Optimización de Almacenamiento

## 🔹 Versionado

```
max_snapshots_per_file = 3
```

---

## 🔹 Compresión

* snapshots antiguos → gzip (antes del cifrado)

---

## 🔹 Deduplicación

* no guardar si hash igual

---

# 🔐 Seguridad del Baseline

## 🔹 Integridad

* AES-256-GCM provee autenticación además de confidencialidad (tag GCM verifica cualquier alteración al descifrar)

---

## 🔹 Protección

* Permisos `0600` para archivos cifrados del baseline, owner `fim-agent`
* `master_secret` con permisos `0400`, owner `fim-agent`, fuera del volumen monitoreado
* Directorios del agente excluidos del propio FIM (un patrón `!/var/lib/fim-agent/**` es obligatorio en la configuración)

---

# 🧩 Backend API (FastAPI + SQLModel)

## Tecnologías del backend

| Componente | Tecnología | Detalle |
|------------|-----------|---------|
| Framework | FastAPI 0.136.0 | Async, OpenAPI auto-generado, SSE nativo |
| ORM | SQLModel | Modelos compartidos entre DB y API (Pydantic + SQLAlchemy) |
| DB | PostgreSQL 18.3 | Eventos, reglas, alertas, acciones, usuarios, audit_log |
| DB Driver | psycopg (v3) | Driver oficial PostgreSQL, sync + async |
| Auth (humanos) | python-jose + JWT | Tokens stateless, refresh tokens con rotación |
| Auth (agentes) | mTLS | Certificados TLS 1.3 mutuos con CA propia |
| Logging | structlog | JSON estructurado con trace_id por request |
| Streams | Valkey 9.0.3 (valkey-py) | Consumer groups para eventos del agente, publisher de comandos |
| Hashing passwords | argon2-cffi (Argon2id) | Ganador PHC, configuración OWASP 2026 |
| Firma de comandos | HMAC-SHA256 | Cada mensaje backend → agente firmado con shared_secret por agente |

## Módulos del backend

```
backend/
├── app/
│   ├── main.py              # FastAPI app + lifespan (create_all + seed_admin)
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── database.py      # Engine + Session (SQLModel, UoW)
│   │   ├── security.py      # JWT encode/decode, Argon2 PasswordHasher
│   │   ├── pki.py           # CA propia, emisión/rotación de certs del agente
│   │   ├── rate_limit.py    # Rate limiters (Valkey counters + TTL)
│   │   ├── logging.py       # structlog + middleware sanitize_logs
│   │   └── dependencies.py  # get_current_user, get_session, rate_limiter
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── router.py            # /auth/login, /auth/refresh, /auth/logout
│   │   │   └── service.py
│   │   ├── users/
│   │   │   ├── router.py            # CRUD de usuarios (admin)
│   │   │   ├── models.py            # User (incluye must_change_password)
│   │   │   └── service.py
│   │   ├── events/
│   │   │   ├── router.py            # GET /events (paginado), GET /events/{id}
│   │   │   ├── models.py            # Event con column `version` (optimistic locking)
│   │   │   ├── service.py           # Lógica de ingesta, validación de transiciones
│   │   │   └── consumer.py          # Consumer group Valkey + XACK + publish ack
│   │   ├── rules/
│   │   │   ├── router.py            # CRUD de reglas
│   │   │   ├── models.py            # Rule + ruleset_version counter
│   │   │   └── service.py           # Sync a agente via Valkey
│   │   ├── actions/
│   │   │   ├── router.py            # /actions/approve, /actions/reject, /actions/bulk-*
│   │   │   ├── models.py
│   │   │   └── service.py           # Flow de aprobación con optimistic locking
│   │   ├── alerts/
│   │   │   ├── router.py
│   │   │   ├── models.py
│   │   │   └── service.py
│   │   ├── agents/
│   │   │   ├── bootstrap_router.py  # POST /agents/bootstrap (CSR + HMAC)
│   │   │   ├── router.py            # Sync reglas, baseline updates, rescan, config
│   │   │   ├── service.py           # Publisher firmado al stream commands
│   │   │   └── heartbeat_consumer.py # Consume agent_heartbeat stream
│   │   ├── health/
│   │   │   └── router.py            # GET /health/components
│   │   ├── audit/
│   │   │   ├── models.py            # audit_log (retención ilimitada)
│   │   │   └── service.py           # Side-effect en servicios sensibles
│   │   └── notifications/
│   │       ├── n8n_client.py        # Webhook con retry + DLQ
│   │       └── models.py            # failed_notifications
├── Dockerfile
└── requirements.txt
```

> **`core/`**: configuración, DB, seguridad, dependencias compartidas — todo lo transversal.
> **`modules/`**: dominios de negocio aislados. Cada módulo tiene su router, models y service.

## Estados del evento (Event Lifecycle)

Todo evento sigue un ciclo de vida con estados definidos (ver C2 en appendix para la máquina de estados explícita):

```
detected -> analyzed -> action
                        │
                        ├── auto_restored  (sistema restauró automáticamente)
                        ├── quarantined    (sistema aisló el archivo)
                        ├── pending        (esperando decisión humana)
                        │     │
                        │     ├── approved     (admin aprobó → baseline actualizado)
                        │     ├── rejected     (admin rechazó → restaurar/cuarentena)
                        │     └── superseded   (nuevo cambio en mismo path → reemplazado)
                        │
                        └── alert_only     (solo registro, sin acción)
```

### Estados posibles (7 totales)

| Estado | Origen | Significado |
|--------|--------|-------------|
| `pending` | Agente (manual_review) | Esperando decisión del admin |
| `approved` | Admin (frontend) | Cambio legítimo confirmado. Baseline actualizado |
| `rejected` | Admin (frontend) | Cambio malicioso/no deseado. Se restaura o cuarentena |
| `auto_restored` | Agente (auto_restore) | Restaurado automáticamente por regla crítica |
| `quarantined` | Agente (quarantine) | Archivo aislado automáticamente |
| `alert_only` | Agente (alert_only o default sin match) | Solo registrado para auditoría |
| `superseded` | Agente (cadena) o backend (re-scan) | Reemplazado por evento más reciente |

La tabla de transiciones canónicas (in-edges / out-edges) está formalizada en C2 del appendix. Cualquier transición no listada es rechazada a nivel de service con HTTP 409.

## Flujo de aprobación (Admin)

### Caso 1: Admin APRUEBA (cambio legítimo)

```
Frontend: POST /actions/approve { event_id, expected_version }
      │
      ▼
Backend (modules/actions/service.py):
  1. UPDATE optimista sobre events:
     UPDATE events SET status='approved', version=version+1, ...
     WHERE id=:id AND version=:expected_version AND status='pending';
     · Si afecta 0 filas → HTTP 409 (conflict)  [ver C5]
  2. Hashear archivo ACTUAL (via comando al agente) — no el hash del evento
  3. Generar nueva entrada de baseline con hash actual
  4. Publicar comando en Valkey stream commands con ruleset_version++ y signature HMAC:
     {
       "type": "baseline_update",
       "path": "/etc/ssh/sshd_config",
       "hash": "<sha256_actual>",
       "ruleset_version": 49,
       "signature": "<HMAC-SHA256>"
     }
  5. Insertar audit_log (action=approve, event_id, user_id)
  6. Responder 200 al frontend
      │
      ▼
Agente:
  · Verifica signature HMAC
  · Verifica ruleset_version >= última aplicada (C11)
  · Actualiza baseline local (re-cifra con AES-GCM)
  · Confirma via stream commands con event_ack
```

**Esto es CRÍTICO**: si no se actualiza el baseline, el agente detecta el mismo cambio como anomalía en el próximo ciclo.

### Caso 2: Admin RECHAZA (cambio malicioso)

```
Frontend: POST /actions/reject { event_id, expected_version, action: "restore" | "quarantine" }
      │
      ▼
Backend:
  1. UPDATE optimista (mismo patrón que approve)
     · HTTP 409 si hay conflicto
  2. Validar baseline state: si status='absent' → no-op con warning (C10)
  3. Publicar comando al agente:
     {
       "type": "restore_file" | "quarantine_file",
       "path": "/etc/ssh/sshd_config",
       "ruleset_version": 50,
       "signature": "<HMAC-SHA256>"
     }
  4. Agente ejecuta acción (con journal pre-acción W2)
  5. Baseline NO se actualiza (se mantiene el estado sano anterior)
  6. audit_log + respuesta 200
```

### Caso 3: Admin APRUEBA pero el archivo fue eliminado

```
Frontend: POST /actions/approve { event_id }
      │
      ▼
Backend:
  1. Consulta estado actual al agente via Valkey
  2. Agente responde: archivo NO EXISTE
  3. Backend retorna warning: "file_deleted"
      │
      ▼
Frontend:
  ⚠️ "El archivo ya no existe en el filesystem.
      Aprobar significa que la AUSENCIA del archivo
      es el nuevo estado válido del baseline."
      │
      ├── Admin CONFIRMA:
      │     1. Baseline: { path, status: "absent", hash: null }
      │     2. Sync al agente: "este path NO debe tener archivo"
      │     3. Si alguien recrea el archivo → anomalía detectada
      │     4. Evento → approved
      │
      └── Admin CANCELA:
            Evento permanece en pending
```

> Un archivo ausente es un estado VÁLIDO del filesystem. Si un sysadmin eliminó un config obsoleto, aprobar esa eliminación es correcto. Si fue un atacante limpiando evidencia, el admin puede rechazar y restaurar desde baseline.

## Cadena de eventos (Event Chain)

### Problema: race condition en eventos `pending`

¿Qué pasa si un archivo cambia DE NUEVO mientras ya hay un evento `pending` para ese path?

```
T1: /etc/ssh/sshd_config cambia → Evento A (pending)
T2: /etc/ssh/sshd_config cambia OTRA VEZ → ???
T3: Admin aprueba Evento A → ¿qué hash se usa como baseline?
```

### Solución: cadena de eventos con `superseded`

Cada nuevo cambio en un path con evento `pending` genera un NUEVO evento vinculado al anterior:

```
Evento A (pending)  ← primer cambio detectado
    │
    └── Evento B (pending, parent_event_id: A)  ← segundo cambio
            │
            └── Evento C (pending, parent_event_id: B)  ← tercer cambio
```

**Reglas de la cadena:**

1. Nuevo cambio en path con `pending` → crear evento nuevo con `parent_event_id` apuntando al pending anterior
2. El evento anterior se marca como `superseded` (ya no es relevante para decisión)
3. Solo el **último evento de la cadena** es `pending` y visible para el admin
4. El admin siempre decide sobre el estado MÁS RECIENTE del archivo

### Flujo completo de la cadena

```
T1: Archivo cambia
    → Agente: crear Evento A (status: pending)

T2: Mismo archivo cambia otra vez
    → Agente: buscar evento pending para este path
    → Encontrado: Evento A
    → Marcar Evento A → status: superseded
    → Crear Evento B (status: pending, parent_event_id: A)

T3: Admin ve Evento B (el último pending)
    → Approve:
        1. Backend hashea el archivo ACTUAL (no el hash del Evento B)
        2. Genera baseline con hash actual
        3. Marca Evento B → approved
        4. Sync baseline al agente
    → Reject:
        1. Backend envía restore/quarantine al agente
        2. Marca Evento B → rejected
        3. Baseline NO se actualiza

Eventos A (superseded) quedan como historial de auditoría.
```

### ¿Por qué hashear el archivo ACTUAL al aprobar?

Porque entre que el admin ve el evento y aprieta "Approve", el archivo podría haber cambiado N veces. Si se usa el hash del evento original, el baseline queda desactualizado y el agente detecta una "anomalía" falsa en el próximo ciclo.

**Al aprobar, el backend SIEMPRE:**
1. Lee el archivo del filesystem actual (o pide hash actual al agente)
2. Genera baseline con ESE hash
3. Sync al agente

### Modelo de datos para event chain

```python
class Event(SQLModel, table=True):
    id: int
    path: str
    hash_detected: str          # Hash al momento de detección
    status: EventStatus         # pending | approved | rejected | auto_restored | quarantined | alert_only | superseded
    parent_event_id: int | None # Referencia al evento anterior en la cadena (None = primer evento)
    action_type: str            # auto_restore | quarantine | manual_review | alert_only
    version: int = 0            # Optimistic locking (C5)
    process_pid: int | None     # Contexto fanotify: proceso causante
    process_uid: int | None
    process_exe: str | None
    detected_at: datetime       # Timestamp del agente
    received_at: datetime       # Timestamp del backend (W13 anti-replay)
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: int | None     # User ID del admin que aprobó/rechazó
```

### Estado "absent" en baseline

El baseline puede registrar que un archivo NO debe existir:

```python
class BaselineEntry:
    path: str
    hash: str | None        # None = archivo debe estar ausente
    status: str              # "present" | "absent"
    last_verified: datetime
```

Cuando `status = "absent"`, el agente trata la CREACIÓN de un archivo en ese path como anomalía (no solo la modificación).

## Baseline dinámico

El baseline NO es estático — se actualiza bajo condiciones controladas:

### Se actualiza cuando:

* ✔ Admin aprueba un cambio (`status = approved`)
* ✔ Cambio legítimo confirmado por humano
* ✔ Re-scan explícito del admin (con warning previo)

### NO se actualiza cuando:

* ❌ Cambio detectado sin aprobación
* ❌ Evento auto-restaurado (el baseline ya era correcto)
* ❌ Evento en cuarentena
* ❌ Evento rechazado

### Sincronización backend → agente

```
Backend                              Agente
   │                                   │
   ├── approve event ──────────────►   │
   │   baseline_update via Valkey      │
   │   (firmado HMAC + ruleset_ver)    │
   │                                   ├── Verifica HMAC + versión
   │                                   ├── Actualiza baseline local
   │                                   ├── Re-cifra con AES-GCM
   │                                   └── Confirma via event_ack
   │                                   │
   ├── reject event ───────────────►   │
   │   restore/quarantine via Valkey   │
   │                                   ├── Journal pre-acción (W2)
   │                                   ├── Ejecuta acción
   │                                   └── Confirma via event_ack
```

## Inicialización de DB

```python
# En lifespan de FastAPI
from sqlmodel import SQLModel, create_engine

engine = create_engine(DATABASE_URL)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
```

* En **desarrollo**: reiniciar contenedor recrea tablas
* En **producción futura**: scripts SQL versionados en `db/migrations/`

### Creación del primer admin

El primer usuario admin se crea como seed durante la inicialización. Con flag `must_change_password=true` (ver W20):

```python
from argon2 import PasswordHasher

ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)  # C9

def seed_admin():
    admin_exists = session.exec(select(User)).first()
    if not admin_exists:
        admin = User(
            username=settings.ADMIN_USERNAME,
            password_hash=ph.hash(settings.ADMIN_PASSWORD),
            role="admin",
            must_change_password=True,  # W20: obliga cambio en primer login
        )
        session.add(admin)
        session.commit()
```

Variables de entorno requeridas:

```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<password-seguro-temporal>
```

> ⚠️ El password del `.env` es solo para el seed inicial. Se fuerza el cambio en el primer login (W20).

### Hashing de passwords (Argon2id)

Todas las contraseñas se hashean con **Argon2id** (via `argon2-cffi`) con los parámetros fijos de C9:

* `time_cost=3, memory_cost=65536, parallelism=4`
* Alineado con la recomendación OWASP 2026
* Resistente a ataques GPU y side-channel

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

# Crear hash
password_hash = ph.hash("user_password")

# Verificar
try:
    ph.verify(password_hash, "user_password")
except VerifyMismatchError:
    raise HTTPException(status_code=401, detail="Credenciales inválidas")
```

## Auth Flow (administradores)

```
POST /auth/login  →  { access_token (15 min), refresh_token (7 días, rotación) }
     │
     ▼
Requests con header: Authorization: Bearer <access_token>
     │
     ▼
Dependency: get_current_user(token) → decode JWT (python-jose) → User
     │
     ▼
Blacklist de jti revocados en Valkey con TTL = exp restante  [C8]
Multi-key signing: JWT_SECRET_CURRENT / JWT_SECRET_PREVIOUS   [C8]
```

## Autenticación del agente (mTLS + bootstrap)

El agente se autentica con el backend usando **mTLS** sobre TLS 1.3:

```
Agente                              Backend
  │                                   │
  ├── Presenta certificado ────────►  │
  │                                   ├── Verifica contra CA propia
  │                                   ├── Consulta revoked_certificates
  │  ◄──── Presenta certificado ────  │
  ├── Verifica contra CA              │
  │                                   │
  └── Canal TLS mutuo establecido ──► │
```

### Bootstrap con CA propia (C6)

La obtención del primer certificado no puede asumir mTLS ya existente. El flujo es:

```
1. Admin pre-registra en UI: { agent_id, bootstrap_secret (32 bytes random) }
   Se persiste en DB.

2. Agente arranca por primera vez:
   - Genera par de claves local (RSA 4096 o Ed25519)
   - Construye CSR (Certificate Signing Request)
   - Firma el CSR con HMAC-SHA256 usando bootstrap_secret
   - Envía POST /agents/bootstrap { agent_id, csr, hmac_signature }

3. Backend (modules/agents/bootstrap_router.py):
   - Recupera bootstrap_secret por agent_id
   - Verifica HMAC del CSR
   - Si OK: firma el CSR con la CA propia, emite cert válido 90 días
   - Genera shared_secret para HMAC de comandos
   - Retorna { cert, ca_cert, shared_secret, master_secret }
   - Invalida bootstrap_secret (single-use)

4. Agente persiste:
   - cert + clave privada en /var/lib/fim-agent/certs/ (0600)
   - shared_secret en /var/lib/fim-agent/secrets/shared_secret (0400)
   - master_secret en /var/lib/fim-agent/secrets/master_secret (0400)
```

### Rotación y revocación

- **Rotación**: 15 días antes de expirar, el agente inicia renovación presentando el cert actual (ya sobre mTLS).
- **Revocación**: tabla `revoked_certificates` en DB (serial, revoked_at, reason). Backend verifica en cada handshake.

### Firma HMAC de comandos (C7)

Además del canal mTLS, cada comando individual del backend al agente se firma con HMAC-SHA256:

```python
signature = hmac.new(
    shared_secret,
    canonical_json(payload),  # orden determinístico de keys
    hashlib.sha256
).hexdigest()
```

El agente rechaza comandos con signature inválida. **Defensa en profundidad**: si alguien compromete Valkey pero no el cert, no puede inyectar comandos.

### Ventajas sobre API keys

* Sin secretos en plaintext — los certificados no son passwords
* Resistente a replay attacks — cada handshake TLS es único
* Identificación criptográfica — el agente es quien dice ser
* Revocable — se puede revocar un certificado sin cambiar passwords

## Responsabilidades del backend

El backend:

* NO restaura archivos directamente
* NO modifica filesystem

👉 El backend:

* Recibe y persiste eventos (con XACK + event_ack bidireccional — C3)
* Valida transiciones de estado contra la máquina formal (C2)
* Aplica optimistic locking en actualizaciones de `status` (C5)
* Evalúa reglas, genera alertas y dispara webhooks
* Procesa aprobaciones/rechazos del admin
* Envía comandos firmados al agente via Valkey
* Dispara notificaciones via n8n con retry + DLQ (W11)
* Mantiene audit_log de retención ilimitada (W18)
* Verifica timestamps dobles contra clock skew (W13)

---

# 🔁 Flujo Completo (Pipeline end-to-end)

```
1. Agente detecta cambio (fanotify via pyfanotify)
   · Recibe: path, pid, uid, exe del proceso causante

2. Calcula SHA-256 del archivo actual
   Descifra entrada de baseline (AES-GCM) y compara hash

3. Si cambió: genera snapshot cifrado + diff (si corresponde)
4. Evalúa regla cacheada

5. Según acción de la regla:
   ├── auto_restore  → journal(pending) → restaurar → journal(completed) → evento (auto_restored)
   ├── quarantine    → journal(pending) → aislar    → journal(completed) → evento (quarantined)
   ├── manual_review → NO tocar                                         → evento (pending)
   └── alert_only    → NO tocar                                         → evento (alert_only)

6. Publica evento en stream events de Valkey
   Payload: event_id UUID v4, detected_at, schema_version, signature HMAC,
            contexto de proceso, path, hash, action_type
   · Si offline: encola en /var/lib/fim-agent/queue/ (atómico write+rename)

7. Backend consume (consumer group fim-backend):
   · Valida timestamps dobles (|received_at - detected_at| <= 5 min) — W13
   · Valida schema_version — W14
   · Valida transición de estado — C2
   · Persiste en PostgreSQL (SQLModel + UoW)
   · XACK en Valkey
   · Publica event_ack en stream commands (para que el agente limpie cola)
   · Evalúa si necesita alerta → dispara webhook a n8n (con retry + DLQ)
   · Registra en audit_log si es sensible

8. Frontend muestra eventos (TanStack Query, paginado 50/pág)
   · SSE para alertas real-time
   · Banner de degradación si algún componente está down (W12)

9. Admin decide (solo eventos pending):
   ├── approve → optimistic UPDATE + hash actual + baseline_update firmado + audit_log
   └── reject  → optimistic UPDATE + restore/quarantine firmado + audit_log

10. Agente recibe comando:
    · Verifica signature HMAC
    · Verifica ruleset_version monotónica (C11)
    · Ejecuta (con journal) → confirma via event_ack
```

## Comunicación bidireccional via Valkey

```
Agente ──── Valkey Stream events ────► Backend
                                          │
Backend ─── Valkey Stream commands ──► Agente
Agente ──── Valkey Stream agent_heartbeat ───► Backend
```

* **events stream**: agente publica eventos detectados (consumer group `fim-backend`)
* **commands stream**: backend envía órdenes firmadas (baseline_update, restore_file, quarantine_file, rescan_baseline, update_config, event_ack)
* **agent_heartbeat stream**: heartbeat cada 10 s con `queue_size`, `ruleset_version`, flag `queue_pressure` si la cola supera 80%, flag `shutdown` si está drenando

---

# 🔔 n8n — Enrutador acotado de notificaciones

## Licencia

**Sustainable Use License** (fair-code). No es OSS puro. **Aceptable** para uso académico y self-hosted. **No apta** para reventa comercial ni incorporación como componente principal de productos comerciales. La política de fallbacks automáticos garantiza que la indisponibilidad de n8n no comprometa el alertado.

## Rol acotado

n8n **no** ejecuta comandos sobre el sistema operativo del anfitrión monitoreado. No coordina el playbook ni toma decisiones. Se limita a:

* Recibir webhooks del backend
* Enrutarlos a canales externos: correo, mensajería corporativa (Teams, Slack, etc.), SIEM
* Reintentar internamente según su propia configuración de workflow

Toda la lógica de decisión (aprobar, rechazar, restaurar, cuarentena) vive en el backend propio, que sí tiene los certificados mTLS y el `shared_secret` para hablar con el agente.

## Integración con backend (con retry + DLQ — W11)

El backend llama a n8n via webhook HTTP:

```
POST http://n8n:5678/webhook/fim-alert
Content-Type: application/json

{
  "event_id": "...",
  "severity": "critical",
  "file_path": "/etc/passwd",
  "process_exe": "/usr/bin/curl",
  "action_taken": "auto_restored",
  "timestamp": "2026-04-23T14:32:11Z"
}
```

**Política de retry**: 3 intentos con delays 5 s / 30 s / 120 s (exponencial).

**DLQ**: si fallan los 3 intentos, se persiste en la tabla `failed_notifications(id, event_id, payload_json, last_error, failed_at, retry_count)`. La UI muestra un banner amarillo persistente mientras haya filas (W11) y el admin puede reintentar manualmente o descartar.

## Cascada de fallbacks (garantía de entrega)

El `NotificationDispatcher` del backend intenta canales en orden de precedencia (Tabla 8 de la tesis):

| Orden | Canal | Condición |
|-------|-------|-----------|
| 1 | n8n webhook | Default, hasta 3 retries |
| 2 | SMTP directo | Si n8n falla los 3 retries (y admin configuró SMTP directo como fallback) |
| 3 | Webhook directo a canal externo | Si tanto n8n como SMTP fallan (p. ej. endpoint Teams pre-configurado) |
| 4 | Log crítico | Siempre se escribe, independientemente de lo anterior |
| 5 | Tabla `failed_notifications` + banner UI | Si ningún canal externo pudo entregar |

## Base de datos de n8n

n8n utiliza la **misma instancia de PostgreSQL** pero una **base de datos separada** (`fim_n8n`):

* Comparte infraestructura (un solo contenedor `db`)
* Datos aislados (bases de datos distintas: `fim` y `fim_n8n`)
* Un script de inicialización crea ambas bases de datos al arrancar

```sql
-- db/init/01-create-databases.sql
CREATE DATABASE fim_n8n;
GRANT ALL PRIVILEGES ON DATABASE fim_n8n TO fim;
```

---

# 🌐 Frontend (React + TypeScript + Vite)

## Stack del frontend

| Componente | Tecnología | Rol |
|------------|-----------|-----|
| UI | React 19 + TypeScript | Componentes tipados |
| Bundler | Vite | Dev server + build |
| Data fetching | TanStack Query v5 | Cache, refetch automático, mutations |
| HTTP | Axios | Cliente HTTP con interceptors para JWT |
| Estado global | Zustand | Store liviano para auth state, UI state |
| Routing | React Router v7 | Navegación SPA |
| Estilos | Tailwind CSS 4.2 + @tailwindcss/vite | Utility-first, CSS-first config, plugin Vite nativo |
| Diff viewer | react-diff-viewer-continued | Con escapado activado; prohibido `dangerouslySetInnerHTML` (W8) |

## Hardening web (W7, W8, W9)

### Headers HTTP emitidos por nginx

* `Content-Security-Policy`: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://backend; frame-ancestors 'none'`
* `Strict-Transport-Security`: `max-age=31536000; includeSubDomains`
* `X-Frame-Options: DENY`
* Validación de header `Origin` contra whitelist en backend
* Cookies con `SameSite=Strict`

### Almacenamiento de tokens en cliente (W9)

* **Access token** (15 min): en memoria (Zustand store). NUNCA en `localStorage`/`sessionStorage`.
* **Refresh token** (7 días, rotación): cookie `httpOnly` + `Secure` + `SameSite=Strict` + `Path=/auth/refresh`.

Resiste XSS (el token no es accesible a JS) y CSRF (SameSite=Strict).

## Configuración Tailwind CSS v4 con Vite

Tailwind v4 es un **rewrite completo**. La integración con Vite es directa:

```bash
# Instalación
pnpm add tailwindcss @tailwindcss/vite
```

```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
})
```

```css
/* src/index.css */
@import "tailwindcss";

/* Customización con @theme (reemplaza tailwind.config.js) */
@theme {
  --color-fim-primary: #1e40af;
  --color-fim-danger: #dc2626;
  --color-fim-warning: #f59e0b;
  --color-fim-success: #16a34a;
}
```

> **No hay `tailwind.config.js`** — toda la configuración es CSS-first con `@theme`.
> **No hay PostCSS** — `@tailwindcss/vite` reemplaza el plugin de PostCSS.
> **No hay `@tailwind base/components/utilities`** — solo `@import "tailwindcss";`.

## Estructura sugerida

```
frontend/
├── src/
│   ├── main.tsx
│   ├── index.css              # @import "tailwindcss" + @theme
│   ├── App.tsx
│   ├── api/
│   │   ├── client.ts          # Axios instance + interceptors
│   │   └── endpoints/
│   │       ├── events.ts      # useEvents(), useEvent(id), useBulkApprove(), useBulkReject()
│   │       ├── rules.ts
│   │       ├── agents.ts
│   │       ├── alerts.ts
│   │       ├── health.ts      # useHealthComponents() polling 10s (W12)
│   │       ├── notifications.ts # useFailedNotifications() (W11)
│   │       └── auth.ts
│   ├── stores/
│   │   └── auth.store.ts      # Zustand: user, access_token in-memory, logout
│   ├── pages/
│   │   ├── Dashboard.tsx
│   │   ├── Events.tsx         # Paginado 50/pág, bulk actions (W15), toggle superseded (W1)
│   │   ├── Rules.tsx
│   │   ├── Agents.tsx         # Muestra estado draining (W17)
│   │   ├── Alerts.tsx
│   │   ├── FailedNotifications.tsx  # W11
│   │   ├── ForcePasswordChange.tsx  # W20
│   │   └── Login.tsx
│   └── components/
│       ├── layout/
│       │   ├── Sidebar.tsx
│       │   ├── Navbar.tsx
│       │   ├── SystemBanner.tsx      # Banner rojo si health != ok (W12)
│       │   ├── NotificationsBanner.tsx # Banner amarillo si hay failed_notifications (W11)
│       │   ├── MainLayout.tsx
│       │   └── AuthLayout.tsx
│       └── ui/
│           ├── DiffViewer.tsx        # react-diff-viewer-continued
│           ├── EventsTable.tsx       # Selección múltiple + paginación
│           ├── BulkActionBar.tsx     # Aprobar/rechazar seleccionados
│           ├── EventTimeline.tsx
│           ├── RejectModal.tsx       # Branch baseline_absent (C10)
│           ├── AgentCard.tsx         # Estado draining visible
│           ├── Badge.tsx
│           ├── Button.tsx
│           └── Card.tsx
├── Dockerfile
├── nginx.conf                 # Headers CSP, HSTS, etc. (W7)
├── vite.config.ts
└── package.json
```

## Capacidades

* Ver diffs de archivos (texto)
* Ver comparación de archivos binarios (hash comparison + hex dump parcial)
* Ver historial de versiones (snapshots)
* Ver acciones automáticas ejecutadas + contexto del proceso causante
* Aprobar o rechazar eventos `pending` (approve / reject) con manejo de conflicto 409 (C5)
* Bulk approve/reject (W15)
* Ver cadena de eventos por path (event chain)
* Toggle "mostrar superseded" (W1)
* Dashboard con métricas de integridad
* Alertas en tiempo real (SSE desde backend)
* Banner de degradación del sistema (W12)
* Banner de notificaciones fallidas + vista de reintento/descarte (W11)
* Forzado de cambio de password en primer login (W20)
* Gestión de paths monitoreados por agente (sin reiniciar el servicio)
* Trigger de re-scan con warning de impacto en pending

---

# ⚠️ Limitaciones tecnológicas conocidas del stack

Alineadas con la sección 6.6 de la tesis v6. Cada limitación motivó una decisión arquitectónica concreta.

| # | Limitación | Decisión arquitectónica derivada |
|---|------------|----------------------------------|
| 1 | **`fanotify` requiere `CAP_SYS_ADMIN`** | Agente desplegado nativo fuera de Docker; hardening con systemd (`ProtectSystem=strict`, `NoNewPrivileges`, etc.). Se documenta como restricción de deployment. |
| 2 | **`fanotify` detecta *después* del write** (aun con modo permisos, la inspección pre-write tiene costos que no asumimos en el MVP) | El diff se genera comparando contra el baseline; el archivo ya está modificado cuando se evalúa. Para protección pre-write se deriva a trabajo futuro (IMA, dm-verity). |
| 3 | **Saturación del consumidor `fanotify`** (eventos pueden perderse silenciosamente si el agente no consume a tiempo) | El agente monitorea activamente el nivel de backpressure y lo reporta como anomalía en el heartbeat (`queue_pressure` flag). |
| 4 | **Valkey con persistencia AOF periódica** — un crash puede perder los últimos ms de escrituras | Cola local del agente actúa como buffer antes de la confirmación `XACK + event_ack` del backend (C3), que es la que autoriza la eliminación local. |
| 5 | **Backend en instancia única** (C4) — no se diseña HA multi-réplica en el MVP | Init-container para arranque rápido + cola local del agente que preserva eventos durante la ventana de reinicio. Documentado como consideración de producción futura. |
| 6 | **n8n no ejecuta comandos nativos del SO** | Delimitado a enrutador de notificaciones externas; toda la lógica de decisión y acción sobre el FS vive en el backend propio + agente. |
| 7 | **n8n licencia fair-code** | No apta para reventa comercial ni incorporación como componente principal de productos comerciales. Compatible con uso académico y self-hosted. Fallbacks automáticos permiten operar sin n8n. |
| 8 | **Raíz de confianza en espacio de usuario** — si el kernel del anfitrión está comprometido, todo el sistema lo está | Reconocida como amenaza residual. Trabajo futuro: integración con IMA, dm-verity, Secure Boot. |
| 9 | **Diffs textuales no aplican a binarios** | Para binarios se muestra comparación de hash + hex dump parcial de primeros bytes. |
| 10 | **Cola offline del agente (JSON files)** — no tiene transaccionalidad | Escritura atómica (`write + rename`), tamaños acotados (100 MB, drop-oldest), confirmación bidireccional via `event_ack`. Aceptable para el caso de uso. |
| 11 | **Argon2id con parámetros fijos** puede resultar desmedido o insuficiente según el hardware | Se fijan parámetros recomendados por OWASP 2026 (C9). Futuro: benchmark al arranque para ajuste por entorno. |

---

# 🐳 Docker Compose

## Servicios (servidor central — el agente NO está acá)

```yaml
# docker-compose.yml (estructura)
services:
  db:
    image: postgres:18
    environment:
      POSTGRES_DB: fim
      POSTGRES_USER: fim
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
      - ./db/init:/docker-entrypoint-initdb.d:ro
    # Sin puerto expuesto al host en producción; solo accesible por la red interna

  db-init:
    build: ./db-init
    depends_on:
      db:
        condition: service_healthy
    restart: "no"
    environment:
      DATABASE_URL: postgresql+psycopg://fim:${DB_PASSWORD}@db:5432/fim
      ADMIN_USERNAME: ${ADMIN_USERNAME}
      ADMIN_PASSWORD: ${ADMIN_PASSWORD}
    # Init-container: corre una vez, crea schema + seed admin (W20), sale

  valkey:
    image: valkey/valkey:9.0
    # Sin puerto expuesto al host en producción

  backend:
    build: ./backend
    depends_on:
      db-init:
        condition: service_completed_successfully
      valkey:
        condition: service_started
    environment:
      DATABASE_URL: postgresql+psycopg://fim:${DB_PASSWORD}@db:5432/fim
      VALKEY_URL: valkey://valkey:6379
      JWT_SECRET_CURRENT: ${JWT_SECRET_CURRENT}
      JWT_SECRET_PREVIOUS: ${JWT_SECRET_PREVIOUS}
      CA_CERT_PATH: /certs/ca.pem
      CA_KEY_PATH: /certs/ca-key.pem
    volumes:
      - backend_certs:/certs:ro
    ports:
      - "8443:8443"  # HTTPS + mTLS para agentes
      - "8000:8000"  # HTTPS para frontend
    deploy:
      replicas: 1  # Single-instance (C4)

  frontend:
    build: ./frontend
    depends_on:
      - backend
    ports:
      - "3000:80"
    # nginx con headers CSP, HSTS, etc. (W7)

  n8n:
    image: n8nio/n8n:2.16.1
    depends_on:
      db-init:
        condition: service_completed_successfully
    environment:
      DB_TYPE: postgresdb
      DB_POSTGRESDB_HOST: db
      DB_POSTGRESDB_DATABASE: fim_n8n
      DB_POSTGRESDB_USER: fim
      DB_POSTGRESDB_PASSWORD: ${DB_PASSWORD}
    # Sin puerto expuesto al host; solo accesible por el backend

volumes:
  pg_data:
  backend_certs:
```

> **El agente NO está en el compose**. Se despliega nativo en cada anfitrión monitoreado mediante la unit file de systemd mostrada en la sección "Despliegue del agente". El compose es solo para el servidor central.

---

# 🔄 CI/CD — GitHub Actions

## Pipeline propuesto

```yaml
# .github/workflows/ci.yml (estructura)
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r backend/requirements.txt
      - run: cd backend && python -m pytest

  agent:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -r agent/requirements.txt
      - run: cd agent && python -m pytest
      # Integration tests de fanotify requieren kernel Linux; ubuntu-latest lo provee

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
      - run: corepack enable && corepack prepare pnpm@latest --activate
      - run: cd frontend && pnpm install --frozen-lockfile
      - run: cd frontend && pnpm lint
      - run: cd frontend && pnpm build

  docker:
    needs: [backend, frontend]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose build
      # Nota: solo construye imágenes del servidor central; el agente se empaqueta aparte
      #       (futuro: packaging nativo en .deb y .rpm — ver sección 8.8 de la tesis)
```

---

# 🧠 Conclusión

Esta arquitectura define un sistema FIM completo con:

✔ Detección reactiva sobre `fanotify` con contexto de proceso causante
✔ Agente nativo con hardening systemd (no en Docker por `CAP_SYS_ADMIN`)
✔ Restauración confiable (snapshot cifrado + baseline dinámico + journal pre-acción)
✔ Motor de decisión basado en reglas (4 niveles de acción)
✔ Flujo de aprobación humana con cadena de eventos `superseded` + optimistic locking
✔ Análisis forense (diff + historial de snapshots + audit_log de retención ilimitada)
✔ Baseline dinámico cifrado (AES-256-GCM + HKDF) sincronizado entre agente y backend
✔ Comunicación bidireccional firmada (mTLS + HMAC + timestamps dobles anti-replay)
✔ Stack completo definido con versiones actuales (Abril 2026)
✔ Servidor central contenedorizado; agente nativo
✔ Seguridad en profundidad (Argon2id + mTLS + HMAC + AES-GCM)
✔ Configuración de agente gestionable en runtime
✔ Patrones glob con negación para reglas flexibles
✔ n8n delimitado a enrutador con política de fallbacks automáticos
✔ Resiliencia offline con cola local + confirmación bidireccional (C3)

---

El sistema implementa un **modelo híbrido de respuesta automatizada y validación humana**:

* **Detección** — `fanotify` vía pyfanotify con contexto forense (PID/UID/exe), motor de decisión local
* **Respuesta** — 4 niveles: auto_restore, quarantine, manual_review, alert_only
* **Control humano** — Aprobación/rechazo de cambios pendientes con cadena de eventos y optimistic locking
* **Baseline inteligente** — Dinámico, cifrado AES-GCM, actualizado solo por decisión humana (approve) o re-scan explícito
* **Auditoría** — diffs, historial de snapshots, cadena con `superseded`, audit_log separado (W18)
* **Alerta** — cascada: n8n → SMTP → webhook directo → log → DLQ con banner UI
* **Visualización** — React SPA con diffs, timeline, aprobaciones (con manejo 409), bulk actions, event chain

---

👉 Esto no es solo monitoreo: es un **sistema activo de detección reactiva, recuperación, control de integridad con validación humana y trazabilidad forense completa**, alineado con el marco normativo argentino (Ley 25.326, Res. AAIP 47/2018 y 126/2024, Res. 44/2023, DNU 941/2025).

---

# 📚 Referencias de versiones

| Tecnología | Fuente | Verificado |
|------------|--------|------------|
| FastAPI 0.136.0 | [PyPI](https://pypi.org/project/fastapi/) / [GitHub](https://github.com/fastapi/fastapi/releases) | 23 Abr 2026 |
| Valkey 9.0.3 | [GitHub](https://github.com/valkey-io/valkey/releases) / [valkey.io](https://valkey.io) | 23 Abr 2026 |
| n8n 2.16.1 | [GitHub](https://github.com/n8n-io/n8n/releases) / [n8n.io](https://n8n.io) | 23 Abr 2026 |
| PostgreSQL 18.3 | [postgresql.org](https://www.postgresql.org/) | 23 Abr 2026 |
| pyfanotify 0.3.0 | [PyPI](https://pypi.org/project/pyfanotify/) | 23 Abr 2026 |
| SQLModel | [sqlmodel.tiangolo.com](https://sqlmodel.tiangolo.com/) | 23 Abr 2026 |
| React 19 | [react.dev](https://react.dev/) | 23 Abr 2026 |
| Tailwind CSS 4.2.2 | [tailwindcss.com](https://tailwindcss.com/) / [GitHub](https://github.com/tailwindlabs/tailwindcss/releases) | 23 Abr 2026 |

---

## Appendix: Decisiones de auditoría — Abril 2026

Las siguientes decisiones resultan de la auditoría de consistencia, lifecycle, seguridad y resiliencia realizada el 2026-04-22. En caso de conflicto con secciones previas del documento, prevalece lo especificado en este appendix.

### Léxico y nomenclatura

#### C1: Léxico canónico en minúsculas
**Decisión**: Los valores del campo `status` de eventos (`pending`, `approved`, `rejected`, `superseded`, `auto_restored`, `quarantined`, `alert_only`) se escriben SIEMPRE en minúsculas (snake_case) tanto en código, schemas, JSON, logs y prosa descriptiva cuando se refieren al valor literal. Se toleran mayúsculas solo como títulos markdown (`## PENDING`) o cuando se referencia la acción del botón de UI en texto narrativo (`click en APPROVE`).
**Motivación**: Eliminar ambigüedad entre variantes mayúsculas/minúsculas detectada en diagramas y prosa.
**Aplicación**: Modelos SQLModel (`EventStatus` enum), schemas API, cliente Valkey, logs estructurados, documentación técnica.

### Modelo de eventos y lifecycle

#### C2: Máquina de estados explícita (in-edges / out-edges)
**Decisión**: Se adopta la siguiente tabla de transiciones canónicas.

| Estado destino | In-edges permitidas | Out-edges permitidas |
|----------------|---------------------|----------------------|
| `pending` | (creación por agente, action=`manual_review`) | `approved`, `rejected`, `superseded` |
| `approved` | `pending` (admin approve) | (terminal) |
| `rejected` | `pending` (admin reject) | (terminal) |
| `superseded` | `pending` (cadena), `pending` (re-scan) | (terminal) |
| `auto_restored` | (creación por agente, action=`auto_restore`) | (terminal) |
| `quarantined` | (creación por agente, action=`quarantine`) | (terminal) |
| `alert_only` | (creación por agente, action=`alert_only` o default) | (terminal) |

Cualquier transición no listada es inválida y debe ser rechazada a nivel de service con error 409.
**Motivación**: Convertir el ciclo de vida informal en un contrato verificable.
**Aplicación**: `modules/events/service.py` (validador de transición), tests de lifecycle.

#### C3: Protocolo ACK Valkey
**Decisión**:
- El agente genera un `event_id` UUID v4 al crear cada evento.
- El backend consume con consumer group `fim-backend`.
- Tras persistir en PostgreSQL, el backend ejecuta `XACK` en el stream `events`.
- El backend publica un mensaje `event_ack` en el stream `commands` con el `event_id`.
- El agente, al recibir el `event_ack`, elimina la entrada correspondiente de su cola local.
**Motivación**: Garantizar entrega exactamente-una-vez end-to-end sin perder eventos en crashes del agente tras publicar pero antes de confirmar.
**Aplicación**: `modules/events/consumer.py` (XACK + publish ack), agente (handler `event_ack` + cleanup de `/var/lib/fim-agent/queue/`).

#### C10: Rechazo sobre baseline `absent` = no-op con warning
**Decisión**: Si un admin rechaza un evento cuyo baseline ya está en `status: absent`, la operación NO envía comando `restore_file` al agente (no hay archivo a restaurar), marca el evento como `rejected`, loguea warning y retorna respuesta 200 con flag `baseline_absent: true`.
**Motivación**: Evitar comandos espurios al agente y degradación silenciosa.
**Aplicación**: `modules/actions/service.py` (reject flow).

#### C11: `ruleset_version` monotónico
**Decisión**: Los comandos `baseline_update`, `rule_sync`, `update_config` y `rescan_baseline` incluyen un `ruleset_version: int` monotónico creciente generado por el backend. El agente persiste el último `ruleset_version` aplicado y descarta mensajes con versión menor (idempotencia + ordering).
**Motivación**: Prevenir aplicación fuera de orden por re-entregas de Valkey.
**Aplicación**: Tabla `ruleset_version` en PostgreSQL (counter), payload de commands, agente (state persistido en `/var/lib/fim-agent/state.json`).

### Arquitectura del sistema

#### C4: Backend single-instance
**Decisión**: El backend FastAPI corre como **un único contenedor**. No se diseña para HA multi-réplica en el MVP. Las asunciones de optimistic locking (C5) y JWT revocation (C8) se basan en este supuesto.
**Motivación**: Simplificar consumer groups, coordinación Valkey y rate limiting in-process.
**Aplicación**: `docker-compose.yml` (replicas: 1), documentación de deployment.

#### C5: Optimistic locking sobre Event
**Decisión**: Se agrega una columna `version: int` (default 0) a la tabla `events`. Toda actualización de `status` usa:
```sql
UPDATE events
SET status = :new_status, version = version + 1, resolved_at = NOW(), resolved_by = :user_id
WHERE id = :event_id AND version = :expected_version AND status = 'pending';
```
Si el `UPDATE` afecta 0 filas, se retorna HTTP 409 con body `{ "error": "conflict", "reason": "event_already_resolved_or_superseded" }`.
**Motivación**: Evitar race conditions entre dos admins aprobando el mismo evento simultáneamente o entre aprobación y auto-superseded por nuevo evento del agente.
**Aplicación**: `modules/events/models.py` (`version: int = Field(default=0)`), `modules/actions/service.py`.

### Seguridad y criptografía

#### C6: Bootstrap mTLS con CA propia
**Decisión**:
- El backend actúa como CA propia (self-hosted PKI).
- El admin pre-registra un `agent_id` y un `bootstrap_secret` (32 bytes aleatorios) en la DB vía UI.
- El agente envía al endpoint `POST /agents/bootstrap` un CSR firmado con el `bootstrap_secret` (HMAC) + el `agent_id`.
- El backend verifica HMAC, firma el CSR, emite un certificado válido por **90 días** y lo retorna.
- El agente persiste el certificado en `/var/lib/fim-agent/certs/`.
- Rotación: 15 días antes de expirar, el agente inicia renovación presentando el cert actual (ya mTLS).
- Revocación: tabla `revoked_certificates` en DB (serial, revoked_at, reason); backend verifica contra la lista en cada handshake.
**Motivación**: Evitar secretos compartidos persistentes y permitir rotación automática.
**Aplicación**: `modules/agents/bootstrap_router.py`, `core/pki.py`, middleware TLS del backend.

#### C7: HMAC-SHA256 en comandos backend → agente
**Decisión**: Cada comando publicado en el stream `commands` incluye un campo `signature` = `HMAC-SHA256(shared_secret, canonical_json(payload))`. El `shared_secret` se genera por agente al emitir su cert mTLS y se distribuye en el mismo payload de bootstrap (cifrado en tránsito por TLS). El agente rechaza comandos con signature inválida.
**Motivación**: Defensa en profundidad contra inyección si alguien compromete Valkey pero no el certificado.
**Aplicación**: `modules/agents/service.py` (publisher), agente (command handler).

#### C8: Gestión de JWT
**Decisión**:
- Access token: exp 15 minutos.
- Refresh token: exp 7 días con rotación en cada uso (el refresh anterior se invalida al emitir uno nuevo).
- Blacklist de `jti` revocados en Valkey con TTL = exp restante del token.
- Multi-key signing: variables `JWT_SECRET_CURRENT` y `JWT_SECRET_PREVIOUS`. Se firma con CURRENT, se verifica intentando primero CURRENT y luego PREVIOUS. Al rotar, se promueve CURRENT→PREVIOUS y se genera un nuevo CURRENT.
**Motivación**: Permitir rotación de clave sin downtime y revocación inmediata de refresh tokens comprometidos.
**Aplicación**: `core/security.py`, `modules/auth/service.py`.

#### C9: Parámetros Argon2id
**Decisión**: `PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)`. No se usan los defaults del paquete.
**Motivación**: Alinearse con la recomendación OWASP 2026 y evitar variaciones entre versiones de `argon2-cffi`.
**Aplicación**: `core/security.py` (instancia singleton de `PasswordHasher`).

#### W10: Cifrado de baseline en disco
**Decisión**: Los archivos dentro de `/var/lib/fim-agent/baseline/` se cifran con AES-256-GCM. La key se deriva con HKDF-SHA256 desde `HKDF(ikm=master_secret, salt=AGENT_ID, info="baseline-v1")`. El `master_secret` se entrega al agente en el payload de bootstrap y se persiste con permisos `0400` en `/var/lib/fim-agent/secrets/master_secret`.
**Motivación**: Proteger el baseline contra lectura offline en caso de compromiso del volumen.
**Aplicación**: Agente (módulo `storage/baseline_crypto.py`).

### Resiliencia y degradación

#### W2: Journal pre-acción
**Decisión**: Antes de ejecutar `auto_restore` o `quarantine`, el agente escribe una entrada JSON en `/var/lib/fim-agent/journal/{event_id}.json` con `{event_id, path, action, started_at, state: "pending"}`. Al completar, se actualiza a `state: "completed"` o `state: "failed"` con detalles. Al arranque, el agente rehidrata el journal y reintenta o reporta acciones incompletas.
**Motivación**: Asegurar consistencia si el agente muere mid-action.
**Aplicación**: Agente (decision engine + recovery on startup).

#### W3: Cola offline con límite y política
**Decisión**: La cola `/var/lib/fim-agent/queue/` tiene un máximo de **100 MB**. Política drop-oldest al superar el límite. Si el uso supera el **80%**, el agente publica (al reconectar) un heartbeat con flag `queue_pressure: true` que la UI muestra como alerta banner.
**Motivación**: Evitar agotar disco del anfitrión en escenarios de desconexión prolongada.
**Aplicación**: Agente (`storage/queue.py`), backend (endpoint `/agents/status`), frontend (banner).

#### W4: Orden al reconectar
**Decisión**: Al restablecerse la conexión, el agente procesa **primero** los comandos pendientes del stream `commands` (en especial `baseline_update`/`rule_sync`/`update_config`) y **después** envía los eventos encolados. Esto garantiza que los eventos se persistan con el ruleset correcto.
**Motivación**: Evitar que eventos offline se evalúen contra reglas desactualizadas al llegar al backend.
**Aplicación**: Agente (reconnect state machine).

#### W11: Retry de webhook n8n + DLQ
**Decisión**: Los webhooks hacia n8n usan retry exponencial **3 intentos con delays 5 s / 30 s / 120 s**. Si fallan los 3, se persiste una fila en la tabla `failed_notifications(id, event_id, payload_json, last_error, failed_at, retry_count)`. La UI muestra un banner persistente mientras haya filas.
**Motivación**: No perder alertas críticas si n8n está caído.
**Aplicación**: `modules/notifications/n8n_client.py`, `modules/notifications/models.py`, frontend (`NotificationsBanner`).

#### W12: Endpoint de salud por componente + UI
**Decisión**: Endpoint `GET /health/components` retorna `{postgres: "ok"|"degraded"|"down", valkey: ..., n8n: ..., agents: [{id, state}]}`. El frontend hace polling cada **10 s** y muestra un banner persistente si algún componente no está `ok`. El mismo endpoint dispara webhook n8n ante cambios de estado.
**Motivación**: Visibilidad operativa unificada.
**Aplicación**: `modules/health/router.py`, frontend (`SystemBanner` en `MainLayout`).

### Operaciones

#### W5: Rate limiting
**Decisión**:
- Login: **5 intentos / 15 minutos** por `(username + IP)`. Key: `rl:login:{user}:{ip}`.
- API autenticada default: **100 requests / minuto** por user.
- Stream de eventos del agente: **100 eventos / minuto** por `agent_id` (en backend, tras consumir del stream; excedente se descarta con alerta).

Implementado en Valkey con counters + TTL.
**Motivación**: Mitigar abuso y DoS accidental.
**Aplicación**: `core/rate_limit.py`, middleware FastAPI, consumer del agente.

#### W6: Logging y retention
**Decisión**: `structlog` con renderer JSON. Middleware `sanitize_logs` que filtra los campos `password`, `access_token`, `refresh_token`, `bootstrap_secret`, `master_secret`, `shared_secret`, `signature` antes de emitir. Retention de logs: **30 días**. **Prohibido loguear contenido de diffs** — solo `hash_before`, `hash_after`, `size_delta`.
**Motivación**: Cumplimiento de buenas prácticas y reducción de superficie si los logs se filtran.
**Aplicación**: `core/logging.py`, pipeline de logs (rotación vía systemd journal / Docker logging driver).

#### W13: Timestamps dobles con anti-replay
**Decisión**: Todo evento publicado por el agente incluye `detected_at: datetime` (agente) y el backend agrega `received_at: datetime` al consumirlo. Si `abs(received_at - detected_at) > 5 minutos`, el backend rechaza el evento con código `clock_skew` y lo persiste en `rejected_events_audit`.
**Motivación**: Detectar relojes desincronizados o replay attacks.
**Aplicación**: Agente (publisher), `modules/events/consumer.py`.

#### W14: `schema_version` en mensajes
**Decisión**: Todo mensaje en streams `events` y `commands` incluye `schema_version: int` (start en 1). El backend rechaza mensajes con `schema_version` mayor que el soportado (`UNSUPPORTED_SCHEMA`). El agente ignora campos desconocidos (forward compat). Se documenta cada bump en `docs/schema_changelog.md`.
**Motivación**: Evolución controlada del protocolo entre versiones de agente y backend.
**Aplicación**: Schemas Pydantic compartidos, agente (payload builder).

#### W16: Heartbeat y estado de agente
**Decisión**: El agente publica cada **10 segundos** al stream `agent_heartbeat` un mensaje `{agent_id, timestamp, queue_size, ruleset_version, queue_pressure, shutdown}`. Backend:
- Sin heartbeat por **30 s** → estado `offline`.
- Sin heartbeat por **5 minutos** → estado `dead` + alerta webhook n8n.
**Motivación**: Detección temprana de agentes caídos.
**Aplicación**: Agente (scheduler), `modules/agents/heartbeat_consumer.py`.

#### W17: Graceful shutdown
**Decisión**: Al recibir `SIGTERM`, el agente:
1. Deja de aceptar nuevos eventos de fanotify.
2. Drena la cola local publicando al stream (timeout 30 s).
3. Exit 0.

Durante el drenaje, el heartbeat incluye flag `shutdown: true`; el backend refleja estado `draining` en `/health/components` y la UI muestra indicador visual.
**Motivación**: Evitar pérdida de eventos en rolling deployments o reinicios planificados.
**Aplicación**: Agente (signal handler).

#### W18: Tabla `audit_log` separada
**Decisión**: Tabla dedicada `audit_log(id, timestamp, user_id, action, resource_type, resource_id, ip, user_agent, metadata_json)`. Registra login/logout, CRUD de reglas, approve/reject, re-scan, cambios de config. Retention ilimitada (no se rota con los logs estructurados).
**Motivación**: Trazabilidad para auditorías de seguridad y cumplimiento normativo (Res. AAIP 47/2018 y 126/2024).
**Aplicación**: `modules/audit/models.py` + `modules/audit/service.py` (called as side-effect en servicios sensibles).

### Frontend

#### W7: Headers HTTP
**Decisión**: nginx del frontend emite:
- `Content-Security-Policy`: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://backend; frame-ancestors 'none'`
- `Strict-Transport-Security`: `max-age=31536000; includeSubDomains`
- `X-Frame-Options: DENY`
- Validación de header `Origin` contra whitelist en backend.
- Cookies con `SameSite=Strict`.
**Motivación**: Mitigar XSS, clickjacking y CSRF.
**Aplicación**: `frontend/nginx.conf`, backend CORS middleware.

#### W8: DiffViewer seguro
**Decisión**: Se adopta `react-diff-viewer-continued` con opciones de escapado activas. Queda **prohibido** el uso de `dangerouslySetInnerHTML` en todo el codebase (lint rule `react/no-danger`).
**Motivación**: Prevenir XSS si un atacante inyecta contenido malicioso en un archivo monitoreado.
**Aplicación**: `components/ui/DiffViewer.tsx`, `.eslintrc`.

#### W9: Almacenamiento de tokens en cliente
**Decisión**:
- Access token: en memoria (Zustand store), nunca en `localStorage`/`sessionStorage`.
- Refresh token: cookie `httpOnly` + `Secure` + `SameSite=Strict` + `Path=/auth/refresh`.
**Motivación**: Resistir XSS (no accesible a JS) y CSRF (SameSite=Strict).
**Aplicación**: `stores/auth.store.ts`, backend `modules/auth/router.py` (Set-Cookie en `/auth/login`).

#### W15: Bulk actions + paginación
**Decisión**:
- La tabla de eventos soporta selección múltiple (checkbox por fila + "seleccionar todos en la página").
- Botones "Aprobar seleccionados" y "Rechazar seleccionados" aparecen cuando hay ≥ 1 fila marcada.
- Bulk approve: modal de confirmación con cuenta de eventos afectados y lista resumida (primeros 10 paths). Ejecuta `POST /actions/bulk-approve` con `event_ids[]`. Respuesta incluye `succeeded[]` y `failed[]` (con razón).
- Bulk reject: adicionalmente pide la acción (`restore` | `quarantine`) que se aplica a todos.
- Paginación: **50 eventos por página** por defecto, navegación numerada + "ir a página".
**Motivación**: Tras un deploy masivo, aprobar uno por uno es impráctico. Paginación fija para previsibilidad de carga.
**Aplicación**: `pages/Events.tsx`, `components/ui/BulkActionBar.tsx`, backend `modules/actions/router.py` (endpoints bulk).

#### W1: Filtro default oculta `superseded`
**Decisión**: La vista de Eventos filtra por defecto excluyendo estados `superseded`. Se agrega un toggle "Mostrar superseded" (checkbox) en el panel de filtros. Al activarlo, reaparecen en la lista con un ícono visual distintivo (cadena rota) y se indica el `parent_event_id`. El toggle se persiste en la URL (query param `?include_superseded=true`).
**Motivación**: Los eventos superseded son ruido operacional; el admin los quiere solo para auditoría.
**Aplicación**: `pages/Events.tsx` (filtro default), `components/ui/EventsTable.tsx`.

#### W20: Seed admin con cambio de password forzado
**Decisión**: El seed del primer admin crea el usuario con flag `must_change_password: bool = True`. En el primer `POST /auth/login` exitoso, el backend emite tokens con scope `password_change_only` y el frontend redirige a una vista donde el admin debe cambiar el password. Hasta que se complete el cambio (y el flag pase a `false`), ninguna otra API responde con éxito (devuelve 403 `password_change_required`).
**Motivación**: Evitar que credenciales de bootstrap queden activas en producción.
**Aplicación**: `modules/users/models.py` (campo `must_change_password`), `core/dependencies.py` (guard), frontend (`pages/ForcePasswordChange.tsx`).

---

## Appendix: Decisiones de implementación — Abril 2026

Las siguientes 8 decisiones cierran las suposiciones abiertas detectadas durante la elaboración del roadmap de implementación ([CHANGES.md](../CHANGES.md)) el 2026-04-24. En caso de conflicto con secciones previas o con el appendix de auditoría, prevalece lo especificado aquí. Las contrapartes normativas (nuevas reglas RN-104 a RN-108 y reescrituras de RN-17, RN-86, RN-102, RN-75) viven en [reglas_de_negocio.md](reglas_de_negocio.md) bajo el mismo título.

### Modelo de datos del backend

#### D1: Réplica de baseline metadata en backend
**Decisión**: El backend persiste una tabla `baseline_entries` con metadata por path monitoreado, sin contenido cifrado. La fuente de verdad del contenido sigue siendo el agente (cifrado AES-256-GCM en `/var/lib/fim-agent/baseline/`).

Schema SQLModel:
```python
class BaselineEntry(SQLModel, table=True):
    __tablename__ = "baseline_entries"
    id: int = Field(primary_key=True)
    path: str = Field(index=True)
    agent_id: str = Field(foreign_key="agents.agent_id", index=True)
    hash: str | None  # null cuando status='absent'
    status: BaselineStatus  # 'present' | 'absent'
    last_updated: datetime
    ruleset_version: int  # versión del comando que generó esta entrada
```

Sincronización: cada `event_ack` exitoso de `baseline_update` (RN-25, RN-59) hace upsert en `baseline_entries`. El backend resuelve approve/reject/UI consultando esta tabla, sin round-trip al agente.

**Motivación**: Eliminar dependencia síncrona del backend hacia el agente para resolver flujos de approve y mostrar estado del baseline en UI. El agente sigue siendo único custodio del contenido cifrado (defensa en profundidad).

**Aplicación**: `modules/agents/models.py` (nueva tabla), `modules/actions/service.py` (consulta `baseline_entries` en approve/reject), `modules/agents/consumer.py` (handler de `event_ack` para `baseline_update`).

#### D4: Tabla `rejected_events_audit` con enum tipado
**Decisión**: Eventos rechazados durante la ingesta (clock skew RN-90, schema inválido RN-91, HMAC inválido, agent desconocido, evento duplicado) se persisten en una tabla auditable con motivo tipado.

Schema SQLModel:
```python
class RejectionReason(str, Enum):
    CLOCK_SKEW = "clock_skew"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_SIGNATURE = "invalid_signature"
    UNKNOWN_AGENT = "unknown_agent"
    DUPLICATE_EVENT = "duplicate_event"

class RejectedEventAudit(SQLModel, table=True):
    __tablename__ = "rejected_events_audit"
    id: int = Field(primary_key=True)
    event_id: str | None  # UUID si pudo parsearse del payload
    agent_id: str
    reason: RejectionReason
    received_at: datetime
    detected_at: datetime | None
    payload_dump: str  # JSON crudo, truncado a 4 KB
```

**Motivación**: `str` libre permite typos que rompen reportes; el enum garantiza léxico cerrado. El truncado a 4 KB evita que un atacante llene la tabla con payloads grandes.

**Aplicación**: `modules/events/models.py` (enum + table), `modules/events/consumer.py` (insert al rechazar).

#### D6: Tabla unificada `alerts` (fusión con `failed_notifications`)
**Decisión**: Se elimina la tabla separada `failed_notifications` mencionada en RN-86 y RN-102. Una única tabla `alerts` cubre todo el lifecycle.

Schema SQLModel:
```python
class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class AlertChannel(str, Enum):
    N8N = "n8n"
    SMTP_FALLBACK = "smtp_fallback"
    WEBHOOK_FALLBACK = "webhook_fallback"
    LOG_ONLY = "log_only"

class Alert(SQLModel, table=True):
    __tablename__ = "alerts"
    id: int = Field(primary_key=True)
    event_id: int = Field(foreign_key="events.id")
    severity: AlertSeverity
    channel: AlertChannel | None  # null mientras pending
    delivered_at: datetime | None
    failed_at: datetime | None
    last_error: str | None
    retry_count: int = Field(default=0)
    created_at: datetime
```

Estados:
- **Pending**: `delivered_at IS NULL AND failed_at IS NULL AND retry_count < 3`
- **Delivered**: `delivered_at IS NOT NULL`
- **Failed terminal**: `delivered_at IS NULL AND failed_at IS NOT NULL`

El banner amarillo del frontend (RN-102) consulta:
```sql
SELECT COUNT(*) FROM alerts WHERE delivered_at IS NULL AND failed_at IS NOT NULL;
```

**Motivación**: Dos tablas duplican lógica para representar el mismo lifecycle. Una sola tabla simplifica queries, índices y la UI de retry/discard.

**Aplicación**: `modules/alerts/models.py` (nueva tabla, elimina `failed_notifications`), `modules/notifications/n8n_client.py` (escribe filas), `modules/health/router.py` (query del banner).

### Despliegue y arranque

#### D3: Lifespan FastAPI ejecuta `seed_admin()` y `create_all()` (sin init-container)
**Decisión**: El seed del primer admin y la creación de tablas (`SQLModel.metadata.create_all()`) se ejecutan en el lifespan de FastAPI. Se elimina el servicio `db-init` del `docker-compose.yml`.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    seed_admin()
    yield
```

**Motivación**: El backend es single-instance (RN-76, C4). No hay race condition. `seed_admin()` y `create_all()` son idempotentes. El init-container agrega complejidad operativa (otra imagen, variable de entorno duplicada para password) sin beneficio en single-instance.

**Trigger de migración a init-container**: si se introduce Alembic con migraciones versionadas, mover seed + migraciones a un init-container es justificado (separar `apply migrations` de `start app`). Documentar este trigger antes de habilitar Alembic.

**Aplicación**: `main.py` (lifespan), `docker-compose.yml` (eliminar servicio `db-init`).

### Sincronización backend ↔ agente

#### D2: Approve usa el hash del evento, no consulta al agente
**Decisión**: **Esta decisión sustituye la versión original de RN-17 que indicaba "el backend consulta al agente el hash actual"**. El backend NO realiza request síncrono al agente al ejecutar approve. Usa el hash que el evento `pending` ya trae al momento de detección.

Justificación técnica:
- El evento `pending` activo refleja el estado más reciente conocido por el sistema. Cualquier cambio detectado posteriormente crea un nuevo evento que marca al anterior como `superseded` (RN-21, C9).
- Aprobar un evento implica que el snapshot al momento de detección es el deseado.
- Aprobar un evento `superseded` retorna 409 (RN-77, C5).

Race window self-healing:
1. T0: archivo cambia, fanotify detecta, evento A con hash_A → pending.
2. T1: archivo cambia de nuevo (microsegundos), fanotify aún no fired.
3. T2: admin aprueba A con hash_A → baseline = hash_A.
4. T3: fanotify procesa T1, evento B con hash_B → pending vs baseline hash_A → admin lo trata normalmente.

El sistema converge sin pérdida de datos.

**Motivación**: Eliminar el patrón request/response síncrono sobre streams asincrónicos. La cadena de eventos (RN-21) ya provee la garantía de consistencia que un round-trip al agente buscaría.

**Aplicación**: `modules/actions/service.py` (approve usa `event.hash` directamente, no publica `get_file_hash`). Reescribir RN-17 en [reglas_de_negocio.md](reglas_de_negocio.md) bajo D2.

#### D5: `target_agent_id` en comandos + semántica de `ruleset_version_applied`
**Decisión**:
- El contador `ruleset_version` (RN-75, C11) sigue siendo global por backend.
- Todo comando publicado al stream `commands` lleva `target_agent_id: str | None`. `null` = broadcast.
- El agente filtra: `if msg.target_agent_id not in (self.agent_id, None): skip`.
- `Agent.ruleset_version_applied` se define como **el max `ruleset_version` confirmado vía `event_ack` de comandos cuyo `target_agent_id` era `self.agent_id` o `null`**.

Check de "agente al día":
```sql
SELECT MAX(ruleset_version) FROM published_commands
WHERE target_agent_id = :agent_id OR target_agent_id IS NULL;
-- comparar con agent.ruleset_version_applied
```

**Motivación**: Sin `target_agent_id`, dos agentes con configuración heterogénea (paths distintos, reglas distintas) ven incrementarse el counter global por cambios que no les aplican. El agente B aparecería perpetuamente "desactualizado" en el dashboard aunque esté al día.

**Aplicación**: Schema de payload de todos los comandos (`baseline_update`, `rule_sync`, `update_config`, `rescan_baseline`, `restore_file`, `quarantine_file`), agente (`commands_consumer.py` filtro), backend (`modules/agents/service.py` cálculo de `is_up_to_date`).

#### D8: Prohibición de servidor HTTP en el agente
**Decisión**: El agente NO expone servidor HTTP, gRPC ni listener TCP. Toda comunicación backend → agente viaja por Valkey Streams (`commands`) y backend ← agente por (`events`, `agent_heartbeat`).

Análisis de casos backend → agente:
| Caso | Resolución |
|------|------------|
| Approve (consultar hash) | D2 lo elimina |
| Re-scan baseline | Async vía `rescan_baseline` + `event_ack` |
| Update config | Async vía `update_config` + `event_ack` |
| Rule sync | Async vía `rule_sync` + `event_ack` |
| Restore / Quarantine | Async vía `restore_file` / `quarantine_file` + `event_ack` |
| Health check del agente | `agent_heartbeat` cada 10s (RN-92, C12) |
| Estado de cola | `agent_heartbeat` enriquecido (`queue_size`, `queue_pressure`) |

Ningún caso requiere request/response síncrono.

**Motivación**: Exponer HTTP en el agente implica abrir puerto TCP, configurar mTLS bidireccional, manejar lifecycle del server, gestionar firewall. Costo desproporcionado para un caso que no existe.

**Excepción futura (out-of-scope MVP)**: si surge necesidad de debug interactivo local, exponer **Unix socket via systemd socket activation** (controlado por permisos de FS, sin TCP, sin certificado adicional). Nunca un puerto TCP.

**Aplicación**: `agent/main.py` no instancia ningún server. Documentación de instalación menciona explícitamente que no hay puerto a abrir en el firewall del host.

### Organización del código

#### D7: Cross-cutting distribuido, no centralizado al final
**Decisión**: Los controles transversales (logging sanitizado, rate limiting, `trace_id`) se introducen en el primer change que los necesita, no se agrupan al final del roadmap.

Matriz feature → control:
| Control | Change donde se introduce | Justificación |
|---------|---------------------------|---------------|
| `sanitize_logs` middleware (W6, RN-89) | Change 02 (`backend-core-scaffold`) | Sin él, los primeros logs ya pueden filtrar secrets. |
| `trace_id` por request (RN-89) | Change 02 (`backend-core-scaffold`) | Mismo razonamiento, va con el middleware de logging. |
| Rate limit login 5/15min (W5, RN-88) | Change 04 (`backend-auth`) | Sin endpoint de login, no aplica antes. |
| Rate limit API auth 100 req/min/user | Change 04 (`backend-auth`) | Va en `get_current_user` (primer endpoint autenticado). |
| Rate limit eventos del agente 100/min/`agent_id` | Change 11 (`backend-event-ingestion`) | Va en el consumer del stream `events`. |
| Validación de `Origin` whitelist (RN-95) | Change 04 (`backend-auth`) | Va en el middleware CORS, primera vez que se sirve API. |

Lo que SÍ queda en el change final (`backend-observability-hardening`):
- Documentación operativa (formato de logs, paths, retención).
- Tuning de parámetros para producción.
- Tests de carga del rate limiter.
- Workflows de ejemplo de n8n.
- Endpoint `POST /users` para creación de admins adicionales.
- Documentación de instalación del agente.

**Motivación**: Centralizar todo al final implica que dev environment opera SIN sanitización de logs ni rate limiting durante todos los changes intermedios — riesgo real de filtrar secrets en logs de desarrollo y de tener regresiones cuando se "agrega" el control al final.

**Aplicación**: Refleja la versión refactorizada del CHANGES.md (changes 02, 04, 11 toman cross-cutting; change 20 queda solo con docs y hardening operativo).

### Resumen de aplicación

| Decisión | Bloqueaba (en CHANGES.md original) | Estado |
|----------|-----------------------------------|--------|
| D1 (BaselineEntry backend) | Change 03, 13 | Cerrada |
| D2 (Hash del evento) | Change 13 | Cerrada |
| D3 (Lifespan FastAPI) | Change 02 | Cerrada |
| D4 (`rejected_events_audit` enum) | Change 11 | Cerrada |
| D5 (`target_agent_id` + semántica) | Change 12 | Cerrada |
| D6 (`alerts` unificada) | Change 16 | Cerrada |
| D7 (Cross-cutting distribuido) | Cierre M1 | Cerrada |
| D8 (NO HTTP en agente) | Change 13 | Cerrada |
| D9 (Fan-out HMAC en broadcast) | Change 12 | Cerrada |
| D10 (`published_commands` table owner) | Change 12 | Cerrada |

#### D9: Fan-out para comandos broadcast — un mensaje firmado por agente
**Decisión**: Cuando el backend publica un comando con semántica "broadcast" (e.g. `rule_sync` global), NO publica un único mensaje con `target_agent_id: null`. En cambio, publica N mensajes físicos en el stream `commands`, uno por cada agente registrado, cada uno con `target_agent_id = agent_id` y firmado con el `shared_secret` específico de ese agente.

El término "broadcast" en D5, RN-29 y CHANGES.md C12 significa "a todos los agentes activos", no "un único mensaje en el stream". El agente consume solo mensajes donde `target_agent_id == self.agent_id` (o la firma coincide), como ya lo hace con `event_ack`.

**Motivación**: Un único mensaje HMAC-firmado en un stream compartido no puede ser verificado por múltiples agentes, cada uno con su propio `shared_secret` generado en bootstrap. Fan-out mantiene la garantía RN-79 sin introducir un segundo secret de broadcast ni comprometer el modelo de seguridad per-agent.

**Aplicación**: `backend/app/modules/rules/service.py` — la función `publish_rule_sync(session)` itera `Agent.all_active()`, firma con cada `agent.shared_secret_hex` y publica en `commands`. El campo `target_agent_id` siempre lleva el ID explícito del agente (nunca null en la práctica para `rule_sync`). Changes que publiquen otros comandos broadcast (C13 `restore_file`, C15 `rescan_baseline`) aplican el mismo patrón.

#### D10: Tabla `published_commands` creada en C12
**Decisión**: La tabla `published_commands` se crea en Change 12 (`backend-rules-crud`), que es el primer change que publica comandos versionados al stream `commands`.

Columnas: `id: int` (PK autoincrement), `command_type: str`, `target_agent_id: str | None`, `ruleset_version: int`, `published_at: datetime`.

El check de "agente al día" de D5 (`SELECT MAX(ruleset_version) FROM published_commands WHERE target_agent_id = :agent_id OR target_agent_id IS NULL`) opera desde C12 en adelante. Changes posteriores que publiquen comandos (C13, C14, C15) insertan en esta misma tabla.

**Motivación**: Diferir la tabla a C14 (`backend-agents-status`) agrega deuda técnica — D5 ya está definida y C12 necesita el registro para que el dashboard posterior tenga datos históricos desde el primer `rule_sync`. La tabla es trivial y su ownership natural es el primer change que la escribe.

**Aplicación**: `backend/app/modules/rules/models.py` agrega `class PublishedCommand(SQLModel, table=True)`. `backend/app/main.py` importa el modelo para que `create_all()` lo incluya. `rules/service.py` inserta en `published_commands` al publicar `rule_sync`.