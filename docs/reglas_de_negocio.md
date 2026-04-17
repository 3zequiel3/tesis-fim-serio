# Reglas de Negocio — Plataforma FIM

> Documento canónico de reglas de negocio del sistema de File Integrity Monitoring.
> Cada regla es verificable, no ambigua, y trazable a decisiones de diseño documentadas.

---

## Índice por Dominio

| # | Dominio | Reglas |
|---|---------|--------|
| 1 | [Detección y monitoreo](#1-detección-y-monitoreo) | RN-01 a RN-04 |
| 2 | [Motor de decisión](#2-motor-de-decisión) | RN-05 a RN-09 |
| 3 | [Ciclo de vida del evento](#3-ciclo-de-vida-del-evento) | RN-10 a RN-14 |
| 4 | [Baseline](#4-baseline) | RN-15 a RN-20 |
| 5 | [Cadena de eventos](#5-cadena-de-eventos) | RN-21 a RN-24 |
| 6 | [Aprobación y rechazo](#6-aprobación-y-rechazo) | RN-25 a RN-29 |
| 7 | [Restauración automática](#7-restauración-automática) | RN-30 a RN-33 |
| 8 | [Cuarentena](#8-cuarentena) | RN-34 a RN-37 |
| 9 | [Resiliencia y offline](#9-resiliencia-y-offline) | RN-38 a RN-42 |
| 10 | [Autenticación y autorización](#10-autenticación-y-autorización) | RN-43 a RN-46 |
| 11 | [Almacenamiento](#11-almacenamiento) | RN-47 a RN-51 |
| 12 | [Notificaciones](#12-notificaciones) | RN-52 a RN-54 |
| 13 | [Sincronización](#13-sincronización) | RN-55 a RN-59 |
| 14 | [Seguridad avanzada](#14-seguridad-avanzada) | RN-60 a RN-67 |
| 15 | [Configuración del agente](#15-configuración-del-agente) | RN-68 a RN-70 |

---

## 1. Detección y monitoreo

### RN-01: Detección de cambios en tiempo real
**Descripción:** El agente detecta cambios en el filesystem mediante watchdog (inotify en Linux).
**Condición:** El agente está en ejecución y monitoreando los paths configurados.
**Resultado:** Se genera un evento de cambio con metadata (path, tipo de operación, timestamp, hash).
**Excepciones:** Los paths excluidos por configuración no generan eventos.

### RN-02: Limitación de captura pre-escritura
**Descripción:** El sistema NO puede capturar el estado de un archivo antes de que se escriba un cambio.
**Condición:** Siempre. Es una limitación técnica de inotify.
**Resultado:** Solo se detecta el cambio posterior a la escritura. El estado previo se obtiene del baseline almacenado.
**Excepciones:** Ninguna.

### RN-03: Diferencias solo para archivos de texto
**Descripción:** El cálculo de diffs (diferencias línea a línea) solo se realiza para archivos de texto.
**Condición:** El archivo detectado es de tipo texto plano (determinado por heurística o extensión).
**Resultado:** Se genera un diff legible entre el baseline y el archivo modificado.
**Excepciones:** Archivos binarios no generan diff textual. En su lugar, el frontend muestra comparación de hashes y hex dump parcial (primeros N bytes, lado a lado).

### RN-04: Monitoreo basado en paths configurados
**Descripción:** El agente monitorea únicamente los directorios y archivos definidos en su configuración.
**Condición:** Al iniciar el agente o al recibir una actualización de configuración.
**Resultado:** Solo los paths incluidos en la configuración generan eventos. Todo lo demás se ignora.
**Excepciones:** Ninguna.

---

## 2. Motor de decisión

### RN-05: Evaluación de reglas por pattern matching
**Descripción:** Ante un cambio detectado, el agente evalúa las reglas cacheadas localmente buscando un pattern (glob) que coincida con el path del archivo modificado.
**Condición:** Se detecta un cambio en un archivo monitoreado.
**Resultado:** Se evalúan todas las reglas (inclusivas y exclusivas con `!`). Si un path matchea una regla inclusiva y una exclusiva, la exclusiva gana.
**Excepciones:** Si ninguna regla hace match, se aplica RN-06.

### RN-06: Acción default — alert_only
**Descripción:** Si ninguna regla definida coincide con el path del archivo modificado, la acción por defecto es `alert_only`.
**Condición:** No existe regla cuyo pattern coincida con el path del evento.
**Resultado:** El evento se registra para auditoría sin ninguna acción automática.
**Excepciones:** Ninguna.

### RN-07: Tipos de acción válidos
**Descripción:** El motor de decisión soporta exactamente 4 tipos de acción.
**Condición:** Al definir o ejecutar una regla.
**Resultado:** La acción debe ser una de: `auto_restore`, `quarantine`, `manual_review`, `alert_only`.
**Excepciones:** Cualquier otro valor es rechazado como inválido.

### RN-08: Estructura de una regla
**Descripción:** Cada regla tiene tres componentes obligatorios: pattern, severity y action.
**Condición:** Al crear o actualizar una regla en el backend.
**Resultado:** `pattern` es un glob que define qué paths afecta, `severity` es uno de `critical | high | medium | low`, `action` es uno de los 4 tipos válidos (RN-07).
**Excepciones:** Ninguna.

### RN-09: Las reglas se definen en el backend
**Descripción:** La definición y gestión de reglas es responsabilidad exclusiva del backend.
**Condición:** Siempre.
**Resultado:** El agente recibe las reglas via sincronización (Valkey) y las cachea localmente. El agente nunca crea ni modifica reglas.
**Excepciones:** Ninguna.

---

## 3. Ciclo de vida del evento

### RN-10: Estados válidos de un evento
**Descripción:** Un evento de integridad tiene exactamente 7 estados posibles.
**Condición:** En cualquier punto del ciclo de vida del evento.
**Resultado:** El estado debe ser uno de: `pending`, `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`.
**Excepciones:** Ninguna.

### RN-11: Estados terminales
**Descripción:** Los estados terminales son aquellos desde los cuales no se puede transicionar a otro estado.
**Condición:** Un evento alcanza uno de los estados terminales.
**Resultado:** Los estados terminales son: `approved`, `rejected`, `auto_restored`, `quarantined`, `alert_only`, `superseded`. Una vez en estado terminal, el evento es inmutable.
**Excepciones:** `superseded` se asigna de forma automática (ver RN-21), no por acción del admin.

### RN-12: Transiciones de estado válidas desde pending
**Descripción:** Un evento en estado `pending` puede transicionar a un subconjunto definido de estados.
**Condición:** El evento está en estado `pending`.
**Resultado:** Transiciones válidas: `pending → approved`, `pending → rejected`, `pending → superseded`.
**Excepciones:** Ninguna otra transición desde `pending` es válida.

### RN-13: Asignación automática de estado por acción
**Descripción:** Cuando el motor de decisión ejecuta una acción automática, el evento se crea directamente en su estado terminal.
**Condición:** La regla matcheada tiene acción `auto_restore`, `quarantine` o `alert_only`.
**Resultado:** El evento se crea con estado `auto_restored`, `quarantined` o `alert_only` respectivamente. No pasa por `pending`.
**Excepciones:** Si la acción es `manual_review`, el evento se crea en estado `pending`.

### RN-14: Solo eventos pending requieren decisión humana
**Descripción:** La intervención del administrador solo se requiere para eventos en estado `pending`.
**Condición:** Un evento está en estado `pending`.
**Resultado:** El admin debe aprobar o rechazar el evento. Los eventos en otros estados no requieren ni permiten acción humana.
**Excepciones:** Un evento `pending` puede ser marcado como `superseded` automáticamente (ver RN-21).

---

## 4. Baseline

### RN-15: Inicialización automática del baseline
**Descripción:** El baseline se inicializa automáticamente en la primera ejecución del agente.
**Condición:** El agente arranca por primera vez (o no existe baseline previo).
**Resultado:** Se realiza un escaneo completo de todos los paths monitoreados, registrando hash y metadata de cada archivo. Este conjunto constituye el baseline inicial.
**Excepciones:** Ninguna.

### RN-16: Actualización del baseline solo por aprobación
**Descripción:** El baseline se actualiza ÚNICAMENTE cuando un administrador aprueba un cambio.
**Condición:** Un admin ejecuta la acción de aprobación sobre un evento `pending`.
**Resultado:** Se hashea el archivo en su estado ACTUAL (no el hash del evento) y se registra como nuevo baseline para ese path.
**Excepciones:** Ninguna. Las acciones `auto_restore`, `quarantine`, `reject` y `alert_only` NO actualizan el baseline.

### RN-17: Hash del archivo actual al aprobar
**Descripción:** Al aprobar un cambio, el baseline se actualiza con el hash del archivo tal como está en el momento de la aprobación, no con el hash registrado en el evento.
**Condición:** Admin aprueba un evento.
**Resultado:** Se lee el archivo del disco, se calcula su hash actual, y ese hash se registra como baseline.
**Excepciones:** Si el archivo no existe al momento de la aprobación (fue eliminado entre detección y aprobación), el frontend muestra un warning y el admin puede aprobar la ausencia como nuevo estado válido del baseline (ver RN-60).

### RN-18: Re-scan manual
**Descripción:** El frontend permite iniciar un re-scan manual del baseline completo.
**Condición:** El admin solicita un re-scan desde la interfaz (caso de uso: post-deploy masivo).
**Resultado:** Antes de ejecutar, el frontend muestra un warning listando los eventos `pending` que serán marcados como `superseded` para los paths seleccionados. El admin debe confirmar. Al confirmar, los eventos pending se marcan como `superseded` y el backend envía un comando `rescan_baseline` al agente via Valkey.
**Excepciones:** Si el admin cancela la confirmación, el re-scan no se ejecuta.

### RN-19: Protección del baseline con HMAC
**Descripción:** El baseline almacenado localmente está protegido mediante HMAC para detectar manipulación.
**Condición:** Siempre que se lee o escribe el baseline local.
**Resultado:** Al escribir, se firma con HMAC. Al leer, se verifica la firma. Si la verificación falla, se reporta un incidente de integridad.
**Excepciones:** Ninguna.

### RN-20: Permisos restringidos del baseline
**Descripción:** Los archivos de baseline tienen permisos restringidos en el filesystem.
**Condición:** Siempre.
**Resultado:** Solo el usuario del agente (o root) tiene acceso de lectura/escritura al directorio de baseline.
**Excepciones:** Ninguna.

---

## 5. Cadena de eventos

### RN-21: Creación de cadena por cambio concurrente
**Descripción:** Si un archivo cambia mientras existe un evento `pending` para el mismo path, se crea una cadena de eventos.
**Condición:** Se detecta un cambio en un path que ya tiene un evento en estado `pending`.
**Resultado:** El evento anterior se marca como `superseded`. Se crea un nuevo evento con `parent_event_id` apuntando al evento anterior. El nuevo evento queda en el estado que corresponda según la regla matcheada.
**Excepciones:** Ninguna.

### RN-22: Solo el último evento de la cadena es accionable
**Descripción:** En una cadena de eventos, solo el evento más reciente es visible para decisión del admin.
**Condición:** Existe una cadena de eventos para un mismo path.
**Resultado:** Los eventos `superseded` permanecen como historial de auditoría. Solo el último evento (no superseded) aparece como accionable en la interfaz.
**Excepciones:** Ninguna.

### RN-23: Vinculación mediante parent_event_id
**Descripción:** Los eventos de una cadena se vinculan mediante la referencia `parent_event_id`.
**Condición:** Se crea un nuevo evento para un path con un evento pending existente.
**Resultado:** El campo `parent_event_id` del nuevo evento apunta al ID del evento que fue marcado como `superseded`.
**Excepciones:** El primer evento de un path no tiene `parent_event_id` (es null).

### RN-24: El admin decide sobre el estado más reciente
**Descripción:** La decisión del administrador siempre se aplica sobre el estado actual del archivo, no sobre un estado histórico.
**Condición:** El admin aprueba o rechaza un evento.
**Resultado:** El sistema opera sobre el archivo en su estado actual en disco. Los estados intermedios (superseded) son solo historial.
**Excepciones:** Ninguna.

---

## 6. Aprobación y rechazo

### RN-25: Flujo de aprobación
**Descripción:** Al aprobar un evento, el backend actualiza el baseline con el hash actual del archivo y sincroniza al agente.
**Condición:** Admin aprueba un evento en estado `pending`.
**Resultado:** 1) Se hashea el archivo ACTUAL en disco, 2) se genera nuevo registro de baseline, 3) se sincroniza al agente via Valkey con comando `baseline_update`, 4) el evento transiciona a `approved`.
**Excepciones:** Si el archivo ya no existe, el sistema muestra warning al admin. Si confirma, el baseline registra el path como "absent" (hash: null). Ver RN-60.

### RN-26: Flujo de rechazo
**Descripción:** Al rechazar un evento, el admin elige entre restaurar o poner en cuarentena.
**Condición:** Admin rechaza un evento en estado `pending`.
**Resultado:** 1) El evento transiciona a `rejected`, 2) el backend envía al agente via Valkey el comando correspondiente (`restore_file` o `quarantine_file`), 3) el baseline NO se actualiza.
**Excepciones:** Ninguna.

### RN-27: Rechazo no actualiza baseline
**Descripción:** El rechazo de un evento nunca modifica el baseline existente.
**Condición:** Admin rechaza un evento.
**Resultado:** El baseline permanece intacto. El objetivo es que el archivo vuelva a su estado original (via restauración o cuarentena).
**Excepciones:** Ninguna.

### RN-28: Restauración ≠ Aprobación
**Descripción:** Restaurar un archivo y aprobar un cambio son operaciones conceptualmente distintas e incompatibles.
**Condición:** Siempre.
**Resultado:** Aprobar significa "el cambio es legítimo, actualizar baseline". Restaurar significa "el cambio no es legítimo, volver al estado anterior". No se pueden combinar.
**Excepciones:** Ninguna.

### RN-29: Solo admins pueden aprobar o rechazar
**Descripción:** La aprobación y el rechazo de eventos son acciones exclusivas del rol admin.
**Condición:** Un usuario intenta aprobar o rechazar un evento.
**Resultado:** Solo usuarios autenticados con rol admin pueden ejecutar estas acciones.
**Excepciones:** Ninguna. No existe otro rol en el sistema.

---

## 7. Restauración automática

### RN-30: Restauración automática solo para severity critical
**Descripción:** La acción `auto_restore` se ejecuta exclusivamente cuando la regla matcheada tiene severity `critical`.
**Condición:** Se detecta un cambio, la regla matcheada tiene `action: auto_restore` y `severity: critical`.
**Resultado:** El agente restaura el archivo desde el baseline (copia completa del archivo sano).
**Excepciones:** Si no hay baseline para el archivo (primera detección), no se puede restaurar.

### RN-31: Restauración desde baseline completo
**Descripción:** La restauración automática utiliza la copia completa del archivo baseline, no un diff.
**Condición:** Se ejecuta una acción `auto_restore`.
**Resultado:** El archivo en disco se reemplaza completamente por la copia almacenada en el baseline.
**Excepciones:** Ninguna.

### RN-32: Verificación post-restauración
**Descripción:** Después de restaurar un archivo, el agente verifica que la restauración fue exitosa.
**Condición:** Se completó una restauración (automática o por rechazo).
**Resultado:** Se calcula el hash del archivo restaurado y se compara con el hash del baseline. Si coincide, la restauración fue exitosa. Si no, se reporta un error.
**Excepciones:** Ninguna.

### RN-33: Restauración no actualiza baseline
**Descripción:** Una restauración automática no genera una actualización de baseline.
**Condición:** Se ejecuta `auto_restore`.
**Resultado:** El baseline permanece intacto (ya contiene el hash correcto, que es el mismo del archivo restaurado). El evento se crea con estado `auto_restored`.
**Excepciones:** Ninguna.

---

## 8. Cuarentena

### RN-34: Destino de archivos en cuarentena
**Descripción:** Los archivos puestos en cuarentena se mueven a un directorio dedicado del agente.
**Condición:** Se ejecuta una acción `quarantine` (automática o por rechazo).
**Resultado:** El archivo se mueve a `/agent/storage/quarantine/`.
**Excepciones:** Ninguna.

### RN-35: Renombrado de archivo en cuarentena
**Descripción:** Los archivos en cuarentena se renombran para evitar colisiones y mantener trazabilidad.
**Condición:** Se mueve un archivo a cuarentena.
**Resultado:** El archivo se renombra incluyendo timestamp y hash en el nombre.
**Excepciones:** Ninguna.

### RN-36: Permisos restringidos en cuarentena
**Descripción:** Los archivos en cuarentena tienen permisos de solo lectura restringidos a root.
**Condición:** Un archivo se coloca en cuarentena.
**Resultado:** Permisos: read-only, propietario root. No se permite escritura ni ejecución.
**Excepciones:** Ninguna.

### RN-37: Cuarentena no actualiza baseline
**Descripción:** Poner un archivo en cuarentena no modifica el baseline.
**Condición:** Se ejecuta `quarantine`.
**Resultado:** El baseline permanece intacto. El evento se crea con estado `quarantined`.
**Excepciones:** Ninguna.

---

## 9. Resiliencia y offline

### RN-38: Cola local cuando agente está offline
**Descripción:** Si el agente no puede conectarse al backend (Valkey no disponible), los eventos se encolan localmente.
**Condición:** El agente detecta un cambio pero no puede enviar el evento al backend.
**Resultado:** El evento se almacena en archivos JSON en disco local.
**Excepciones:** Ninguna.

### RN-39: Envío FIFO al reconectar
**Descripción:** Al restablecerse la conexión, los eventos encolados se envían en orden FIFO.
**Condición:** El agente recupera la conexión con Valkey.
**Resultado:** Los eventos se envían en el orden en que fueron creados (primero en entrar, primero en salir).
**Excepciones:** Ninguna.

### RN-40: Eliminación de cola tras confirmación
**Descripción:** Los archivos JSON de la cola local se eliminan solo después de confirmación de recepción.
**Condición:** El backend confirma la recepción del evento.
**Resultado:** El archivo JSON correspondiente se elimina del disco local.
**Excepciones:** Si la confirmación no llega, el archivo permanece para reintento.

### RN-41: Cola offline sin transaccionalidad
**Descripción:** La cola local no ofrece garantías transaccionales (no es ACID).
**Condición:** Siempre (limitación técnica documentada).
**Resultado:** En caso de crash del agente durante escritura de la cola, puede haber eventos parcialmente escritos o perdidos.
**Excepciones:** Ninguna. Es una limitación aceptada.

### RN-42: Acciones automáticas durante offline
**Descripción:** El agente ejecuta acciones automáticas (auto_restore, quarantine) incluso sin conexión al backend.
**Condición:** El agente está offline pero detecta un cambio que matchea una regla con acción automática.
**Resultado:** La acción se ejecuta localmente usando las reglas cacheadas. El evento resultante se encola para envío posterior.
**Excepciones:** Si las reglas cacheadas están desactualizadas respecto al backend, se opera con la versión local.

---

## 10. Autenticación y autorización

### RN-43: Autenticación JWT stateless
**Descripción:** La autenticación se implementa mediante JWT stateless con par de tokens.
**Condición:** Para toda operación autenticada.
**Resultado:** Se emite un `access_token` (corta duración) y un `refresh_token` (larga duración). El servidor no mantiene estado de sesión.
**Excepciones:** Ninguna.

### RN-44: Rol único — admin
**Descripción:** El sistema tiene un único rol: admin.
**Condición:** Siempre.
**Resultado:** Todo usuario autenticado es admin. No existe jerarquía de roles ni permisos granulares.
**Excepciones:** Ninguna.

### RN-45: Sin registro público de usuarios
**Descripción:** No existe un endpoint de registro público. Los usuarios se crean administrativamente.
**Condición:** Siempre.
**Resultado:** El primer admin se crea automáticamente como seed al inicializar la base de datos (credenciales desde variables de entorno, password hasheado con Argon2id). Admins adicionales pueden ser creados desde la interfaz por un admin existente. No hay flujo de sign-up público.
**Excepciones:** Ninguna.

### RN-46: Refresh token para renovación de sesión
**Descripción:** La renovación de sesión se realiza exclusivamente mediante el refresh token.
**Condición:** El access token expiró.
**Resultado:** El cliente presenta el refresh token para obtener un nuevo par access/refresh. Si el refresh token expiró, se requiere nuevo login.
**Excepciones:** Ninguna.

---

## 11. Almacenamiento

### RN-47: Máximo de snapshots por archivo
**Descripción:** Se almacena un máximo de 3 snapshots (copias) por archivo monitoreado.
**Condición:** Se genera un nuevo snapshot para un archivo.
**Resultado:** Si ya existen 3 snapshots, el más antiguo se elimina antes de almacenar el nuevo (FIFO).
**Excepciones:** Ninguna.

### RN-48: Compresión de snapshots antiguos
**Descripción:** Los snapshots que no son la versión más reciente se comprimen con gzip.
**Condición:** Un snapshot deja de ser la versión activa (se genera uno más nuevo).
**Resultado:** El snapshot anterior se comprime con gzip para ahorrar espacio en disco.
**Excepciones:** El snapshot activo (más reciente) permanece sin comprimir para acceso rápido.

### RN-49: Deduplicación por hash
**Descripción:** No se almacena un nuevo snapshot si el hash del archivo es idéntico al último snapshot almacenado.
**Condición:** Se genera un cambio detectado.
**Resultado:** Se compara el hash del archivo actual con el hash del último snapshot. Si son iguales, no se crea un nuevo snapshot.
**Excepciones:** Ninguna.

### RN-50: Protección de baseline con HMAC
**Descripción:** Los archivos de baseline se protegen con HMAC para garantizar su integridad.
**Condición:** Al leer o escribir archivos de baseline.
**Resultado:** Escritura: se calcula y almacena HMAC. Lectura: se verifica HMAC antes de usar el contenido.
**Excepciones:** Si la verificación HMAC falla, se trata como incidente de seguridad.

### RN-51: Permisos restringidos en almacenamiento
**Descripción:** Los directorios de baseline y snapshots tienen permisos restringidos.
**Condición:** Siempre.
**Resultado:** Solo el usuario del agente (o root) tiene acceso. Se previene lectura/escritura por otros usuarios del sistema.
**Excepciones:** Ninguna.

---

## 12. Notificaciones

### RN-52: Notificaciones via N8N
**Descripción:** Las notificaciones del sistema se canalizan a través de N8N como orquestador de flujos.
**Condición:** Se produce un evento que requiere notificación.
**Resultado:** El backend dispara un webhook o evento hacia N8N, que se encarga de la distribución (email, Slack, etc.).
**Excepciones:** Si N8N no está disponible, el evento se registra pero la notificación puede perderse.

### RN-53: Eventos que disparan notificación
**Descripción:** Se generan notificaciones para eventos que requieren atención o representan un riesgo.
**Condición:** Se crea un evento con estado `pending`, `auto_restored`, o `quarantined`.
**Resultado:** Se dispara una notificación con la información del evento (path, severidad, acción tomada).
**Excepciones:** Los eventos `alert_only` y `superseded` pueden no generar notificación dependiendo de la configuración.

### RN-54: Notificaciones no bloquean el flujo principal
**Descripción:** El envío de notificaciones es asíncrono y no bloquea el procesamiento de eventos.
**Condición:** Siempre.
**Resultado:** Si la notificación falla, el evento se procesa normalmente. La notificación es best-effort.
**Excepciones:** Ninguna.

---

## 13. Sincronización

### RN-55: Comunicación bidireccional via Valkey Streams
**Descripción:** La comunicación entre agente y backend es bidireccional a través de Valkey Streams.
**Condición:** Siempre que agente y backend necesitan intercambiar información.
**Resultado:** Se utilizan dos streams: `events` (agente → backend) y `commands` (backend → agente).
**Excepciones:** Si Valkey no está disponible, aplican las reglas de resiliencia offline (RN-38 a RN-42).

### RN-56: Stream de eventos (agente → backend)
**Descripción:** El agente publica eventos detectados en el stream `events`.
**Condición:** El agente detecta un cambio y genera un evento.
**Resultado:** El evento se publica en el stream `events` de Valkey. El backend lo consume y persiste en PostgreSQL.
**Excepciones:** Si Valkey no está disponible, el evento se encola localmente (RN-38).

### RN-57: Stream de comandos (backend → agente)
**Descripción:** El backend publica comandos para el agente en el stream `commands`.
**Condición:** El backend necesita instruir al agente (aprobación, rechazo, re-scan).
**Resultado:** Se publica un comando en el stream. Los comandos válidos son: `baseline_update`, `restore_file`, `quarantine_file`, `rescan_baseline`.
**Excepciones:** Ninguna.

### RN-58: Sincronización de reglas al agente
**Descripción:** Las reglas de decisión definidas en el backend se sincronizan al agente via Valkey.
**Condición:** Se crean, modifican o eliminan reglas en el backend.
**Resultado:** El agente recibe el conjunto actualizado de reglas y reemplaza su cache local.
**Excepciones:** Si el agente está offline, aplica las reglas cacheadas hasta la próxima sincronización.

### RN-59: Sincronización de baseline tras aprobación
**Descripción:** Tras aprobar un evento, el nuevo baseline se sincroniza al agente.
**Condición:** Admin aprueba un evento y se genera nuevo baseline.
**Resultado:** El backend envía un comando `baseline_update` con el hash actualizado. El agente actualiza su baseline local para ese path.
**Excepciones:** Si el agente está offline, la actualización se procesa al reconectar.

---

## 14. Seguridad avanzada

### RN-60: Aprobación de archivo ausente
**Descripción:** El admin puede aprobar un evento pending cuyo archivo ya no existe en el filesystem.
**Condición:** Admin aprueba un evento pero el archivo fue eliminado entre detección y aprobación.
**Resultado:** El frontend muestra un warning explícito. Si el admin confirma, el baseline registra el path con `status: "absent"` y `hash: null`. El agente trata la creación futura de ese archivo como anomalía.
**Excepciones:** Si el admin cancela, el evento permanece en `pending`.

### RN-61: Hashing de contraseñas con Argon2id
**Descripción:** Todas las contraseñas de usuario se hashean con Argon2id.
**Condición:** Al crear o modificar la contraseña de un usuario.
**Resultado:** Se utiliza `argon2-cffi` con Argon2id (ganador de la Password Hashing Competition). Configurable en memoria, iteraciones y paralelismo. Recomendación actual de OWASP.
**Excepciones:** Ninguna. No se aceptan otros algoritmos de hashing.

### RN-62: Creación del primer admin por seed
**Descripción:** El primer usuario admin se crea automáticamente al inicializar la base de datos.
**Condición:** La base de datos se inicializa y no existe ningún usuario.
**Resultado:** Se crea un usuario admin con las credenciales definidas en variables de entorno (`ADMIN_USERNAME`, `ADMIN_PASSWORD`). El password se hashea con Argon2id.
**Excepciones:** Si ya existe al menos un usuario, el seed no se ejecuta.

### RN-63: Autenticación del agente via mTLS
**Descripción:** El agente se autentica con el backend mediante mTLS (mutual TLS).
**Condición:** Toda comunicación entre agente y backend.
**Resultado:** Ambos presentan certificados TLS y verifican contra una CA compartida. No se utilizan API keys ni secretos en plaintext.
**Excepciones:** Ninguna. La conexión se rechaza si el certificado no es válido.

### RN-64: Ventajas de mTLS sobre API keys
**Descripción:** mTLS provee garantías de seguridad superiores a API keys.
**Condición:** Siempre (decisión de diseño).
**Resultado:** Sin secretos en plaintext, resistente a replay attacks, identificación criptográfica, certificados revocables sin rotación de passwords.
**Excepciones:** Ninguna.

### RN-65: Patrones glob con negación
**Descripción:** Las reglas de monitoreo soportan patrones glob con negación usando prefijo `!`.
**Condición:** Al evaluar reglas contra un path modificado.
**Resultado:** Las reglas con `!` excluyen paths del match de reglas más amplias. Si un path matchea una regla inclusiva y una exclusiva, la exclusiva gana. Si no matchea ninguna regla, se aplica `alert_only` (RN-06).
**Excepciones:** Ninguna.

### RN-66: Baseline con estado "absent"
**Descripción:** El baseline puede registrar que un archivo NO debe existir.
**Condición:** Admin aprueba la eliminación de un archivo (RN-60).
**Resultado:** El baseline almacena `{ path, status: "absent", hash: null }`. Si el archivo se crea en el futuro, el agente lo detecta como anomalía.
**Excepciones:** Ninguna.

### RN-67: Base de datos separada para N8N
**Descripción:** N8N utiliza la misma instancia de PostgreSQL pero una base de datos separada.
**Condición:** Configuración de infraestructura.
**Resultado:** Se crean dos bases de datos en el mismo servidor PostgreSQL: `fim` (aplicación) y `fim_n8n` (N8N). Un script de inicialización (`docker-entrypoint-initdb.d`) crea ambas al arrancar.
**Excepciones:** Ninguna.

---

## 15. Configuración del agente

### RN-68: Configuración inicial via .env
**Descripción:** La configuración inicial del agente proviene de variables de entorno.
**Condición:** Primer arranque del agente.
**Resultado:** El agente lee `WATCH_PATHS`, `VALKEY_URL`, `AGENT_ID` desde el `.env` del contenedor. Estos valores definen el estado de bootstrap.
**Excepciones:** Ninguna.

### RN-69: Gestión de paths en runtime desde frontend
**Descripción:** El admin puede agregar o quitar paths monitoreados desde el frontend sin reiniciar el agente.
**Condición:** Admin modifica la configuración de paths desde la sección de Agentes.
**Resultado:** El backend persiste la nueva configuración en PostgreSQL y envía un comando `update_config` via Valkey. El agente recarga los paths sin reinicio. Para paths nuevos, ejecuta baseline scan automáticamente.
**Excepciones:** Parámetros como `VALKEY_URL` o `AGENT_ID` solo se configuran via `.env` y requieren reinicio.

### RN-70: Confirmación previa al re-scan
**Descripción:** El re-scan requiere confirmación explícita del admin cuando existen eventos pending.
**Condición:** Admin solicita re-scan para paths que tienen eventos en estado `pending`.
**Resultado:** El frontend lista los eventos pending que serán marcados como `superseded` y solicita confirmación. Solo al confirmar se ejecuta el re-scan.
**Excepciones:** Si no hay eventos pending para los paths seleccionados, el re-scan se ejecuta sin confirmación adicional.

---

> **Nota:** Este documento refleja las decisiones de diseño tomadas para el MVP. Las reglas pueden evolucionar conforme avance la implementación. Todo cambio debe documentarse y trazarse a la decisión que lo motivó.
