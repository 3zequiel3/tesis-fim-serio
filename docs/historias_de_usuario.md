# Historias de Usuario — Plataforma FIM

> Última actualización: 23 de abril de 2026
> Estado: Documentación de diseño detallado — sin implementación. La construcción del código y la ejecución del protocolo experimental se proyectan para la fase inmediata siguiente y se entregarán en una adenda formal.

## Índice por Épica

### 1. Autenticación
- [US-01: Inicio de sesión](#us-01-inicio-de-sesión)
- [US-02: Cierre de sesión](#us-02-cierre-de-sesión)
- [US-03: Renovación automática de sesión](#us-03-renovación-automática-de-sesión)

### 2. Dashboard
- [US-04: Visualización de métricas generales](#us-04-visualización-de-métricas-generales)
- [US-05: Visualización de estado general del sistema](#us-05-visualización-de-estado-general-del-sistema)

### 3. Gestión de Eventos
- [US-06: Listado de eventos](#us-06-listado-de-eventos)
- [US-07: Filtrado de eventos por estado](#us-07-filtrado-de-eventos-por-estado)
- [US-08: Detalle de un evento](#us-08-detalle-de-un-evento)
- [US-09: Visualización de diff de un evento](#us-09-visualización-de-diff-de-un-evento)
- [US-10: Visualización de cadena de eventos](#us-10-visualización-de-cadena-de-eventos)

### 4. Aprobación / Rechazo
- [US-11: Aprobación de un evento pending](#us-11-aprobación-de-un-evento-pending)
- [US-12: Rechazo de un evento pending](#us-12-rechazo-de-un-evento-pending)
- [US-13: Superseded automático de eventos](#us-13-superseded-automático-de-eventos)

### 5. Gestión de Reglas
- [US-14: Listado de reglas de monitoreo](#us-14-listado-de-reglas-de-monitoreo)
- [US-15: Creación de una regla de monitoreo](#us-15-creación-de-una-regla-de-monitoreo)
- [US-16: Edición de una regla de monitoreo](#us-16-edición-de-una-regla-de-monitoreo)
- [US-17: Eliminación de una regla de monitoreo](#us-17-eliminación-de-una-regla-de-monitoreo)
- [US-18: Sincronización automática de reglas al agente](#us-18-sincronización-automática-de-reglas-al-agente)

### 6. Alertas
- [US-19: Listado de alertas](#us-19-listado-de-alertas)
- [US-20: Recepción de alertas en tiempo real](#us-20-recepción-de-alertas-en-tiempo-real)

### 7. Gestión de Agentes
- [US-21: Visualización del estado de agentes](#us-21-visualización-del-estado-de-agentes)
- [US-22: Disparo de re-scan de baseline](#us-22-disparo-de-re-scan-de-baseline)

### 8. Notificaciones
- [US-23: Notificación externa ante eventos críticos](#us-23-notificación-externa-ante-eventos-críticos)

### 9. Configuración de Agentes
- [US-24: Gestión de paths monitoreados desde el frontend](#us-24-gestión-de-paths-monitoreados-desde-el-frontend)

### Nuevas historias — Auditoría Abril 2026
- [US-25: Bulk approve/reject de eventos](#us-25-bulk-approvereject-de-eventos-w15)
- [US-26: Paginación de eventos](#us-26-paginación-de-eventos-w15)
- [US-27: Primer login con cambio obligatorio de password](#us-27-primer-login-con-cambio-obligatorio-de-password-w20)
- [US-28: Banner de degradación del sistema](#us-28-banner-de-degradación-del-sistema-w12)
- [US-29: Visualización y reintento de webhooks fallidos](#us-29-visualización-y-reintento-de-webhooks-fallidos-w11)
- [US-30: Indicador de agente en shutdown graceful](#us-30-indicador-de-agente-en-shutdown-graceful-w17)
- [US-31: Toggle para mostrar eventos superseded](#us-31-toggle-para-mostrar-eventos-superseded-w1)

---

## 1. Autenticación

### US-01: Inicio de sesión
**Como** administrador, **quiero** iniciar sesión con mis credenciales, **para** acceder a la plataforma de monitoreo de integridad de archivos.

**Criterios de aceptación:**
- [ ] El sistema presenta un formulario con campos de usuario y contraseña.
- [ ] Al ingresar credenciales válidas, se obtiene un par de tokens JWT (access token de 15 min + refresh token de 7 días con rotación) y se redirige al dashboard.
- [ ] Al ingresar credenciales inválidas, se muestra un mensaje de error genérico sin revelar qué campo es incorrecto.
- [ ] El access token se almacena en memoria (store Zustand), nunca en `localStorage` ni `sessionStorage` (W9).
- [ ] El refresh token se persiste como cookie `httpOnly` + `Secure` + `SameSite=Strict` + `Path=/auth/refresh` (W9).
- [ ] Las contraseñas se hashean con Argon2id (parámetros C9: `time_cost=3, memory_cost=65536, parallelism=4`).
- [ ] Existe rate limiting: 5 intentos / 15 minutos por `(username + IP)` (W5).
- [ ] Si el admin tiene el flag `must_change_password = true` (primer login del seed), la respuesta emite tokens con scope `password_change_only` y el frontend redirige a `/account/change-password` (W20, detalle en US-27).

> **Nota:** El primer usuario admin se crea automáticamente como seed al inicializar la base de datos (credenciales desde variables de entorno). No existe registro público de usuarios. Admins adicionales se crean desde la interfaz por un admin existente.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Auth)

---

### US-02: Cierre de sesión
**Como** administrador, **quiero** cerrar mi sesión activa, **para** evitar accesos no autorizados desde mi dispositivo.

**Criterios de aceptación:**
- [ ] Existe un botón de logout visible en la interfaz.
- [ ] Al cerrar sesión, se limpia el access token de memoria y se invalida la cookie del refresh token.
- [ ] El backend agrega el `jti` del refresh token a una blacklist en Valkey con TTL igual a su tiempo restante (C8).
- [ ] Tras cerrar sesión, se redirige al formulario de login.
- [ ] Las solicitudes posteriores con tokens invalidados son rechazadas por el backend (401).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Auth)

---

### US-03: Renovación automática de sesión
**Como** administrador, **quiero** que mi sesión se renueve automáticamente mientras esté activo, **para** no tener que volver a iniciar sesión frecuentemente.

**Criterios de aceptación:**
- [ ] El frontend solicita un nuevo access token usando el refresh token antes de que expire.
- [ ] El refresh token rota en cada uso (el anterior se invalida al emitir uno nuevo) — C8.
- [ ] Si el refresh token también expiró o fue revocado (blacklist), se redirige al login.
- [ ] La renovación es transparente para el usuario y no interrumpe su flujo de trabajo.
- [ ] El sistema soporta rotación de claves JWT sin downtime mediante `JWT_SECRET_CURRENT` + `JWT_SECRET_PREVIOUS` (C8).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Auth)

---

## 2. Dashboard

### US-04: Visualización de métricas generales
**Como** administrador, **quiero** ver un resumen de métricas del sistema en el dashboard, **para** tener una visión rápida del estado de integridad de los archivos monitoreados.

**Criterios de aceptación:**
- [ ] El dashboard muestra la cantidad de eventos agrupados por estado (`pending`, `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`).
- [ ] Los valores de estado se muestran siempre en minúsculas (snake_case), alineados al léxico canónico C1.
- [ ] Las métricas se cargan al acceder al dashboard.
- [ ] Los datos se presentan de forma clara con indicadores numéricos.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Dashboard)

---

### US-05: Visualización de estado general del sistema
**Como** administrador, **quiero** ver el estado general del sistema en el dashboard, **para** identificar rápidamente si hay situaciones que requieran mi atención.

**Criterios de aceptación:**
- [ ] El dashboard indica cuántos eventos `pending` existen sin resolver.
- [ ] Se muestra el estado de conectividad de los agentes registrados (`online` / `offline` / `draining` / `dead`).
- [ ] Se destacan visualmente las situaciones críticas (eventos `pending` con severidad `critical` o `high`).
- [ ] Si hay componentes degradados (`postgres`, `valkey`, `n8n` o algún agente en estado `down` / `degraded`), se muestra banner rojo persistente (ver US-28).
- [ ] Si hay notificaciones externas fallidas (`failed_notifications` con `retry_count >= 3`), se muestra banner amarillo persistente (ver US-29).

**Prioridad:** Media
**Módulo:** Frontend / Backend (Dashboard)

---

## 3. Gestión de Eventos

### US-06: Listado de eventos
**Como** administrador, **quiero** ver un listado de todos los eventos de integridad registrados, **para** revisar la actividad detectada por los agentes.

**Criterios de aceptación:**
- [ ] Se muestra una tabla paginada con los eventos registrados (50 por página por defecto, W15 / US-26).
- [ ] Cada fila muestra: path del archivo, estado, tipo de acción, severidad, fecha de creación y **proceso causante** (PID, UID, `exe` del ejecutable que realizó el cambio — contexto provisto por `fanotify`).
- [ ] El listado se ordena por fecha de creación descendente por defecto.
- [ ] El filtro default excluye eventos `superseded` (W1 / US-31).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Eventos)

---

### US-07: Filtrado de eventos por estado
**Como** administrador, **quiero** filtrar los eventos por su estado, **para** enfocarme en los que requieren mi acción.

**Criterios de aceptación:**
- [ ] Existe un selector que permite filtrar por estado: `pending`, `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`.
- [ ] Se puede seleccionar uno o más estados simultáneamente.
- [ ] Por defecto, `superseded` queda excluido del listado (W1).
- [ ] Existe toggle "Mostrar superseded" en el panel de filtros que los reincorpora con ícono visual distintivo (ver US-31).
- [ ] El listado se actualiza dinámicamente al aplicar o quitar filtros.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Eventos)

---

### US-08: Detalle de un evento
**Como** administrador, **quiero** ver el detalle completo de un evento, **para** comprender qué cambio fue detectado y tomar una decisión informada.

**Criterios de aceptación:**
- [ ] Al seleccionar un evento del listado, se muestra una vista de detalle.
- [ ] La vista muestra: path, hash detectado (SHA-256), estado actual, tipo de acción, severidad, fecha de creación, fecha de resolución (si aplica), quién lo resolvió (si aplica).
- [ ] Se muestran los **timestamps dobles** (`detected_at` del agente y `received_at` del backend) validados contra clock skew de 5 minutos (W13).
- [ ] Se muestra el **contexto forense del proceso causante**: PID, UID, path del ejecutable (`exe`). Este contexto es provisto por `fanotify` y no estaría disponible con alternativas basadas en `inotify`.
- [ ] Si el evento tiene un `parent_event_id`, se muestra un enlace al evento padre.
- [ ] Si el evento pertenece a una cadena, se indica su posición y se permite navegar a los eventos relacionados (ver US-10).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Eventos)

---

### US-09: Visualización de diff de un evento
**Como** administrador, **quiero** ver las diferencias entre el contenido anterior y el actual de un archivo modificado, **para** evaluar el impacto del cambio detectado.

**Criterios de aceptación:**
- [ ] En el detalle de un evento, se muestra un diff lado a lado o unificado del contenido.
- [ ] El diff textual (lado a lado o unificado) solo está disponible para archivos de texto.
- [ ] Para archivos binarios, se muestra: comparación de hashes (hash anterior vs. nuevo con indicador visual) y hex dump parcial (primeros N bytes, lado a lado).
- [ ] El componente DiffViewer detecta automáticamente si el archivo es texto o binario y cambia de modo.
- [ ] Se utiliza `react-diff-viewer-continued` con opciones de escapado activas; queda prohibido el uso de `dangerouslySetInnerHTML` (W8).
- [ ] El contenido del diff nunca se loguea en los logs estructurados (W6) — solo se registran `hash_before`, `hash_after` y `size_delta`.

**Prioridad:** Media
**Módulo:** Frontend / Backend (Eventos)

---

### US-10: Visualización de cadena de eventos
**Como** administrador, **quiero** ver la cadena de eventos asociada a un mismo archivo (path), **para** entender el historial de cambios y cómo se vinculan entre sí.

**Criterios de aceptación:**
- [ ] Desde el detalle de un evento, se puede acceder a la cadena de eventos del mismo path.
- [ ] La cadena muestra todos los eventos ordenados cronológicamente, con indicación visual de cuáles fueron marcados como `superseded`.
- [ ] Cada evento de la cadena es navegable hacia su detalle.
- [ ] El evento `superseded` se muestra con ícono de cadena rota y referencia a su `parent_event_id`.

**Prioridad:** Media
**Módulo:** Frontend / Backend (Eventos)

---

## 4. Aprobación / Rechazo

### US-11: Aprobación de un evento pending
**Como** administrador, **quiero** aprobar un evento en estado `pending`, **para** aceptar el cambio detectado y actualizar el baseline del archivo.

**Criterios de aceptación:**
- [ ] En el detalle de un evento `pending`, existe un botón "Aprobar".
- [ ] Al aprobar, el backend aplica un UPDATE optimista usando `version = :expected_version` (C5).
- [ ] Al tener éxito, el estado del evento cambia a `approved` y se registran `resolved_at` y `resolved_by`.
- [ ] El baseline del archivo se actualiza con el **hash actual** del archivo (no con el hash del momento del evento), para reflejar el estado real del filesystem al momento del approve.
- [ ] Se envía la actualización de baseline al agente vía Valkey Streams, firmada con HMAC-SHA256 (C7) e incluyendo `ruleset_version` monotónico (C11).
- [ ] El agente rechaza el comando si la firma HMAC es inválida o si `ruleset_version` es menor que el último aplicado.
- [ ] El agente actualiza su baseline local, re-cifrado con AES-256-GCM (W10) y confirma mediante `event_ack` (C3).
- [ ] Si el archivo ya no existe en el filesystem al momento de aprobar, se muestra un warning: "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline."
- [ ] El admin debe confirmar explícitamente la aprobación de un archivo ausente.
- [ ] Al confirmar, el baseline registra el path como `absent` (hash: null), y el agente trata la creación futura de ese archivo como anomalía.
- [ ] La operación se registra en `audit_log` con retención ilimitada (W18).
- [ ] Si el evento fue resuelto o marcado como `superseded` entre el render y el click de APPROVE (UPDATE optimista afecta 0 filas), el backend retorna HTTP 409 y el frontend muestra un toast: "Este evento ya fue resuelto o reemplazado. Refrescando lista..." (C5).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Eventos)

---

### US-12: Rechazo de un evento pending
**Como** administrador, **quiero** rechazar un evento en estado `pending` indicando una acción correctiva, **para** revertir o aislar un cambio no autorizado.

**Criterios de aceptación:**
- [ ] En el detalle de un evento `pending`, existe un botón "Rechazar".
- [ ] Al rechazar, el administrador selecciona la acción correctiva: `restore` (restaurar desde baseline) o `quarantine` (mover a cuarentena).
- [ ] Si el baseline del path está en `status: absent`, el modal de rechazo oculta las opciones de acción correctiva y muestra: "No hay archivo a restaurar (baseline ausente). Confirmar rechazará el evento sin acción en filesystem." — C10.
- [ ] Al confirmar rechazo sobre baseline absent, el evento pasa a `rejected` y NO se envía comando al agente; se loguea warning.
- [ ] El backend aplica el mismo UPDATE optimista que en approve (C5). En caso de 409, toast + refresh.
- [ ] Al tener éxito, el estado del evento cambia a `rejected` y se registran `resolved_at` y `resolved_by`.
- [ ] Se envía la instrucción de acción correctiva al agente vía Valkey Streams, firmada con HMAC (C7) e incluyendo `ruleset_version` (C11).
- [ ] El agente escribe journal pre-acción (W2) antes de ejecutar restore o quarantine; al completar actualiza el journal a `completed` o `failed` con detalles.
- [ ] La operación se registra en `audit_log` (W18).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Eventos)

---

### US-13: Superseded automático de eventos
**Como** administrador, **quiero** que cuando un archivo con un evento `pending` reciba un nuevo cambio, el evento anterior se marque automáticamente como `superseded`, **para** mantener solo el evento más reciente como activo.

**Criterios de aceptación:**
- [ ] Si se recibe un nuevo evento para un path que ya tiene un evento en estado `pending`, el evento anterior cambia a `superseded`.
- [ ] El nuevo evento se vincula al anterior mediante `parent_event_id`.
- [ ] El evento `superseded` no aparece en la lista de eventos pending a resolver.
- [ ] La transición `pending → superseded` se valida contra la máquina de estados explícita (C2).
- [ ] Los eventos `superseded` quedan accesibles para auditoría mediante el toggle descrito en US-31.

**Prioridad:** Alta
**Módulo:** Backend (Eventos) / Agente

---

## 5. Gestión de Reglas

### US-14: Listado de reglas de monitoreo
**Como** administrador, **quiero** ver todas las reglas de monitoreo configuradas, **para** conocer las políticas activas de detección y respuesta.

**Criterios de aceptación:**
- [ ] Se muestra una tabla con las reglas existentes.
- [ ] Cada fila muestra: patrón (`pattern`), severidad, acción configurada.
- [ ] Se indica que la acción por defecto (sin regla que matchee) es `alert_only`.
- [ ] Se muestra el `ruleset_version` actual del sistema para referencia de ordering (C11).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Reglas)

---

### US-15: Creación de una regla de monitoreo
**Como** administrador, **quiero** crear una nueva regla de monitoreo, **para** definir cómo el sistema debe reaccionar ante cambios en archivos específicos.

**Criterios de aceptación:**
- [ ] Existe un formulario para crear una regla con los campos: patrón (pattern con soporte de glob y negación `!`), severidad (`critical`, `high`, `medium`, `low`) y acción (`auto_restore`, `quarantine`, `manual_review`, `alert_only`).
- [ ] El patrón soporta glob estándar (`/etc/**`) y negación con prefijo `!` (`!/etc/motd`) para excluir paths específicos.
- [ ] Al evaluar, las reglas con prefijo `!` excluyen paths del match de reglas más amplias. Si un path matchea tanto una regla inclusiva como una exclusiva, la exclusiva gana.
- [ ] Al guardar, la regla se persiste en la base de datos.
- [ ] Se valida que el patrón no esté duplicado.
- [ ] Tras la creación, el backend incrementa `ruleset_version` (C11) y dispara sincronización automática al agente (US-18).
- [ ] La operación se registra en `audit_log` (W18).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Reglas)

---

### US-16: Edición de una regla de monitoreo
**Como** administrador, **quiero** editar una regla de monitoreo existente, **para** ajustar la severidad o acción ante cambios en las políticas de seguridad.

**Criterios de aceptación:**
- [ ] Al seleccionar una regla, se muestra un formulario precargado con los valores actuales.
- [ ] Se pueden modificar el patrón, la severidad y la acción.
- [ ] Al guardar, los cambios se persisten en la base de datos.
- [ ] El backend incrementa `ruleset_version` (C11) y dispara sincronización automática al agente (US-18).
- [ ] La operación se registra en `audit_log` (W18).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Reglas)

---

### US-17: Eliminación de una regla de monitoreo
**Como** administrador, **quiero** eliminar una regla de monitoreo, **para** desactivar una política que ya no es necesaria.

**Criterios de aceptación:**
- [ ] Existe una opción para eliminar una regla desde el listado o desde el detalle.
- [ ] Se solicita confirmación antes de eliminar.
- [ ] Al confirmar, la regla se elimina de la base de datos.
- [ ] El backend incrementa `ruleset_version` (C11) y dispara sincronización automática al agente (US-18).
- [ ] Los archivos que matcheaban con esa regla pasan a usar la acción por defecto (`alert_only`).
- [ ] La operación se registra en `audit_log` (W18).

**Prioridad:** Media
**Módulo:** Frontend / Backend (Reglas)

---

### US-18: Sincronización automática de reglas al agente
**Como** administrador, **quiero** que los cambios en las reglas de monitoreo se sincronicen automáticamente al agente, **para** que las políticas se apliquen sin intervención manual adicional.

**Criterios de aceptación:**
- [ ] Tras cualquier operación CRUD sobre reglas, el backend publica el set actualizado en el stream `commands` de Valkey con tipo `rule_sync`.
- [ ] Cada comando incluye `signature` HMAC-SHA256 (C7) y `ruleset_version` monotónico (C11).
- [ ] El agente verifica firma HMAC; rechaza con error si es inválida.
- [ ] El agente verifica que `ruleset_version` sea mayor o igual al último aplicado; descarta mensajes con versión menor (idempotencia + ordering).
- [ ] El agente reemplaza su caché local de reglas con las recibidas sin reiniciar el proceso.
- [ ] El agente persiste el nuevo `ruleset_version` aplicado en `/var/lib/fim-agent/state.json`.
- [ ] Si el agente está desconectado, al reconectar procesa primero los comandos pendientes del stream antes de enviar los eventos encolados (W4).
- [ ] El agente confirma aplicación mediante `event_ack` (C3).

**Prioridad:** Alta
**Módulo:** Backend (Reglas) / Agente

---

## 6. Alertas

### US-19: Listado de alertas
**Como** administrador, **quiero** ver un listado de alertas generadas por el sistema, **para** revisar los eventos que requieren atención.

**Criterios de aceptación:**
- [ ] Se muestra una lista de alertas ordenada por fecha descendente.
- [ ] Cada alerta muestra: path del archivo, severidad, tipo de acción, fecha, canal de entrega.
- [ ] Las alertas son navegables hacia el detalle del evento asociado.

**Prioridad:** Media
**Módulo:** Frontend / Backend (Alertas)

---

### US-20: Recepción de alertas en tiempo real
**Como** administrador, **quiero** recibir alertas en tiempo real en la interfaz web, **para** enterarme inmediatamente cuando se detecta un cambio de integridad.

**Criterios de aceptación:**
- [ ] El frontend establece una conexión SSE (Server-Sent Events) con el backend.
- [ ] Cuando se registra un nuevo evento, se recibe una alerta en tiempo real.
- [ ] La alerta se muestra como una notificación visual sin necesidad de recargar la página.
- [ ] Si la conexión SSE se pierde, se intenta reconectar automáticamente.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Alertas / SSE)

---

## 7. Gestión de Agentes

### US-21: Visualización del estado de agentes
**Como** administrador, **quiero** ver el estado de los agentes de monitoreo registrados, **para** saber cuáles están activos y conectados.

**Criterios de aceptación:**
- [ ] Se muestra una lista de agentes registrados.
- [ ] Cada agente muestra: identificador, estado de conexión (`online` / `offline` / `draining` / `dead`), última actividad, `ruleset_version` aplicado, `queue_size` local.
- [ ] Se destacan visualmente los agentes no-ok.
- [ ] El backend determina el estado a partir del stream `agent_heartbeat` (heartbeat cada 10 s — W16):
  - Sin heartbeat por 30 s → `offline`
  - Sin heartbeat por 5 minutos → `dead` (y dispara webhook n8n)
  - Heartbeat con flag `shutdown: true` → `draining` (ver US-30)
- [ ] Si el heartbeat trae `queue_pressure: true` (cola local > 80%), se muestra banner de alerta específico del agente (W3).

**Prioridad:** Media
**Módulo:** Frontend / Backend (Agentes)

---

### US-22: Disparo de re-scan de baseline
**Como** administrador, **quiero** disparar un re-scan de baseline desde la interfaz, **para** forzar al agente a recalcular los hashes de todos los archivos monitoreados.

**Criterios de aceptación:**
- [ ] Existe un botón para disparar el re-scan asociado a un agente, con opción de seleccionar paths específicos.
- [ ] Antes de ejecutar, se muestra un diálogo de confirmación listando los eventos `pending` que serán marcados como `superseded` para los paths seleccionados.
- [ ] El admin debe confirmar explícitamente antes de proceder.
- [ ] Al confirmar, los eventos `pending` para esos paths se marcan como `superseded`, y el backend publica un comando `rescan_baseline` en el stream `commands`, firmado con HMAC (C7) y con `ruleset_version++` (C11).
- [ ] El agente verifica firma HMAC y versión antes de ejecutar.
- [ ] El agente regenera el baseline completo para los paths indicados, re-cifrado con AES-256-GCM (W10).
- [ ] El agente confirma mediante `event_ack` (C3).
- [ ] Se muestra confirmación de que la solicitud fue enviada al agente.
- [ ] La operación se registra en `audit_log` (W18).
- [ ] Si el agente está en estado `draining`, el botón queda deshabilitado con tooltip (ver US-30).

**Prioridad:** Media
**Módulo:** Frontend / Backend (Agentes)

---

## 8. Notificaciones

### US-23: Notificación externa ante eventos críticos
**Como** administrador, **quiero** recibir notificaciones externas (email u otros canales) cuando se detectan eventos de alta severidad, **para** estar informado incluso cuando no estoy viendo la interfaz.

**Criterios de aceptación:**
- [ ] El backend envía un webhook a n8n cuando se registra un evento con severidad `critical` o `high`.
- [ ] El payload del webhook incluye: `event_id`, path del archivo, severidad, tipo de acción tomada, contexto del proceso causante (`process_pid`, `process_uid`, `process_exe`), timestamps (`detected_at`, `received_at`).
- [ ] n8n está delimitado al rol de **enrutador de notificaciones externas**. No ejecuta comandos sobre el sistema operativo ni coordina la respuesta; toda la lógica de decisión vive en el backend propio.
- [ ] n8n procesa el webhook y reencamina la notificación por el canal configurado (correo, mensajería corporativa, SIEM).
- [ ] Si el webhook a n8n falla, se aplica retry con delays exponenciales 5 s / 30 s / 120 s (W11).
- [ ] Si fallan los 3 intentos, el backend aplica **cascada de fallbacks automáticos**: SMTP directo → webhook directo pre-configurado → log crítico.
- [ ] Si ningún canal externo pudo entregar, se persiste una fila en `failed_notifications(event_id, payload_json, last_error, failed_at, retry_count)` (W11) y la UI muestra banner amarillo (ver US-29).
- [ ] La indisponibilidad de n8n no compromete la operación del sistema: los fallbacks garantizan continuidad del alertado.

**Prioridad:** Media
**Módulo:** Backend (Notificaciones) / n8n

---

## 9. Configuración de Agentes

### US-24: Gestión de paths monitoreados desde el frontend
**Como** administrador, **quiero** agregar o quitar paths monitoreados por el agente desde la interfaz web, **para** gestionar el monitoreo sin necesidad de reiniciar el servicio del agente en el anfitrión.

**Criterios de aceptación:**
- [ ] En la sección de Agentes, se muestra la lista de paths actualmente monitoreados por cada agente.
- [ ] Existe la opción de agregar un nuevo path al listado.
- [ ] Existe la opción de quitar un path existente del listado.
- [ ] Al guardar los cambios, el backend persiste la nueva configuración en PostgreSQL.
- [ ] El backend publica un comando `update_config` en el stream `commands` de Valkey con la lista actualizada de paths, firmado con HMAC (C7) y con `ruleset_version++` (C11).
- [ ] El agente verifica firma HMAC y versión, y recarga los paths monitoreados **sin reiniciar el proceso** (los watchers de `fanotify` se reconfiguran en caliente).
- [ ] Para paths nuevos, el agente ejecuta un baseline scan automáticamente y cifra las entradas con AES-256-GCM (W10).
- [ ] El agente confirma mediante `event_ack` (C3).
- [ ] La configuración inicial (bootstrap) proviene del archivo local `/etc/fim-agent/config.yaml` del anfitrión. A partir del primer arranque, la configuración autoritativa vive en PostgreSQL y se gestiona desde el frontend.
- [ ] La operación se registra en `audit_log` (W18).
- [ ] Si el agente está en estado `draining`, los botones de guardar configuración quedan deshabilitados (ver US-30).

> **Nota sobre el despliegue:** el agente se despliega como servicio nativo de `systemd` en cada anfitrión monitoreado (no como contenedor Docker), porque `fanotify` requiere la capability `CAP_SYS_ADMIN` y el aislamiento estándar de contenedores no es compatible con otorgar esa capability sin romper el modelo de seguridad del runtime.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Agentes) / Agente

---

## Nuevas Historias de Usuario — Auditoría Abril 2026

### US-25: Bulk approve/reject de eventos (W15)
**Como** administrador, **quiero** aprobar o rechazar múltiples eventos `pending` en una sola acción, **para** gestionar eficientemente un alto volumen de cambios (por ejemplo, tras un deploy planificado).

**Criterios de aceptación:**
- [ ] La tabla de Eventos permite seleccionar múltiples filas mediante checkbox (por fila + checkbox "seleccionar todo en la página actual").
- [ ] Al seleccionar >= 1 evento `pending`, aparecen los botones "Aprobar seleccionados" y "Rechazar seleccionados".
- [ ] "Aprobar seleccionados" abre un modal con la cantidad de eventos afectados y lista resumida (primeros 10 paths). Requiere confirmación explícita.
- [ ] "Rechazar seleccionados" adicionalmente requiere elegir la acción (`restore` o `quarantine`) aplicada a todos los eventos seleccionados.
- [ ] Ejecuta `POST /actions/bulk-approve` o `POST /actions/bulk-reject` con `event_ids[]`.
- [ ] El backend procesa cada evento con optimistic locking individual (C5); un evento que falla no bloquea al resto.
- [ ] La respuesta incluye `succeeded[]` y `failed[]` (con razón por cada fallo — p. ej. `conflict`, `not_pending`, `baseline_absent`).
- [ ] Por cada evento aprobado exitosamente, el backend genera baseline update firmado con HMAC y `ruleset_version++` (C7, C11).
- [ ] Cada operación exitosa se registra en `audit_log` (W18).
- [ ] Se muestra un resumen visual: X aprobados correctamente, Y fallidos (con detalle expandible).
- [ ] La tabla se refresca automáticamente tras la operación bulk.

**Prioridad:** Media
**Módulo:** Frontend / Backend (Eventos)

---

### US-26: Paginación de eventos (W15)
**Como** administrador, **quiero** navegar la lista de eventos en páginas de tamaño fijo, **para** que la carga de la tabla sea predecible incluso con miles de eventos.

**Criterios de aceptación:**
- [ ] La tabla de Eventos muestra **50 eventos por página** por defecto.
- [ ] Existe navegación numerada (primera / anterior / números / siguiente / última).
- [ ] Existe input "ir a página" con validación (número entre 1 y total).
- [ ] El endpoint `GET /events` soporta `?page=N&page_size=50`.
- [ ] La paginación respeta los filtros activos (estado, path, fecha, toggle `include_superseded`).

**Prioridad:** Media
**Módulo:** Frontend / Backend (Eventos)

---

### US-27: Primer login con cambio obligatorio de password (W20)
**Como** administrador que loguea por primera vez, **quiero** ser forzado a cambiar el password del seed, **para** no operar el sistema con credenciales expuestas en variables de entorno.

**Criterios de aceptación:**
- [ ] El seed del primer admin crea el usuario con `must_change_password: true`.
- [ ] En el primer login exitoso, el backend retorna tokens con scope `password_change_only` y la respuesta incluye `must_change_password: true`.
- [ ] El frontend redirige forzosamente a `/account/change-password` (sin posibilidad de acceder al dashboard).
- [ ] El formulario de cambio pide: password actual, password nuevo (>= 12 caracteres, al menos 1 mayúscula, 1 minúscula, 1 número), confirmación.
- [ ] El backend valida la contraseña actual y las reglas de complejidad antes de aceptar.
- [ ] La nueva contraseña se hashea con Argon2id con parámetros C9.
- [ ] Al completar el cambio exitosamente, el backend marca `must_change_password = false` y emite nuevos tokens con scope completo.
- [ ] Cualquier intento de navegar a otra ruta mientras `must_change_password = true` redirige de vuelta al formulario.
- [ ] Si el admin cierra el navegador sin completar, el próximo login vuelve a exigir el cambio.
- [ ] La operación se registra en `audit_log` (W18).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Auth)

---

### US-28: Banner de degradación del sistema (W12)
**Como** administrador, **quiero** ver un banner persistente cuando algún componente del sistema está degradado o caído, **para** enterarme sin tener que abrir dashboards externos.

**Criterios de aceptación:**
- [ ] El frontend consume `GET /health/components` cada **10 segundos**.
- [ ] El endpoint retorna el estado de: `postgres`, `valkey`, `n8n`, y cada agente (`ok` | `degraded` | `down`).
- [ ] Si algún componente no está `ok`, se muestra un banner rojo persistente en el header con el nombre del componente afectado y timestamp del último check saludable.
- [ ] El banner es cerrable manualmente pero reaparece en el siguiente poll si la condición persiste.
- [ ] El banner NO bloquea el uso normal de la UI.
- [ ] El backend dispara webhook n8n ante cambios de estado (p. ej. `ok → degraded`).

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Health)

---

### US-29: Visualización y reintento de webhooks fallidos (W11)
**Como** administrador, **quiero** ver las notificaciones externas que fallaron y poder reintentarlas o descartarlas, **para** no perder alertas críticas cuando n8n está caído.

**Criterios de aceptación:**
- [ ] Cuando la tabla `failed_notifications` tiene al menos 1 fila con `retry_count >= 3`, el frontend muestra un banner amarillo en el header: "Notificaciones pendientes: N alertas no pudieron ser enviadas".
- [ ] El banner incluye un link que abre la vista `/notifications/failed`.
- [ ] La vista muestra tabla con: `event_id` (link al evento), timestamp del primer intento, último error, `retry_count`.
- [ ] Por cada fila, el admin puede: "Reintentar" (dispara un intento inmediato contra la cascada de fallbacks) o "Descartar" (elimina la fila).
- [ ] Bulk "Reintentar todos" disponible.
- [ ] Tras un reintento exitoso, la fila se elimina automáticamente.
- [ ] El banner desaparece cuando la tabla queda vacía.
- [ ] La acción (reintentar / descartar) se registra en `audit_log` (W18).

**Prioridad:** Media
**Módulo:** Frontend / Backend (Notificaciones)

---

### US-30: Indicador de agente en shutdown graceful (W17)
**Como** administrador, **quiero** ver cuándo un agente está en proceso de apagado ordenado, **para** no disparar acciones que no podrán ejecutarse.

**Criterios de aceptación:**
- [ ] El agente, al recibir `SIGTERM`, deja de aceptar nuevos eventos de `fanotify`, drena la cola local publicando al stream (timeout 30 s), y emite heartbeats con flag `shutdown: true`.
- [ ] El backend marca a ese agente con estado `draining` mientras el flag esté activo.
- [ ] En la sección Agentes, el agente `draining` se muestra con indicador visual distintivo (ícono + texto "Drenando N eventos").
- [ ] Los botones de re-scan, update config y similares quedan deshabilitados con tooltip: "No disponible durante shutdown graceful".
- [ ] Una vez completado el drenaje, el agente pasa a `offline` (si volverá pronto) o `dead` (si se superan 5 minutos sin heartbeat).

**Prioridad:** Baja
**Módulo:** Frontend / Backend (Agentes)

---

### US-31: Toggle para mostrar eventos superseded (W1)
**Como** administrador, **quiero** ocultar por defecto los eventos `superseded` y poder mostrarlos cuando necesite auditarlos, **para** reducir ruido en la vista operativa.

**Criterios de aceptación:**
- [ ] El filtro por estado oculta `superseded` por defecto.
- [ ] Existe un checkbox "Mostrar superseded" en el panel de filtros.
- [ ] Al activarlo, los eventos `superseded` reaparecen con ícono visual distintivo (cadena rota) y su `parent_event_id` visible.
- [ ] El toggle se persiste en la URL (query param `?include_superseded=true`) para compartir vistas.
- [ ] El endpoint `GET /events` respeta este parámetro al aplicar el filtro del backend.

**Prioridad:** Media
**Módulo:** Frontend (Eventos)

---

## Appendix: Decisiones de auditoría — Abril 2026

Las siguientes decisiones resultan de la auditoría de consistencia, lifecycle, seguridad y resiliencia realizada el 2026-04-22. En caso de conflicto con los criterios de aceptación previos, prevalece lo especificado en este appendix.

### Léxico y nomenclatura

#### C1: Léxico canónico en minúsculas
**Decisión**: Todos los valores de estado (`pending`, `approved`, `rejected`, `superseded`, `auto_restored`, `quarantined`, `alert_only`) se usan en minúsculas (snake_case) en criterios de aceptación, datos de ejemplo y mockups.
**Motivación**: Alineación con el modelo de datos canónico del backend.
**Aplicación**: Todas las historias que referencian estados de eventos (US-04, US-07, US-11, US-12, US-13).

### Modelo de eventos y lifecycle

#### C2: Máquina de estados explícita
**Decisión**: Se adopta una tabla canónica de transiciones permitidas (in-edges / out-edges). Transiciones no listadas se rechazan con HTTP 409 a nivel de service.
**Aplicación**: US-11, US-12, US-13.

#### C3: Protocolo ACK Valkey
**Decisión**: El backend consume con consumer group `fim-backend`, ejecuta `XACK` y publica `event_ack` en el stream `commands`. El agente elimina la entrada local solo al recibir `event_ack`.
**Aplicación**: US-11, US-12, US-18, US-22, US-24.

#### C5: Optimistic locking sobre Event
**Decisión**: Columna `version` en `events`; UPDATE condicionado `WHERE id = :id AND version = :expected_version AND status = 'pending'`. Si afecta 0 filas, HTTP 409 con toast + refresh en frontend.
**Aplicación**: US-11, US-12, US-25.

#### C10: Rechazo sobre baseline `absent` = no-op con warning
**Decisión**: Si se rechaza sobre baseline `status: absent`, no se envía comando al agente; evento pasa a `rejected`, warning en log.
**Aplicación**: US-12, US-25.

#### C11: `ruleset_version` monotónico
**Decisión**: Todos los comandos al agente (`baseline_update`, `rule_sync`, `update_config`, `rescan_baseline`) incluyen `ruleset_version` monotónico creciente. El agente descarta mensajes con versión menor al último aplicado.
**Aplicación**: US-11, US-12, US-15, US-16, US-17, US-18, US-22, US-24.

### Seguridad y criptografía

#### C6: Bootstrap mTLS con CA propia
**Decisión**: El backend opera como CA propia. Admin pre-registra `(agent_id, bootstrap_secret)`. El agente envía CSR firmado con HMAC. Backend emite cert válido 90 días. Rotación 15 días antes de expirar.
**Aplicación**: Base para toda comunicación backend ↔ agente.

#### C7: HMAC-SHA256 en comandos backend → agente
**Decisión**: Cada comando en el stream `commands` incluye `signature = HMAC-SHA256(shared_secret, canonical_json(payload))`. El agente rechaza comandos con firma inválida.
**Aplicación**: US-11, US-12, US-15, US-16, US-17, US-18, US-22, US-24.

#### C8: Gestión de JWT
**Decisión**: Access 15 min, refresh 7 días con rotación en cada uso. Blacklist en Valkey. Multi-key signing (`JWT_SECRET_CURRENT` + `JWT_SECRET_PREVIOUS`).
**Aplicación**: US-01, US-02, US-03.

#### C9: Parámetros Argon2id fijos
**Decisión**: `time_cost=3, memory_cost=65536, parallelism=4`.
**Aplicación**: US-01, US-27.

#### W10: Cifrado de baseline en disco
**Decisión**: Baseline cifrada con AES-256-GCM. Clave derivada `HKDF-SHA256(master_secret, salt=AGENT_ID, info="baseline-v1")`. `master_secret` en `/var/lib/fim-agent/secrets/master_secret` con permisos `0400`.
**Aplicación**: US-11, US-22, US-24.

### Resiliencia y degradación

#### W2: Journal pre-acción
**Decisión**: Antes de ejecutar `auto_restore` o `quarantine`, el agente escribe entrada en `/var/lib/fim-agent/journal/{event_id}.json` con `state: "pending"`. Al completar actualiza a `"completed"` o `"failed"`. Al arranque, rehidrata entradas incompletas.
**Aplicación**: US-12.

#### W3: Cola offline con límite y política
**Decisión**: Cola en `/var/lib/fim-agent/queue/` con límite 100 MB, política drop-oldest. Flag `queue_pressure: true` al superar 80%.
**Aplicación**: US-21.

#### W4: Orden al reconectar
**Decisión**: Al reconectar, el agente procesa primero los comandos pendientes del stream antes de enviar los eventos encolados.
**Aplicación**: US-18.

#### W5: Rate limiting
**Decisión**: Login: 5 intentos / 15 min por `(username + IP)`. API autenticada: 100 req/min por user. Stream de eventos por agente: 100 eventos/min.
**Aplicación**: US-01.

#### W6: Logging y retention
**Decisión**: `structlog` JSON. Middleware `sanitize_logs` filtra `password`, `access_token`, `refresh_token`, `bootstrap_secret`, `master_secret`, `shared_secret`, `signature`. Retention 30 días. Prohibido loguear contenido de diffs.
**Aplicación**: US-09.

#### W11: Retry de webhook n8n + DLQ + fallbacks
**Decisión**: 3 intentos con delays 5 s / 30 s / 120 s. Cascada de fallbacks: n8n → SMTP directo → webhook directo → log crítico. Si ningún canal entrega: fila en `failed_notifications`.
**Aplicación**: US-23, US-29.

#### W12: Endpoint de salud por componente + UI
**Decisión**: `GET /health/components` cada 10 s. Banner rojo persistente si componentes no están `ok`. Webhook n8n ante cambios de estado.
**Aplicación**: US-05, US-28.

#### W13: Timestamps dobles con anti-replay
**Decisión**: Evento incluye `detected_at` (agente) y `received_at` (backend). Si `|received_at - detected_at| > 5 minutos`, se rechaza con código `clock_skew`.
**Aplicación**: US-08.

#### W14: `schema_version` en mensajes
**Decisión**: Todo mensaje en streams incluye `schema_version: int`. Backend rechaza mensajes con versión mayor que la soportada.
**Aplicación**: Infraestructura de mensajería.

#### W16: Heartbeat y estado de agente
**Decisión**: Heartbeat cada 10 s con `queue_size`, `ruleset_version`, `queue_pressure`, `shutdown`. Sin heartbeat 30 s → `offline`. Sin heartbeat 5 min → `dead` + webhook.
**Aplicación**: US-21, US-30.

#### W17: Graceful shutdown
**Decisión**: Al `SIGTERM`, agente deja de aceptar eventos, drena cola (timeout 30 s), exit 0. Durante drenaje: heartbeat con `shutdown: true`, backend marca `draining`.
**Aplicación**: US-22, US-24, US-30.

#### W18: Tabla `audit_log` separada
**Decisión**: Tabla dedicada con retención ilimitada. Registra login/logout, CRUD de reglas, approve/reject, re-scan, cambios de config, bulk actions, reintentos de notificaciones, cambios de password.
**Aplicación**: US-11, US-12, US-15, US-16, US-17, US-22, US-24, US-25, US-27, US-29.

### Frontend

#### W1: Filtro default oculta `superseded`
**Decisión**: Vista de Eventos filtra por defecto excluyendo `superseded`. Toggle "Mostrar superseded" los reincorpora con ícono de cadena rota. Persistencia en URL vía query param.
**Aplicación**: US-07, US-31.

#### W7: Headers HTTP
**Decisión**: nginx del frontend emite CSP, HSTS, `X-Frame-Options: DENY`, valida header `Origin` contra whitelist, cookies con `SameSite=Strict`.
**Aplicación**: Infraestructura de seguridad.

#### W8: DiffViewer seguro
**Decisión**: `react-diff-viewer-continued` con escapado activo. Prohibido `dangerouslySetInnerHTML` en codebase.
**Aplicación**: US-09.

#### W9: Almacenamiento de tokens en cliente
**Decisión**: Access token en memoria (Zustand). Refresh token como cookie `httpOnly` + `Secure` + `SameSite=Strict` + `Path=/auth/refresh`.
**Aplicación**: US-01, US-02, US-03.

#### W15: Bulk actions + paginación
**Decisión**: Selección múltiple, botones bulk, modal de confirmación, 50 eventos/página default.
**Aplicación**: US-25, US-26.

#### W20: Seed admin con cambio de password forzado
**Decisión**: Seed con `must_change_password: true`. Primer login emite tokens con scope `password_change_only`, fuerza redirect a formulario de cambio hasta completarse.
**Aplicación**: US-01, US-27.