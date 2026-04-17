# Historias de Usuario — Plataforma FIM

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

---

## 1. Autenticación

### US-01: Inicio de sesión
**Como** administrador, **quiero** iniciar sesión con mis credenciales, **para** acceder a la plataforma de monitoreo de integridad de archivos.

**Criterios de aceptación:**
- [ ] El sistema presenta un formulario con campos de usuario y contraseña.
- [ ] Al ingresar credenciales válidas, se obtiene un token JWT y se redirige al dashboard.
- [ ] Al ingresar credenciales inválidas, se muestra un mensaje de error sin revelar qué campo es incorrecto.
- [ ] El token JWT se almacena de forma segura en el cliente.

> **Nota:** El primer usuario admin se crea automáticamente como seed al inicializar la base de datos (credenciales desde `.env`). No existe registro público de usuarios.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Auth)

---

### US-02: Cierre de sesión
**Como** administrador, **quiero** cerrar mi sesión activa, **para** evitar accesos no autorizados desde mi dispositivo.

**Criterios de aceptación:**
- [ ] Existe un botón de logout visible en la interfaz.
- [ ] Al cerrar sesión, se elimina el token JWT del cliente.
- [ ] Tras cerrar sesión, se redirige al formulario de login.
- [ ] Las solicitudes posteriores con el token eliminado son rechazadas por el backend.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Auth)

---

### US-03: Renovación automática de sesión
**Como** administrador, **quiero** que mi sesión se renueve automáticamente mientras esté activo, **para** no tener que volver a iniciar sesión frecuentemente.

**Criterios de aceptación:**
- [ ] El frontend solicita un nuevo access token usando el refresh token antes de que expire.
- [ ] Si el refresh token también expiró, se redirige al login.
- [ ] La renovación es transparente para el usuario y no interrumpe su flujo de trabajo.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Auth)

---

## 2. Dashboard

### US-04: Visualización de métricas generales
**Como** administrador, **quiero** ver un resumen de métricas del sistema en el dashboard, **para** tener una visión rápida del estado de integridad de los archivos monitoreados.

**Criterios de aceptación:**
- [ ] El dashboard muestra la cantidad de eventos agrupados por estado (pending, approved, rejected, auto_restored, quarantined, alert_only, superseded).
- [ ] Las métricas se cargan al acceder al dashboard.
- [ ] Los datos se presentan de forma clara con indicadores numéricos.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Dashboard)

---

### US-05: Visualización de estado general del sistema
**Como** administrador, **quiero** ver el estado general del sistema en el dashboard, **para** identificar rápidamente si hay situaciones que requieran mi atención.

**Criterios de aceptación:**
- [ ] El dashboard indica cuántos eventos pending existen sin resolver.
- [ ] Se muestra el estado de conectividad de los agentes registrados.
- [ ] Se destacan visualmente las situaciones críticas (eventos pending con severidad critical o high).

**Prioridad:** Media
**Módulo:** Frontend / Backend (Dashboard)

---

## 3. Gestión de Eventos

### US-06: Listado de eventos
**Como** administrador, **quiero** ver un listado de todos los eventos de integridad registrados, **para** revisar la actividad detectada por los agentes.

**Criterios de aceptación:**
- [ ] Se muestra una tabla paginada con los eventos registrados.
- [ ] Cada fila muestra: path del archivo, estado, tipo de acción, fecha de creación.
- [ ] El listado se ordena por fecha de creación descendente por defecto.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Eventos)

---

### US-07: Filtrado de eventos por estado
**Como** administrador, **quiero** filtrar los eventos por su estado, **para** enfocarme en los que requieren mi acción.

**Criterios de aceptación:**
- [ ] Existe un selector que permite filtrar por estado: pending, approved, rejected, auto_restored, quarantined, alert_only, superseded.
- [ ] Se puede seleccionar uno o más estados simultáneamente.
- [ ] El listado se actualiza dinámicamente al aplicar o quitar filtros.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Eventos)

---

### US-08: Detalle de un evento
**Como** administrador, **quiero** ver el detalle completo de un evento, **para** comprender qué cambio fue detectado y tomar una decisión informada.

**Criterios de aceptación:**
- [ ] Al seleccionar un evento del listado, se muestra una vista de detalle.
- [ ] La vista muestra: path, hash detectado, estado actual, tipo de acción, fecha de creación, fecha de resolución (si aplica), quién lo resolvió (si aplica).
- [ ] Si el evento tiene un parent_event_id, se muestra un enlace al evento padre.

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

**Prioridad:** Media
**Módulo:** Frontend / Backend (Eventos)

---

### US-10: Visualización de cadena de eventos
**Como** administrador, **quiero** ver la cadena de eventos asociada a un mismo archivo (path), **para** entender el historial de cambios y cómo se vinculan entre sí.

**Criterios de aceptación:**
- [ ] Desde el detalle de un evento, se puede acceder a la cadena de eventos del mismo path.
- [ ] La cadena muestra todos los eventos ordenados cronológicamente, con indicación de cuáles fueron superseded.
- [ ] Cada evento de la cadena es navegable hacia su detalle.

**Prioridad:** Media
**Módulo:** Frontend / Backend (Eventos)

---

## 4. Aprobación / Rechazo

### US-11: Aprobación de un evento pending
**Como** administrador, **quiero** aprobar un evento en estado pending, **para** aceptar el cambio detectado y actualizar el baseline del archivo.

**Criterios de aceptación:**
- [ ] En el detalle de un evento pending, existe un botón "Aprobar".
- [ ] Al aprobar, el estado del evento cambia a approved y se registra resolved_at y resolved_by.
- [ ] El baseline del archivo se actualiza con el nuevo hash.
- [ ] Se envía la actualización de baseline al agente vía Valkey Streams.
- [ ] Si el archivo ya no existe en el filesystem al momento de aprobar, se muestra un warning: "El archivo ya no existe. Aprobar = la ausencia es el nuevo estado válido del baseline."
- [ ] El admin debe confirmar explícitamente la aprobación de un archivo ausente.
- [ ] Al confirmar, el baseline registra el path como "absent" (hash: null), y el agente trata la creación futura de ese archivo como anomalía.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Eventos)

---

### US-12: Rechazo de un evento pending
**Como** administrador, **quiero** rechazar un evento en estado pending indicando una acción correctiva, **para** revertir o aislar un cambio no autorizado.

**Criterios de aceptación:**
- [ ] En el detalle de un evento pending, existe un botón "Rechazar".
- [ ] Al rechazar, el administrador selecciona la acción correctiva: auto_restore (restaurar desde backup) o quarantine (mover a cuarentena).
- [ ] El estado del evento cambia a rejected y se registra resolved_at y resolved_by.
- [ ] Se envía la instrucción de acción correctiva al agente vía Valkey Streams.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Eventos)

---

### US-13: Superseded automático de eventos
**Como** administrador, **quiero** que cuando un archivo con un evento pending reciba un nuevo cambio, el evento anterior se marque automáticamente como superseded, **para** mantener solo el evento más reciente como activo.

**Criterios de aceptación:**
- [ ] Si se recibe un nuevo evento para un path que ya tiene un evento en estado pending, el evento anterior cambia a superseded.
- [ ] El nuevo evento se vincula al anterior mediante parent_event_id.
- [ ] El evento superseded no aparece en la lista de eventos pending a resolver.

**Prioridad:** Alta
**Módulo:** Backend (Eventos) / Agente

---

## 5. Gestión de Reglas

### US-14: Listado de reglas de monitoreo
**Como** administrador, **quiero** ver todas las reglas de monitoreo configuradas, **para** conocer las políticas activas de detección y respuesta.

**Criterios de aceptación:**
- [ ] Se muestra una tabla con las reglas existentes.
- [ ] Cada fila muestra: patrón (pattern), severidad, acción configurada.
- [ ] Se indica que la acción por defecto (sin regla) es alert_only.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Reglas)

---

### US-15: Creación de una regla de monitoreo
**Como** administrador, **quiero** crear una nueva regla de monitoreo, **para** definir cómo el sistema debe reaccionar ante cambios en archivos específicos.

**Criterios de aceptación:**
- [ ] Existe un formulario para crear una regla con los campos: patrón (pattern con soporte de glob y negación `!`), severidad (critical, high, medium, low) y acción (auto_restore, quarantine, manual_review, alert_only).
- [ ] El patrón soporta glob estándar (`/etc/**`) y negación con prefijo `!` (`!/etc/motd`) para excluir paths específicos.
- [ ] Al guardar, la regla se persiste en la base de datos.
- [ ] Se valida que el patrón no esté duplicado.
- [ ] Tras la creación, se dispara la sincronización automática de reglas al agente.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Reglas)

---

### US-16: Edición de una regla de monitoreo
**Como** administrador, **quiero** editar una regla de monitoreo existente, **para** ajustar la severidad o acción ante cambios en las políticas de seguridad.

**Criterios de aceptación:**
- [ ] Al seleccionar una regla, se muestra un formulario precargado con los valores actuales.
- [ ] Se pueden modificar la severidad y la acción.
- [ ] Al guardar, los cambios se persisten en la base de datos.
- [ ] Tras la edición, se dispara la sincronización automática de reglas al agente.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Reglas)

---

### US-17: Eliminación de una regla de monitoreo
**Como** administrador, **quiero** eliminar una regla de monitoreo, **para** desactivar una política que ya no es necesaria.

**Criterios de aceptación:**
- [ ] Existe una opción para eliminar una regla desde el listado o desde el detalle.
- [ ] Se solicita confirmación antes de eliminar.
- [ ] Al confirmar, la regla se elimina de la base de datos.
- [ ] Tras la eliminación, se dispara la sincronización automática de reglas al agente.
- [ ] Los archivos que matcheaban con esa regla pasan a usar la acción por defecto (alert_only).

**Prioridad:** Media
**Módulo:** Frontend / Backend (Reglas)

---

### US-18: Sincronización automática de reglas al agente
**Como** administrador, **quiero** que los cambios en las reglas de monitoreo se sincronicen automáticamente al agente, **para** que las políticas se apliquen sin intervención manual adicional.

**Criterios de aceptación:**
- [ ] Tras cualquier operación CRUD sobre reglas, el backend envía el set actualizado de reglas al agente vía Valkey Streams.
- [ ] El agente reemplaza su caché local de reglas con las recibidas.
- [ ] Si el agente está desconectado, recibe las reglas actualizadas al reconectarse.

**Prioridad:** Alta
**Módulo:** Backend (Reglas) / Agente

---

## 6. Alertas

### US-19: Listado de alertas
**Como** administrador, **quiero** ver un listado de alertas generadas por el sistema, **para** revisar los eventos que requieren atención.

**Criterios de aceptación:**
- [ ] Se muestra una lista de alertas ordenada por fecha descendente.
- [ ] Cada alerta muestra: path del archivo, severidad, tipo de acción, fecha.
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
- [ ] Cada agente muestra: identificador, estado de conexión (conectado/desconectado), última actividad.
- [ ] Se destaca visualmente los agentes desconectados.

**Prioridad:** Media
**Módulo:** Frontend / Backend (Agentes)

---

### US-22: Disparo de re-scan de baseline
**Como** administrador, **quiero** disparar un re-scan de baseline desde la interfaz, **para** forzar al agente a recalcular los hashes de todos los archivos monitoreados.

**Criterios de aceptación:**
- [ ] Existe un botón para disparar el re-scan asociado a un agente.
- [ ] Antes de ejecutar, se muestra un diálogo de confirmación listando los eventos pending que serán marcados como superseded para los paths seleccionados.
- [ ] El admin debe confirmar explícitamente antes de proceder.
- [ ] Al confirmar, los eventos pending para esos paths se marcan como superseded, y se envía un POST a /agents/rescan.
- [ ] Se muestra confirmación de que la solicitud fue enviada al agente.
- [ ] El agente recalcula los hashes y reporta cualquier discrepancia como nuevos eventos.

**Prioridad:** Media
**Módulo:** Frontend / Backend (Agentes)

---

## 8. Notificaciones

### US-23: Notificación externa ante eventos críticos
**Como** administrador, **quiero** recibir notificaciones externas (email u otros canales) cuando se detectan eventos de alta severidad, **para** estar informado incluso cuando no estoy viendo la interfaz.

**Criterios de aceptación:**
- [ ] El backend envía un webhook a N8N cuando se registra un evento con severidad critical o high.
- [ ] El payload del webhook incluye: path del archivo, severidad, tipo de acción, timestamp.
- [ ] N8N procesa el webhook y envía la notificación por el canal configurado (email, Slack, etc.).
- [ ] Si el webhook falla, se registra el error en los logs del backend sin afectar el flujo principal.

**Prioridad:** Media
**Módulo:** Backend (Notificaciones) / N8N

---

## 9. Configuración de Agentes

### US-24: Gestión de paths monitoreados desde el frontend
**Como** administrador, **quiero** agregar o quitar paths monitoreados por el agente desde la interfaz web, **para** gestionar el monitoreo sin necesidad de reiniciar el contenedor del agente.

**Criterios de aceptación:**
- [ ] En la sección de Agentes, se muestra la lista de paths actualmente monitoreados por cada agente.
- [ ] Existe la opción de agregar un nuevo path al listado.
- [ ] Existe la opción de quitar un path existente del listado.
- [ ] Al guardar los cambios, el backend persiste la nueva configuración en PostgreSQL.
- [ ] El backend envía un comando `update_config` al agente vía Valkey Streams con la lista actualizada de paths.
- [ ] El agente recarga los paths monitoreados sin reinicio.
- [ ] Para paths nuevos, el agente ejecuta un baseline scan automáticamente.
- [ ] La configuración inicial proviene del `.env` del contenedor (bootstrap). A partir del primer arranque, se gestiona desde el frontend.

**Prioridad:** Alta
**Módulo:** Frontend / Backend (Agentes) / Agente
