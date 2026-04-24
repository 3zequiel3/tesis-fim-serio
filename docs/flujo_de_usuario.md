# 🧑‍💻 FIM Platform – Flujo de Usuario

> Última actualización: 23 de abril de 2026
> Estado: Documentación de diseño detallado — sin implementación. La construcción del código y la ejecución del protocolo experimental se proyectan para la fase inmediata siguiente y se entregarán en una adenda formal.

## 🎯 Objetivo

Documentar los flujos de interacción del **administrador** (único rol del sistema) con la plataforma FIM, cubriendo todas las acciones disponibles desde el frontend.

---

# 👤 Rol Único: Administrador

El sistema tiene un único rol: **Admin**. No existen usuarios finales, viewers ni roles diferenciados. El admin gestiona TODO: eventos, reglas, alertas, agentes y autenticación.

Los usuarios admin no se registran desde el frontend — el primer admin se crea automáticamente como seed al inicializar la base de datos (credenciales desde variables de entorno). Admins adicionales se crean desde la interfaz por un admin existente.

> **Primer login**: las credenciales del seed (`.env`) no son un secreto a largo plazo. En el primer login exitoso el sistema **fuerza el cambio de password** antes de permitir cualquier otra acción (ver sección "Primer login con cambio obligatorio de password").

---

# 🔄 Flujo Principal del Administrador

## Ciclo típico de uso

```
┌─────────────┐
│   LOGIN     │ ← JWT (access_token 15 min + refresh_token 7 días con rotación)
└──────┬──────┘
       ▼
┌─────────────┐
│  DASHBOARD  │ ← Vista general: métricas, estado agentes, contadores
└──────┬──────┘
       │
       ├──────────────────────────────────┐
       │                                  │
       ▼                                  ▼
┌─────────────┐                    ┌─────────────┐
│  EVENTOS    │                    │   REGLAS    │
│  (revisar   │                    │  (CRUD de   │
│   pending)  │                    │   reglas)   │
└──────┬──────┘                    └──────┬──────┘
       │                                  │
       ├── APPROVE ──► baseline update    │ sync automático
       │   (firmado HMAC, ruleset_ver++)  │ al agente via
       ├── REJECT ───► restaurar /        │ Valkey Streams
       │               cuarentena         │ (ruleset_version++)
       │                                  │
       ▼                                  ▼
┌─────────────┐                    ┌─────────────┐
│  ALERTAS    │                    │  AGENTES    │
│  (real-time │                    │  (estado,   │
│   via SSE)  │                    │   re-scan,  │
│             │                    │   paths)    │
└─────────────┘                    └─────────────┘
```

## Descripción paso a paso

1. **Login** — El admin ingresa credenciales. El backend emite un `access_token` (15 min) y un `refresh_token` (7 días con rotación). El frontend almacena el access token en memoria (Zustand) y el refresh como cookie `httpOnly`.

2. **Dashboard** — Primera pantalla tras login. El admin obtiene una visión general:
   - Contadores de eventos agrupados por estado
   - Estado de los agentes registrados (online / offline / draining / dead)
   - Banners de salud del sistema (rojo si algún componente está degradado, amarillo si hay notificaciones externas fallidas)

3. **Revisión de eventos** — El admin navega a Eventos, filtra por `pending`, y revisa los cambios detectados por el agente. Cada evento incluye el contexto forense del proceso causante (PID, UID, ejecutable). Decide aprobar o rechazar individualmente o en bulk.

4. **Gestión de reglas** — El admin configura qué hacer ante cambios en paths específicos: restaurar automáticamente, poner en cuarentena, revisar manualmente o solo alertar.

5. **Monitoreo de alertas** — Las alertas llegan en tiempo real vía SSE. El admin puede ver el detalle de cada alerta y su evento asociado.

6. **Gestión de agentes** — El admin verifica el estado de los agentes, gestiona los paths monitoreados en runtime, y puede disparar un re-scan de baseline cuando lo necesite.

7. **Logout** — El admin cierra sesión. El refresh token es invalidado en el backend (blacklist en Valkey con TTL) y eliminado del cliente.

---

# 📱 Pantallas y Acciones

## Dashboard

| Elemento | Descripción |
|----------|-------------|
| Contadores de eventos | Cantidad de eventos por estado (`pending`, `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`) |
| Estado de agentes | Lista de agentes registrados con indicador `online` / `offline` / `draining` / `dead` |
| Indicador de alertas pendientes | Eventos `pending` con severidad `critical` o `high` destacados visualmente |
| Banner del sistema (W12) | Rojo si `postgres`, `valkey`, `n8n` o algún agente están `degraded` o `down` |
| Banner de notificaciones fallidas (W11) | Amarillo si hay filas en `failed_notifications` con `retry_count >= 3` |

**Acciones disponibles:** solo lectura. El dashboard es informativo.

---

## Eventos

| Elemento | Descripción |
|----------|-------------|
| Lista de eventos | Tabla paginada (**50 por página**, W15) con filtros por estado, fecha, path |
| Filtro por estado | Multi-select. Por defecto **excluye `superseded`** (W1); toggle "Mostrar superseded" para incluirlos con ícono de cadena rota |
| Selección múltiple | Checkbox por fila + "seleccionar todos en la página" (W15) |
| Bulk actions | Botones "Aprobar seleccionados" / "Rechazar seleccionados" aparecen al tener ≥ 1 fila marcada |
| Detalle de evento | Vista expandida: path, hash, timestamps (`detected_at` / `received_at`), acción tomada, **contexto del proceso causante** (PID, UID, `exe`), diff (si es texto) o comparación de hash + hex dump parcial (si es binario) |
| Cadena de eventos | Historial de todos los eventos vinculados al mismo path vía `parent_event_id` |
| Botón APPROVE | Aprueba un evento `pending` → actualiza baseline (con manejo de conflicto 409 — C5) |
| Botón REJECT | Rechaza un evento `pending` → abre modal de acción (con branch `baseline_absent` — C10) |

**Acciones disponibles:**
- Filtrar eventos por estado (con toggle para ver `superseded`)
- Ver detalle de cualquier evento con contexto de proceso causante
- Ver cadena de eventos (event chain) de un path
- Aprobar evento `pending` (individual o en bulk)
- Rechazar evento `pending` eligiendo restaurar o cuarentena (individual o en bulk)

---

## Reglas

| Elemento | Descripción |
|----------|-------------|
| Lista de reglas | Tabla con todas las reglas configuradas |
| Formulario de creación | Campos: patrón (glob con soporte de negación `!`), severidad, acción |
| Edición inline | Modificar regla existente |
| Botón eliminar | Elimina regla (con confirmación) |

**Acciones disponibles:**
- Ver lista de reglas
- Crear regla nueva (se sincroniza al agente, con `ruleset_version` monotónico — C11)
- Editar regla existente
- Eliminar regla

---

## Alertas

| Elemento | Descripción |
|----------|-------------|
| Lista de alertas | Tabla con alertas generadas, ordenadas por timestamp |
| Detalle de alerta | Evento asociado, severidad, timestamp, canal de entrega |
| Indicador real-time | Las alertas nuevas aparecen automáticamente via SSE |
| Notificaciones fallidas (W11) | Vista separada accesible desde el banner: tabla de `failed_notifications` con opción de reintentar o descartar |

**Acciones disponibles:**
- Solo lectura sobre el stream de alertas (se generan automáticamente)
- Reintentar / descartar notificaciones externas fallidas (vista dedicada)

---

## Agentes

| Elemento | Descripción |
|----------|-------------|
| Estado de agentes | Lista de agentes con estado `online` / `offline` / `draining` / `dead` |
| Paths monitoreados | Lista editable de paths que el agente monitorea |
| Botón re-scan | Dispara re-scan de baseline para paths específicos (con confirmación) |
| Indicador de saturación | Si `queue_pressure: true` en el último heartbeat, se muestra banner de alerta |
| Indicador de shutdown graceful (W17) | Agente en estado `draining` muestra "Drenando N eventos"; botones de re-scan / update config deshabilitados |
| Historial de sincronizaciones | Registro de comandos enviados y confirmados |

**Acciones disponibles:**
- Ver estado de agentes registrados
- Agregar o quitar paths monitoreados (cambios en runtime, sin reiniciar el servicio del anfitrión)
- Disparar re-scan de baseline con paths específicos (requiere confirmación si hay eventos `pending`)
- Ver historial de sincronizaciones

---

# ✅ Flujo de Aprobación / Rechazo

## Flujo completo paso a paso

```
                    ┌──────────────────────────┐
                    │  AGENTE detecta cambio   │
                    │  (fanotify: path, PID,   │
                    │   UID, exe del proceso)  │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Evalúa regla aplicable  │
                    │  Regla dice:             │
                    │  manual_review           │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Publica evento en       │
                    │  stream events de Valkey │
                    │  (firmado, con UUID,     │
                    │   schema_version,        │
                    │   detected_at, contexto  │
                    │   del proceso)           │
                    │  estado: pending         │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Backend consume evento  │
                    │  · Valida timestamps     │
                    │    (anti-replay W13)     │
                    │  · Valida schema_version │
                    │  · Persiste en           │
                    │    PostgreSQL            │
                    │  · XACK + event_ack      │
                    │    al agente (C3)        │
                    │  · Genera alerta         │
                    │  · Dispara webhook n8n   │
                    │    con retry + DLQ (W11) │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Admin ve evento pending │
                    │  en el frontend          │
                    │                          │
                    │  Revisa:                 │
                    │  • Path afectado         │
                    │  • Hash nuevo vs. viejo  │
                    │  • Proceso causante      │
                    │    (PID, UID, exe)       │
                    │  • Diff (si es texto)    │
                    │  • Cadena de eventos     │
                    └─────┬──────────┬─────────┘
                          │          │
                 approve  │          │  reject
                          ▼          ▼
              ┌───────────────┐  ┌───────────────────┐
              │ Backend:      │  │ Admin elige:      │
              │ 1. UPDATE     │  │                   │
              │    optimista  │  │ ┌───────────────┐ │
              │    (C5)       │  │ │  RESTAURAR    │ │
              │    · 409 si   │  │ │  archivo      │ │
              │      conflict │  │ └───────┬───────┘ │
              │ 2. Hashea     │  │         │         │
              │    archivo    │  │ ┌───────────────┐ │
              │    ACTUAL     │  │ │  CUARENTENA   │ │
              │ 3. Genera     │  │ │  aislar       │ │
              │    nuevo      │  │ │  archivo      │ │
              │    baseline   │  │ └───────┬───────┘ │
              │ 4. Comando    │  │         │         │
              │    firmado    │  │ Backend envía     │
              │    HMAC +     │  │ comando firmado   │
              │    ruleset_   │  │ al agente; W2     │
              │    version++  │  │ journal           │
              │    al agente  │  │ pre-acción        │
              │ 5. audit_log  │  │                   │
              │               │  │ Estado:           │
              │ Estado:       │  │ → rejected        │
              │ → approved    │  └───────────────────┘
              └───────────────┘
```

### Detalle de APPROVE

1. Admin hace click en **APPROVE** sobre un evento `pending` (el frontend envía `event_id` y `expected_version`).
2. El frontend envía la acción al backend.
3. El backend:
   - Intenta `UPDATE events SET status='approved', version=version+1 WHERE id=:id AND version=:expected_version AND status='pending'` (optimistic locking — C5).
   - Si afecta 0 filas → HTTP 409 `conflict`. El frontend muestra toast "Este evento ya fue resuelto o reemplazado" y refresca la lista.
   - Si afecta 1 fila: hashea el archivo en su estado **actual** (post-cambio) consultando al agente.
   - Genera una nueva entrada de baseline con el hash actualizado.
   - Publica un comando `baseline_update` en Valkey Streams con `ruleset_version++` y `signature` HMAC (C7, C11).
   - Inserta fila en `audit_log` (W18).
4. El agente:
   - Verifica la firma HMAC del comando.
   - Verifica que `ruleset_version` sea mayor o igual que el último aplicado.
   - Actualiza su baseline local, re-cifrado con AES-256-GCM.
   - Confirma via `event_ack`.
5. El evento pasa a estado `approved`. El archivo modificado pasa a ser el nuevo "estado sano".

### Detalle de REJECT

1. Admin hace click en **REJECT** sobre un evento `pending`.
2. El frontend presenta un modal con dos opciones:
   - **Restaurar archivo**: volver al estado del último baseline conocido.
   - **Cuarentena**: aislar el archivo en un directorio seguro.
3. Si el baseline del path ya está en `status: absent` (no hay archivo a restaurar), el modal oculta ambas opciones y muestra (C10): *"No existe archivo a restaurar. Confirmar rechazará el evento sin acción en filesystem."*
4. El admin elige una opción (o confirma en el caso `baseline_absent`).
5. El frontend envía la acción elegida al backend.
6. El backend:
   - Aplica el mismo `UPDATE` optimista que en approve (HTTP 409 si hay conflicto).
   - Si es `baseline_absent`: no envía comando al agente; loguea warning y marca `rejected`.
   - Si no: publica un comando `restore_file` o `quarantine_file` firmado en Valkey Streams.
   - Inserta fila en `audit_log`.
7. El agente (si recibió comando) escribe el journal pre-acción (W2), ejecuta la acción, y actualiza el journal al completar.
8. El evento pasa a estado `rejected`.

### Nota sobre fanotify

Cuando el agente detecta un cambio, el archivo **ya fue modificado**. El subsistema `fanotify` del núcleo notifica *después* del write en el modo de operación utilizado por el sistema (notificación pura), aunque ofrece modos de permisos que permiten inspeccionar antes de que se persista la escritura — esos modos tienen costos de rendimiento que no asumimos en el MVP. Por eso:

- El diff se genera comparando el archivo actual contra el snapshot del baseline cifrado.
- Si se aprueba, se hashea el archivo **como está ahora** al momento del approve.
- Si se restaura, se usa la copia del baseline que mantiene el agente (descifrada de AES-GCM).
- Ventaja clave sobre `inotify`: cada evento incluye el **contexto del proceso causante** (PID, UID, path del ejecutable), visible en la vista de detalle del evento.

### Caso especial: APPROVE cuando el archivo fue eliminado

Si el admin aprueba un evento pero el archivo ya no existe en el filesystem:

```
Admin: click APPROVE
       │
       ▼
Backend consulta estado actual al agente via Valkey
       │
       ▼
Agente responde: archivo NO EXISTE
       │
       ▼
Frontend muestra warning:
┌─────────────────────────────────────────┐
│  ⚠️ El archivo ya no existe en el       │
│  filesystem.                            │
│                                         │
│  Aprobar significa que la AUSENCIA      │
│  del archivo es el nuevo estado válido  │
│  del baseline.                          │
│                                         │
│  Si alguien recrea este archivo en el   │
│  futuro, será detectado como anomalía.  │
│                                         │
│  [Cancelar]  [Confirmar aprobación]     │
└─────────────────────────────────────────┘
       │
       ├── Admin CONFIRMA:
       │     Baseline: { path, status: "absent", hash: null }
       │     Agente: trata creación futura como anomalía
       │     Evento → approved
       │
       └── Admin CANCELA:
             Evento permanece pending
```

> Un archivo ausente es un estado válido. Si un sysadmin eliminó un config obsoleto, aprobar es correcto. Si fue un atacante limpiando evidencia, el admin puede rechazar y restaurar desde baseline.

### Manejo de conflictos concurrentes (C5)

Si dos admins intentan aprobar el mismo evento simultáneamente, o si el agente marca el evento como `superseded` entre el render y el click:

1. El segundo `UPDATE` afecta 0 filas (la condición `version = :expected_version` falla).
2. El backend devuelve HTTP 409 con body `{"error": "conflict", "reason": "event_already_resolved_or_superseded"}`.
3. El frontend muestra un toast:
   > *"Este evento ya fue resuelto o reemplazado por un cambio más reciente. Refrescando lista..."*
4. La tabla se refresca automáticamente y se destaca el nuevo estado del evento.
5. El botón de aprobar queda deshabilitado tras el refresh (el evento ya no es `pending`).

---

# 🧩 Bulk approve/reject

Para situaciones en las que el admin necesita gestionar múltiples eventos simultáneamente (por ejemplo, tras un deploy planificado con muchos archivos modificados):

```
┌─────────────────────────────────────────┐
│  Admin selecciona múltiples eventos     │
│  (checkbox por fila + "seleccionar      │
│   todos en la página actual")           │
│                                         │
│  Aparecen botones en la barra superior: │
│  [ Aprobar seleccionados ]              │
│  [ Rechazar seleccionados ]             │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  Click "Aprobar seleccionados"          │
│                                         │
│  Modal de confirmación:                 │
│  ┌───────────────────────────────────┐  │
│  │ Se aprobarán 47 eventos:          │  │
│  │  • /var/www/app/index.html        │  │
│  │  • /var/www/app/style.css         │  │
│  │  • /var/www/app/script.js         │  │
│  │  • ... (47 más)                   │  │
│  │                                   │  │
│  │  [Cancelar] [Confirmar aprobación]│  │
│  └───────────────────────────────────┘  │
└──────────────────┬──────────────────────┘
                   │ (admin confirma)
                   ▼
┌─────────────────────────────────────────┐
│  POST /actions/bulk-approve             │
│  { event_ids: [...] }                   │
│                                         │
│  Backend procesa cada evento con        │
│  optimistic locking individual.         │
│                                         │
│  Respuesta:                             │
│  {                                      │
│    "succeeded": [42 event_ids],         │
│    "failed": [                          │
│      { "event_id": ..., "reason":       │
│        "conflict" },                    │
│      { "event_id": ..., "reason":       │
│        "not_pending" },                 │
│      { "event_id": ..., "reason":       │
│        "baseline_absent" }              │
│    ]                                    │
│  }                                      │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  Frontend muestra resumen:              │
│                                         │
│  ✔ 42 eventos aprobados correctamente   │
│  ✘ 5 eventos fallaron (ver detalle)     │
│                                         │
│  [Expandir detalle]                     │
│                                         │
│  La tabla se refresca automáticamente.  │
└─────────────────────────────────────────┘
```

El bulk reject funciona igual pero adicionalmente pide la acción (`restore` o `quarantine`) que se aplica a todos los eventos seleccionados.

---

# 📏 Flujo de Gestión de Reglas

## CRUD completo

```
┌─────────────────────────────────────────────────────┐
│                    REGLAS                            │
├─────────────────────────────────────────────────────┤
│                                                     │
│  CREAR regla                                        │
│  ┌───────────────────────────────────────────┐      │
│  │ Patrón:    /etc/nginx/**  (glob, ! para   │      │
│  │            excluir: !/etc/nginx/temp)      │      │
│  │ Severidad: critical | high | medium | low │      │
│  │ Acción:    auto_restore | quarantine |    │      │
│  │            manual_review | alert_only     │      │
│  └───────────────────────────────────────────┘      │
│       │                                             │
│       ▼                                             │
│  Backend persiste en PostgreSQL                     │
│       │                                             │
│       ▼                                             │
│  Backend incrementa ruleset_version (C11)           │
│       │                                             │
│       ▼                                             │
│  Sync automático al agente via Valkey               │
│  (comando firmado con HMAC, ruleset_version++)      │
│  (el agente recarga las reglas sin reiniciar)       │
│                                                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  LEER reglas                                        │
│  Lista todas las reglas configuradas con:           │
│  • Patrón                                           │
│  • Severidad                                        │
│  • Acción configurada                               │
│  • Fecha de creación/modificación                   │
│                                                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  EDITAR regla                                       │
│  Mismo formulario que crear, precargado.            │
│  Al guardar → sync automático al agente             │
│  (ruleset_version++ + HMAC).                        │
│                                                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ELIMINAR regla                                     │
│  Confirmación requerida.                            │
│  Al eliminar → sync automático al agente            │
│  (ruleset_version++ + HMAC).                        │
│  El agente deja de aplicar la regla                 │
│  inmediatamente; los paths que matcheaban           │
│  pasan a usar la acción default (alert_only).       │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Acciones disponibles por regla

| Acción | Qué pasa cuando se detecta un cambio |
|--------|---------------------------------------|
| `auto_restore` | El agente escribe journal pre-acción (W2), descifra el archivo del baseline (AES-GCM), lo restaura sobre el filesystem, verifica el hash post-restauración, y actualiza el journal. Evento con estado `auto_restored`. |
| `quarantine` | El agente escribe journal pre-acción, mueve el archivo a `/var/lib/fim-agent/quarantine/` con permisos restringidos, y actualiza el journal. Evento con estado `quarantined`. |
| `manual_review` | El evento queda `pending` para que el admin decida (approve / reject). |
| `alert_only` | Solo se registra el evento y se genera alerta. Evento con estado `alert_only`. No se toma acción sobre el archivo. |

### Severidades

| Severidad | Uso típico |
|-----------|-----------|
| `critical` | Archivos de sistema, binarios críticos, configuraciones de seguridad |
| `high` | Configuraciones de servicios, scripts de deploy |
| `medium` | Archivos de aplicación, configuraciones no críticas |
| `low` | Logs, archivos temporales, caches |

### Sincronización de reglas

Cada operación CRUD sobre reglas dispara una sincronización automática:

```
Admin crea/edita/elimina regla
       │
       ▼
Backend persiste cambio en PostgreSQL
       │
       ▼
Backend incrementa ruleset_version (counter monotónico)
       │
       ▼
Backend publica reglas actualizadas en Valkey Stream
(firmado con HMAC-SHA256 contra el shared_secret del agente)
       │
       ▼
Agente:
  · Verifica firma HMAC
  · Verifica ruleset_version >= último aplicado (descarta reenvíos)
  · Recarga reglas en memoria (sin reiniciar el servicio)
  · Persiste ruleset_version en /var/lib/fim-agent/state.json
  · Confirma via event_ack
```

El admin **no** necesita hacer nada adicional. La sincronización es transparente.

---

# ⚙️ Flujo de Gestión de Configuración del Agente

## Configuración inicial (bootstrap)

Al arrancar por primera vez, el agente lee su configuración desde el archivo local `/etc/fim-agent/config.yaml`:

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

> El agente es un servicio nativo de `systemd`, no un contenedor Docker. Corre con la capability `CAP_SYS_ADMIN` que `fanotify` requiere; esta capability no se otorga a un contenedor estándar sin romper su aislamiento.

## Gestión en runtime (desde frontend)

Una vez arrancado, el admin puede modificar los paths monitoreados desde el frontend:

```
┌──────────────────────────────────────┐
│  Admin navega a sección AGENTES      │
│                                      │
│  Ve la lista de paths monitoreados:  │
│  ┌────────────────────────────────┐  │
│  │  ✓ /etc                        │  │
│  │  ✓ /var/www                    │  │
│  │  ✓ /opt/app                    │  │
│  │  + Agregar path...             │  │
│  └────────────────────────────────┘  │
│                                      │
│  Admin agrega: /opt/newservice       │
│  Click en "Guardar configuración"    │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  Backend:                            │
│  1. Persiste config en PostgreSQL    │
│  2. Incrementa ruleset_version (C11) │
│  3. Firma el comando con HMAC (C7)   │
│  4. Publica en stream commands:      │
│     {                                │
│       "type": "update_config",       │
│       "watch_paths": [...,           │
│         "/opt/newservice"],          │
│       "ruleset_version": 48,         │
│       "signature": "<HMAC-SHA256>"   │
│     }                                │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  Agente:                             │
│  1. Verifica firma HMAC              │
│  2. Verifica ruleset_version         │
│  3. Recarga paths monitoreados       │
│     (sin reiniciar el proceso)       │
│  4. Ejecuta baseline scan para       │
│     los paths nuevos                 │
│  5. Cifra la baseline con AES-GCM    │
│  6. Confirma al backend via Valkey   │
└──────────────────────────────────────┘
```

> El archivo `config.yaml` define solo el estado inicial de bootstrap. A partir del primer arranque, el admin gestiona paths desde el frontend y la configuración autoritativa vive en PostgreSQL.

---

# 🔍 Flujo de Re-scan de Baseline

## Cuándo hacer un re-scan

- Después de un deploy o actualización planificada de archivos.
- Si se sospecha que el baseline quedó desactualizado.
- Después de restaurar archivos desde un backup externo.
- Al agregar nuevos paths a monitorear.

## Cómo funciona

```
┌──────────────────────────────────────┐
│  Admin navega a sección AGENTES      │
│                                      │
│  Selecciona paths para re-scan:      │
│  ┌────────────────────────────────┐  │
│  │  /var/www                      │  │
│  │  /etc/nginx                    │  │
│  │  (paths específicos)           │  │
│  └────────────────────────────────┘  │
│                                      │
│  Click en "Re-scan Baseline"         │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  ⚠️ CONFIRMACIÓN REQUERIDA          │
│                                      │
│  "Los siguientes eventos pending     │
│   serán marcados como superseded:    │
│                                      │
│   - /var/www/index.html (pending)    │
│   - /etc/nginx/conf.d/site.conf     │
│                                      │
│   ¿Confirmar re-scan?"              │
│                                      │
│  [Cancelar]  [Confirmar Re-scan]     │
└──────────────────┬───────────────────┘
                   │ (admin confirma)
                   ▼
┌──────────────────────────────────────┐
│  Backend:                            │
│  1. Marca eventos pending como       │
│     superseded para esos paths       │
│  2. Incrementa ruleset_version       │
│  3. Publica comando firmado en       │
│     stream commands:                 │
│     { "type": "rescan_baseline",     │
│       "paths": [...],                │
│       "ruleset_version": 49,         │
│       "signature": "<HMAC>" }        │
│  4. Registra en audit_log (W18)      │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  Agente:                             │
│  1. Verifica firma HMAC y versión    │
│  2. Para cada path:                  │
│     · Escanea todos los archivos     │
│     · Calcula hash SHA-256           │
│     · Cifra y guarda snapshot nuevo  │
│     · Actualiza baseline en memoria  │
│  3. Confirma al backend via Valkey   │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  El estado actual de los archivos    │
│  pasa a ser el nuevo baseline.       │
│  Cualquier cambio posterior será     │
│  detectado contra este nuevo estado. │
└──────────────────────────────────────┘
```

### Consideraciones

- El re-scan **no genera eventos**: asume que el estado actual es el correcto.
- Antes de ejecutar, el admin recibe un **warning** listando todos los eventos `pending` que serán marcados como `superseded`.
- El admin debe **confirmar explícitamente** antes de que el re-scan se ejecute.
- Durante el re-scan, el monitoreo sigue activo — los cambios que ocurran en ese momento se evalúan contra el baseline anterior hasta que el nuevo se complete.
- El admin puede ver el historial de sincronizaciones para confirmar que el re-scan se completó.

---

# 🔐 Primer login con cambio obligatorio de password

El seed del primer admin (creado al inicializar la base de datos desde `.env`) queda marcado con el flag `must_change_password: true`. Este flag fuerza al admin a cambiar el password antes de poder usar el sistema.

```
┌──────────────────────────────────────┐
│  Admin ingresa credenciales del seed │
│  (usuario + password del .env)       │
│                                      │
│  POST /auth/login                    │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  Backend:                            │
│  1. Verifica credenciales            │
│  2. Detecta must_change_password     │
│  3. Emite tokens con scope           │
│     "password_change_only"           │
│  4. Responde:                        │
│     {                                │
│       access_token: "...",           │
│       refresh_token: "...",          │
│       must_change_password: true     │
│     }                                │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  Frontend:                           │
│  Redirige FORZOSAMENTE a             │
│  /account/change-password            │
│                                      │
│  Cualquier intento de navegar a      │
│  otra ruta redirige de vuelta al     │
│  formulario.                         │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  Formulario de cambio obligatorio:   │
│  ┌────────────────────────────────┐  │
│  │  Password actual:     [_____]  │  │
│  │  Password nuevo:      [_____]  │  │
│  │  Confirmación:        [_____]  │  │
│  │                                │  │
│  │  Requisitos:                   │  │
│  │  · Mínimo 12 caracteres        │  │
│  │  · Al menos 1 mayúscula        │  │
│  │  · Al menos 1 minúscula        │  │
│  │  · Al menos 1 número           │  │
│  │                                │  │
│  │       [Cambiar password]       │  │
│  └────────────────────────────────┘  │
└──────────────────┬───────────────────┘
                   │ (admin completa)
                   ▼
┌──────────────────────────────────────┐
│  Backend:                            │
│  1. Verifica password actual         │
│  2. Verifica reglas de complejidad   │
│  3. Hashea nuevo password (Argon2id) │
│  4. Marca must_change_password=false │
│  5. Emite nuevos tokens con scope    │
│     completo                         │
│  6. Registra en audit_log            │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  Frontend redirige al dashboard.     │
│  A partir de este punto, el admin    │
│  opera con el resto del sistema      │
│  normalmente.                        │
└──────────────────────────────────────┘
```

Si el admin cierra el navegador sin completar el cambio, el próximo login vuelve a exigirlo (el flag sigue en `true` hasta que se complete exitosamente).

---

# 🚫 Limitaciones del Usuario

## Qué NO puede hacer el admin

| Acción restringida | Razón |
|-------------------|-------|
| Modificar archivos del filesystem directamente | El frontend no tiene acceso al filesystem. El agente es el único componente con acceso directo. |
| Ejecutar comandos en el agente | No existe shell remoto ni terminal. La comunicación es solo vía comandos estructurados firmados HMAC por Valkey. |
| Ver contenido completo de archivos | El sistema solo muestra diffs de texto por razones de seguridad y rendimiento. |
| Ver diffs textuales de archivos binarios | Los diffs línea a línea solo aplican a archivos de texto. Para binarios se muestra comparación de hashes y hex dump parcial (primeros N bytes). |
| Desactivar el agente desde el frontend | El agente es un servicio autónomo de `systemd` en el anfitrión. Se gestiona a nivel sistema operativo (`systemctl`). |
| Modificar parámetros del agente anteriores al bootstrap | `agent_id`, `valkey_url` y `ca_cert_path` se fijan en el `config.yaml` local. Los paths monitoreados se gestionan desde el frontend. |
| Registrar usuarios públicamente | El primer admin se crea por seed. Admins adicionales se crean desde la interfaz por un admin existente. No hay registro público. |

## Limitaciones técnicas del sistema

| Limitación | Impacto | Mitigación |
|-----------|---------|------------|
| `fanotify` requiere `CAP_SYS_ADMIN` | El agente no puede correr dentro de un contenedor Docker estándar | Despliegue nativo como servicio `systemd` en el anfitrión con hardening (`ProtectSystem=strict`, `NoNewPrivileges`) |
| `fanotify` notifica después del write (en modo notificación pura) | No se puede capturar el estado "antes" del cambio con ese modo | Se compara contra el snapshot cifrado del baseline; para protección pre-write se deriva a trabajo futuro (IMA, dm-verity) |
| Saturación del consumidor `fanotify` | Bajo alta carga, eventos pueden perderse silenciosamente | El agente reporta el nivel de backpressure (`queue_pressure`) en cada heartbeat y la UI lo muestra como alerta |
| Diffs textuales solo para texto | Archivos binarios no tienen diff línea a línea | Se muestra comparación de hashes + hex dump parcial de primeros bytes |
| Cola offline es JSON plano | Sin transaccionalidad, riesgo de pérdida si el anfitrión muere mid-write | Escritura atómica (write + rename), archivos pequeños, confirmación bidireccional `XACK + event_ack` antes de borrar local |
| Baseline puede crecer | Snapshots consumen disco | Máximo 3 snapshots por archivo, compresión gzip, cifrado AES-GCM |
| **n8n no ejecuta comandos nativos del SO** | No puede coordinar el playbook ni tomar acción sobre el filesystem | Delimitado a **enrutador acotado de notificaciones externas**; toda la lógica de decisión vive en el backend propio |
| **n8n licencia fair-code (Sustainable Use License)** | No es OSS puro; no apta para reventa comercial ni incorporación como componente principal de productos comerciales | Aceptable para proyecto académico y self-hosted; **fallbacks automáticos** (SMTP directo → webhook directo → log crítico) permiten operar sin n8n |
| Backend en instancia única | No se diseña HA multi-réplica en el MVP | Init-container para arranque rápido + cola local del agente preserva eventos durante reinicios |
| Raíz de confianza en espacio de usuario del anfitrión | Si el kernel del anfitrión está comprometido, todo el sistema lo está | Reconocido como amenaza residual; trabajo futuro: IMA, dm-verity, Secure Boot |

---

# 📖 Escenarios de Uso Típicos

## Escenario 1: Detección y aprobación de un cambio legítimo

**Contexto:** Un administrador de sistemas actualizó la configuración de nginx. El agente FIM detectó el cambio.

```
1. Admin de sistemas modifica /etc/nginx/nginx.conf
                │
                ▼
2. Agente detecta cambio vía fanotify
   Contexto: proceso = /usr/bin/nano, pid = 4521, uid = 0
   Regla para /etc/nginx/** → manual_review
   Genera evento pending
                │
                ▼
3. Agente publica evento firmado en Valkey Stream
                │
                ▼
4. Backend consume, valida timestamps (W13), persiste en PostgreSQL,
   ejecuta XACK + publica event_ack (C3), genera alerta,
   dispara webhook n8n
                │
                ▼
5. Admin FIM recibe alerta en tiempo real (SSE)
   Navega a Eventos → filtra pending
                │
                ▼
6. Admin FIM abre el detalle del evento:
   • Path: /etc/nginx/nginx.conf
   • Proceso causante: /usr/bin/nano (uid 0)
   • Diff: ve que se agregó un nuevo upstream
   • Cadena: verifica que no hay eventos previos sospechosos
                │
                ▼
7. Admin FIM reconoce el cambio como legítimo
   Click en APPROVE
                │
                ▼
8. Backend hashea el archivo actual, aplica optimistic UPDATE,
   genera nueva entrada de baseline,
   publica comando firmado con HMAC + ruleset_version++,
   registra en audit_log
                │
                ▼
9. Agente verifica HMAC, verifica versión, actualiza baseline local
   (re-cifrado AES-GCM), confirma via event_ack
                │
                ▼
10. Evento pasa a approved
    nginx.conf actualizado es el nuevo baseline
```

---

## Escenario 2: Detección y rechazo de un cambio sospechoso

**Contexto:** Se detecta una modificación inesperada en un script de deploy. Nadie del equipo hizo cambios.

```
1. Archivo /opt/deploy/run.sh fue modificado
                │
                ▼
2. Agente detecta cambio
   Contexto: proceso = /tmp/.cache/unknown, pid = 7891, uid = 1001
   Regla para /opt/deploy/** → manual_review (severidad: high)
   Genera evento pending
                │
                ▼
3. Backend persiste evento, genera alerta de severidad HIGH,
   dispara webhook n8n con retry + DLQ si falla (W11)
                │
                ▼
4. Admin recibe alerta, navega a detalle del evento
   • Proceso causante sospechoso: /tmp/.cache/unknown ejecutado por uid 1001
   • Diff: se agregaron líneas sospechosas al script
   • No hay registro de deploy reciente
                │
                ▼
5. Admin decide REJECT → elige RESTAURAR
                │
                ▼
6. Backend aplica optimistic UPDATE, publica comando firmado
   RESTORE al agente via Valkey,
   registra en audit_log
                │
                ▼
7. Agente verifica HMAC y ruleset_version, escribe journal pre-acción,
   descifra archivo del baseline (AES-GCM), lo restaura,
   verifica hash post-restauración, actualiza journal a "completed"
                │
                ▼
8. Evento pasa a rejected
   El archivo vuelve a su estado original
   Admin investiga el incidente por otros medios
   (el PID / UID / exe del proceso causante quedan registrados en audit_log)
```

---

## Escenario 3: Configuración de reglas para un nuevo servicio

**Contexto:** Se desplegó un nuevo servicio y el admin necesita configurar el monitoreo.

```
1. Nuevo servicio desplegado en /opt/newservice/
                │
                ▼
2. Admin navega a sección REGLAS
                │
                ▼
3. Admin crea regla 1:
   • Patrón: /opt/newservice/config/**
   • Severidad: critical
   • Acción: manual_review
   "Cualquier cambio en configuración requiere revisión"
                │
                ▼
4. Admin crea regla 2:
   • Patrón: /opt/newservice/bin/**
   • Severidad: critical
   • Acción: auto_restore
   "Binarios NUNCA deben cambiar — restaurar inmediatamente"
                │
                ▼
5. Admin crea regla 3:
   • Patrón: /opt/newservice/logs/**
   • Severidad: low
   • Acción: alert_only
   "Logs cambian constantemente — solo registrar"
                │
                ▼
6. Cada regla se sincroniza automáticamente al agente
   (ruleset_version++ + HMAC)
   El agente comienza a aplicar las reglas inmediatamente
                │
                ▼
7. Admin navega a AGENTES → agrega /opt/newservice a paths monitoreados
   → dispara re-scan de baseline para /opt/newservice/
                │
                ▼
8. Agente escanea el directorio completo,
   genera baseline inicial cifrado para todos los archivos.
   El servicio queda monitoreado.
```

---

## Escenario 4: Re-scan post-deploy planificado con bulk approve

**Contexto:** Se realizó un deploy planificado que modifica múltiples archivos. El admin quiere aceptar todos los cambios como nuevo baseline.

```
Opción A: Re-scan (si no le interesa revisar cada evento)

1. Deploy planificado modifica archivos en:
   • /var/www/app/
   • /etc/app/config/
                │
                ▼
2. Agente detecta múltiples cambios
   Genera eventos pending (si las reglas dicen manual_review)
                │
                ▼
3. Admin sabe que el deploy es legítimo
                │
                ▼
4. Admin navega a AGENTES
   Selecciona paths: /var/www/app/, /etc/app/config/
   Click en "Re-scan Baseline"
   El sistema muestra warning:
   "47 eventos pending serán marcados como superseded"
   Admin confirma
                │
                ▼
5. Backend marca los pending como superseded,
   publica comando rescan firmado,
   registra en audit_log
                │
                ▼
6. Agente re-escanea los paths indicados,
   genera nuevo baseline cifrado con el estado actual
                │
                ▼
7. A partir de ahora, cualquier cambio se compara
   contra el baseline post-deploy


Opción B: Bulk approve (si le interesa dejar trazabilidad por evento)

1. Admin navega a EVENTOS, filtra pending
                │
                ▼
2. Usa "seleccionar todos en la página" → tiene 47 eventos seleccionados
   Click "Aprobar seleccionados"
                │
                ▼
3. Modal de confirmación lista primeros 10 paths + "y 37 más"
   Admin confirma
                │
                ▼
4. Backend procesa cada evento con optimistic locking individual.
   Respuesta: 45 aprobados, 2 fallidos (razón: "conflict" — alguien
   más los aprobó mientras tanto; o "baseline_absent").
                │
                ▼
5. Frontend muestra resumen: 45 ✔ / 2 ✘
   La tabla se refresca automáticamente
```

La **opción A** es más rápida pero no deja trazabilidad evento a evento en el audit_log.
La **opción B** mantiene trazabilidad completa (cada approve se registra con user_id y timestamp).

---

# 📊 Resumen de Estados de Eventos

```
┌──────────────────────────────────────────────────────────┐
│                  ESTADOS DE EVENTOS                      │
├──────────────┬───────────────────────────────────────────┤
│ pending      │ Esperando decisión del admin              │
│ approved     │ Admin aprobó → baseline actualizado       │
│ rejected     │ Admin rechazó → archivo restaurado o      │
│              │ puesto en cuarentena                      │
│ auto_restored│ Sistema restauró automáticamente          │
│              │ (regla: auto_restore)                     │
│ quarantined  │ Sistema aisló automáticamente             │
│              │ (regla: quarantine)                       │
│ alert_only   │ Solo registro, sin acción sobre archivo   │
│              │ (regla: alert_only o default sin match)   │
│ superseded   │ Reemplazado por evento más reciente       │
│              │ en el mismo path o por re-scan            │
└──────────────┴───────────────────────────────────────────┘
```

### Diagrama de transiciones (C2 — máquina de estados explícita)

```
                    ┌─────────┐
                    │ pending │
                    └────┬────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
              ▼          ▼          ▼
        ┌──────────┐ ┌────────┐ ┌───────────┐
        │ approved │ │rejected│ │superseded │
        └──────────┘ └────────┘ └───────────┘

  (generados directamente por reglas automáticas,
   nunca pasan por pending — transiciones terminales)

        ┌───────────────┐  ┌──────────────┐  ┌────────────┐
        │ auto_restored │  │ quarantined  │  │ alert_only │
        └───────────────┘  └──────────────┘  └────────────┘
```

Cualquier transición no listada es inválida y se rechaza con HTTP 409.

---

## Appendix: Decisiones de auditoría — Abril 2026

Las siguientes decisiones resultan de la auditoría de consistencia, lifecycle, seguridad y resiliencia realizada el 2026-04-22. En caso de conflicto con secciones previas del documento, prevalece lo especificado en este appendix.

### Léxico y nomenclatura

#### C1: Léxico canónico en minúsculas
**Decisión**: Los estados de evento se muestran siempre en minúsculas (snake_case) en toda la UI (`pending`, `approved`, `rejected`, `superseded`, `auto_restored`, `quarantined`, `alert_only`). Los botones de acción (`APPROVE`, `REJECT`) pueden aparecer en mayúsculas como énfasis de UI.
**Motivación**: Consistencia visual y alineación con el modelo de datos canónico.
**Aplicación**: Componentes `Badge`, tablas de eventos, filtros, modales de confirmación.

### Modelo de eventos y lifecycle

#### C5: UX de conflicto de aprobación concurrente (optimistic locking)
**Decisión**: Si dos admins intentan aprobar el mismo evento simultáneamente (o uno aprueba mientras el agente marca el evento como `superseded`), el backend devuelve HTTP 409. El frontend muestra un toast:
> "Este evento ya fue resuelto o reemplazado por un cambio más reciente. Refrescando lista..."

La tabla se refresca automáticamente y se destaca el nuevo estado del evento. El botón de aprobar queda deshabilitado tras el refresh.
**Motivación**: Evitar decisiones inconsistentes en edición concurrente.
**Aplicación**: Hook `useApproveEvent` / `useRejectEvent` (manejo de 409), toast + refetch de TanStack Query.

#### C10: UX de rechazo sobre baseline absent
**Decisión**: Si el admin hace click en **REJECT** sobre un evento cuyo path tiene baseline `status: absent` (no hay archivo a restaurar), el modal de rechazo oculta las opciones "Restaurar" y "Cuarentena" y muestra:
> "No existe archivo a restaurar (baseline ausente). Confirmar rechazo registrará el evento como rejected sin acción en el filesystem."

Al confirmar, el evento pasa a `rejected` y se dispara un warning en logs (sin comando al agente).
**Motivación**: Transparencia sobre el no-op del backend.
**Aplicación**: `components/ui/RejectModal.tsx` (branch `baseline_absent`).

### Resiliencia y degradación

#### W11: Banner de webhooks fallidos
**Decisión**: Si la tabla `failed_notifications` tiene filas con `retry_count >= 3`, el backend expone `GET /notifications/failed/count`. El frontend hace polling cada 30 s y muestra un banner amarillo persistente en el header:
> "Notificaciones externas pendientes: N alertas no pudieron ser enviadas a n8n. [Ver detalle]"

El link abre una vista que permite reintentar manualmente o descartar.
**Motivación**: Visibilidad de alertas perdidas por caída de n8n.
**Aplicación**: `components/layout/NotificationsBanner.tsx`, `pages/FailedNotifications.tsx`.

#### W12: Banner de degradación del sistema
**Decisión**: El frontend consume `GET /health/components` cada 10 segundos. Si cualquier componente (`postgres`, `valkey`, `n8n`, o algún agente) está en estado `degraded` o `down`, se muestra un banner rojo persistente con el nombre del componente y timestamp del último check saludable. El banner NO bloquea la UI pero es cerrable solo hasta el próximo poll.
**Motivación**: Operador enterado de degradación sin necesidad de abrir dashboards externos.
**Aplicación**: `components/layout/SystemBanner.tsx` en `MainLayout`.

### UX y features

#### W1: Filtro default oculta `superseded`
**Decisión**: La vista de Eventos filtra por defecto excluyendo estados `superseded`. Se agrega un toggle "Mostrar superseded" (checkbox) en el panel de filtros. Al activarlo, reaparecen en la lista con un ícono visual distintivo (cadena rota) y se indica el `parent_event_id`. El toggle se persiste en la URL (query param `?include_superseded=true`).
**Motivación**: Los eventos superseded son ruido operacional; el admin los quiere solo para auditoría.
**Aplicación**: `pages/Events.tsx` (filtro default), `components/ui/EventsTable.tsx`.

#### W15: Bulk approve/reject + paginación
**Decisión**:
- La tabla de eventos soporta selección múltiple (checkbox por fila + "seleccionar todos en la página").
- Botones "Aprobar seleccionados" y "Rechazar seleccionados" aparecen cuando hay ≥ 1 fila marcada.
- Bulk approve: modal de confirmación con cuenta de eventos afectados y lista resumida (primeros 10 paths). Ejecuta `POST /actions/bulk-approve` con `event_ids[]`. Respuesta incluye `succeeded[]` y `failed[]` (con razón).
- Bulk reject: adicionalmente pide la acción (`restore` | `quarantine`) que se aplica a todos.
- Paginación: **50 eventos por página** por defecto, navegación numerada + "ir a página".
**Motivación**: Tras un deploy masivo, aprobar uno por uno es impráctico. Paginación fija para previsibilidad de carga.
**Aplicación**: `pages/Events.tsx`, `components/ui/BulkActionBar.tsx`, backend `modules/actions/router.py` (endpoints bulk).

#### W17: Mensaje de agente en shutdown graceful
**Decisión**: Cuando un agente está en shutdown graceful (recibido SIGTERM, drenando cola), el backend lo marca con estado `draining`. En la sección Agentes, el frontend muestra para ese agente:
> "Agente en proceso de apagado ordenado. Drenando N eventos de cola local. No se pueden ejecutar acciones (re-scan, update config) hasta que se complete o se reinicie."

Los botones de re-scan / guardar config quedan disabled con tooltip explicativo.
**Motivación**: Evitar que el admin dispare comandos durante un shutdown.
**Aplicación**: `pages/Agents.tsx`, `components/ui/AgentCard.tsx` (estado `draining`).

#### W20: Primer login con cambio obligatorio de password
**Decisión**: Si el admin loguea por primera vez con las credenciales del seed (`.env`), el backend devuelve tokens con scope `password_change_only` y la respuesta de login incluye `must_change_password: true`. El frontend redirige **forzosamente** a `/account/change-password` (sin opción de dashboard). El formulario pide:
- Password actual.
- Password nuevo (>= 12 caracteres, al menos 1 mayúscula, 1 minúscula, 1 número).
- Confirmación del nuevo.

Al completar exitosamente, el backend marca `must_change_password = false` y emite nuevos tokens con scope completo. Hasta que no se cambie, cualquier intento de navegar a otra ruta redirige de vuelta al formulario.
**Motivación**: Password del seed en `.env` no es secreto a largo plazo (está en archivos de config, git history, CI/CD).
**Aplicación**: `pages/Login.tsx` (redirect), `pages/ForcePasswordChange.tsx`, router guards.