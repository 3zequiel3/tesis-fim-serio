# 🛡️ FIM Platform 2026 – Spec-Driven Architecture

> Última actualización: 16 de abril de 2026
> Estado: Documentación — sin implementación

## 🎯 Objetivo

Definir una arquitectura profesional para un sistema FIM (File Integrity Monitoring) con:

* 🧠 Agente autónomo y resiliente
* 🔁 Restauración automática confiable
* 📊 Capacidades forenses (diffs)
* ⚙️ Backend modular (FastAPI)
* 🌐 Frontend moderno (React + TypeScript)
* ⚡ Infraestructura desacoplada (Valkey + N8N)
* 🐳 Containerización completa (Docker Compose)

---

# 🧠 Principios Clave

* Agent-first (desacoplado)
* Event-driven
* Snapshot + Diff (estrategia híbrida)
* Forensic-ready
* Resiliencia offline

---

# 📋 Stack Tecnológico

## Versiones validadas — Abril 2026

| Capa | Tecnología | Versión | Rol |
|------|-----------|---------|-----|
| **Agente** | Python + watchdog | 6.0.0 | Monitoreo filesystem (wrapper de inotify en Linux) |
| **Backend** | FastAPI | 0.136.0 | API REST modular, SSE para alertas real-time |
| **ORM** | SQLModel | latest | Modelos + queries, integración nativa con FastAPI y Pydantic |
| **DB Driver** | psycopg (psycopg3) | latest | Driver PostgreSQL async-capable para Python |
| **Base de datos** | PostgreSQL | 18.3 | Almacenamiento persistente de eventos, reglas, alertas, acciones |
| **Migraciones** | SQL manual + db-init | — | Scripts SQL versionados. Tablas creadas por SQLModel al iniciar |
| **Streams + Cache** | Valkey | 9.0.3 | Cola de eventos agent→backend, cache de reglas/config |
| **Notificaciones** | N8N | 2.16.1 | Pipeline de alertas, health checks, integración SIEM |
| **Auth** | python-jose + JWT | latest | Autenticación stateless con tokens JWT |
| **Hashing Passwords** | argon2-cffi | latest | Hashing de contraseñas con Argon2id (ganador de PHC) |
| **Auth Agente** | mTLS (certificados) | — | Autenticación mutua agente↔backend con certificados TLS |
| **Frontend** | React + TypeScript | React 19 | SPA moderna |
| **Bundler** | Vite | latest | Build y dev server |
| **Data fetching** | TanStack Query | v5 | Cache, refetch, mutations |
| **HTTP Client** | Axios | latest | Requests al backend |
| **State** | Zustand | latest | Estado global del frontend |
| **Estilos** | Tailwind CSS + @tailwindcss/vite | 4.2.2 | Utility-first CSS, integración directa con Vite (sin PostCSS) |
| **Package Manager** | pnpm | latest | Gestor de paquetes rápido, eficiente en disco (symlinks) |
| **Logging** | structlog | latest | Logging estructurado JSON, trace_id por request |
| **Containerización** | Docker + Docker Compose | latest | Orquestación de todos los servicios |
| **CI/CD** | GitHub Actions | — | Pipeline de integración y despliegue continuo |

### Notas sobre elecciones

* **SQLModel** sobre SQLAlchemy puro: creado por el mismo autor de FastAPI (tiangolo), comparte modelos entre ORM y API schemas (Pydantic + SQLAlchemy en uno).
* **psycopg3** (paquete `psycopg`) sobre `asyncpg`: compatible con SQLModel/SQLAlchemy, soporta sync y async, es el driver oficial recomendado para PostgreSQL moderno.
* **python-jose** sobre PyJWT: soporta JWS, JWE, JWK — más completo para manejo de JWT.
* **structlog** sobre loguru: salida JSON nativa, procesadores encadenables, ideal para logs parseables en producción. Se integra bien con `trace_id` por request vía middleware.
* **watchdog** sobre inotify directo: abstrae el backend del OS. En Linux usa inotify internamente. Permite cross-platform si se necesita en el futuro.
* **Tailwind CSS v4** sobre v3: v4 es un rewrite completo. NO usa `tailwind.config.js` — la configuración es CSS-first con `@theme`. Se instala como plugin de Vite (`@tailwindcss/vite`), no como plugin de PostCSS. En el CSS solo se pone `@import "tailwindcss";` (no más `@tailwind base/components/utilities`). Soporta Vite 8.
* **N8N licencia**: Sustainable Use License (fair-code), no es OSS puro. Aceptable para proyecto académico.
* **Migraciones**: SQLModel crea las tablas al iniciar (`SQLModel.metadata.create_all(engine)`). En desarrollo, se reinicia el contenedor. En producción futura, se pueden agregar migraciones SQL versionadas.
* **argon2-cffi** sobre bcrypt: Argon2id es el ganador de la Password Hashing Competition (PHC). Resistente a ataques GPU y side-channel. Configurable en memoria y paralelismo. Es la recomendación actual de OWASP.
* **mTLS para autenticación del agente**: Autenticación mutua con certificados TLS. El agente presenta su certificado al backend y viceversa, ambos verifican contra una CA compartida. Más seguro que API keys — no requiere secretos en plaintext, resistente a replay attacks, y permite identificación criptográfica del agente.

---

# 🏗️ Arquitectura General

```
[ FIM AGENT (Python + watchdog) ]
     │
     ├── Monitoreo (inotify vía watchdog)
     ├── Análisis local
     ├── Snapshot + Diff
     ├── Restauración automática
     ├── Cola local (archivos JSON en disco)
     │
     ▼
[ Valkey (Streams) ] ◄──── events ──── Agente publica eventos
     │                  ────► commands ── Backend envía órdenes
     │                       (baseline_update, restore, quarantine)
     ▼
[ Backend API (FastAPI + SQLModel) ]
     │
     ├── events        (ingesta + estados)
     ├── rules         (CRUD + sync al agente)
     ├── actions       (approve / reject)
     ├── agents        (sync baseline → agente)
     ├── alerts
     ├── notifications ───► N8N (2.16.1)
     │
     ▼
[ PostgreSQL 18.3 ]

[ Frontend (React + TS + Vite) ] ──── Axios ────► Backend
     │
     ├── TanStack Query (data fetching)
     ├── Zustand (state)
     └── Approve / Reject events (pending)
```

### Servicios Docker Compose

```yaml
services:
  agent:        # Python + watchdog
  backend:      # FastAPI + SQLModel
  frontend:     # React (Vite build → nginx)
  db:           # PostgreSQL 18.3
  valkey:       # Valkey 9.0.3
  n8n:          # N8N 2.16.1
```

---

# 🧩 FIM Agent

## Tecnologías del agente

| Componente | Tecnología | Detalle |
|------------|-----------|---------|
| Runtime | Python 3.12+ | Compatible con watchdog 6.0.0 |
| Monitoreo FS | watchdog 6.0.0 | Usa inotify en Linux internamente |
| Hashing | hashlib (stdlib) | SHA-256 para integridad |
| Cola offline | Archivos JSON en disco | Resiliencia sin DB embebida |
| Conexión backend | Valkey Streams (via valkey-py) | Publicación async de eventos |

### Cola offline del agente

El agente NO usa una base de datos embebida. Cuando no puede conectar con Valkey/backend:

1. Serializa el evento a JSON
2. Escribe en `/agent/storage/queue/` con nombre `{timestamp}_{hash}.json`
3. Al reconectar, envía los eventos pendientes en orden FIFO
4. Elimina el archivo JSON tras confirmación

Esto es más simple que SQLite, no requiere driver extra, y cumple el requisito de resiliencia offline.

### Inicialización del baseline

El baseline se genera de forma híbrida:

```
Primera ejecución del agente:
  1. Leer lista de paths monitoreados (configuración)
  2. Escanear todos los archivos
  3. Calcular hash SHA-256 de cada uno
  4. Guardar copia completa en /agent/storage/baseline/
  5. Registrar metadata (path, hash, timestamp, permisos)
  6. Asumir estado actual como "sano" (baseline inicial)
```

**Re-scan manual** (admin desde frontend):

```
POST /agents/rescan { paths: ["/var/www", "/etc"] }
  │
  ▼
Backend envía comando via Valkey:
  { "type": "rescan_baseline", "paths": ["/var/www", "/etc"] }
  │
  ▼
Agente:
  1. Escanear paths indicados
  2. Regenerar baseline COMPLETO para esos paths
  3. Confirmar via Valkey
```

¿Cuándo usar re-scan? Después de un deploy legítimo masivo, una migración, o cuando necesitás resetear el baseline sin aprobar eventos uno por uno.

**⚠️ Impacto en eventos pending:**

Antes de ejecutar el re-scan, el frontend muestra un diálogo de confirmación:

```
"Los siguientes eventos PENDING para los paths seleccionados
 serán marcados como SUPERSEDED:

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

**Fase 1 — Bootstrap (arranque inicial via `.env`):**

```
# .env del contenedor agente
WATCH_PATHS=/etc,/var/www,/opt/app
VALKEY_URL=valkey://valkey:6379
AGENT_ID=agent-prod-01
```

El agente lee los paths a monitorear desde variables de entorno al arrancar. Esto define el estado inicial.

**Fase 2 — Runtime (gestión en caliente desde frontend):**

```
Admin agrega path /opt/newservice desde el frontend
       │
       ▼
Backend: POST /agents/{id}/config
       │
       ▼
Backend publica en Valkey Stream (commands):
  { "type": "update_config", "watch_paths": [..., "/opt/newservice"] }
       │
       ▼
Agente recibe → recarga paths monitoreados SIN reiniciar
Agente ejecuta baseline scan para los paths nuevos
```

La configuración de paths se persiste en PostgreSQL. El `.env` define solo el estado de bootstrap — a partir del primer arranque, el admin gestiona todo desde el frontend y los cambios se sincronizan via Valkey.

## Sistema híbrido de restauración y análisis

## 🔹 Estrategia de Integridad (Core del sistema)

```
Baseline (snapshot completo)
        +
Diffs (para auditoría)
```

---

# 📦 1. Baseline (Snapshot completo)

## ✔ Qué es

Copia completa del archivo en estado “sano”.

## 📁 Ubicación

```
/agent/storage/baseline/
```

## ✔ Contenido

* archivo completo
* hash SHA256
* metadata

---

## 🔐 Uso

* restauración automática
* validación de integridad

---

# 🔍 2. Diffs (Análisis forense)

## ✔ Qué es

Diferencia entre versión anterior y nueva.

## 📁 Ubicación

```
/agent/storage/diffs/
```

---

## ✔ Uso

* auditoría
* análisis de cambios
* visualización en frontend

---

## ⚠️ Limitaciones

* solo archivos de texto
* no confiable para restauración

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
DETECTED → ANALYZED → ACTION → (AUTO_RESTORED | QUARANTINED | PENDING | ALERT_ONLY)
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
Evento detectado (watchdog/inotify)
      │
      ├── Calcular hash (SHA-256)
      ├── Comparar con baseline
      │
      ├── Si NO cambió → ignorar
      │
      ├── Si CAMBIÓ:
      │       │
      │       ├── Generar snapshot (si corresponde)
      │       ├── Generar diff (si texto)
      │       │
      │       ├── Consultar regla (cacheada)
      │       │
      │       ├── SIN REGLA (ningún patrón matchea)
      │       │       → DEFAULT: enviar evento (status: alert_only)
      │       │
      │       ├── action = auto_restore
      │       │       → restaurar archivo desde baseline
      │       │       → verificar hash post-restauración
      │       │       → enviar evento (status: auto_restored)
      │       │
      │       ├── action = quarantine
      │       │       → mover archivo a /agent/storage/quarantine/
      │       │       → enviar evento (status: quarantined)
      │       │
      │       ├── action = manual_review
      │       │       → NO tocar el archivo
      │       │       → enviar evento (status: pending)
      │       │
      │       └── action = alert_only
      │               → enviar evento (status: alert_only)
      │
      └── Encolar en Valkey Stream (o cola local si offline)
```

---

# 🧪 Sistema de Respuesta del Agente

## 🔹 1. Auto-restauración (solo reglas críticas)

**Condición**: `action = auto_restore` en la regla.

```
1. Detectar cambio
2. Validar que baseline existe y tiene archivo completo
3. Restaurar archivo original desde baseline
4. Verificar hash post-restauración
5. Registrar acción → enviar evento (status: auto_restored)
```

> Restauración ≠ Aprobación. La restauración es inmediata y automática. La aprobación es humana y posterior.

## 🔹 2. Cuarentena

**Condición**: `action = quarantine` en la regla.

```
/agent/storage/quarantine/
```

* Mover archivo sospechoso
* Renombrar con timestamp/hash
* Permisos restringidos (read-only, root)
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

👉 El baseline DEBE contener el archivo completo
(no solo hash)

---

# 🧠 Clasificación Inteligente de Archivos

## 🔹 Críticos

Ej:

* `/etc/passwd`
* binarios del sistema

✔ snapshot obligatorio
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

* snapshots antiguos → gzip

---

## 🔹 Deduplicación

* no guardar si hash igual

---

# 🔐 Seguridad del Baseline

## 🔹 Integridad

* HMAC del snapshot

---

## 🔹 Protección

* permisos restringidos
* fuera de paths monitoreados

---

# 🧩 Backend API (FastAPI + SQLModel)

## Tecnologías del backend

| Componente | Tecnología | Detalle |
|------------|-----------|---------|
| Framework | FastAPI 0.136.0 | Async, OpenAPI auto-generado, SSE nativo |
| ORM | SQLModel | Modelos compartidos entre DB y API (Pydantic + SQLAlchemy) |
| DB | PostgreSQL 18.3 | Eventos, reglas, alertas, acciones, usuarios |
| DB Driver | psycopg (v3) | Driver oficial PostgreSQL, sync + async |
| Auth | python-jose + JWT | Tokens stateless, refresh tokens |
| Logging | structlog | JSON estructurado con trace_id por request |
| Streams | Valkey 9.0.3 (valkey-py) | Consumir eventos del agente via Streams |
| Hashing | argon2-cffi (Argon2id) | latest | Hashing de contraseñas, ganador PHC, OWASP recomendado |
| Auth Agente | mTLS | — | Certificados TLS mutuos para autenticación agente↔backend |

## Módulos del backend

```
backend/
├── app/
│   ├── main.py              # FastAPI app + lifespan (create_all tables)
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── database.py      # Engine + Session (SQLModel)
│   │   ├── security.py      # JWT encode/decode (python-jose)
│   │   └── dependencies.py  # get_current_user, get_session
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── router.py    # Login, refresh
│   │   │   └── service.py
│   │   ├── events/
│   │   │   ├── router.py    # GET /events, GET /events/{id}
│   │   │   ├── models.py    # SQLModel: Event, EventStatus
│   │   │   ├── service.py   # Lógica de ingesta y consultas
│   │   │   └── consumer.py  # Consumer de Valkey Stream
│   │   ├── rules/
│   │   │   ├── router.py    # CRUD de reglas
│   │   │   ├── models.py    # SQLModel: Rule
│   │   │   └── service.py
│   │   ├── actions/
│   │   │   ├── router.py    # POST /actions/approve, /actions/reject
│   │   │   ├── models.py    # SQLModel: Action
│   │   │   └── service.py   # Lógica de aprobación/rechazo
│   │   ├── alerts/
│   │   │   ├── router.py
│   │   │   ├── models.py
│   │   │   └── service.py
│   │   ├── agents/
│   │   │   ├── router.py    # Sync de reglas, baseline updates, rescan, config management
│   │   │   └── service.py   # Comunicación backend → agente
│   │   └── notifications/
│   │       └── n8n_client.py # Webhook trigger a N8N
├── Dockerfile
└── requirements.txt
```

> **`core/`**: configuración, DB, seguridad, dependencias compartidas — todo lo transversal.
> **`modules/`**: dominios de negocio aislados. Cada módulo tiene su router, models y service.

## Estados del evento (Event Lifecycle)

Todo evento sigue un ciclo de vida con estados definidos:

```
DETECTED → ANALYZED → ACTION
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

### Estados posibles

| Estado | Origen | Significado |
|--------|--------|-------------|
| `pending` | Agente (manual_review) | Esperando decisión del admin |
| `approved` | Admin (frontend) | Cambio legítimo confirmado. Baseline actualizado |
| `rejected` | Admin (frontend) | Cambio malicioso/no deseado. Se restaura o cuarentena |
| `auto_restored` | Agente (auto_restore) | Restaurado automáticamente por regla crítica |
| `quarantined` | Agente (quarantine) | Archivo aislado automáticamente |
| `alert_only` | Agente (alert_only) | Solo registrado para auditoría |
| `superseded` | Agente (cadena de eventos) | Reemplazado por evento más reciente en el mismo path |

## Flujo de aprobación (Admin)

### Caso 1: Admin APRUEBA (cambio legítimo)

```
Frontend: POST /actions/approve { event_id }
      │
      ▼
Backend:
  1. Marcar evento → status = approved
  2. Generar nuevo baseline con el archivo actual
  3. Enviar baseline_update al agente (via Valkey):
     {
       "type": "baseline_update",
       "path": "/etc/ssh/sshd_config",
       "hash": "nuevo_hash_sha256"
     }
  4. Agente recibe → actualiza su baseline local
```

**Esto es CRÍTICO**: si no actualizás el baseline, el agente va a detectar el mismo cambio como anomalía en el próximo ciclo.

### Caso 2: Admin RECHAZA (cambio malicioso)

```
Frontend: POST /actions/reject { event_id, action: "restore" | "quarantine" }
      │
      ▼
Backend:
  1. Marcar evento → status = rejected
  2. Enviar comando al agente (via Valkey):
     {
       "type": "restore_file" | "quarantine_file",
       "path": "/etc/ssh/sshd_config"
     }
  3. Agente ejecuta la acción
  4. Baseline NO se actualiza (se mantiene el estado sano anterior)
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

### Estado `superseded`

| Estado | Significado |
|--------|-------------|
| `superseded` | Reemplazado por un evento más reciente en la misma cadena |

> Se suma a los 6 estados existentes. Total: 7 estados posibles.

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

Porque entre que el admin ve el evento y aprieta "Approve", el archivo podría haber cambiado N veces. Si usás el hash del evento original, el baseline queda desactualizado y el agente detecta una "anomalía" falsa en el próximo ciclo.

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
   │                                   ├── Actualiza baseline local
   │                                   ├── Recalcula hash
   │                                   └── Confirma via Valkey
   │                                   │
   ├── reject event ───────────────►   │
   │   restore/quarantine via Valkey   │
   │                                   ├── Ejecuta acción
   │                                   └── Confirma via Valkey
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

El primer usuario admin se crea como seed durante la inicialización de la base de datos:

```python
# En lifespan de FastAPI
from argon2 import PasswordHasher

ph = PasswordHasher()

def seed_admin():
    """Crea el admin inicial si no existe ningún usuario."""
    admin_exists = session.exec(select(User)).first()
    if not admin_exists:
        admin = User(
            username=settings.ADMIN_USERNAME,  # desde .env
            password_hash=ph.hash(settings.ADMIN_PASSWORD),  # desde .env
            role="admin"
        )
        session.add(admin)
        session.commit()
```

Variables de entorno requeridas:

```
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<password-seguro>
```

> ⚠️ El password del `.env` es solo para el seed inicial. Debería cambiarse desde la interfaz tras el primer login.

### Hashing de passwords (Argon2id)

Todas las contraseñas se hashean con **Argon2id** (via `argon2-cffi`):

* Ganador de la Password Hashing Competition (PHC)
* Resistente a ataques GPU y side-channel
* Configurable: memoria, iteraciones, paralelismo
* Recomendación actual de OWASP

```python
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher()

# Crear hash
password_hash = ph.hash("user_password")

# Verificar
try:
    ph.verify(password_hash, "user_password")
except VerifyMismatchError:
    raise HTTPException(status_code=401, detail="Credenciales inválidas")
```

## Auth Flow

```
POST /auth/login  →  { access_token, refresh_token }
     │
     ▼
Requests con header: Authorization: Bearer <access_token>
     │
     ▼
Dependency: get_current_user(token) → decode JWT (python-jose) → User
```

## Autenticación del agente (mTLS)

El agente se autentica con el backend usando **mTLS** (mutual TLS):

```
Agente                              Backend
  │                                   │
  ├── Presenta certificado ────────►  │
  │                                   ├── Verifica contra CA
  │  ◄──── Presenta certificado ────  │
  ├── Verifica contra CA              │
  │                                   │
  └── Canal TLS mutuo establecido ──► │
```

### Componentes

| Componente | Ubicación | Propósito |
|------------|-----------|----------|
| CA cert | Docker secret compartido | Autoridad certificadora que firma ambos certs |
| Agent cert + key | Montado en contenedor agent | Identifica al agente ante el backend |
| Backend cert + key | Montado en contenedor backend | Identifica al backend ante el agente |

### Ventajas sobre API keys

* Sin secretos en plaintext — los certificados no son passwords
* Resistente a replay attacks — cada handshake TLS es único
* Identificación criptográfica — el agente es quien dice ser
* Revocable — se puede revocar un certificado sin cambiar passwords

### Generación de certificados (desarrollo)

```bash
# CA (una vez)
openssl req -x509 -newkey rsa:4096 -days 365 \
  -keyout ca-key.pem -out ca-cert.pem -subj "/CN=FIM-CA"

# Agente
openssl req -newkey rsa:4096 -keyout agent-key.pem -out agent-req.pem -subj "/CN=fim-agent"
openssl x509 -req -in agent-req.pem -CA ca-cert.pem -CAkey ca-key.pem -out agent-cert.pem

# Backend
openssl req -newkey rsa:4096 -keyout backend-key.pem -out backend-req.pem -subj "/CN=fim-backend"
openssl x509 -req -in backend-req.pem -CA ca-cert.pem -CAkey ca-key.pem -out backend-cert.pem
```

> En producción, los certificados se gestionan con un sistema de PKI o se rotan automáticamente.

El backend:

* NO restaura archivos directamente
* NO modifica filesystem

👉 El backend:

* Recibe y persiste eventos
* Gestiona el ciclo de vida del evento (estados)
* Evalúa reglas y genera alertas
* Procesa aprobaciones/rechazos del admin
* Envía comandos al agente via Valkey (baseline_update, restore, quarantine)
* Dispara notificaciones via N8N

---

# 🔁 Flujo Completo (Pipeline end-to-end)

```
1. Agente detecta cambio (watchdog/inotify)
2. Calcula hash, compara con baseline
3. Genera snapshot + diff (si corresponde)
4. Evalúa regla cacheada

5. Según acción de la regla:
   ├── auto_restore → restaurar archivo → evento (auto_restored)
   ├── quarantine   → aislar archivo    → evento (quarantined)
   ├── manual_review → NO tocar         → evento (pending)
   └── alert_only   → NO tocar          → evento (alert_only)

6. Encolar evento → Valkey Stream (o cola local si offline)

7. Backend consume evento:
   ├── Persiste en PostgreSQL (SQLModel)
   ├── Evalúa si necesita alerta
   └── Dispara webhook a N8N (si corresponde)

8. Frontend muestra eventos (TanStack Query)

9. Admin decide (solo para eventos pending):
   ├── APPROVE → backend actualiza baseline → sync agente
   └── REJECT  → backend ordena restaurar/cuarentena → sync agente

10. Agente recibe comando → ejecuta → confirma
```

## Comunicación bidireccional via Valkey

```
Agente ──── Valkey Stream (events) ────► Backend
                                            │
Backend ─── Valkey Stream (commands) ──► Agente
```

* **events stream**: agente publica eventos detectados
* **commands stream**: backend envía órdenes (baseline_update, restore, quarantine)

---

# 🔔 N8N (2.16.1)

## Licencia

Sustainable Use License (fair-code). No es OSS puro. Aceptable para uso académico y self-hosted.

## Funciones

* Alertas por email
* Health checks (backend/agentes)
* Reintentos de notificación
* Escaneo programado fallback
* Integración con SIEM

## Integración con backend

El backend llama a N8N via webhook HTTP:

```
POST http://n8n:5678/webhook/fim-alert
Content-Type: application/json

{
  "event_id": "...",
  "severity": "critical",
  "file_path": "/etc/passwd",
  "action_taken": "restored"
}
```

N8N ejecuta el workflow configurado (email, Slack, SIEM, etc.).

## Base de datos de N8N

N8N utiliza la **misma instancia de PostgreSQL** pero una **base de datos separada** (`fim_n8n`):

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
│   │       ├── events.ts      # useEvents(), useEvent(id)
│   │       ├── alerts.ts
│   │       └── auth.ts
│   ├── stores/
│   │   └── auth.store.ts      # Zustand: user, token, logout
│   ├── pages/
│   │   ├── Dashboard.tsx
│   │   ├── Events.tsx
│   │   ├── Alerts.tsx
│   │   └── Login.tsx
│   └── components/
│       ├── layout/                 # Estructura visual de la app
│       │   ├── Sidebar.tsx
│       │   ├── Navbar.tsx
│       │   ├── MainLayout.tsx      # Layout principal (sidebar + content)
│       │   └── AuthLayout.tsx      # Layout para login/register
│       └── ui/                     # Componentes reutilizables de UI
│           ├── DiffViewer.tsx      # Visualización de diffs
│           ├── EventTimeline.tsx
│           ├── RestoreApproval.tsx
│           ├── Badge.tsx
│           ├── Button.tsx
│           └── Card.tsx
├── Dockerfile
├── vite.config.ts
└── package.json
```

## Capacidades

* Ver diffs de archivos (texto)
* Ver comparación de archivos binarios (hash comparison + hex dump parcial)
* Ver historial de versiones (snapshots)
* Ver acciones automáticas ejecutadas
* Aprobar o rechazar eventos `pending` (approve / reject)
* Ver cadena de eventos por path (event chain)
* Dashboard con métricas de integridad
* Alertas en tiempo real (SSE desde backend)

---

# ⚠️ Limitaciones conocidas

* `inotify` (vía watchdog) no garantiza captura PREVIA al write — cuando se detecta, el archivo ya cambió
* Baseline puede crecer — mitigado con `max_snapshots_per_file = 3` y compresión gzip
* Diffs textuales no aplican a archivos binarios — para binarios se muestra comparación de hash y hex dump parcial de los primeros bytes
* N8N licencia fair-code — no OSS puro, pero self-hostable sin restricciones para uso académico
* Cola offline del agente (JSON files) — no tiene transaccionalidad, aceptable para el caso de uso

---

# 🐳 Docker Compose

## Servicios

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
    ports:
      - "5432:5432"

  valkey:
    image: valkey/valkey:9.0
    ports:
      - "6379:6379"

  backend:
    build: ./backend
    depends_on:
      - db
      - valkey
    environment:
      DATABASE_URL: postgresql+psycopg://fim:${DB_PASSWORD}@db:5432/fim
      VALKEY_URL: valkey://valkey:6379
      JWT_SECRET: ${JWT_SECRET}
    ports:
      - "8000:8000"

  frontend:
    build: ./frontend
    depends_on:
      - backend
    ports:
      - "3000:80"

  n8n:
    image: n8nio/n8n:2.16.1
    depends_on:
      - db
    environment:
      DB_TYPE: postgresdb
      DB_POSTGRESDB_HOST: db
      DB_POSTGRESDB_DATABASE: fim_n8n
      DB_POSTGRESDB_USER: fim
      DB_POSTGRESDB_PASSWORD: ${DB_PASSWORD}
    ports:
      - "5678:5678"

  agent:
    build: ./agent
    depends_on:
      - valkey
    volumes:
      - /monitored/path:/watch:ro    # Path a monitorear (read-only)
      - agent_storage:/agent/storage  # Baselines, diffs, quarantine, queue
    privileged: false

volumes:
  pg_data:
  agent_storage:
```

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
```

---

# 🧠 Conclusión

Esta arquitectura define un sistema FIM completo con:

✔ Restauración confiable (snapshot + baseline dinámico)
✔ Motor de decisión basado en reglas (4 niveles de acción)
✔ Flujo de aprobación humana con cadena de eventos
✔ Análisis forense (diff + historial de snapshots)
✔ Baseline dinámico sincronizado entre agente y backend
✔ Comunicación bidireccional via Valkey Streams
✔ Stack completo definido con versiones actuales (Abril 2026)
✔ Containerización lista para desarrollo y despliegue
✔ Seguridad robusta (Argon2id + mTLS + HMAC)
✔ Configuración de agente gestionable en runtime
✔ Patrones glob con negación para reglas flexibles

---

El sistema implementa un **modelo híbrido de respuesta automatizada y validación humana**:

* **Detección** — watchdog + inotify, motor de decisión local
* **Respuesta** — 4 niveles: auto_restore, quarantine, manual_review, alert_only
* **Control humano** — Aprobación/rechazo de cambios pendientes con cadena de eventos
* **Baseline inteligente** — Dinámico, actualizado solo por decisión humana (approve)
* **Auditoría** — diffs, historial de snapshots, cadena de eventos con `superseded`
* **Alerta** — N8N pipeline con reintentos
* **Visualización** — React SPA con diffs, timeline, aprobaciones, event chain

---

👉 Esto no es solo monitoreo: es un **sistema activo de defensa, recuperación y control de integridad con validación humana**.

---

# 📚 Referencias de versiones

| Tecnología | Fuente | Verificado |
|------------|--------|------------|
| FastAPI 0.136.0 | [PyPI](https://pypi.org/project/fastapi/) / [GitHub](https://github.com/fastapi/fastapi/releases) | 16 Abr 2026 |
| Valkey 9.0.3 | [GitHub](https://github.com/valkey-io/valkey/releases) / [valkey.io](https://valkey.io) | 16 Abr 2026 |
| N8N 2.16.1 | [GitHub](https://github.com/n8n-io/n8n/releases) / [n8n.io](https://n8n.io) | 16 Abr 2026 |
| PostgreSQL 18.3 | [postgresql.org](https://www.postgresql.org/) | 16 Abr 2026 |
| watchdog 6.0.0 | [PyPI](https://pypi.org/project/watchdog/) | 16 Abr 2026 |
| SQLModel | [sqlmodel.tiangolo.com](https://sqlmodel.tiangolo.com/) | 16 Abr 2026 |
| React 19 | [react.dev](https://react.dev/) | 16 Abr 2026 |
| Tailwind CSS 4.2.2 | [tailwindcss.com](https://tailwindcss.com/) / [GitHub](https://github.com/tailwindlabs/tailwindcss/releases) | 16 Abr 2026 |
