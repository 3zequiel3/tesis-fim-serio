# 🧑‍💻 FIM Platform – Flujo de Usuario

> Última actualización: 16 de abril de 2026
> Estado: Documentación — sin implementación

## 🎯 Objetivo

Documentar los flujos de interacción del **administrador** (único rol del sistema) con la plataforma FIM, cubriendo todas las acciones disponibles desde el frontend.

---

# 👤 Rol Único: Administrador

El sistema tiene un único rol: **Admin**. No existen usuarios finales, viewers ni roles diferenciados. El admin gestiona TODO: eventos, reglas, alertas, agentes y autenticación.

Los usuarios admin no se registran desde el frontend — el primer admin se crea automáticamente como seed al inicializar la base de datos (credenciales desde variables de entorno). Admins adicionales se crean desde la interfaz por un admin existente.

---

# 🔄 Flujo Principal del Administrador

## Ciclo típico de uso

```
┌─────────────┐
│   LOGIN     │ ← JWT (access_token + refresh_token)
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
       │                                  │ al agente via
       ├── REJECT ───► restaurar /        │ Valkey
       │               cuarentena         │
       │                                  │
       ▼                                  ▼
┌─────────────┐                    ┌─────────────┐
│  ALERTAS    │                    │  AGENTES    │
│  (real-time │                    │  (estado,   │
│   via SSE)  │                    │   re-scan)  │
└─────────────┘                    └─────────────┘
```

## Descripción paso a paso

1. **Login** — El admin ingresa credenciales. El backend emite un `access_token` (corta duración) y un `refresh_token` (larga duración). El frontend almacena ambos tokens.

2. **Dashboard** — Primera pantalla tras login. El admin obtiene una visión general:
   - Métricas de integridad del sistema (% de archivos verificados, etc.)
   - Estado de los agentes conectados (online/offline)
   - Contadores de eventos agrupados por estado

3. **Revisión de eventos** — El admin navega a Eventos, filtra por `pending`, y revisa los cambios detectados por el agente. Decide aprobar o rechazar cada uno.

4. **Gestión de reglas** — El admin configura qué hacer ante cambios en paths específicos: restaurar automáticamente, poner en cuarentena, revisar manualmente o solo alertar.

5. **Monitoreo de alertas** — Las alertas llegan en tiempo real via SSE. El admin puede ver el detalle de cada alerta y su evento asociado.

6. **Gestión de agentes** — El admin verifica el estado de los agentes y puede disparar un re-scan de baseline cuando lo necesite.

7. **Logout** — El admin cierra sesión. Los tokens se invalidan del lado del cliente.

---

# 📱 Pantallas y Acciones

## Dashboard

| Elemento | Descripción |
|----------|-------------|
| Métricas de integridad | Indicadores del estado general del filesystem monitoreado |
| Estado de agentes | Lista de agentes con indicador online/offline |
| Contadores de eventos | Cantidad de eventos por estado (pending, approved, rejected, etc.) |

**Acciones disponibles:** Solo lectura. El dashboard es informativo.

---

## Eventos

| Elemento | Descripción |
|----------|-------------|
| Lista de eventos | Tabla con todos los eventos detectados por los agentes |
| Filtro por estado | Selector para filtrar: pending, approved, rejected, auto_restored, quarantined, alert_only, superseded |
| Detalle de evento | Vista expandida: path, hash, timestamp, acción tomada, diff (si es texto) o comparación de hash + hex dump parcial (si es binario) |
| Cadena de eventos | Historial de todos los eventos vinculados al mismo path (via parent_event_id) |
| Botón APPROVE | Aprueba un evento pending → actualiza baseline |
| Botón REJECT | Rechaza un evento pending → abre modal de acción |

**Acciones disponibles:**
- Filtrar eventos por estado
- Ver detalle de cualquier evento
- Ver cadena de eventos (event chain) de un path
- Aprobar evento pending
- Rechazar evento pending (eligiendo restaurar o cuarentena)

---

## Reglas

| Elemento | Descripción |
|----------|-------------|
| Lista de reglas | Tabla con todas las reglas configuradas |
| Formulario de creación | Campos: patrón (path/glob), severidad, acción |
| Edición inline | Modificar regla existente |
| Botón eliminar | Elimina regla (con confirmación) |

**Acciones disponibles:**
- Ver lista de reglas
- Crear regla nueva
- Editar regla existente
- Eliminar regla

---

## Alertas

| Elemento | Descripción |
|----------|-------------|
| Lista de alertas | Tabla con alertas generadas, ordenadas por timestamp |
| Detalle de alerta | Evento asociado, severidad, timestamp |
| Indicador real-time | Las alertas nuevas aparecen automáticamente via SSE |

**Acciones disponibles:** Solo lectura. Las alertas se generan automáticamente.

---

## Agentes

| Elemento | Descripción |
|----------|-------------|
| Estado de agentes | Lista de agentes conectados con estado online/offline |
| Paths monitoreados | Lista editable de paths que el agente monitorea |
| Botón re-scan | Dispara re-scan de baseline para paths específicos (con confirmación) |
| Historial de sync | Registro de sincronizaciones realizadas |

**Acciones disponibles:**
- Ver estado de agentes conectados
- Agregar o quitar paths monitoreados (cambios en runtime, sin reinicio del agente)
- Disparar re-scan de baseline con paths específicos (requiere confirmación si hay eventos pending)
- Ver historial de sincronizaciones

---

# ✅ Flujo de Aprobación / Rechazo

## Flujo completo paso a paso

```
                    ┌──────────────────────────┐
                    │  AGENTE detecta cambio   │
                    │  en archivo monitoreado  │
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
                    │  Valkey Stream con        │
                    │  estado: PENDING         │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Backend consume evento  │
                    │  Persiste en PostgreSQL  │
                    │  Genera alerta           │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  Admin ve evento PENDING │
                    │  en el frontend          │
                    │                          │
                    │  Revisa:                 │
                    │  • Path afectado         │
                    │  • Hash nuevo vs. viejo  │
                    │  • Diff (si es texto)    │
                    │  • Cadena de eventos     │
                    └─────┬──────────┬─────────┘
                          │          │
                 APPROVE  │          │  REJECT
                          ▼          ▼
              ┌───────────────┐  ┌───────────────────┐
              │ Backend:      │  │ Admin elige:      │
              │ 1. Hashea     │  │                   │
              │    archivo    │  │ ┌───────────────┐ │
              │    ACTUAL     │  │ │  RESTAURAR    │ │
              │ 2. Genera     │  │ │  archivo      │ │
              │    nuevo      │  │ └───────┬───────┘ │
              │    baseline   │  │         │         │
              │ 3. Sync con   │  │ ┌───────────────┐ │
              │    agente     │  │ │  CUARENTENA   │ │
              │    via Valkey │  │ │  aislar       │ │
              │               │  │ │  archivo      │ │
              │ Estado:       │  │ └───────┬───────┘ │
              │ → APPROVED    │  │         │         │
              └───────────────┘  │ Backend ordena   │
                                 │ al agente via    │
                                 │ Valkey           │
                                 │                  │
                                 │ Estado:          │
                                 │ → REJECTED       │
                                 └──────────────────┘
```

### Detalle de APPROVE

1. Admin hace click en **APPROVE** sobre un evento `pending`
2. El frontend envía la acción al backend
3. El backend:
   - Hashea el archivo en su estado **actual** (post-cambio)
   - Genera una nueva entrada de baseline con el hash actualizado
   - Publica un comando `baseline_update` en Valkey Streams
4. El agente recibe el comando y actualiza su baseline local
5. El evento cambia a estado `approved`
6. El archivo modificado pasa a ser el nuevo "estado sano"

### Detalle de REJECT

1. Admin hace click en **REJECT** sobre un evento `pending`
2. El frontend presenta un modal con dos opciones:
   - **Restaurar archivo**: volver al estado del último baseline conocido
   - **Cuarentena**: aislar el archivo en un directorio seguro
3. El admin elige una opción
4. El frontend envía la acción elegida al backend
5. El backend:
   - Publica un comando `restore` o `quarantine` en Valkey Streams
   - El agente ejecuta la acción correspondiente
6. El evento cambia a estado `rejected`

### Nota importante sobre inotify

Cuando el agente detecta un cambio, el archivo **ya fue modificado**. No es posible capturar el estado "antes" del write porque inotify notifica *después* del hecho. Por eso:
- El diff se genera comparando contra el snapshot del baseline
- Si se aprueba, se hashea el archivo **como está ahora**
- Si se restaura, se usa la copia del baseline guardada por el agente

### Caso especial: APPROVE cuando el archivo fue eliminado

Si el admin aprueba un evento pero el archivo ya no existe en el filesystem:

```
Admin: click APPROVE
       │
       ▼
Backend consulta estado actual al agente
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
       │     Evento → APPROVED
       │
       └── Admin CANCELA:
             Evento permanece PENDING
```

> Un archivo ausente es un estado válido. Si un sysadmin eliminó un config obsoleto, aprobar es correcto. Si fue un atacante limpiando evidencia, el admin puede rechazar y restaurar desde baseline.

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
│  Sync automático al agente via Valkey               │
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
│  Al guardar → sync automático al agente.            │
│                                                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ELIMINAR regla                                     │
│  Confirmación requerida.                            │
│  Al eliminar → sync automático al agente.           │
│  El agente deja de aplicar la regla                 │
│  inmediatamente.                                    │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Acciones disponibles por regla

| Acción | Qué pasa cuando se detecta un cambio |
|--------|---------------------------------------|
| `auto_restore` | El agente restaura el archivo automáticamente desde el baseline. Evento con estado `auto_restored`. |
| `quarantine` | El agente mueve el archivo a cuarentena. Evento con estado `quarantined`. |
| `manual_review` | El evento queda `pending` para que el admin decida (approve/reject). |
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
Backend publica reglas actualizadas en Valkey Stream
       │
       ▼
Agente recibe actualización
       │
       ▼
Agente recarga reglas en memoria (sin reinicio)
```

El admin **no** necesita hacer nada adicional. La sincronización es transparente.

---

# ⚙️ Flujo de Gestión de Configuración del Agente

## Configuración inicial (bootstrap)

Al arrancar por primera vez, el agente lee su configuración desde variables de entorno (`.env`):

```
WATCH_PATHS=/etc,/var/www,/opt/app
VALKEY_URL=valkey://valkey:6379
AGENT_ID=agent-prod-01
```

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
│  2. Envía update_config via Valkey:  │
│     { "type": "update_config",       │
│       "watch_paths": ["/etc",        │
│         "/var/www", "/opt/app",      │
│         "/opt/newservice"] }         │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  Agente:                             │
│  1. Recibe config actualizada        │
│  2. Recarga paths monitoreados       │
│     (sin reinicio)                   │
│  3. Ejecuta baseline scan para       │
│     los paths nuevos                 │
│  4. Confirma al backend via Valkey   │
└──────────────────────────────────────┘
```

> El `.env` define solo el estado inicial de bootstrap. A partir del primer arranque, el admin gestiona paths desde el frontend.

---

# 🔍 Flujo de Re-scan de Baseline

## Cuándo hacer un re-scan

- Después de un deploy o actualización planificada de archivos
- Si se sospecha que el baseline quedó desactualizado
- Después de restaurar archivos desde un backup
- Al agregar nuevos paths a monitorear

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
│  "Los siguientes eventos PENDING     │
│   serán marcados como SUPERSEDED:    │
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
│  Backend recibe la solicitud         │
│  1. Marca eventos pending como       │
│     SUPERSEDED para esos paths       │
│  2. Publica comando rescan en Valkey │
│     con los paths indicados          │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│  Agente recibe comando               │
│                                      │
│  Para cada path:                     │
│  1. Escanea todos los archivos       │
│  2. Calcula hash SHA-256             │
│  3. Guarda snapshot nuevo            │
│  4. Actualiza baseline en memoria    │
│  5. Confirma al backend via Valkey   │
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

- El re-scan **no genera eventos**: asume que el estado actual es el correcto
- Antes de ejecutar, el admin recibe un **warning** listando todos los eventos `pending` que serán marcados como `superseded`
- El admin debe **confirmar explícitamente** antes de que el re-scan se ejecute
- Durante el re-scan, el monitoreo sigue activo — los cambios que ocurran en ese momento se evalúan contra el baseline anterior hasta que el nuevo se complete
- El admin puede ver el historial de sincronizaciones para confirmar que el re-scan se completó

---

# 🚫 Limitaciones del Usuario

## Qué NO puede hacer el admin

| Acción restringida | Razón |
|-------------------|-------|
| Modificar archivos del filesystem directamente | El frontend no tiene acceso al filesystem. El agente es el único componente con acceso directo. |
| Ejecutar comandos en el agente | No existe shell remoto ni terminal. La comunicación es solo via comandos estructurados por Valkey. |
| Ver contenido completo de archivos | El sistema solo muestra diffs de texto por razones de seguridad y rendimiento. |
| Ver diffs textuales de archivos binarios | Los diffs línea a línea solo aplican a archivos de texto. Para binarios, se muestra comparación de hashes y hex dump parcial (primeros N bytes). |
| Desactivar el agente desde el frontend | El agente es un servicio autónomo. Se gestiona a nivel contenedor (Docker). |
| Modificar configuración avanzada del agente | Los paths monitoreados se gestionan desde el frontend, pero parámetros como VALKEY_URL o AGENT_ID son del contenedor (.env). |
| Registrar usuarios públicamente | El primer admin se crea por seed. Admins adicionales se crean desde la interfaz. No hay registro público. |

## Limitaciones técnicas del sistema

| Limitación | Impacto | Mitigación |
|-----------|---------|------------|
| inotify notifica después del write | No se puede capturar el estado "antes" del cambio | Se compara contra el snapshot del baseline |
| Diffs textuales solo para texto | Archivos binarios no tienen diff línea a línea | Se muestra comparación de hashes + hex dump parcial de primeros bytes |
| Cola offline es JSON plano | Sin transaccionalidad, riesgo de pérdida si el contenedor muere mid-write | Escritura atómica (write + rename), archivos pequeños |
| Baseline puede crecer | Snapshots consumen disco | Máximo 3 snapshots por archivo, compresión gzip |
| N8N licencia fair-code | No es open source puro | Aceptable para proyecto académico |

---

# 📖 Escenarios de Uso Típicos

## Escenario 1: Detección y aprobación de un cambio legítimo

**Contexto:** Un administrador de sistemas actualizó la configuración de nginx. El agente FIM detectó el cambio.

```
1. Admin de sistemas modifica /etc/nginx/nginx.conf
                │
                ▼
2. Agente detecta cambio via watchdog/inotify
   Regla para /etc/nginx/** → manual_review
   Genera evento PENDING
                │
                ▼
3. Agente publica evento en Valkey Stream
                │
                ▼
4. Backend consume, persiste en PostgreSQL, genera alerta
                │
                ▼
5. Admin FIM recibe alerta en tiempo real (SSE)
   Navega a Eventos → filtra PENDING
                │
                ▼
6. Admin FIM abre el detalle del evento:
   • Path: /etc/nginx/nginx.conf
   • Diff: ve que se agregó un nuevo upstream
   • Cadena: verifica que no hay eventos previos sospechosos
                │
                ▼
7. Admin FIM reconoce el cambio como legítimo
   Click en APPROVE
                │
                ▼
8. Backend hashea el archivo actual
   Actualiza baseline
   Sync al agente via Valkey
                │
                ▼
9. Evento pasa a APPROVED
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
   Regla para /opt/deploy/** → manual_review (severidad: high)
   Genera evento PENDING
                │
                ▼
3. Backend persiste evento, genera alerta de severidad HIGH
                │
                ▼
4. Admin recibe alerta, navega a detalle del evento
   • Diff: se agregaron líneas sospechosas al script
   • No hay registro de deploy reciente
                │
                ▼
5. Admin decide REJECT → elige RESTAURAR
                │
                ▼
6. Backend envía comando RESTORE al agente via Valkey
                │
                ▼
7. Agente restaura run.sh desde el snapshot del baseline
                │
                ▼
8. Evento pasa a REJECTED
   El archivo vuelve a su estado original
   Admin investiga el incidente por otros medios
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
   El agente comienza a aplicar las reglas inmediatamente
                │
                ▼
7. Admin navega a AGENTES → dispara re-scan de baseline
   para /opt/newservice/
                │
                ▼
8. Agente escanea el directorio completo
   Genera baseline inicial para todos los archivos
   El servicio queda monitoreado
```

---

## Escenario 4: Re-scan post-deploy planificado

**Contexto:** Se realizó un deploy planificado que modifica múltiples archivos. El admin quiere aceptar todos los cambios como nuevo baseline sin revisar uno por uno.

```
1. Deploy planificado modifica archivos en:
   • /var/www/app/
   • /etc/app/config/
                │
                ▼
2. Agente detecta múltiples cambios
   Genera eventos PENDING (si las reglas dicen manual_review)
                │
                ▼
3. Admin sabe que el deploy es legítimo
   En lugar de aprobar evento por evento:
                │
                ▼
4. Admin navega a AGENTES
   El sistema muestra warning:
   "X eventos PENDING serán marcados como SUPERSEDED"
   Admin confirma el re-scan
   Selecciona paths: /var/www/app/, /etc/app/config/
   Click en "Re-scan Baseline"
                │
                ▼
5. Agente re-escanea los paths indicados
   Genera nuevo baseline con el estado actual
                │
                ▼
6. Los eventos PENDING previos quedan SUPERSEDED
   (reemplazados por el re-scan que estableció
    un nuevo punto de referencia)
                │
                ▼
7. A partir de ahora, cualquier cambio se compara
   contra el baseline post-deploy
```

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
│              │ (regla: alert_only)                       │
│ superseded   │ Reemplazado por evento más reciente       │
│              │ en el mismo path (ej: tras re-scan)       │
└──────────────┴───────────────────────────────────────────┘
```

### Diagrama de transiciones

```
                    ┌─────────┐
                    │ PENDING │
                    └────┬────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
              ▼          ▼          ▼
        ┌──────────┐ ┌────────┐ ┌───────────┐
        │ APPROVED │ │REJECTED│ │SUPERSEDED │
        └──────────┘ └────────┘ └───────────┘

  (generados directamente por reglas automáticas,
   nunca pasan por PENDING)

        ┌───────────────┐  ┌──────────────┐  ┌────────────┐
        │ AUTO_RESTORED │  │ QUARANTINED  │  │ ALERT_ONLY │
        └───────────────┘  └──────────────┘  └────────────┘
```
