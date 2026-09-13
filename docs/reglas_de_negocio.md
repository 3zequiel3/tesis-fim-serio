# Reglas de Negocio — Plataforma FIM

> Última actualización: 23 de abril de 2026
> Estado: Documentación de diseño detallado — sin implementación. La construcción del código y la ejecución del protocolo experimental se proyectan para la fase inmediata siguiente y se entregarán en una adenda formal.
>
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
| Apx | [Decisiones de auditoría — Abril 2026](#appendix-decisiones-de-auditoría--abril-2026) | RN-71 a RN-100 |
| 16 | [Observabilidad y degradación](#16-observabilidad-y-degradación-dominio-nuevo) | RN-101 a RN-103 |
| Apx | [Decisiones de implementación — Abril 2026](#appendix-decisiones-de-implementación--abril-2026) | RN-104 a RN-146 |

---

## 1. Detección y monitoreo

### RN-01: Detección de cambios en tiempo real
**Descripción:** El agente detecta cambios en el filesystem mediante un backend propio sobre el subsistema `fanotify` del núcleo Linux (kernel ≥ 5.1), implementado en `agent/_fanotify.py` con `ctypes` sobre syscalls crudas y operando en **modo FID** (`FAN_REPORT_DFID_NAME`). No se depende de `pyfanotify` — ver D46/RN-140, que explica por qué el modo fd clásico no puede entregar las máscaras que RN-110 exige.
**Condición:** El agente está en ejecución como servicio nativo de `systemd` y monitoreando los paths configurados.
**Resultado:** Se genera un evento de cambio con metadata: path, tipo de operación, timestamp del agente (`detected_at`), hash SHA-256 del contenido, **y contexto del proceso causante** (PID, UID, path del ejecutable).
**Excepciones:** Los paths excluidos por configuración no generan eventos. Los directorios del propio agente (`/var/lib/fim-agent/**`) deben estar excluidos para evitar recursión.

### RN-02: Limitación de captura pre-escritura
**Descripción:** En el modo de operación adoptado (notificación pura), `fanotify` notifica *después* de que la escritura se persiste en el filesystem.
**Condición:** Siempre. `fanotify` ofrece modos de permisos que permiten inspeccionar antes de la escritura, pero esos modos no se utilizan en el MVP por su impacto en rendimiento.
**Resultado:** Solo se detecta el cambio posterior a la escritura. El estado previo se obtiene del baseline cifrado almacenado por el agente.
**Excepciones:** Ninguna en el MVP. La protección pre-escritura queda en trabajo futuro mediante integración con IMA y dm-verity.

### RN-03: Diferencias solo para archivos de texto
**Descripción:** El cálculo de diffs (diferencias línea a línea) solo se realiza para archivos de texto.
**Condición:** El archivo detectado es de tipo texto plano (determinado por heurística o extensión).
**Resultado:** Se genera un diff legible entre el baseline y el archivo modificado.
**Excepciones:** Archivos binarios no generan diff textual. En su lugar, el frontend muestra comparación de hashes y hex dump parcial (primeros N bytes, lado a lado).

### RN-04: Monitoreo basado en paths configurados
**Descripción:** El agente monitorea únicamente los directorios y archivos definidos en su configuración.
**Condición:** Al iniciar el agente o al recibir un comando `update_config` con la lista actualizada de paths.
**Resultado:** Solo los paths incluidos en la configuración generan eventos. Todo lo demás se ignora. El agente reconfigura los watchers de `fanotify` en caliente sin reiniciar el proceso.
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
**Resultado:** El evento se registra para auditoría sin ninguna acción automática sobre el filesystem.
**Excepciones:** Ninguna.

### RN-07: Tipos de acción válidos
**Descripción:** El motor de decisión soporta exactamente 4 tipos de acción.
**Condición:** Al definir o ejecutar una regla.
**Resultado:** La acción debe ser una de: `auto_restore`, `quarantine`, `manual_review`, `alert_only`.
**Excepciones:** Cualquier otro valor es rechazado como inválido.

### RN-08: Estructura de una regla
**Descripción:** Cada regla tiene tres componentes obligatorios: pattern, severity y action.
**Condición:** Al crear o actualizar una regla en el backend.
**Resultado:** `pattern` es un glob que define qué paths afecta (con soporte de negación `!`), `severity` es uno de `critical | high | medium | low`, `action` es uno de los 4 tipos válidos (RN-07).
**Excepciones:** Ninguna.

### RN-09: Las reglas se definen en el backend
**Descripción:** La definición y gestión de reglas es responsabilidad exclusiva del backend.
**Condición:** Siempre.
**Resultado:** El agente recibe las reglas vía sincronización (Valkey Streams, comando firmado HMAC con `ruleset_version` monotónico — ver RN-75 y RN-79) y las cachea localmente. El agente nunca crea ni modifica reglas.
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
**Excepciones:** Ninguna otra transición desde `pending` es válida. (Ver RN-72 para máquina de estados completa.)

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
**Condición:** El agente arranca por primera vez (o no existe baseline previo para un path agregado en runtime).
**Resultado:** Se realiza un escaneo completo de todos los paths monitoreados, registrando hash SHA-256 y metadata de cada archivo. El contenido completo se cifra con AES-256-GCM (ver RN-82). Este conjunto constituye el baseline inicial.
**Excepciones:** Ninguna.

### RN-16: Actualización del baseline solo por aprobación
**Descripción:** El baseline se actualiza ÚNICAMENTE cuando un administrador aprueba un cambio o cuando se ejecuta un re-scan explícito.
**Condición:** Un admin ejecuta la acción de aprobación sobre un evento `pending`, o dispara un re-scan (RN-18).
**Resultado:** Se hashea el archivo en su estado ACTUAL (no el hash del evento) y se registra como nuevo baseline para ese path.
**Excepciones:** Ninguna. Las acciones `auto_restore`, `quarantine`, `reject` y `alert_only` NO actualizan el baseline.

### RN-17: Hash del archivo actual al aprobar
**Descripción:** Al aprobar un cambio, el baseline se actualiza con el hash del archivo tal como está en el momento de la aprobación, no con el hash registrado en el evento.
**Condición:** Admin aprueba un evento.
**Resultado:** El backend consulta al agente el hash actual del archivo, lo registra como baseline, y publica el `baseline_update` firmado con HMAC y `ruleset_version++` (ver RN-75, RN-79). El agente actualiza su baseline local re-cifrado con AES-256-GCM (RN-82).
**Excepciones:** Si el archivo no existe al momento de la aprobación (fue eliminado entre detección y aprobación), el frontend muestra un warning y el admin puede aprobar la ausencia como nuevo estado válido del baseline (ver RN-60).

### RN-18: Re-scan manual
**Descripción:** El frontend permite iniciar un re-scan manual del baseline para paths seleccionados.
**Condición:** El admin solicita un re-scan desde la interfaz (caso de uso: post-deploy masivo).
**Resultado:** Antes de ejecutar, el frontend muestra un warning listando los eventos `pending` que serán marcados como `superseded` para los paths seleccionados. El admin debe confirmar. Al confirmar, los eventos pending se marcan como `superseded` y el backend envía un comando `rescan_baseline` firmado con HMAC al agente vía Valkey, con `ruleset_version++`.
**Excepciones:** Si el admin cancela la confirmación, el re-scan no se ejecuta.

### RN-19: Protección del baseline mediante cifrado autenticado
**Descripción:** El baseline almacenado localmente se protege mediante cifrado autenticado AES-256-GCM, que provee tanto confidencialidad como integridad.
**Condición:** Siempre que se lee o escribe el baseline local.
**Resultado:** Al escribir, el archivo se cifra con AES-256-GCM (la etiqueta GCM autentica el contenido). Al leer, el descifrado verifica automáticamente la autenticidad: si el archivo cifrado fue alterado, el descifrado falla y se reporta un incidente de integridad.
**Excepciones:** Ninguna. Esta regla reemplaza al uso de HMAC sobre baseline en plaintext: AES-GCM provee la garantía de integridad de forma integrada al cifrado, sin necesidad de un mecanismo HMAC separado. Ver RN-82 para detalles del esquema de derivación de clave.

### RN-20: Permisos restringidos del baseline
**Descripción:** Los archivos de baseline tienen permisos restringidos en el filesystem.
**Condición:** Siempre.
**Resultado:** Archivos cifrados del baseline en `/var/lib/fim-agent/baseline/` con permisos `0600`, owner `fim-agent`. El `master_secret` para derivación de clave en `/var/lib/fim-agent/secrets/master_secret` con permisos `0400`. Los directorios del agente quedan excluidos del propio FIM mediante un patrón `!/var/lib/fim-agent/**` obligatorio.
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
**Resultado:** Los eventos `superseded` permanecen como historial de auditoría. Solo el último evento (no superseded) aparece como accionable en la interfaz. Por defecto los `superseded` están ocultos en la vista (ver RN-98).
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
**Resultado:** 1) Se aplica UPDATE optimista (ver RN-77); 2) se hashea el archivo ACTUAL en disco (consultado al agente); 3) se genera nuevo registro de baseline; 4) se publica comando `baseline_update` firmado con HMAC y `ruleset_version++` al stream `commands` de Valkey; 5) el agente verifica firma, verifica versión, actualiza baseline local re-cifrado con AES-GCM y confirma vía `event_ack`; 6) el evento transiciona a `approved`; 7) la operación se registra en `audit_log` (RN-94).
**Excepciones:** Si el UPDATE optimista afecta 0 filas, se retorna HTTP 409 (ver RN-77). Si el archivo ya no existe, el sistema muestra warning al admin y el baseline puede registrar el path como `absent` (ver RN-60).

### RN-26: Flujo de rechazo
**Descripción:** Al rechazar un evento, el admin elige entre restaurar o poner en cuarentena.
**Condición:** Admin rechaza un evento en estado `pending`.
**Resultado:** 1) Se aplica UPDATE optimista (RN-77); 2) el evento transiciona a `rejected`; 3) el backend publica el comando correspondiente (`restore_file` o `quarantine_file`) firmado con HMAC y `ruleset_version++`; 4) el agente escribe journal pre-acción (RN-83), ejecuta la acción y actualiza el journal; 5) el baseline NO se actualiza; 6) la operación se registra en `audit_log` (RN-94).
**Excepciones:** Si el baseline está en `status: absent`, no se publica comando al agente (ver RN-74).

### RN-27: Rechazo no actualiza baseline
**Descripción:** El rechazo de un evento nunca modifica el baseline existente.
**Condición:** Admin rechaza un evento.
**Resultado:** El baseline permanece intacto. El objetivo es que el archivo vuelva a su estado original (vía restauración o cuarentena).
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
**Excepciones:** Ninguna. No existe otro rol en el sistema (ver RN-44).

---

## 7. Restauración automática

### RN-30: Restauración automática por configuración de regla
**Descripción:** La acción `auto_restore` se ejecuta cuando la regla matcheada tiene esa acción configurada explícitamente, independientemente de la severidad.
**Condición:** Se detecta un cambio y la regla matcheada tiene `action: auto_restore`.
**Resultado:** El agente restaura el archivo desde el baseline (descifrando con AES-GCM). El uso típico — pero no exclusivo — es para reglas con `severity: critical`.
**Excepciones:** Si no existe baseline para el archivo (primera detección sin baseline previo), no se puede restaurar; se reporta error.

### RN-31: Restauración desde baseline completo
**Descripción:** La restauración automática utiliza la copia completa del archivo desde el baseline cifrado, no un diff.
**Condición:** Se ejecuta una acción `auto_restore`.
**Resultado:** El agente descifra el archivo del baseline (AES-256-GCM), lo escribe sobre el filesystem reemplazando completamente el contenido modificado.
**Excepciones:** Ninguna.

### RN-32: Verificación post-restauración
**Descripción:** Después de restaurar un archivo, el agente verifica que la restauración fue exitosa.
**Condición:** Se completó una restauración (automática o por rechazo).
**Resultado:** Se calcula el hash SHA-256 del archivo restaurado y se compara con el hash del baseline. Si coincide, la restauración fue exitosa y el journal se actualiza a `state: completed`. Si no, se reporta error y se actualiza a `state: failed` con detalles.
**Excepciones:** Ninguna.

### RN-33: Restauración no actualiza baseline
**Descripción:** Una restauración automática no genera una actualización de baseline.
**Condición:** Se ejecuta `auto_restore`.
**Resultado:** El baseline permanece intacto (ya contiene el hash correcto, que es el mismo del archivo restaurado). El evento se crea con estado `auto_restored`.
**Excepciones:** Ninguna.

---

## 8. Cuarentena

### RN-34: Destino de archivos en cuarentena
**Descripción:** Los archivos puestos en cuarentena se conservan como artefactos cifrados en un directorio dedicado del agente.
**Condición:** Se ejecuta una acción `quarantine` (automática o por rechazo).
**Resultado:** Se crea y verifica un artefacto AES-256-GCM en `/var/lib/fim-agent/quarantine/`; recién después se retira la entrada de origen.
**Excepciones:** Ninguna.

### RN-35: Renombrado de archivo en cuarentena
**Descripción:** Los artefactos usan identificadores opacos y determinísticos para evitar colisiones sin filtrar la ruta original.
**Condición:** Se mueve un archivo a cuarentena.
**Resultado:** El nombre deriva de la identidad de acción y ruta; contenido, ruta, hash y metadatos quedan autenticados y cifrados.
**Excepciones:** Ninguna.

La clave de cuarentena se deriva desde `master_secret` mediante HKDF-SHA256 con dominio `quarantine-v1`; no reutiliza la clave `baseline-v1`. Esto protege una copia aislada de la cuarentena sin el directorio de secretos. No protege una adquisición que incluya `master_secret`, al usuario `root`, la memoria del proceso ni un host activo comprometido.

### RN-36: Permisos restringidos en cuarentena
**Descripción:** Los archivos en cuarentena tienen permisos restringidos.
**Condición:** Un archivo se coloca en cuarentena.
**Resultado:** Permisos `0400`, owner `fim-agent`. No se permite escritura ni ejecución.
**Excepciones:** Ninguna.

### RN-37: Cuarentena no actualiza baseline
**Descripción:** Poner un archivo en cuarentena no modifica el baseline.
**Condición:** Se ejecuta `quarantine`.
**Resultado:** El baseline permanece intacto. El evento se crea con estado `quarantined`.
**Excepciones:** Ninguna.

### RN-37a: Retención y migración local de cuarentena
**Descripción:** La cuarentena cifrada tiene retención local configurable y migra los dos formatos históricos en texto plano.
**Condición:** Al arrancar el agente y cada 24 horas.
**Resultado:** Primero se migran de forma atómica e idempotente los nombres históricos `{event_id}_{basename}` y `{basename}.{YYYYMMDDTHHMMSS}` a artefactos cifrados; luego se eliminan únicamente artefactos autenticados cuya antigüedad alcanzó `quarantine_retention_days` (30 días por defecto, rango 1–365). El inventario agregado informa migrados, omitidos, fallidos y pendientes sin registrar nombres ni rutas.
**Excepciones:** Artefactos corruptos o no autenticables y formatos legacy desconocidos se conservan, producen estado degradado y requieren revisión. Los hardlinks legacy se rechazan; los symlinks se migran como target textual sin seguirlos. Los dos nombres históricos sólo conservaron el basename, no el directorio original: la migración marca `original_path_known: false` y no inventa un destino de restauración. El formato automático tampoco registró una fecha; para retención se conserva el `ctime` local disponible como aproximación explícita. Esta política no constituye borrado seguro del soporte ni validación productiva.

---

## 9. Resiliencia y offline

### RN-38: Cola local cuando agente está offline
**Descripción:** Si el agente no puede conectarse al backend (Valkey no disponible), los eventos se encolan localmente.
**Condición:** El agente detecta un cambio pero no puede enviar el evento al backend.
**Resultado:** El evento se almacena en archivos JSON en `/var/lib/fim-agent/queue/` con escritura atómica (`write + rename`) y nombre `{timestamp}_{event_id_uuid}.json`.
**Excepciones:** Ninguna. La cola tiene límite de tamaño y política definidos en RN-84.

### RN-39: Envío FIFO al reconectar
**Descripción:** Al restablecerse la conexión, los eventos encolados se envían en orden FIFO.
**Condición:** El agente recupera la conexión con Valkey.
**Resultado:** Los eventos se envían en el orden en que fueron creados (primero en entrar, primero en salir). El procesamiento de comandos pendientes ocurre antes (ver RN-85).
**Excepciones:** Ninguna.

### RN-40: Eliminación de cola tras confirmación bidireccional
**Descripción:** Los archivos JSON de la cola local se eliminan solo después de la confirmación end-to-end del backend (XACK + `event_ack`).
**Condición:** El backend confirma la recepción y persistencia del evento mediante `event_ack` publicado en el stream `commands` (ver RN-73).
**Resultado:** El archivo JSON correspondiente se elimina del disco local solo al recibir `event_ack`.
**Excepciones:** Si el `event_ack` no llega en 60 s, el agente reintenta la publicación (deduplicado por `event_id` en backend).

### RN-41: Cola offline sin transaccionalidad
**Descripción:** La cola local no ofrece garantías transaccionales (no es ACID).
**Condición:** Siempre (limitación técnica documentada).
**Resultado:** En caso de crash del agente durante escritura de la cola, puede haber eventos parcialmente escritos. La escritura atómica `write + rename` mitiga el problema pero no lo elimina por completo.
**Excepciones:** Ninguna. Es una limitación aceptada.

### RN-42: Acciones automáticas durante offline
**Descripción:** El agente ejecuta acciones automáticas (auto_restore, quarantine) incluso sin conexión al backend.
**Condición:** El agente está offline pero detecta un cambio que matchea una regla con acción automática.
**Resultado:** La acción se ejecuta localmente usando las reglas cacheadas y el baseline cifrado local. El evento resultante se encola para envío posterior.
**Excepciones:** Si las reglas cacheadas están desactualizadas respecto al backend, se opera con la versión local; al reconectar, los comandos pendientes se aplican primero (RN-85).

---

## 10. Autenticación y autorización

### RN-43: Autenticación JWT stateless
**Descripción:** La autenticación se implementa mediante JWT stateless con par de tokens.
**Condición:** Para toda operación autenticada del admin.
**Resultado:** Se emite un `access_token` (15 min) y un `refresh_token` (7 días con rotación). El servidor no mantiene estado de sesión, salvo la blacklist de `jti` revocados (ver RN-80).
**Excepciones:** Ninguna.

### RN-44: Rol único — admin
**Descripción:** El sistema tiene un único rol: admin.
**Condición:** Siempre.
**Resultado:** Todo usuario autenticado es admin. No existe jerarquía de roles ni permisos granulares.
**Excepciones:** Ninguna.

### RN-45: Sin registro público de usuarios
**Descripción:** No existe un endpoint de registro público. Los usuarios se crean administrativamente.
**Condición:** Siempre.
**Resultado:** El primer admin se crea automáticamente como seed al inicializar la base de datos (credenciales desde variables de entorno, password hasheado con Argon2id — ver RN-81). El primer login fuerza cambio de password (ver RN-100). Admins adicionales pueden ser creados desde la interfaz por un admin existente.
**Excepciones:** Ninguna.

### RN-46: Refresh token para renovación de sesión
**Descripción:** La renovación de sesión se realiza exclusivamente mediante el refresh token.
**Condición:** El access token expiró.
**Resultado:** El cliente presenta el refresh token para obtener un nuevo par. El refresh token rota en cada uso (el anterior se invalida — ver RN-80). Si el refresh token expiró o fue revocado, se requiere nuevo login.
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
**Resultado:** El snapshot anterior se comprime con gzip antes del cifrado AES-GCM, para ahorrar espacio en disco.
**Excepciones:** El snapshot activo (más reciente) permanece sin comprimir para acceso rápido.

### RN-49: Deduplicación por hash
**Descripción:** No se almacena un nuevo snapshot si el hash del archivo es idéntico al último snapshot almacenado.
**Condición:** Se genera un cambio detectado.
**Resultado:** Se compara el hash del archivo actual con el hash del último snapshot. Si son iguales, no se crea un nuevo snapshot.
**Excepciones:** Ninguna.

### RN-50: Protección de baseline mediante cifrado autenticado
**Descripción:** Los archivos de baseline se protegen con AES-256-GCM, que provee confidencialidad e integridad de forma integrada.
**Condición:** Al leer o escribir archivos de baseline.
**Resultado:** Escritura: el contenido se cifra con AES-256-GCM (clave derivada por HKDF-SHA256, ver RN-82); la etiqueta GCM autentica el ciphertext. Lectura: el descifrado verifica la etiqueta automáticamente; si el archivo fue alterado en disco, el descifrado falla y se reporta como incidente de seguridad.
**Excepciones:** Ninguna. Esta regla absorbe lo que en versiones anteriores se especificaba como "HMAC sobre baseline plaintext"; AES-GCM provee la garantía equivalente en una sola operación criptográfica.

### RN-51: Permisos restringidos en almacenamiento
**Descripción:** Los directorios de baseline, snapshots, cola, journal y secretos del agente tienen permisos restringidos.
**Condición:** Siempre.
**Resultado:** `/var/lib/fim-agent/{baseline,quarantine,queue,journal}/` con permisos `0700`, owner `fim-agent`. `/var/lib/fim-agent/secrets/{master_secret,shared_secret}` con permisos `0400`. `/var/lib/fim-agent/certs/` con permisos `0600`. Ningún otro usuario del sistema tiene acceso. Adicionalmente, el servicio `systemd` aplica `ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`, y `ReadWritePaths` **derivado** de los `watch_paths` configurados vía un drop-in generado por `install.sh` (`D36/RN-130`) — no una lista fija en el unit base. El proceso del servicio corre con `AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN` (D36/RN-130), necesarias para que `auto_restore`/`quarantine` (RN-30 a RN-37) puedan escribir sobre los `watch_paths` remediables. `/opt/fim-agent` y `/etc/fim-agent` son propiedad de `root` (legibles por el grupo `fim-agent`); solo `/var/lib/fim-agent` y `/var/log/fim-agent` pertenecen al usuario del servicio — el proceso, no el uid, sostiene las capabilities.
**Excepciones:** Ninguna. Ver D36/RN-130 en el appendix "Decisiones de implementación — Abril 2026" para el detalle completo del modelo de capabilities, el preflight de escritura y la limitación conocida de los `watch_paths` agregados en runtime.

---

## 12. Notificaciones

### RN-52: Notificaciones vía n8n con cascada de fallbacks
**Descripción:** Las notificaciones del sistema se canalizan principalmente a través de n8n como **enrutador acotado**, con cascada de fallbacks automáticos para garantizar entrega.
**Condición:** Se produce un evento que requiere notificación.
**Resultado:** El backend dispara un webhook a n8n. Si falla los 3 intentos del retry exponencial (ver RN-86), se aplica cascada de fallbacks: SMTP directo → webhook directo pre-configurado → log crítico → tabla `failed_notifications` con banner UI persistente.
**Excepciones:** n8n está delimitado al rol de **enrutador de notificaciones externas**: no ejecuta comandos sobre el sistema operativo del anfitrión monitoreado, no coordina el playbook ni toma decisiones. La indisponibilidad de n8n no compromete la operación del sistema gracias a los fallbacks.

### RN-53: Eventos que disparan notificación
**Descripción:** Se generan notificaciones para eventos que requieren atención o representan un riesgo.
**Condición:** Se crea un evento con severidad `critical` o `high` en cualquier estado, o cuando el sistema cambia de estado de salud (ver RN-87).
**Resultado:** Se dispara una notificación con la información del evento: `event_id`, path, severidad, acción tomada, contexto del proceso causante (`process_pid`, `process_uid`, `process_exe`), timestamps (`detected_at`, `received_at`).
**Excepciones:** Los eventos `superseded` no generan notificación. Los `alert_only` con severidad baja pueden no generar notificación dependiendo de la configuración.

### RN-54: Notificaciones no bloquean el flujo principal
**Descripción:** El envío de notificaciones es asíncrono y no bloquea el procesamiento de eventos.
**Condición:** Siempre.
**Resultado:** Si el envío falla, el evento se procesa normalmente. La notificación entra a la cascada de fallbacks (RN-52) y si todos fallan, se persiste en `failed_notifications` para reintento manual.
**Excepciones:** Ninguna.

---

## 13. Sincronización

### RN-55: Comunicación bidireccional vía Valkey Streams
**Descripción:** La comunicación entre agente y backend es bidireccional a través de Valkey Streams.
**Condición:** Siempre que agente y backend necesitan intercambiar información.
**Resultado:** Se utilizan tres streams: `events` (agente → backend), `commands` (backend → agente), `agent_heartbeat` (agente → backend). Toda la comunicación viaja sobre el canal mTLS establecido en bootstrap (ver RN-78).
**Excepciones:** Si Valkey no está disponible, aplican las reglas de resiliencia offline (RN-38 a RN-42).

### RN-56: Stream de eventos (agente → backend)
**Descripción:** El agente publica eventos detectados en el stream `events`.
**Condición:** El agente detecta un cambio y genera un evento.
**Resultado:** El evento se publica con: `event_id` UUID v4, `detected_at`, `schema_version`, payload de datos del cambio (path, hashes, contexto del proceso causante PID/UID/exe). El backend lo consume con consumer group `fim-backend` y persiste en PostgreSQL.
**Excepciones:** Si Valkey no está disponible, el evento se encola localmente (RN-38).

### RN-57: Stream de comandos (backend → agente)
**Descripción:** El backend publica comandos firmados para el agente en el stream `commands`.
**Condición:** El backend necesita instruir al agente (aprobación, rechazo, re-scan, sincronización de reglas, actualización de configuración, ack de eventos).
**Resultado:** Se publica un comando con `signature` HMAC-SHA256 (ver RN-79) y `ruleset_version` monotónico (RN-75). Comandos válidos: `baseline_update`, `restore_file`, `quarantine_file`, `rescan_baseline`, `rule_sync`, `update_config`, `event_ack`.
**Excepciones:** Ninguna.

### RN-58: Sincronización de reglas al agente
**Descripción:** Las reglas de decisión definidas en el backend se sincronizan al agente vía Valkey con firma HMAC y `ruleset_version`.
**Condición:** Se crean, modifican o eliminan reglas en el backend.
**Resultado:** El backend incrementa `ruleset_version`, firma el comando `rule_sync` con HMAC y lo publica. El agente verifica firma y versión, reemplaza su cache local, persiste el nuevo `ruleset_version` aplicado en `/var/lib/fim-agent/state.json`, y confirma vía `event_ack`.
**Excepciones:** Si el agente está offline, aplica las reglas cacheadas hasta la próxima sincronización; al reconectar procesa los comandos pendientes antes que los eventos encolados (RN-85).

### RN-59: Sincronización de baseline tras aprobación
**Descripción:** Tras aprobar un evento, el nuevo baseline se sincroniza al agente.
**Condición:** Admin aprueba un evento y se genera nuevo baseline.
**Resultado:** El backend envía un comando `baseline_update` firmado con HMAC y `ruleset_version++` que incluye el path y el hash actualizado. El agente verifica, actualiza su baseline local re-cifrado con AES-GCM y confirma vía `event_ack`.
**Excepciones:** Si el agente está offline, la actualización se procesa al reconectar.

---

## 14. Seguridad avanzada

### RN-60: Aprobación de archivo ausente
**Descripción:** El admin puede aprobar un evento pending cuyo archivo ya no existe en el filesystem.
**Condición:** Admin aprueba un evento pero el archivo fue eliminado entre detección y aprobación.
**Resultado:** El frontend muestra un warning explícito. Si el admin confirma, el baseline registra el path con `status: "absent"` y `hash: null`. El agente trata la creación futura de ese archivo como anomalía.
**Excepciones:** Si el admin cancela, el evento permanece en `pending`. El rechazo sobre baseline absent es no-op (ver RN-74).

### RN-61: Hashing de contraseñas con Argon2id
**Descripción:** Todas las contraseñas de usuario se hashean con Argon2id.
**Condición:** Al crear o modificar la contraseña de un usuario.
**Resultado:** Se utiliza `argon2-cffi` con Argon2id (ganador de la Password Hashing Competition) con parámetros explícitos: `time_cost=3, memory_cost=65536, parallelism=4` (RN-81). Recomendación OWASP 2026.
**Excepciones:** Ninguna. No se aceptan otros algoritmos de hashing.

### RN-62: Creación del primer admin por seed
**Descripción:** El primer usuario admin se crea automáticamente al inicializar la base de datos.
**Condición:** La base de datos se inicializa y no existe ningún usuario.
**Resultado:** Se crea un usuario admin con las credenciales definidas en variables de entorno (`ADMIN_USERNAME`, `ADMIN_PASSWORD`). El password se hashea con Argon2id. El usuario se marca con `must_change_password: true` (ver RN-100).
**Excepciones:** Si ya existe al menos un usuario, el seed no se ejecuta.

### RN-63: Autenticación del agente vía mTLS
**Descripción:** El agente se autentica con el backend mediante mTLS (mutual TLS).
**Condición:** Toda comunicación entre agente y backend.
**Resultado:** Ambos presentan certificados TLS y verifican contra una CA propia operada por el backend (ver RN-78). No se utilizan API keys ni secretos en plaintext.
**Excepciones:** Ninguna. La conexión se rechaza si el certificado no es válido o está revocado.

### RN-64: Ventajas de mTLS sobre API keys
**Descripción:** mTLS provee garantías de seguridad superiores a API keys.
**Condición:** Siempre (decisión de diseño).
**Resultado:** Sin secretos en plaintext, resistente a replay attacks (cada handshake TLS es único), identificación criptográfica del agente, certificados revocables sin rotación de passwords.
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

### RN-67: Base de datos separada para n8n
**Descripción:** n8n utiliza la misma instancia de PostgreSQL pero una base de datos separada.
**Condición:** Configuración de infraestructura.
**Resultado:** Se crean dos bases de datos en el mismo servidor PostgreSQL: `fim` (aplicación) y `fim_n8n` (n8n). Un script de inicialización (`docker-entrypoint-initdb.d`) crea ambas al arrancar.
**Excepciones:** Ninguna.

---

## 15. Configuración del agente

### RN-68: Configuración inicial vía archivo local
**Descripción:** La configuración inicial del agente proviene de un archivo local en el anfitrión.
**Condición:** Primer arranque del agente como servicio nativo de `systemd`.
**Resultado:** El agente lee `agent_id`, `valkey_url`, `ca_cert_path`, lista inicial de `watch_paths` y rutas de almacenamiento desde `/etc/fim-agent/config.yaml`. Estos valores definen el estado de bootstrap.
**Excepciones:** El agente NO se ejecuta dentro de un contenedor Docker porque `fanotify` requiere la capability `CAP_SYS_ADMIN`, incompatible con el aislamiento estándar de contenedores. Se despliega como servicio nativo con hardening por `systemd` (ver RN-51).

### RN-69: Gestión de paths en runtime desde frontend
**Descripción:** El admin puede agregar o quitar paths monitoreados desde el frontend sin reiniciar el agente.
**Condición:** Admin modifica la configuración de paths desde la sección de Agentes.
**Resultado:** El backend persiste la nueva configuración en PostgreSQL como fuente autoritativa, incrementa `ruleset_version`, firma el comando `update_config` con HMAC y lo publica vía Valkey. El agente verifica firma y versión, recarga los paths reconfigurando los watchers de `fanotify` en caliente. Para paths nuevos, ejecuta baseline scan automáticamente y cifra las entradas con AES-GCM. A partir del primer arranque, la configuración autoritativa vive en PostgreSQL — `config.yaml` es solo el bootstrap.
**Excepciones:** Parámetros como `valkey_url`, `agent_id` o `ca_cert_path` solo se configuran vía archivo local y requieren reinicio del servicio.

### RN-70: Confirmación previa al re-scan
**Descripción:** El re-scan requiere confirmación explícita del admin cuando existen eventos pending.
**Condición:** Admin solicita re-scan para paths que tienen eventos en estado `pending`.
**Resultado:** El frontend lista los eventos pending que serán marcados como `superseded` y solicita confirmación. Solo al confirmar se ejecuta el re-scan.
**Excepciones:** Si no hay eventos pending para los paths seleccionados, el re-scan se ejecuta sin confirmación adicional.

---

> **Nota:** Este documento refleja las decisiones de diseño tomadas para el MVP en fase de diseño detallado. Las reglas pueden evolucionar conforme avance la implementación. Todo cambio debe documentarse y trazarse a la decisión que lo motivó.

---

## Appendix: Decisiones de auditoría — Abril 2026

Las siguientes decisiones resultan de la auditoría de consistencia, lifecycle, seguridad y resiliencia realizada el 2026-04-22. En caso de conflicto con reglas previas (RN-01 a RN-70), prevalece lo especificado en este appendix.

### Léxico y nomenclatura

#### C1 / RN-71: Léxico canónico en minúsculas
**Descripción:** Los valores del campo `status` de eventos se escriben SIEMPRE en minúsculas: `pending`, `approved`, `rejected`, `superseded`, `auto_restored`, `quarantined`, `alert_only`.
**Condición:** Siempre (persistencia, APIs, streams Valkey, logs, documentación técnica).
**Resultado:** Cualquier valor que no cumpla este léxico es rechazado a nivel de schema/enum.
**Excepciones:** Títulos markdown o énfasis de botón en UI pueden usar mayúsculas.

---

### Modelo de eventos y lifecycle

#### C2 / RN-72: Máquina de estados canónica (in/out edges)
**Descripción:** Las transiciones válidas están definidas por la siguiente tabla y cualquier transición no listada se rechaza.

| Estado | In-edges permitidas | Out-edges permitidas |
|--------|---------------------|----------------------|
| `pending` | creación (action=`manual_review`) | `approved`, `rejected`, `superseded` |
| `approved` | `pending` | terminal |
| `rejected` | `pending` | terminal |
| `superseded` | `pending` (por cadena o re-scan) | terminal |
| `auto_restored` | creación (action=`auto_restore`) | terminal |
| `quarantined` | creación (action=`quarantine`) | terminal |
| `alert_only` | creación (action=`alert_only` o default) | terminal |

**Condición:** Al intentar actualizar el `status` de un evento.
**Resultado:** Transición válida → aplica. Inválida → HTTP 409 conflict.
**Excepciones:** Ninguna.

#### C3 / RN-73: Protocolo ACK Valkey end-to-end
**Descripción:** El ack de un evento sigue un protocolo de 4 pasos que garantiza at-least-once y limpieza idempotente.
**Condición:** Siempre que el agente publique un evento.
**Resultado:** 1) Agente genera `event_id` UUID v4. 2) Backend consume con consumer group `fim-backend`. 3) Tras persistir en PostgreSQL ejecuta `XACK` + publica `event_ack` al stream `commands`. 4) Agente al recibir el ack elimina la entrada de `/var/lib/fim-agent/queue/`.
**Excepciones:** Si el agente no recibe ack en 60 s, reintenta la publicación (deduplicado por `event_id` en backend).

#### C10 / RN-74: Rechazo sobre baseline absent es no-op
**Descripción:** Rechazar un evento cuyo baseline está en `status: absent` no envía comando al agente.
**Condición:** Admin rechaza un evento y el baseline asociado tiene `status: absent`.
**Resultado:** El evento pasa a `rejected`, se loguea warning, se retorna 200 con `baseline_absent: true`. NO se publica `restore_file` ni `quarantine_file`.
**Excepciones:** Ninguna.

#### C11 / RN-75: `ruleset_version` monotónico
**Descripción:** Los comandos `baseline_update`, `rule_sync`, `update_config` y `rescan_baseline` incluyen un `ruleset_version: int` monotónico creciente generado por el backend.
**Condición:** Al publicar comandos que afectan estado replicado del agente.
**Resultado:** El agente persiste el último `ruleset_version` aplicado en `/var/lib/fim-agent/state.json` y descarta mensajes con versión menor. Garantiza ordering + idempotencia ante re-entregas.
**Excepciones:** Ninguna.

---

### Arquitectura del sistema

#### C4 / RN-76: Backend single-instance (no HA)
**Descripción:** El backend corre como única instancia. El MVP no soporta réplicas múltiples.
**Condición:** Siempre.
**Resultado:** Optimistic locking, consumer groups, rate limiting y JWT blacklist se diseñan asumiendo una única instancia.
**Excepciones:** Ninguna hasta decisión explícita de ampliación.

#### C5 / RN-77: Optimistic locking sobre Event
**Descripción:** Toda mutación de `status` en un evento `pending` usa una cláusula de versión optimista.
**Condición:** Admin aprueba o rechaza; backend aplica `superseded` automático.
**Resultado:** Columna `version: int` (default 0). El UPDATE incluye `WHERE id=X AND version=V AND status='pending'`. Si afecta 0 filas → HTTP 409.
**Excepciones:** Ninguna.

---

### Seguridad y criptografía

#### C6 / RN-78: Bootstrap mTLS con CA propia
**Descripción:** El backend actúa como CA. Los agentes se registran con un secret pre-compartido y reciben cert firmado.
**Condición:** Primer arranque del agente.
**Resultado:** Admin pre-registra `agent_id + bootstrap_secret` (32 bytes random). Agente POSTea CSR + HMAC a `/agents/bootstrap`. Cert válido 90 días. Junto con el cert se entregan `shared_secret` (para HMAC de comandos — RN-79) y `master_secret` (para derivación de clave de baseline — RN-82). Rotación automática 15 días antes de expirar. Revocación por lista en tabla `revoked_certificates`.
**Excepciones:** Ninguna.

#### C7 / RN-79: HMAC de comandos backend → agente
**Descripción:** Los comandos publicados en `commands` están firmados con HMAC-SHA256.
**Condición:** Todo comando hacia el agente.
**Resultado:** Campo `signature` = `HMAC-SHA256(shared_secret, canonical_json(payload))`. El `shared_secret` se entrega junto con el certificado mTLS en bootstrap. Comandos con signature inválida se descartan.
**Excepciones:** Ninguna.

#### C8 / RN-80: Gestión de JWT
**Descripción:** JWT con access/refresh, rotación, blacklist y multi-key.
**Condición:** Toda sesión de usuario.
**Resultado:** Access token 15 minutos, refresh token 7 días con rotación en cada uso, blacklist de `jti` en Valkey con TTL, dos keys activas (`JWT_SECRET_CURRENT` + `JWT_SECRET_PREVIOUS`) para rotar sin downtime.
**Excepciones:** Ninguna.

#### C9 / RN-81: Parámetros Argon2id explícitos
**Descripción:** Argon2id se configura con parámetros fijos, no defaults.
**Condición:** Hashing y verificación de passwords.
**Resultado:** `PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)`.
**Excepciones:** Ninguna.

#### W10 / RN-82: Baseline cifrado en disco
**Descripción:** Los archivos del baseline del agente se cifran con AES-256-GCM.
**Condición:** Escritura o lectura de `/var/lib/fim-agent/baseline/`.
**Resultado:** Key derivada con `HKDF-SHA256(ikm=master_secret, salt=AGENT_ID, info="baseline-v1")`. `master_secret` entregado en bootstrap, persistido en `/var/lib/fim-agent/secrets/master_secret` con permisos `0400`. Cada archivo cifrado lleva un nonce GCM único de 96 bits. La etiqueta GCM autentica el contenido.
**Excepciones:** Ninguna.

---

### Resiliencia y degradación

#### W2 / RN-83: Journal pre-acción
**Descripción:** Acciones destructivas del agente (`auto_restore`, `quarantine`) se registran en journal antes de ejecutarse.
**Condición:** Antes de modificar filesystem.
**Resultado:** Se escribe `/var/lib/fim-agent/journal/{event_id}.json` con `state: pending` antes de actuar, luego se actualiza a `completed` o `failed`. Al reiniciar, el agente rehidrata el journal y reintenta o reporta.
**Excepciones:** Ninguna.

#### W3 / RN-84: Límite y política de cola offline
**Descripción:** La cola offline tiene límite de tamaño y política de descarte.
**Condición:** El agente está offline y la cola crece.
**Resultado:** Máximo **100 MB** en `/var/lib/fim-agent/queue/`. Política drop-oldest. Si el uso supera **80 %**, el próximo heartbeat incluye flag `queue_pressure: true` para que la UI lo muestre como alerta.
**Excepciones:** Ninguna.

#### W4 / RN-85: Orden de procesamiento al reconectar
**Descripción:** Al reconectar, el agente procesa primero comandos y luego envía eventos.
**Condición:** Restablecimiento de conexión con Valkey.
**Resultado:** 1) Consume y aplica todos los comandos pendientes (especialmente `baseline_update`, `rule_sync` y `update_config`). 2) Publica eventos de la cola local en FIFO.
**Excepciones:** Ninguna.

#### W11 / RN-86: Retry exponencial, DLQ y cascada de fallbacks de notificaciones
**Descripción:** Los webhooks a n8n reintentan con backoff y, ante fallo total, se aplica cascada de fallbacks.
**Condición:** El backend dispara una notificación.
**Resultado:** Retry: 3 intentos con delays 5 s / 30 s / 120 s. Si fallan los 3, cascada de fallbacks: SMTP directo → webhook directo pre-configurado → log crítico → tabla `failed_notifications(id, event_id, payload_json, last_error, failed_at, retry_count)`. UI muestra banner amarillo persistente mientras haya filas. La indisponibilidad de n8n no compromete la entrega.
**Excepciones:** Ninguna.

#### W12 / RN-87: Health check por componente
**Descripción:** El backend expone un endpoint que reporta el estado de cada componente.
**Condición:** Siempre.
**Resultado:** `GET /health/components` retorna `{postgres, valkey, n8n, agents[]}` con estado `ok | degraded | down`. Frontend hace polling cada 10 s y muestra banner rojo persistente. Cambios de estado disparan webhook n8n.
**Excepciones:** Ninguna.

---

### Operaciones

#### W5 / RN-88: Rate limiting
**Descripción:** Rate limiting aplicado a endpoints sensibles y publicación de eventos.
**Condición:** Cada request entrante o evento publicado por agente.
**Resultado:**
- Login: 5 intentos / 15 min por `(user + IP)`.
- API autenticada: 100 req/min por user.
- Eventos de agente: 100 eventos/min por `agent_id`.

Implementado con counters + TTL en Valkey. Excedentes retornan 429 (API) o se descartan con alerta (eventos).

> **Superado por D37/RN-131 en la parte de eventos.** Un evento excedido ya no se descarta: el backend responde `event_nack` con `retry_after` y el agente lo retiene en cola aplicando backpressure. La alerta que este párrafo prometía nunca se implementó. El límite de recursos sigue siendo el drop-oldest de RN-40. El comportamiento de la API (429) no cambia.
**Excepciones:** Ninguna.

#### W6 / RN-89: Logging estructurado con sanitización
**Descripción:** Todos los logs son JSON estructurado con sanitización de secretos.
**Condición:** Cualquier emisión de log.
**Resultado:** Middleware `sanitize_logs` filtra `password`, `access_token`, `refresh_token`, `bootstrap_secret`, `master_secret`, `shared_secret`, `signature`. Retention 30 días. **Prohibido loguear contenido de diffs** — solo `hash_before`, `hash_after`, `size_delta`.
**Excepciones:** Ninguna.

#### W13 / RN-90: Timestamps dobles y rechazo por skew
**Descripción:** Los eventos llevan dos timestamps y se rechazan si hay desfase excesivo.
**Condición:** Consumo de evento por el backend.
**Resultado:** Evento incluye `detected_at` (agente). Backend agrega `received_at`. Si `abs(received_at - detected_at) > 5 min`, se rechaza con código `clock_skew` y se persiste en `rejected_events_audit`.

> **Enmendada por D37/RN-131.** La ventana de 5 minutos se evalúa sobre `sent_at` —sellado al publicar y re-sellado en cada republicación, dentro del payload firmado— y `detected_at` deja de tener ventana, conservando sólo su validación de parseabilidad. El texto de arriba describe el comportamiento previo y sigue vigente como fallback cuando el payload no trae `sent_at` (agente anterior a la enmienda). Motivo: tal como estaba, esta regla anulaba a RN-38/RN-41 — cualquier corte mayor a cinco minutos convertía el contenido íntegro de la cola offline en eventos irrecibibles.
**Excepciones:** Ninguna.

#### W14 / RN-91: `schema_version` en payloads
**Descripción:** Todo mensaje en streams incluye `schema_version`.
**Condición:** Publicación o consumo de mensaje en `events` / `commands` / `agent_heartbeat`.
**Resultado:** Receptor rechaza `schema_version` mayor que el soportado. Receptor ignora campos desconocidos (forward compat). Bumps se documentan en `docs/schema_changelog.md`.
**Excepciones:** Ninguna.

#### W16 / RN-92: Heartbeat y transiciones de estado de agente
**Descripción:** El estado del agente se infiere de heartbeats periódicos.
**Condición:** Siempre.
**Resultado:** Agente publica al stream `agent_heartbeat` cada **10 s** con `{agent_id, timestamp, queue_size, ruleset_version, queue_pressure, shutdown, event_drops}`. Sin heartbeat 30 s → `offline`. Sin heartbeat 5 min → `dead` + webhook n8n. El campo `event_drops: int` acumula el total de eventos descartados por la cola interna del detector (asyncio.Queue llena) desde el arranque del agente; el backend lo expone en el dashboard de salud del agente. Payloads sin `event_drops` (versión anterior) se tratan como `event_drops: 0`.
**Excepciones:** Durante shutdown graceful el agente publica con `shutdown: true` (estado `draining` — ver RN-93).

#### W17 / RN-93: Graceful shutdown del agente
**Descripción:** El agente drena su cola al recibir SIGTERM antes de salir.
**Condición:** Recepción de SIGTERM.
**Resultado:** Deja de aceptar nuevos eventos de `fanotify`, drena la cola local al stream (timeout 30 s), exit 0. Durante el drenaje reporta estado `draining`; el `/health/components` lo refleja para ese agente y la UI deshabilita acciones (re-scan, update config).
**Excepciones:** Si el drenaje supera timeout, exit 0 con eventos remanentes en disco (rehidratados en próximo arranque).

#### W18 / RN-94: Tabla `audit_log` dedicada
**Descripción:** Todas las acciones administrativas relevantes se registran en una tabla de auditoría separada de los logs.
**Condición:** Login/logout, CRUD de reglas, approve/reject, bulk approve/reject, re-scan, cambios de config, reintentos de notificaciones, cambios de password.
**Resultado:** Tabla `audit_log(id, timestamp, user_id, action, resource_type, resource_id, ip, user_agent, metadata_json)`. Retention ilimitada (no rota con logs estructurados). Cumple con requisitos de Resoluciones AAIP 47/2018 y 126/2024.
**Excepciones:** Ninguna.

---

### Frontend

#### W7 / RN-95: Headers HTTP de seguridad
**Descripción:** nginx del frontend emite un conjunto estricto de headers y el backend valida origen.
**Condición:** Toda respuesta HTTP del frontend y toda request al backend.
**Resultado:** CSP estricto (`default-src 'self'`, etc.), `Strict-Transport-Security` 1 año con subdominios, `X-Frame-Options: DENY`, cookies `SameSite=Strict`, backend valida `Origin` contra whitelist.
**Excepciones:** Ninguna.

#### W8 / RN-96: DiffViewer con escapado
**Descripción:** Solo se permite render de diffs mediante componente con escapado automático.
**Condición:** Render de contenido de archivo.
**Resultado:** Se usa `react-diff-viewer-continued` con escapado activo. **Prohibido** `dangerouslySetInnerHTML` (lint rule `react/no-danger`).
**Excepciones:** Ninguna.

#### W9 / RN-97: Almacenamiento de tokens en cliente
**Descripción:** Access y refresh tokens se almacenan por separado con distintos requisitos.
**Condición:** Toda sesión de admin.
**Resultado:** Access token solo en memoria (Zustand). Refresh token en cookie `httpOnly + Secure + SameSite=Strict + Path=/auth/refresh`. Nunca `localStorage` / `sessionStorage`.
**Excepciones:** Ninguna.

---

### UX y features

#### W1 / RN-98: Filtro default oculta superseded + retention
**Descripción:** La UI oculta `superseded` por defecto y los eventos tienen retention operativa.
**Condición:** Vista operativa de Eventos.
**Resultado:** Filtro default excluye `superseded`. Toggle explícito para incluirlos (con persistencia en URL). **Máximo 10 eventos en una cadena** (por path); al intentar crear el 11 se compacta eliminando los `superseded` más antiguos. **Retention 30 días** para eventos en estados terminales (salvo auditoría activa).
**Excepciones:** Eventos referenciados desde `audit_log` no se eliminan.

#### W15 / RN-99: Bulk approve/reject y paginación
**Descripción:** Operaciones masivas y paginación fija.
**Condición:** Vista de Eventos.
**Resultado:** Selección múltiple + endpoints `POST /actions/bulk-approve` y `POST /actions/bulk-reject` con `event_ids[]`. Cada evento se procesa con optimistic locking individual (RN-77). Respuesta con `succeeded[]` y `failed[]` (con razón por fallo). Paginación **50 eventos/página** por defecto.
**Excepciones:** Ninguna.

#### W20 / RN-100: Seed admin con cambio forzado
**Descripción:** El primer admin debe cambiar su password antes de operar.
**Condición:** Primer login del usuario seed.
**Resultado:** Flag `must_change_password: bool = True` al crear el seed. Tokens emitidos con scope `password_change_only` hasta completar el cambio. Cualquier endpoint responde 403 `password_change_required` mientras el flag sea true. Requerimientos del nuevo password: ≥ 12 chars, al menos 1 mayúscula, 1 minúscula, 1 número.
**Excepciones:** Ninguna.

---

## 16. Observabilidad y degradación (Dominio nuevo)

### RN-101: Polling de health desde frontend
**Descripción:** El frontend refresca el estado de salud del sistema periódicamente.
**Condición:** Sesión activa del admin.
**Resultado:** `GET /health/components` cada 10 segundos. Banner rojo persistente si cualquier componente != `ok`.
**Excepciones:** Ninguna.

### RN-102: Visibilidad de DLQ de notificaciones
**Descripción:** El admin siempre puede ver y actuar sobre notificaciones que fallaron.
**Condición:** Existen filas en `failed_notifications`.
**Resultado:** Banner amarillo persistente. Vista `/notifications/failed` permite reintentar (individual o bulk) o descartar. Banner desaparece cuando la tabla queda vacía. Cada acción se registra en `audit_log` (RN-94).
**Excepciones:** Ninguna.

### RN-103: Degradación no bloquea UI
**Descripción:** Los banners de degradación no impiden operar la UI.
**Condición:** Cualquier banner de degradación activo.
**Resultado:** El banner es informativo, cerrable hasta el próximo poll, y no bloquea acciones (salvo las que dependen directamente del componente caído).

---

## Appendix: Decisiones de implementación — Abril 2026

Las siguientes decisiones cierran las suposiciones abiertas detectadas durante la elaboración del roadmap de implementación ([CHANGES.md](../CHANGES.md)). Las decisiones D1–D8 se cerraron el 2026-04-24; D11–D13 (RN-109 a RN-111) se agregaron el 2026-06-23; D14–D17 (RN-112 a RN-115) se agregaron el 2026-06-26; D18–D20 (RN-116 a RN-118) se agregaron el 2026-06-26; D29 (RN-123) se agregó el 2026-07-01; D30–D32 (RN-124 a RN-126) se agregaron el 2026-07-02; D33 (RN-127) se agregó el 2026-07-02; D34 (RN-128) se agregó el 2026-07-02; D35 (RN-129) se agregó el 2026-08-13; D36 (RN-130) se agregó el 2026-08-14; D37 (RN-131) se agregó el 2026-08-16; D38 (RN-132) se agregó el 2026-08-18; D39 (RN-133) se agregó el 2026-08-21; D52 (RN-146) se agregó el 2026-09-12. En caso de conflicto con reglas previas (RN-01 a RN-103) o con el appendix de auditoría, prevalece lo especificado en este appendix. Las decisiones que solo afectan la implementación técnica (despliegue, organización del código) se documentan en [arquitectura_stack.md](arquitectura_stack.md) bajo el mismo título.

### Modelo de datos

#### D1 / RN-104: Réplica de baseline metadata en backend
**Descripción:** El backend mantiene una tabla `baseline_entries` con metadata por path monitoreado, sin contenido cifrado. La fuente de verdad del contenido sigue siendo el agente (cifrado AES-256-GCM en `/var/lib/fim-agent/baseline/`).
**Condición:** Siempre que un comando `baseline_update` sea confirmado por el agente vía `event_ack` (RN-25, RN-59).
**Resultado:** Schema:
- `path: str`
- `agent_id: str`
- `hash: str | null` (null cuando `status = 'absent'`)
- `status: 'present' | 'absent'` (RN-66)
- `last_updated: datetime`
- `ruleset_version: int` (versión del comando que generó esta entrada)

Sincronización: cada `event_ack` exitoso de `baseline_update` actualiza la fila en backend. El backend consulta `baseline_entries` (no al agente) para resolver flujos de approve, reject y visualización en UI.
**Excepciones:** Ninguna. Si el agente y el backend divergen, RN-50 (verificación al leer en agente) lo detecta y genera un evento de incidente.

#### D4 / RN-105: Tabla `rejected_events_audit` y enum `RejectionReason`
**Descripción:** Eventos publicados por el agente que el backend rechaza durante la ingesta se persisten en una tabla auditable separada.
**Condición:** Validación de `schema_version`, HMAC, clock skew (RN-90, RN-91) o `agent_id` falla.
**Resultado:** Schema:
- `id: int` (pk)
- `event_id: str` (UUID del payload, si pudo parsearse)
- `agent_id: str`
- `reason: RejectionReason` (enum: `clock_skew`, `invalid_schema`, `invalid_signature`, `unknown_agent`, `duplicate_event`)
- `received_at: datetime`
- `detected_at: datetime | null` (del payload original)
- `payload_dump: str` (JSON crudo, truncado a 4 KB)

El uso de enum (no `str` libre) garantiza que cualquier valor fuera del léxico es rechazado a nivel de schema.

> **Ampliada por D37/RN-131.** La persistencia en `rejected_events_audit` no cambia: todo rechazo se sigue auditando igual. Lo que se agrega es que el rechazo además **se comunica** al agente mediante una respuesta tipada, para cuatro de los motivos. `invalid_signature` y `unknown_agent` siguen sin respuesta: no se puede firmar una respuesta verificable para un emisor que no autenticó, y responder convertiría al backend en un oráculo que confirma qué `agent_id` existen. El enum incorpora `rate_limited` y `schema_version_unsupported`.

**Excepciones:** Ninguna.

#### D6 / RN-107: Tabla unificada `alerts` (fusión con `failed_notifications`)
**Descripción:** Se elimina la tabla separada `failed_notifications` (mencionada en RN-86, RN-102). Una única tabla `alerts` cubre el lifecycle completo (pending → delivered o terminal_failed).
**Condición:** Cualquier evento con severidad `critical` o `high` (RN-53) genera una fila en `alerts` al ser ingresado.
**Resultado:** Schema:
- `id: int` (pk)
- `event_id: int` (FK a `events`)
- `severity: 'critical' | 'high' | 'medium' | 'low'`
- `channel: str | null` (`n8n` | `smtp_fallback` | `webhook_fallback` | `log_only`; null mientras está pending)
- `delivered_at: datetime | null`
- `failed_at: datetime | null`
- `last_error: str | null`
- `retry_count: int` (default 0)
- `created_at: datetime`

Estados:
- **Pending**: `delivered_at IS NULL AND failed_at IS NULL AND retry_count < 3`
- **Delivered**: `delivered_at IS NOT NULL` (puede haber retry_count > 0)
- **Failed terminal**: `delivered_at IS NULL AND failed_at IS NOT NULL` (típicamente `retry_count >= 3`)

`delivered_at` y `failed_at` son **mutuamente excluyentes solo en estado terminal**.
**Excepciones:** Ninguna.

### Aprobación y sincronización

#### D2: Reescritura de RN-17 — el approve usa el hash del evento, no consulta al agente
**Descripción:** **Esta decisión sustituye el comportamiento descrito en la versión original de RN-17 (que indicaba "se consulta al agente el hash actual").**

El backend NO consulta al agente al ejecutar approve. Usa directamente el hash que el evento `pending` ya trae al momento de detección (publicado por el agente vía `fanotify`).
**Condición:** Admin ejecuta approve sobre un evento `pending`.
**Resultado:** El baseline se actualiza con el hash del evento aprobado. La cadena de eventos (RN-21) garantiza que el evento `pending` activo SIEMPRE refleja el estado más reciente conocido del archivo: cualquier cambio posterior crea un nuevo evento que marca al anterior como `superseded`. Si el admin intenta aprobar un evento `superseded`, retorna 409 (RN-77).

**Race window self-healing**: existe una ventana microsegundo entre que el archivo cambia en el FS y `fanotify` emite el evento. Si un cambio ocurre en esa ventana entre `detected_at` y la confirmación del approve:
1. El approve completa con el hash del evento aprobado.
2. El nuevo cambio genera un nuevo evento `pending` cuyo hash difiere del baseline recién actualizado.
3. El admin ve un nuevo pending y lo trata normalmente.

El sistema converge sin pérdida de datos ni inconsistencia detectable.
**Excepciones:** Approve con archivo eliminado mantiene RN-60: `BaselineEntry` se persiste con `hash: null, status: 'absent'`.

#### D5 / RN-106: `target_agent_id` en comandos y semántica de `ruleset_version_applied`
**Descripción:** El contador `ruleset_version` (RN-75) sigue siendo global por backend (single-instance, RN-76). Para soportar configuración heterogénea entre agentes, todo comando publicado al stream `commands` lleva un campo `target_agent_id: str | null` (null = broadcast).
**Condición:** Backend publica cualquier comando (`baseline_update`, `rule_sync`, `update_config`, `rescan_baseline`, `restore_file`, `quarantine_file`).
**Resultado:**
- El agente filtra por `target_agent_id IN (self.agent_id, NULL)` antes de procesar.
- `Agent.ruleset_version_applied` se define como: **el max `ruleset_version` confirmado vía `event_ack` de comandos cuyo `target_agent_id` era `self.agent_id` o `NULL`**.
- El check "agente al día" en backend usa: `agent.ruleset_version_applied == max(version FROM commands WHERE target_agent_id IN (agent_id, NULL))`. **No** comparar contra el counter global.

Sin esta semántica, agentes que no son target de comandos recientes aparecerían perpetuamente "desactualizados" en el dashboard.
**Excepciones:** Ninguna.

### Arquitectura del agente

#### D8 / RN-108: Prohibición de servidor HTTP en el agente
**Descripción:** El agente NO expone servidor HTTP, gRPC ni ningún listener TCP. Toda comunicación backend → agente viaja por streams Valkey asincrónicos (`commands` y `agent_heartbeat`).
**Condición:** Siempre.
**Resultado:**
- Comandos: backend publica en stream `commands`, agente confirma vía `event_ack`.
- Salud y estado del agente: backend lee del stream `agent_heartbeat` (RN-92), enriquecido con `queue_size`, `queue_pressure`, `ruleset_version_applied`, `shutdown`.
- Consultas síncronas backend → agente: **no existen** en el MVP. La fusión D2 + heartbeat enriquecido las elimina.

Excepción futura (out-of-scope MVP): si se requiere debug interactivo local, se habilitará un **Unix socket via systemd socket activation** (sin puerto TCP, sin certificado adicional, controlado por permisos de FS). Nunca un puerto TCP.
**Excepciones:** Ninguna en el MVP.

#### D12 / RN-110: Máscaras fanotify monitoreadas y léxico de operaciones de filesystem

**Descripción:** El agente registra las siguientes máscaras fanotify en el mark del filesystem:
`FAN_CLOSE_WRITE`, `FAN_DELETE`, `FAN_MOVED_FROM`, `FAN_MOVED_TO`, `FAN_CREATE`.

**Resolución de path (D46/RN-140):** el detector opera en **modo FID** con `FAN_REPORT_DFID_NAME` y reconstruye el path vía `open_by_handle_at(2)` sobre el handle del directorio padre más el nombre que reporta el kernel. Eso es lo que permite resolver el path de un archivo **ya borrado**, imposible con un fd del objeto. Si el path no puede resolverse, el evento se descarta con log warning.

El modo fd clásico (`FAN_CLASS_NOTIF` sin FID) **no admite** `FAN_CREATE`, `FAN_DELETE` ni `FAN_MOVED_*` sobre una marca de filesystem: el kernel responde `EINVAL`. Por eso prohibir el reporte FID y a la vez exigir esas máscaras era contradictorio.

`open_by_handle_at(2)` requiere **`CAP_DAC_READ_SEARCH` además de `CAP_SYS_ADMIN`**.

**Léxico canónico de operaciones** (extiende RN-71 al campo `operation_type` del payload de evento, además de `status`):

| Valor | Condición |
|-------|-----------|
| `file_modified` | `FAN_CLOSE_WRITE` y hash difiere del baseline |
| `file_absent` | `FAN_CLOSE_WRITE` y el archivo no existe al momento de hashear (race condition) |
| `file_deleted` | `FAN_DELETE` o `FAN_MOVED_FROM` |
| `file_created` | `FAN_CREATE` o `FAN_MOVED_TO` |

Todos en minúsculas snake_case. El backend indexa `operation_type` para filtros en UI. Los payloads sin `operation_type` (versión de agente anterior) se tratan como `file_modified`.

**Condición:** Siempre que el agente esté registrado con fanotify sobre un filesystem monitorizado.

**Excepciones:** `FAN_DELETE`/`FAN_MOVED_FROM` no producen hash (el archivo ya no existe); el payload omite el campo `hash` o lo envía como `null`. El backend acepta `hash: null` para estos tipos.

#### D13 / RN-111: Renovación automática de certificado vía `/agents/renew`

**Descripción:** El agente ejecuta una tarea asyncio en background que verifica la vigencia del cert cada 24 h. Si el cert vence en ≤ 15 días, llama al endpoint `POST /agents/renew` del backend usando mTLS con el cert actual (sin reusar el `bootstrap_secret`, que es de un solo uso).

El endpoint `/agents/renew` (a implementar en el backend, fuera de C26) verifica que el cert del cliente sea válido y esté firmado por la CA, luego emite un nuevo cert. El agente guarda el nuevo cert en `certs_dir` con escritura atómica. Las nuevas conexiones Valkey (tras reconexión) usarán el cert renovado.

Si el endpoint retorna error o no existe (backend no actualizado), el agente registra una advertencia y reintenta en 24 h. No interrumpe la operación normal.

**Condición:** Tarea en background activa desde el arranque del agente, solo si los certs ya fueron bootstrapped.

**Excepciones:** Si la renovación falla repetidamente y el cert expira, el agente continúa operando hasta que la conexión TLS sea rechazada por el servidor (el error de TLS es la condición de terminal, no la verificación proactiva). El backend refleja el estado de cert en el dashboard de agentes.

#### D11 / RN-109: Cursor persistente del stream `commands` y orden de reconexión

**Descripción:** El agente persiste el último `stream_id` procesado del stream `commands` en `AgentState` (`state.json`, campo `last_stream_command_id`). Este cursor se actualiza tras cada mensaje procesado con éxito. Al arrancar sin cursor previo (`"0-0"`), el agente consume todos los mensajes existentes en el stream desde el origen, recuperando comandos emitidos durante cualquier downtime.

**Condición:** Todo arranque del agente y tras cada mensaje del stream `commands` procesado con éxito.

**Resultado:**

Orden de arranque obligatorio del Publisher:
1. Leer `last_stream_command_id` del estado persistido (`"0-0"` si no existe).
2. Flush de comandos pendientes: loop `XREAD COUNT 100 BLOCK 0` desde el cursor, hasta ronda vacía o hasta superar `command_flush_timeout_s` (configurable, default `2.0 s`). Aplicar cada comando normalmente durante el flush.
3. Lanzar `_drain_queue()` (publicar eventos encolados).
4. Arrancar el `_ack_listener` en background para comandos futuros.

Este orden es el que la tesis describe en la Tabla 14 ("Comandos procesados antes que eventos encolados → Sí") y lo que hace ejecutable RN-85 ("consume y aplica todos los comandos pendientes"). Sin cursor persistente, `last_id = "$"` solo lee mensajes futuros y RN-85 es inejecutable.

**Excepciones:** Si el flush supera `command_flush_timeout_s`, el agente continúa con el drain sin procesar los comandos pendientes restantes y emite una advertencia de log. El cursor queda apuntando al último mensaje procesado antes del timeout.

#### D14 / RN-112: Modelo de tracking de baseline — "último aprobado", no "último visto"

**Descripción:** El baseline activo (`content_b64`, `hash`) siempre refleja el **último estado aprobado/conocido-bueno** de cada archivo monitoreado. Cuando se detecta una modificación que NO resulta en auto_restore (regla `alert_only`, `manual_review`, o auto_restore fallido), el baseline activo NO se actualiza con el nuevo contenido — solo se agrega un snapshot de auditoría del contenido nuevo vía `add_snapshot`.

Consecuencia directa: `select_restorable_content(entry)` leyendo `content_b64` activo siempre retorna el estado conocido-bueno. `restore_file` siempre restaura al estado aprobado, nunca al contenido del atacante.

**Orden de operaciones corregido:**

| Tipo de evento | Orden correcto |
|----------------|---------------|
| `file_deleted` / `file_moved_from` | `evaluate_and_act` PRIMERO → luego `mark_absent(path)` (solo si no fue restaurado) |
| `file_created` / `file_moved_to` | `evaluate_and_act` PRIMERO → luego `write_entry(path)` (solo si no fue puesto en cuarentena) |
| `file_modified` (non-restore) | Solo `add_snapshot(path, new_hash, new_content)` — NO llamar `write_entry` con el nuevo contenido |

El baseline debe estar disponible para el motor de decisión durante la evaluación (`evaluate_and_act`). Mutarlo antes destruye la información necesaria para auto_restore.

**Condición:** Siempre que un evento de filesystem sea evaluado por el motor de decisión.

**Excepciones:** Ninguna en el MVP.

#### D15 / RN-113: Lifecycle de entradas del journal — borrar al confirmar

**Descripción:** Las journal entries se borran inmediatamente cuando se llama `mark_completed()` (dentro del commit_fn). Secuencia del commit_fn: `journal.mark_completed(event_id)` → `journal.delete(event_id)` (borra el archivo JSON del journal_dir). Las entradas con estado `failed` se retienen indefinidamente en el MVP (sin limpieza automática). Esto evita la acumulación ilimitada de archivos en el journal_dir.

**Condición:** Cada publish exitoso que dispara commit_fn.

**Excepciones:** Ninguna en el MVP.

#### D16 / RN-114: Trust anchor del bootstrap vía `ca_cert_path`

**Descripción:** La llamada HTTP inicial del bootstrap (`POST /backend/bootstrap`) usa `config.ca_cert_path` como ancla de confianza TLS: `httpx.post(..., verify=str(config.ca_cert_path))`. `verify=False` queda **prohibido**. El operador debe pre-provisionar el cert del CA del backend en `ca_cert_path` antes de ejecutar el bootstrap. Si el archivo no existe al iniciar, el bootstrap falla con mensaje explicativo y `sys.exit(1)`.

El `ca_cert_pem` recibido en la **respuesta** del bootstrap es el CA que firmará el `agent-cert.pem` para mTLS — puede ser el mismo CA del backend o uno diferente; esa es una decisión operativa. No sustituye al `config.ca_cert_path` como ancla de confianza del endpoint HTTPS.

**Condición:** Siempre durante el bootstrap inicial.

**Excepciones:** Ninguna. El flag `verify=False` no se expone como opción configurable.

#### D17 / RN-115: Verificación de hostname en mTLS Valkey

**Descripción:** La conexión Valkey con esquema `valkeys://` activa `ssl_check_hostname=True`. El CN o SAN del certificado del servidor Valkey debe coincidir con el hostname en `valkey_url`. En entornos de desarrollo con `valkeys://localhost:6380`, el cert del servidor Valkey debe incluir `localhost` como CN o SAN.

**Condición:** Toda conexión con esquema `valkeys://`.

**Excepciones:** Ninguna. El check de hostname es obligatorio — no se provee un flag de override para deshabilitarlo en el MVP.

#### D18 / RN-116: Validación de path containment en handlers de archivo de comandos

**Descripción:** Los handlers `handle_quarantine_file` y `handle_restore_file` en el agente deben validar que el `path` solicitado esté contenido dentro de alguno de los `watch_paths` antes de ejecutar cualquier operación de filesystem. La validación usa `os.path.realpath(path)` para resolver symlinks y verifica `any(realpath.startswith(w) for w in state.watch_paths)`. Si el path no cumple: publicar un `event_ack` de error y retornar sin ejecutar la operación.

**Condición:** Cualquier ejecución de `handle_quarantine_file` o `handle_restore_file`.

**Resultado:** Los handlers rechazan operaciones sobre paths fuera de watch_paths aunque la firma HMAC sea válida.

**Excepciones:** Si `state.watch_paths` está vacío (estado corrupto), rechazar la operación con log de error. Esta validación es defensa en profundidad sobre la garantía HMAC.

#### D19 / RN-117: Sufijo `.fim_restore_tmp` filtrado en el detector, y descarte por hash del `MOVED_TO` sobre el path final

**Descripción:** El mecanismo tiene dos mitades. **Primera mitad:** el detector ignora todos los eventos de fanotify para paths cuyo nombre de archivo (`path.name`) termina en `.fim_restore_tmp`. Este sufijo es el mecanismo interno de escritura atómica del agente para restauración de archivos (`_auto_restore` y `handle_restore_file`). El filtro se aplica al inicio de `_process_event`, antes de cualquier clasificación, y cubre los eventos sobre el archivo temporal. **Segunda mitad:** ese filtro no alcanza al `FAN_MOVED_TO` que `os.replace` entrega sobre el path FINAL al completar la restauración — ese path nunca lleva el sufijo. Por eso, para toda clasificación que produce un hash (`file_modified`, `file_absent`, `file_created` — que cubre tanto `FAN_CREATE` como `FAN_MOVED_TO`), el detector descarta el evento sin publicar cuando el hash resultante coincide con el hash registrado en el baseline **y** el tipo de objeto no cambió (symlink vs. archivo regular, ver D33/RN-127). Ambas mitades son necesarias: la primera evita el ruido del archivo temporal, la segunda evita reportar como cambio una restauración que, por RN-33, deja contenido idéntico al baseline.

**Limitación conocida:** El filtro de sufijo crea un punto ciego deliberado — archivos externos que por coincidencia terminen en `.fim_restore_tmp` no serán monitoreados. El riesgo es negligible dado lo específico del sufijo.

**Condición:** El filtro de sufijo aplica siempre en `_process_event`, para todos los tipos de evento. El descarte por hash aplica a toda clasificación que produce un `current_hash` (`file_modified`, `file_absent`, `file_created`); no aplica a `file_deleted`, que no produce hash.

**Motivación:** Sin el filtro de sufijo, cada restauración genera eventos espurios (FAN_CREATE, FAN_CLOSE_WRITE, FAN_MOVED_FROM para el tmp) que contaminan el baseline y el backend. Las reglas de decisión se evalúan por path, no por tipo de evento (`RulesCache.evaluate` no recibe el `event_type`), así que **cualquier** regla `auto_restore` que cubra el path —no solo una hipotética regla acotada a `file_created`— alcanza para que el `FAN_MOVED_TO` que emite `os.replace` sobre el path final dispare una nueva restauración. Sin el descarte por hash de la segunda mitad, eso genera un loop infinito: cada restauración exitosa produce un `MOVED_TO` con contenido idéntico al baseline, que sin el descarte se reporta igual como cambio y reactiva la remediación sobre el mismo path.

**Excepciones:** Ninguna.

#### D22 / RN-119: Verificación HMAC en el stream `agent_heartbeat`

**Descripción:** El consumer del stream `agent_heartbeat` verifica la firma HMAC-SHA256 del payload antes de actualizar el estado del agente. Sigue el mismo protocolo que el consumer de eventos (RN-79): tras obtener el agente de DB, se llama `verify_payload(shared_secret_bytes, payload)` con `hmac.compare_digest`. Un payload con firma inválida o de un agente desconocido se descarta sin actualizar estado.

**Condición:** Cada mensaje procesado por `_handle_heartbeat` en `modules/agents/heartbeat_consumer.py`.

**Resultado:** Agentes desconocidos o con firma inválida no pueden modificar el estado de liveness de otros agentes. Simétrico con la verificación de eventos (RN-79).

**Excepciones:** Si el agente tiene `shared_secret_hex` vacío (estado de migración incompleta), el heartbeat se descarta con log de error.

#### D23 / RN-120: Semántica de `log_only` en la cascada de notificaciones

**Descripción:** La cascada de notificaciones (`_try_cascade`) distingue entre el canal `log_only` como resultado intencionado y como resultado de fallo degradado. Si al menos un canal primario (`n8n_webhook_url`, `smtp_host`, `webhook_fallback_url`) está configurado pero todos fallaron, la función retorna `(False, None)` activando el retry loop con delays `[5, 30, 120]` s. Tras agotar los reintentos, `failed_at` se persiste y la alerta entra en la DLQ. Si ningún canal primario está configurado, `log_only` es el canal intencionado y la alerta se marca como `delivered`.

**Condición:** Cada ejecución de `notify_event` en `modules/alerts/service.py`.

**Resultado:** La DLQ (`list_failed_alerts`, `retry_alert`) y el retry loop son operacionales en entornos con canales configurados. En entornos sin canales externos (dev/CI), `log_only` sigue siendo éxito sin retry.

**Excepciones:** `log_only` nunca falla — es el piso del sistema de notificaciones (RN-54).

#### D25 / RN-121: Inserción del evento nuevo cuando falla `mark_superseded`

**Descripción:** Cuando `mark_superseded` no afecta ninguna fila (el evento pending fue resuelto concurrentemente por un approve/reject), `ingest_event` re-consulta si existe un pending activo para el mismo path. Si no hay pending activo, el nuevo evento se inserta como pending independiente sin `parent_event_id`. Si todavía hay pending, el skip es legítimo.

**Condición:** Toda llamada a `ingest_event` donde `mark_superseded` retorna `False`.

**Resultado:** Ningún cambio real del filesystem reportado por el agente se descarta silenciosamente por una condición de carrera resuelta en el backend.

**Excepciones:** En single-instance con asyncio cooperativo, la carrera genuina es imposible (no hay preemption entre `get_pending_event_for_path` y `mark_superseded`). La corrección protege ante extensiones futuras de la arquitectura.

#### D26 / RN-122: Revocación de agentes — soft revocation a nivel aplicación

**Descripción:** El sistema implementa revocación de agentes a nivel aplicación mediante el estado `revoked` en `Agent.status`. Los consumers de eventos y heartbeat verifican `agent.status != AgentStatus.revoked` antes de procesar mensajes. Un agente revocado no puede publicar eventos ni actualizar su estado de liveness; sus mensajes se descartan con log de error.

**Limitación conocida:** La revocación a nivel TLS (verificar el serial del cert en el handshake mTLS) no está implementada. Un agente con cert revocado puede establecer la conexión mTLS hasta la expiración natural del cert (máx 90 días, D13/RN-111).

**Condición:** Cada mensaje procesado por `_get_shared_secret` (events consumer) y `_handle_heartbeat` (heartbeat consumer).

**Resultado:** Tras setear `status=revoked`, el agente queda silenciado a nivel aplicación. Para evicción inmediata a nivel TLS es necesario intervención manual (revocar el cert en el servidor Valkey o reiniciar el agente con credenciales inválidas).

**Excepciones:** Si `AgentStatus.revoked` no está presente (migración en curso), las conexiones previas a la actualización del enum no son afectadas.

#### D20 / RN-118: Guard explícito para conexión Valkey en texto plano

**Descripción:** `AgentConfig` agrega el campo `allow_plaintext_valkey: bool = False`. En `transport.create_valkey_client()`, si el esquema de `valkey_url` es `valkey://` o `redis://` (texto plano) y `allow_plaintext_valkey` es `False`, se emite un log de nivel `WARNING` prominente advirtiendo que el mTLS está desactivado. La conexión continúa (no es `sys.exit(1)`) para no bloquear entornos de desarrollo. En producción, el operador debe usar `valkeys://` y puede configurar monitoreo sobre la aparición de este warning.

**Condición:** Al crear el cliente Valkey en `__main__.py`.

**Motivación:** Un error tipográfico en la configuración (`valkey://` en vez de `valkeys://`) desactiva todo el mTLS de D17 silenciosamente. El warning hace visible el problema en lugar de silenciarlo.

**Excepciones:** En entornos CI/test donde Valkey corre sin TLS, el warning es esperado e ignorable.

#### D29 / RN-123: `User.email` — campo de email obligatorio, único y validado

**Descripción:** El modelo `User` agrega el campo `email` con las siguientes propiedades:
- Tipo: `EmailStr` (validación de formato RFC 5321).
- Constraint en DB: `NOT NULL UNIQUE`.
- El admin inicial se siembra con el valor de `ADMIN_EMAIL` (env var, default `admin@fim.local`).
- `CreateUserRequest.email` valida formato; `UserItem` expone el email real (no el username).
- Migración: script SQL idempotente en `backend/db/migrations/` (convención D3, sin Alembic).

**Condición:** Aplica a todos los endpoints que crean o devuelven usuarios (`POST /users`, `GET /users`, `GET /users/{id}`).

**Motivación:** El campo es requerido para enrutar notificaciones por email via n8n (M3 de la auditoría 2026-06-23). Sin email real, las notificaciones no se pueden entregar al usuario responsable del evento. El campo también es necesario para el reset de password y auditoría de identidad.

**Excepciones:** En entornos donde no se configura n8n, el email puede ser un placeholder válido (ej. `admin@fim.local`) pero el formato debe ser válido según RFC 5321.

#### D30 / RN-124: Confirmación de ejecución de comandos vía `command_ack` (stream `event_ack`)

**Descripción:** Todo comando emitido por el backend hacia el agente (`baseline_update`, `restore_file`, `quarantine_file`, `update_config`, `rescan_baseline`) debe confirmarse mediante un **`command_ack`** — la confirmación de ejecución que el agente publica en el stream Valkey `event_ack`. El nombre del stream Valkey no cambia; lo que se renombra es el concepto, para desambiguarlo del ack de ingesta homónimo de RN-40/RN-54 (el `event_ack` que el backend publica en el stream `commands` para confirmar la persistencia de un evento). El backend agrega un consumer dedicado de `event_ack` que persiste el estado de ejecución de cada comando.

**Condición:** Todo comando publicado en el stream `commands` y rastreado en `PublishedCommand`.

**Resultado:**
- `PublishedCommand` incorpora: `command_id` (identificador del comando, generado al publicarlo), estado de ejecución (`pending | acked | failed | timeout`), `acked_at` (datetime, nulo hasta la confirmación) y `error` (string, nulo salvo falla reportada por el agente).
- Un comando queda en `pending` hasta que llega su `command_ack`, o hasta que un barrido periódico lo marca `timeout` al superar un umbral configurable (mismo patrón de barrido que RN-92).
- El `command_ack` de un `baseline_update` exitoso hace cumplir RN-104 (actualización de `baseline_entries` en el backend).
- `Agent.ruleset_version_applied` se actualiza únicamente al confirmarse el comando vía `command_ack` — nunca al publicarlo. Esto corrige la implementación vigente de `update_agent_config`, que hoy actualiza `ruleset_version_applied` al publicar el comando `update_config`, en violación de la semántica normativa de RN-106.
- La UI expone el estado de ejecución como un indicador secundario por evento. Esto no crea un nuevo estado en la máquina de eventos: `approved`/`rejected` siguen siendo terminales (RN-72).

**Excepciones:** Ninguna.

#### D31 / RN-125: Cumplimiento de RN-04 mediante containment por `realpath` en el detector y el baseline scan

**Descripción:** Esta decisión es una corrección de implementación de una política de negocio ya vigente (RN-04: "Solo los paths incluidos en la configuración generan eventos. Todo lo demás se ignora. Excepciones: Ninguna"), no una regla nueva. El agente marca el filesystem completo (`FAN_MARK_FILESYSTEM`, limitación del kernel ya documentada como tradeoff arquitectónico — no es objeto de esta decisión). Todo evento fanotify cuyo `os.path.realpath()` no esté contenido en ninguno de los `watch_paths` canonicalizados se descarta antes de encolarse. Todo symlink descubierto durante el escaneo de baseline cuyo `realpath` escape del `watch_path` se omite del baseline en vez de cifrarse.

**Condición:** Todo evento capturado por el detector fanotify y todo symlink encontrado durante el escaneo inicial o el re-scan del baseline.

**Resultado:**
- El filtro de containment se aplica en el punto de lectura del evento, antes de construir el objeto de evento interno — no solo en la etapa de clasificación —, para que la cola acotada del agente no absorba ruido irrelevante generado por el mark a nivel filesystem.
- Los `watch_paths` se resuelven a `realpath` una única vez (al iniciar el monitoreo y en cada recarga de configuración), no en cada evento.
- Un symlink dentro de un `watch_path` cuyo destino resuelto escapa del `watch_path` canonicalizado se omite del baseline con log de advertencia, en vez de cifrarse como si fuera contenido en alcance.
- Se agrega un contador de eventos descartados por estar fuera de alcance, expuesto en el heartbeat, análogo al contador de descarte de cola ya existente (RN-84).

**Excepciones:** Ninguna. Un `watch_path` que sea a su vez un symlink se canonicaliza una sola vez y ese `realpath` define el límite de containment.

**Refinada por D33/RN-127 (2026-07-02)**: la cláusula de symlinks (omitir del baseline los que apuntan afuera) se reemplaza por el reporte del symlink como objeto de filesystem propio; ver D33.

#### D32 / RN-126: Transición a `dead` para agentes que nunca enviaron heartbeat

**Descripción:** El modelo `Agent` incorpora el campo `registered_at` (datetime, seteado en el momento del registro del agente). Un agente cuyo `last_heartbeat` es `NULL` (nunca llegó a enviar un heartbeat) transiciona a `dead` cuando el tiempo transcurrido desde `registered_at` supera el mismo umbral usado para la transición `offline → dead`: **300 segundos (5 minutos)**.

**Condición:** Barrido periódico de agentes (RN-92) sobre agentes con `last_heartbeat IS NULL`.

**Resultado:** El barrido evalúa `now - registered_at > 300 s` para agentes sin heartbeat, en lugar de depender de la comparación `last_heartbeat < threshold` (que en SQL excluye filas `NULL` sin marcarlas, por lo que nunca las transicionaba). Se usa el mismo umbral que `offline → dead` (no el umbral más corto de `online → offline`, 30 segundos) para no marcar `dead` a un agente que está en pleno proceso de arranque/instalación.

**Excepciones:** Ninguna. Los agentes existentes al momento de la migración reciben `registered_at` con el timestamp de ejecución de la migración como valor de backfill, dado que no hay dato histórico real de cuándo se registraron.

#### D33 / RN-127: Symlink como objeto de filesystem propio — containment por ubicación del link, nunca por destino resuelto

**Descripción:** Esta decisión refina D31/RN-125 y cierra el hallazgo MEDIUM-2 de la revisión dual-judge de C37 (2026-07-02): un symlink de escape creado dentro de un `watch_path` (p. ej. `/etc/evil -> /root/.ssh/authorized_keys`) es invisible para el filtro de containment por `realpath` completo, porque `os.path.realpath()` resuelve el symlink final y descarta el evento por caer el destino fuera de alcance — pese a que la creación del link **en sí misma** es un evento en scope (vector de persistencia) que un FIM debe reportar. La decisión reemplaza el containment "por destino resuelto" (usado en el punto de descarte del detector) por un containment "por ubicación del link": se canonicaliza únicamente el directorio padre del path, sin seguir el componente final si este es un symlink. El symlink deja de tratarse como un proxy transparente de su destino y pasa a reportarse como un objeto de filesystem propio.

**Condición:** Todo evento fanotify cuyo path final sea o involucre un symlink, y todo symlink encontrado durante el escaneo de baseline (inicial o re-scan).

**Resultado:**
- Nueva función de containment `_path_location_in_scope(path, watch_paths)`: canonicaliza el directorio padre del path (`os.path.realpath(os.path.dirname(path))`) y compara el basename literal contra los `watch_paths` — **no** resuelve (no sigue) el componente final aunque sea un symlink. Esta función reemplaza al containment por `realpath` completo (D31) en el punto de descarte del detector.
- **Symlink-as-object**: para todo symlink en scope (por ubicación), el agente nunca sigue el link ni lee/hashea/cifra el contenido del destino, esté este dentro o fuera de scope. El evento se reporta con el léxico canónico ya existente de RN-71 (`file_created`, `file_deleted`, `file_modified` — no se introduce un `event_type` nuevo). El hash reportado es `sha256(os.readlink(path))` (hash de la cadena del destino, no de su contenido); el campo `diff`/contenido queda `None`.
- **Baseline**: `write_symlink_entry` usa `os.lstat`/`os.readlink` (nunca sigue el link) y agrega `symlink_target: str | None` a la entrada de baseline. `init_scan` y el re-scan chequean `is_symlink()` **antes** que `is_file()` (`is_file()` sigue symlinks y produciría un falso "archivo regular").
- Se elimina la asimetría create/delete introducida por D31: como el symlink ahora se reporta y se registra en el baseline en el momento de su creación, ya no hay `file_deleted` espurio cuando luego se borra (la entrada de baseline existe para poder distinguir el borrado real de un `file_absent`).
- **Persistencia y exposición (scope completo — agente + backend + frontend)**: el metadato `is_symlink`/`symlink_target` se persiste en el modelo `Event` del backend, se expone en el schema de salida de eventos, y se muestra en la interfaz mediante un badge/indicador visual que distingue un evento sobre un symlink de un evento sobre un archivo regular.
- Un symlink intermedio (no el componente final) que apunta fuera de scope sigue resolviendo su archivo final como fuera de alcance (el contenido real vive afuera) — pero el symlink intermedio en sí, si está en un `watch_path`, se reporta como objeto propio. Un symlink intermedio que permanece dentro de scope no cambia el comportamiento existente.

**Excepciones:**
- **Hardlinks**: quedan documentados como limitación conocida, no resuelta por esta decisión. Un hardlink es, para el filesystem, un segundo nombre para el mismo inodo — `realpath`/`lstat` no lo distinguen de un archivo regular, y determinar si otro nombre del mismo inodo cae fuera de scope requeriría un escaneo completo del filesystem (incompatible con el diseño de cola acotada y reactivo del agente). Esta limitación es inherente a POSIX, no un defecto de implementación. Mitigación: el baseline permanece cifrado con AES-256-GCM y bajo permisos `0700`, limitando el impacto de un hardlink no detectado. Se admite, como contador detective opcional (sin cambio de comportamiento), `hardlink_suspected` en el heartbeat cuando se crea un archivo regular con `st_nlink >= 2`.
- Un `watch_path` que sea él mismo un symlink conserva el tratamiento de D31: se canonicaliza una sola vez y ese `realpath` define el límite de containment (esta excepción no cambia).

#### D34 / RN-128: Severidad persistida en el evento (`Event.severity`)

**Descripción:** El modelo `Event` incorpora el campo `severity` (`RuleSeverity`: `critical | high | medium | low`), calculado en el momento de la ingesta con la lógica ya existente `_determine_severity` (D-C15-01): la severidad más alta entre todas las reglas cuyo patrón glob matchea el path del evento; si ninguna regla matchea, `low`. Hasta esta decisión la severidad se calculaba on-the-fly únicamente para decidir si un evento genera alerta (RN-52/RN-53) y no se persistía: el evento no tenía severidad consultable ni filtrable, y la UI (KPI "pending critical + high" del dashboard) no podía obtenerla del backend.

**Condición:** Todo evento ingerido por el consumer del stream `events` (`ingest_event`).

**Resultado:**
- `Event.severity` se persiste al ingerir, calculado con la misma función que usa el pipeline de alertas (D-C15-01) — una única fuente de cálculo compartida, no duplicada.
- `GET /events` acepta `severity` como filtro (parámetro repetible, mismo patrón que el filtro `status`).
- `EventOut` expone `severity`.
- Migración SQL idempotente en `backend/db/migrations/` (convención D3, sin Alembic). Las filas preexistentes reciben backfill `low` — el default de D-C15-01 para paths sin regla — porque recalcular contra el ruleset actual atribuiría severidades de reglas que podían no existir al momento del evento.
- La severidad del evento es un snapshot al momento de la ingesta: cambios posteriores del ruleset no re-etiquetan eventos ya persistidos (consistente con la semántica de alertas, cuya severidad también se congela al crearse la fila `Alert`).

**Excepciones:** Ninguna.

#### D35 / RN-129: Derivación del estado terminal del evento en la ingesta (`action` → `status`)

**Descripción:** RN-13 establece que un evento sobre el que el agente ya ejecutó una acción se crea con estado `auto_restored`, `quarantined` o `alert_only` y **no pasa por `pending`**. Esa regla era inoperante: el agente nunca emitió un campo `status` en el payload del evento, y la ingesta del backend defaultea a `pending` (`ingest_event`), por lo que los tres estados terminales de origen agente eran inalcanzables en la base de datos. Un archivo ya restaurado automáticamente se presentaba al operador como pendiente de decisión, y aprobarlo emitía un segundo comando redundante sobre un archivo ya resuelto.

Esta decisión cierra el contrato: el estado **se deriva en el backend** a partir de los campos `action` y `action_failed` que el agente ya publica, en lugar de aceptar un `status` enviado por el agente. La derivación en el backend es deliberada y tiene fundamento de seguridad: `action` es un vocabulario cerrado de cuatro valores producidos por el motor de reglas del agente, mientras que un campo `status` de escritura libre permitiría a un agente comprometido inyectar eventos ya marcados como `approved` o `rejected`, saltándose el ciclo de decisión humano y la auditoría asociada. El backend es la única autoridad sobre `EventStatus`.

**Condición:** Todo evento ingerido por el consumer del stream `events` (`ingest_event`).

**Resultado:**

- Tabla de derivación, evaluada sobre `action` (`auto_restore | quarantine | manual_review | alert_only`, vocabulario de `RulesCache.evaluate`, default `alert_only` por RN-06) y `action_failed`:

  | `action` | `action_failed` | `status` resultante |
  |---|---|---|
  | `auto_restore` | `false` | `auto_restored` |
  | `quarantine` | `false` | `quarantined` |
  | `alert_only` | — | `alert_only` |
  | `manual_review` | — | `pending` |
  | `auto_restore` | `true` | `pending` |
  | `quarantine` | `true` | `pending` |
  | ausente o desconocida | — | `pending` |

- **Acción fallida ⇒ `pending`, no terminal.** Cuando la acción automática falla, el archivo permanece adulterado en disco: el incidente no está resuelto y debe volver a la cola del operador con las acciones de aprobar y rechazar disponibles. Cerrarlo como terminal dejaría un archivo comprometido sin ningún actor capaz de intervenir desde la interfaz.
- **`Event.action_failed: bool`** (default `false`) se persiste para no perder la información de que se intentó una acción automática y falló. La interfaz distingue visualmente un `pending` normal de un `pending` con `action_failed = true`, que representa un fallo de remediación y tiene prioridad operativa. `EventOut` expone el campo.
- **Un `action` desconocido o ausente no invalida el evento**: se ingiere como `pending` (tolerancia hacia adelante, mismo criterio que D33 para `is_symlink`/`symlink_target`). Un agente de una versión anterior mantiene el comportamiento actual.
- **Eventos terminales de origen agente** (`auto_restored`, `quarantined`, `alert_only`) se persisten con `resolved_at = received_at` y `resolved_by = NULL`. `resolved_by` nulo con `resolved_at` presente identifica una resolución automática del agente, sin operador humano; la traza de la acción vive en el journal del agente y en el propio evento.
- **Limpieza del léxico (RN-71)**: `_auto_restore` sobrescribe `payload["event_type"]` con el literal `"auto_restored"`, contaminando un campo cuyo vocabulario declarado es `file_modified | file_absent | file_deleted | file_created`. `_quarantine` no hace lo simétrico. Esa sobrescritura se elimina: `event_type` conserva siempre el tipo de operación del filesystem, y el resultado de la acción viaja exclusivamente en `action` / `action_failed`.
- Migración SQL idempotente en `backend/db/migrations/` (convención D3, sin Alembic). Las filas preexistentes reciben backfill `action_failed = false`.

**Excepciones:**
- Los estados `approved`, `rejected` y `superseded` no son derivables desde el agente en ninguna circunstancia: son transiciones exclusivas del backend, originadas por una decisión de operador (RN-25/RN-26) o por la supersesión automática (RN-77). Un payload de agente que pretenda inducirlos se ingiere como `pending`.
- Esta decisión no altera la lógica de supersesión de `ingest_event`: un evento entrante, sea terminal o `pending`, sigue superseding al `pending` activo del mismo path si existe.

#### D36 / RN-130: Acceso de escritura del agente para remediación automática

**Descripción:** Las acciones automáticas `auto_restore` y `quarantine` (RN-30 a RN-37) son inejecutables en el despliegue especificado. Dos barreras independientes lo impiden, y ninguna de las dos se levanta corrigiendo la otra:

1. **Mount read-only.** `ProtectSystem=strict` (RN-51) remonta toda la jerarquía del sistema como solo-lectura para el servicio, salvo lo declarado en `ReadWritePaths`, que hoy lista únicamente `/var/lib/fim-agent` y `/var/log/fim-agent`. Los `watch_paths` por defecto (`/etc`, `/bin`, `/usr/bin`) quedan afuera. Ninguna capability atraviesa un mount de solo-lectura: la escritura falla con `EROFS` con independencia de los privilegios del proceso.
2. **Chequeo DAC.** El servicio corre como `User=fim-agent` con `AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH`. `CAP_DAC_READ_SEARCH` habilita lectura y búsqueda, no escritura; `CAP_SYS_ADMIN` no exime de los chequeos de permisos DAC. Reemplazar un archivo cuyo dueño es `root` requiere `CAP_DAC_OVERRIDE`, y restaurar modo y propiedad desde la entrada de baseline (RN-30) requiere además `CAP_FOWNER` y `CAP_CHOWN`.

**Condición:** Todo despliegue del agente como servicio systemd nativo.

**Resultado:**

- **Capabilities**: `AmbientCapabilities` y `CapabilityBoundingSet` incorporan `CAP_DAC_OVERRIDE`, `CAP_FOWNER` y `CAP_CHOWN`. La expansión de privilegio marginal es baja: el servicio ya posee `CAP_SYS_ADMIN`, que es equivalente a root en la práctica. El valor real de `ProtectSystem=strict` no es contener a un atacante que ya controle el proceso, sino acotar el daño de un defecto del propio agente — por eso se conserva.
- **`ProtectSystem=strict` se mantiene.** `ReadWritePaths` deja de ser una lista fija: `install.sh` la deriva de los `watch_paths` declarados en `/etc/fim-agent/config.yaml` y la emite como drop-in de systemd (`/etc/systemd/system/fim-agent.service.d/10-watchpaths.conf`), preservando el unit base sin editar. Se descartó bajar a `ProtectSystem=full` porque dejaría `/usr/bin` en solo-lectura, es decir sin remediación posible sobre binarios del sistema — precisamente el escenario de un atacante que reemplaza un binario, que motiva la herramienta.
- **Preflight de escritura.** Al arrancar y en cada recarga de configuración (`update_config`), el agente verifica que cada `watch_path` sea escribible. Un path no escribible **no detiene al agente ni interrumpe el monitoreo**: se marca como solo-detección, se registra en el log y se reporta en el heartbeat. La detección es la función primaria; la remediación es una capacidad adicional que puede estar ausente sin invalidar el servicio.
- **Causa de fallo distinguible.** Un fallo de acción por falta de permiso de escritura se distingue de un fallo por baseline ausente o corrupto (`no_baseline_content`, `no_restorable_content`), de modo que el operador pueda diferenciar un problema de despliegue de un problema de datos. Compone con `Event.action_failed` (D35/RN-129).
- **`install.sh` no otorga al usuario del servicio la propiedad de su propio código.** `/opt/fim-agent` y `/etc/fim-agent` quedan bajo propiedad de `root` con permiso de lectura para `fim-agent`; sólo `/var/lib/fim-agent` y `/var/log/fim-agent` pertenecen al usuario del servicio. Hoy `install.sh` hace `chown -R fim-agent` sobre los tres, lo que permitiría a quien obtenga ese uid reescribir el código del agente y recibir `CAP_SYS_ADMIN` en el siguiente reinicio.
- Se actualizan en consecuencia las menciones a `ReadWritePaths` y al modelo de capabilities en [arquitectura_stack.md](arquitectura_stack.md), [flujo_de_usuario.md](flujo_de_usuario.md) y RN-51 de este documento.

**Excepciones:**
- **Limitación conocida — `watch_paths` agregados en runtime.** `ReadWritePaths` se materializa en el momento de la instalación; `update_config` cambia los `watch_paths` en caliente. Un path incorporado desde la interfaz queda **monitoreado pero no remediable** hasta que se re-ejecute la configuración privilegiada en el anfitrión (regeneración del drop-in y `systemctl daemon-reload`). Esta limitación es inherente a que el aislamiento de systemd se resuelve en el espacio de nombres de montaje al arrancar el servicio, no un defecto de implementación. El preflight la hace visible en lugar de silenciosa: el operador ve en la interfaz que ese path es solo-detección.
- La remediación automática sobre paths fuera de todo `watch_path` sigue prohibida por D18/RN-116; esta decisión no amplía el alcance de containment.

#### D37 / RN-131: Durabilidad del transporte — ack tipado, ventana de skew sobre `sent_at` y outbox de comandos

**Descripción:** La cola offline del agente (RN-38 a RN-41) no puede drenar nunca, y los comandos de aprobación y rechazo pueden perderse sin que nadie se entere. Son tres defectos con una raíz común: el transporte agente↔backend no tiene un contrato de durabilidad, sólo un camino feliz.

1. **Conflicto de especificación entre RN-90 y RN-38/RN-41.** RN-90 rechaza todo evento con `abs(received_at - detected_at) > 5 min`. RN-38 a RN-41 definen una cola en disco de 100 MB cuyo propósito explícito es sobrevivir una caída del backend. Las dos reglas se anulan: cualquier corte mayor a cinco minutos convierte el contenido íntegro de la cola en eventos irrecibibles. La cola de resiliencia sólo funciona mientras no haga falta.
2. **El rechazo no se comunica.** `_reject` inserta la auditoría y hace `XACK`, pero no publica `event_ack`. El agente sólo borra un evento de la cola cuando recibe ack, y republica todo lo no ackeado cada 60 segundos indefinidamente. Un evento rechazado queda en un ciclo permanente: se republica, se vuelve a rechazar, y cada vuelta agrega una fila a `rejected_events_audit`, tabla que ninguna política de retención toca.
3. **Los comandos de decisión no tienen outbox.** Sólo `rule_sync` es durable. `baseline_update`, `restore_file` y `quarantine_file` se publican de forma síncrona después del `commit`, con dos modos de pérdida: si falla la obtención del secreto compartido el publicador registra y retorna, y el endpoint responde `200` con el evento ya terminal y ningún comando emitido; si falla el `XADD` la excepción se propaga como `500` con el evento igualmente terminal. En ambos casos el operador cree haber restaurado un archivo que nadie tocó.

**Condición:** Todo evento publicado por un agente y todo comando emitido por el backend hacia un agente.

**Resultado:**

- **`sent_at` como base de la ventana de skew (enmienda RN-90).** El payload incorpora `sent_at`, sellado en el momento de publicar o republicar. La ventana de cinco minutos pasa a evaluarse sobre `sent_at`; `detected_at` permanece como verdad forense y **deja de tener ventana**. El propósito original de RN-90 —detectar un reloj adulterado o un replay— se conserva y hasta se afila, porque `sent_at` es el timestamp que un atacante tendría que falsificar para que un mensaje viejo parezca actual. Un evento legítimamente encolado durante un corte de horas llega con `detected_at` antiguo y `sent_at` reciente, y se acepta. **Esta cláusula prevalece sobre RN-90.**
- **Respuesta tipada a todo evento, con tres comportamientos según el motivo:**

  | Motivo | Respuesta | Efecto en el agente |
  |---|---|---|
  | ingesta exitosa · `duplicate_event` | `event_ack` | borra el evento de la cola |
  | `invalid_schema` (payload ilegible) · `clock_skew` | `event_nack` terminal | borra el evento de la cola y lo registra localmente |
  | `schema_version` mayor que el soportado | `event_nack` retenible con `retry_after` | **conserva** el evento y espera al backend |
  | `rate_limited` | `event_nack` con `retry_after` | **conserva** el evento y aplica backpressure |
  | `invalid_signature` · `unknown_agent` | sin respuesta | el evento caduca por el límite de reintentos |

- **Un evento excedido por rate limit nunca se destruye.** Un evento de integridad descartado es una detección perdida, y una tormenta de cambios es precisamente el momento en que un atacante se mueve. Ante `rate_limited` el agente deja de reintentar cada 60 segundos y frena la publicación hasta que haya presupuesto, conservando el evento en cola. El límite real de recursos sigue siendo el drop-oldest de los 100 MB de RN-40, que ya es una decisión tomada y acotada. **Esta cláusula prevalece sobre la frase "se descartan con alerta" de RN-88**, que además nunca se implementó: hoy no se emite ninguna alerta.
- **Sin respuesta para fallos de autenticación.** Un `invalid_signature` o un `unknown_agent` no permiten firmar una respuesta verificable ni identificar al destinatario, y responder convertiría al backend en un oráculo que confirma qué `agent_id` existen. El emisor caduca por su propio límite de reintentos.
- **Límite de reintentos por evento y cola de descarte local.** Un evento sin respuesta de ningún tipo no puede reintentarse para siempre. Superado el límite se mueve a un directorio local de descarte con su motivo, se contabiliza en el heartbeat y se deja de publicar.
- **Outbox para los comandos de decisión.** `baseline_update`, `restore_file` y `quarantine_file` pasan por el mismo outbox transaccional que ya usa `rule_sync`: la fila del comando se escribe en la misma transacción que la mutación del evento, y un despachador la publica después. Deja de existir el estado en que un evento es terminal y su comando no se emitió. Un fallo de publicación se vuelve un reintento del despachador, no una pérdida silenciosa ni un `500`.

- **`invalid_schema` distingue dos causas, y sólo una es terminal.** Un payload ilegible —claves faltantes, tipos inválidos, `schema_version` no parseable— es un defecto permanente: reintentar no lo arregla y el evento se descarta. En cambio un `schema_version` **mayor que el soportado** significa que el agente va adelantado respecto del backend: el evento es válido y el receptor todavía no sabe leerlo. Descartarlo destruiría eventos legítimos y convertiría todo bump futuro de esquema en un despliegue obligatoriamente backend-primero, bajo pena de pérdida de datos. Se responde con un nack retenible y el agente espera. `check_schema_version` deja de devolver un booleano y pasa a distinguir los dos casos.
- **Parámetros operativos.** Techo de reintentos por evento: **20** (con el reintento cada 60 s, cubre unas 20 horas de backend inalcanzable antes de descartar, holgadamente por encima de una ventana de mantenimiento). Techo del `retry_after` que el agente acepta del backend: **60 s** (impide que un backend comprometido o con un bug silencie a un agente indefinidamente mandándole un valor enorme). Cota del directorio local de descarte: **1000 archivos** con drop-oldest, mismo criterio que la cola de RN-40. Los tres son configurables; estos son los valores por defecto.

**Excepciones:**
- La ventana de skew sobre `sent_at` no protege contra un agente comprometido que sella `sent_at` con la hora actual: ese atacante controla el proceso y puede publicar lo que quiera. RN-90 nunca protegió contra eso; su alcance real es el mensaje capturado y reproducido por un tercero, y ese caso sigue cubierto.
- El backpressure no acota el crecimiento de la cola por sí solo: lo acota el drop-oldest de RN-40. Una tormenta sostenida más allá de los 100 MB pierde los eventos más antiguos, que es el comportamiento ya especificado y no se modifica acá.

#### D38 / RN-132: Rate limit de ingesta configurable y definición del tiempo de recuperación

**Descripción:** El límite de ingesta de eventos por agente (RN-88: 100 eventos/min) estaba fijado en el código. Eso vuelve **infalsable** el indicador "tiempo de recuperación tras reconexión < 30 s" del protocolo de evaluación: con 3.000 eventos encolados durante un corte y el límite vigente, el drenaje tarda unos 30 minutos, de modo que el umbral no se puede cumplir **ni refutar**. Un criterio que ningún resultado posible puede contradecir no es un criterio.

**Condición:** Configuración del backend y ejecución de las baterías de medición del capítulo de resultados.

**Resultado:**

- El límite y la ventana del rate limiter de ingesta se exponen como configuración (`Settings`), con **valores por defecto idénticos a los actuales** (100 eventos, ventana de 60 s). Esta decisión no cambia el comportamiento de producción: sólo lo hace observable y ajustable.
- **El "tiempo de recuperación" se define como el intervalo entre la reconexión del agente y el momento en que su cola local queda vacía con todos los eventos persistidos en el backend** — es decir, drenaje completo, no reconexión.
- Una corrida de medición **puede** elevar el límite para que el drenaje no quede dominado por el estrangulamiento artificial, y en ese caso **debe declarar el valor efectivo usado** junto al resultado. Un número de recuperación sin el límite con el que se obtuvo no es interpretable.
- El valor por defecto de producción no se modifica en función de las mediciones. Si una corrida sugiere que 100/min es inadecuado para una carga real, eso abre una decisión propia y no se resuelve subiendo el default de forma tácita.

**Excepciones:**
- El límite configurado no relaja ninguna otra garantía: los eventos que exceden el presupuesto siguen tratándose según D37/RN-131 —nack retenible con `retry_after` y backpressure, sin destruir el evento—, con lo cual un límite bajo alarga el drenaje pero **no pierde** eventos. Esa es justamente la propiedad que vuelve medible al indicador.

#### D39 / RN-133: Instantes con zona horaria explícita de punta a punta

**Descripción:** El sistema representa instantes de tres maneras incompatibles a la vez, y el resultado es que **toda la interfaz muestra las fechas corridas por el desfase horario local**. Son tres defectos encadenados:

1. **Las 19 columnas de fecha son `timestamp without time zone`.** El instante que guardan es UTC por convención, no por tipo: nada en el esquema lo declara.
2. **El código mezcla naive y aware** — 9 usos de `datetime.utcnow()` (naive) contra 25 de `datetime.now(timezone.utc)` (aware), escribiendo todos sobre las mismas columnas naive. Hoy no rompe **únicamente** porque la zona horaria de la sesión de PostgreSQL es UTC: es una dependencia implícita de configuración por debajo de la ventana anti-replay de RN-90/RN-131, que es un control de seguridad.
3. **La API serializa sin desfase**: `'2026-08-20T19:55:59.641248'`, sin `Z` ni offset. La especificación de ECMAScript obliga a interpretar una fecha-hora sin zona como **hora local**, de modo que `new Date(iso)` en el navegador desplaza cada instante por el desfase del operador. En Argentina (UTC−3) la consola muestra cada evento **tres horas más tarde** de lo ocurrido.

El caso más visible es la tarjeta del agente, que calcula `Date.now() - fecha`: con un latido recién recibido la resta da **negativo**. Para una consola forense, donde la correlación temporal es el instrumento principal, esto invalida la pantalla — y con ella los criterios de US-08 y US-21.

**Condición:** Toda persistencia, serialización y presentación de un instante.

**Resultado:**

- **Las 19 columnas migran a `timestamptz`.** PostgreSQL convierte in situ con `ALTER COLUMN ... TYPE timestamptz USING columna AT TIME ZONE 'UTC'`, que es exactamente la semántica correcta porque el contenido ya era UTC. El instante deja de depender de la configuración de la sesión.
- **Se elimina `datetime.utcnow()` del código.** Toda escritura usa `datetime.now(timezone.utc)`. `utcnow()` devuelve un naive que *aparenta* ser UTC y es la fuente de la mezcla; además está desaconsejado desde Python 3.12.
- **La API emite ISO-8601 con desfase explícito** (`...+00:00`). Ningún cliente vuelve a adivinar la zona de un instante.
- **El frontend deja de depender de la interpretación por defecto** y presenta en la zona del operador de forma deliberada. Los filtros de fecha (`datetime-local`, hora local del navegador) se convierten a UTC antes de enviarse: hoy se comparan crudos contra columnas UTC, con lo cual el rango filtrado no es el rango pedido.
- **La interfaz muestra siempre la zona junto a la hora**, y las horas absolutas se acompañan de la forma relativa donde ayuda a decidir («hace 4 min»). Un operador que correlaciona con `journalctl` o con un `.pcap` necesita saber contra qué reloj está leyendo.

**Excepciones:**
- No se altera la semántica de ninguna comparación existente: la ventana de skew de RN-90/RN-131, la retención de RN-98 y el barrido de comandos siguen operando sobre los mismos instantes. Lo que cambia es que dejan de depender de que la sesión esté en UTC.
- `detected_at` viaja en el payload del agente como cadena ISO y no cambia de formato: `_parse_datetime` ya normaliza a UTC-aware en la ingesta.

#### D40 / RN-134: Contrato canónico del payload de notificación (sobre plano)

**Descripción:** El payload que el backend emite hacia n8n adopta un **sobre plano**: los campos de
metadatos del sobre (`schema_version`, `notification_id`, `type`) son hermanos de los campos de
datos, no sus padres. La forma anidada (`{"type": ..., "data": {...}}`) queda **descartada**: el
receptor de laboratorio de la Batería 4 lee `alert_id`, `event_id`, `severity` y `path` al tope del
objeto (`scripts/receptor_webhook.py`), y los workflows de n8n leen `$json.body.<campo>` — anidar
rompería ambos y obligaría a re-correr la Batería 4 sin beneficio.

El contrato queda:

```json
{
  "schema_version": 1,
  "notification_id": "<uuid v4, estable a lo largo de toda la escalera de reintentos>",
  "type": "alert",
  "alert_id": 123,
  "event_id": "<uuid del agente>",
  "path": "/etc/passwd",
  "severity": "critical",
  "status": "pending",
  "action_taken": "auto_restored",
  "action_failed": false,
  "is_symlink": false,
  "agent_id": "<agent_id>",
  "process_pid": 4242,
  "process_uid": 0,
  "process_exe": "/usr/bin/curl",
  "detected_at": "...",
  "received_at": "...",
  "alert_created_at": "..."
}
```

**Condición:** Toda emisión de `_build_payload` en `modules/alerts/service.py`.

**Resultado:** El payload cumple RN-53, que exige `event_id`, path, severidad, **acción tomada**,
**contexto del proceso causante** (`process_pid`, `process_uid`, `process_exe`) y los timestamps
`detected_at` y `received_at`. Ninguno de esos campos requiere captura nueva: el modelo `Event` ya
los persiste. El nombre canónico del path es **`path`** — el que fija RN-53, el que usa el código y
el que leen los tres workflows.

El campo `type` discrimina las dos formas que hoy comparten una única URL de webhook: `"alert"` y
`"health_change"`. Sin él, n8n no puede distinguir una alerta de evento de una notificación de
cambio de salud.

**Excepciones:** `notification_id` es estable **entre reintentos de la misma notificación** y
distinto entre notificaciones — es la clave de deduplicación de D41/RN-135, no un identificador de
intento.

**Deroga:** el ejemplo de payload de `arquitectura_stack.md` (§«Integración con backend»), que usa
`file_path` y `timestamp`. RN-53 es la regla normativa y dice `path`; el ejemplo de arquitectura
queda alineado a este contrato.

#### D41 / RN-135: Idempotencia asimétrica de la entrega de notificaciones

**Descripción:** La entrega hacia n8n es **at-least-once**, no exactly-once, y el sistema lo asume
explícitamente. Un timeout del webhook no distingue «n8n no recibió» de «n8n recibió, ejecutó el
workflow y se perdió la respuesta»; con el enrutador operativo, cada reintento de la escalera
**vuelve a abanicar** hacia los canales.

La defensa es **asimétrica según el costo del duplicado**:

| Canal | Costo del duplicado | Defensa |
|---|---|---|
| Email | Molesto | Ninguna — se acepta at-least-once |
| Mensajería (Slack/Teams) | Molesto | Ninguna — se acepta at-least-once |
| Ticketing (Jira/Linear) | Contamina el backlog | **Search-before-create** por `event_id` en el sub-flujo |

**Condición:** Cualquier reintento de `notify_event` sobre una notificación ya emitida.

**Resultado:** El sub-flujo de ticketing consulta por `event_id` antes de crear y no crea un segundo
issue para el mismo evento. Los canales de mensajería y correo pueden entregar duplicados ante
reintento, y eso se declara como comportamiento conocido, no como defecto.

**Excepciones:** Ninguna. `notification_id` (D40/RN-134) viaja siempre para que un consumidor futuro
pueda deduplicar por su cuenta sin cambiar el contrato.

#### D42 / RN-136: Durabilidad de la escalera de reintentos de notificaciones

**Descripción:** La escalera `[5, 30, 120]` s deja de vivir en memoria. Hoy `notify_event` corre un
bucle `for` con `asyncio.sleep` dentro de una task fire-and-forget: la escalera dura hasta 155 s y,
si el proceso reinicia en esa ventana, la fila queda con `delivered_at IS NULL AND failed_at IS
NULL` para siempre — no entra a la DLQ, no aparece en el banner de RN-102, y nada la retoma.

El modelo `Alert` incorpora `next_retry_at: datetime | None` y `attempt: int`. `notify_event`
ejecuta **un** intento y agenda el siguiente escribiendo `next_retry_at`. Una tarea de barrido
`notification_dispatch_task()` corre en el lifespan de FastAPI y toma las filas con
`delivered_at IS NULL AND failed_at IS NULL AND next_retry_at <= now()`.

El patrón es el mismo que ya usa `outbox_publisher_task()` (H6) para el outbox de `rule_sync`:
poll periódico desde el lifespan, trabajo sync en threadpool, y la regla de que **el poller nunca
muere** — cualquier excepción se loguea y el ciclo continúa, porque matarlo anula la durabilidad.

**Condición:** Toda notificación disparada por RN-53.

**Resultado:** La garantía de entrega pasa a ser una propiedad del **sistema** y no de un proceso
vivo. Un reinicio del backend durante la ventana de reintentos ya no pierde la notificación.

Además:

- `retry_count` **acumula el total histórico** de intentos, en lugar de sobrescribirse con el índice
  del intento actual. Un reintento manual desde la DLQ **suma**, no resetea. Es lo que pide RN-86.
- `last_error` registra **el error real de cada canal**, no el genérico `"All channels failed on
  attempt N"`. RN-86 define `last_error` como el dato accionable de la DLQ; un mensaje que no dice
  qué falló no lo es.

**Excepciones:** Las filas huérfanas preexistentes (`delivered_at IS NULL AND failed_at IS NULL` sin
`next_retry_at`) las adopta el primer barrido tras el deploy.

#### D43 / RN-137: Health check de n8n con URL propia; sin webhook no hay canal configurado

**Descripción:** Dos correcciones al canal n8n, ambas de configuración.

**(a) `n8n_health_url` separada del webhook.** `_check_n8n` hace hoy fallback a `GET` sobre la misma
URL del webhook cuando `HEAD` devuelve 404/405 — y el propio docstring del código admite que «un GET
a un webhook productivo puede disparar el workflow n8n». Con el enrutador operativo, eso significa
que el health check puede emitir notificaciones espurias cada 10 s. Se incorpora
`n8n_health_url` a `Settings`, apuntando al `/healthz` de n8n, y el check deja de tocar el webhook.

**(b) Sin `n8n_webhook_url` explícito, el canal no está configurado.** Se elimina el default
`${N8N_WEBHOOK_URL:-http://n8n:5678/healthz}` del `docker-compose.yml`. Ese default apunta el canal
principal a un endpoint de salud que responde 200 a cualquier POST, con lo cual `send_n8n` retorna
`True` y la alerta se marca `delivered` con `channel="n8n"` sin que nadie haya recibido nada.

Las ocho variables de notificación (`n8n_webhook_url`, `n8n_health_url`, `smtp_*`,
`webhook_fallback_url`) se declaran en `.env.example`, para que configurarlas no exija editar el
compose.

**Condición:** Siempre.

**Resultado:** Un deploy limpio reporta el canal n8n como **no configurado**, no como falsamente
sano. El health check no puede disparar workflows.

**Excepciones:** `send_smtp` deja de forzar `start_tls=True` incondicionalmente — se incorporan
`smtp_starttls` y `smtp_ssl` a `Settings`, porque un relay en 465 (SMTPS implícito) o uno interno
sin STARTTLS falla siempre con el comportamiento actual.

#### D44 / RN-138: n8n como enrutador único `fim-alert` con sub-flujos invocados

**Descripción:** n8n expone **un solo webhook**, `fim-alert`, coherente con lo documentado en
`arquitectura_stack.md`. Ese workflow enrutador recibe el payload de D40/RN-134, discrimina por
`type`, y abanica por severidad y por configuración del administrador hacia los sub-flujos de correo,
mensajería y ticketing.

Los tres workflows existentes dejan de ser webhooks y pasan a `Execute Workflow Trigger`. La decisión
es estructural, no cosmética: mientras haya tres webhooks paralelos con tres paths distintos y el
backend tenga una sola `n8n_webhook_url`, como mucho **uno** puede recibir tráfico y los otros dos
son inalcanzables por construcción. Con sub-flujos invocados, esa divergencia deja de ser posible.

Esto materializa el rol que RN-52 ya le asigna a n8n — **«enrutador acotado»** — y que hoy no tiene
implementación: ningún workflow recibe una vez y abanica.

**Condición:** Toda notificación emitida por el backend.

**Resultado:** Un `POST` a `/webhook/fim-alert` entrega a los canales que el administrador configuró.

**Excepciones:** El provisioning es **idempotente por `id`**: cada workflow lleva un UUID estable en
la raíz del JSON, y `n8n import:workflow` sobrescribe la entrada existente con el mismo `id` en vez
de duplicarla. Un servicio one-shot del compose monta `./n8n/workflows` y corre el import contra el
volumen `n8n_data`.

**Limitación conocida:** `n8n import:workflow --activeState` tiene default `false` — todo lo
importado queda **desactivado**, y un workflow inactivo sólo responde en la URL de prueba
`/webhook-test/...`, no en `/webhook/...`. La variante `--activeState=fromJson` está documentada
únicamente para *multi-main* y *queue mode*, y el despliegue es single-instance por RN-76. El
provisioning debe **verificar la activación efectiva**, no asumirla: importar sin activar produce un
404 en el primer POST del backend aun con todo lo demás correcto.

#### D45 / RN-139: Pin de n8n en 2.17.8 y setup de owner por variables de entorno

**Descripción:** El pin de n8n sube de **2.16.1** a **2.17.8**, y el setup de owner de la instancia pasa
a resolverse por variables de entorno en lugar de un procedimiento manual.

**Motivo.** n8n 2.x exige completar el setup de owner en el primer arranque **antes** de poder activar
un workflow, y un workflow inactivo sólo responde en la URL de prueba `/webhook-test/...`, no en
`/webhook/...`. Con el puerto 5678 sin publicar por D-04, no existe camino de UI para completarlo. El
mecanismo declarativo —`N8N_INSTANCE_OWNER_MANAGED_BY_ENV` junto con `N8N_INSTANCE_OWNER_EMAIL`,
`N8N_INSTANCE_OWNER_FIRST_NAME`, `N8N_INSTANCE_OWNER_LAST_NAME` y `N8N_INSTANCE_OWNER_PASSWORD_HASH`—
está documentado **a partir de n8n 2.17.0**, de modo que en 2.16.1 ese camino no existe.

Se elige **2.17.8**: la patch más alta de la **mínima** minor que incorpora la capacidad. Subir lo
mínimo necesario acota la superficie de cambio; tomar su última patch evita arrastrar defectos ya
corregidos dentro de esa misma minor. La existencia del tag está verificada contra el registro de
imágenes.

**Condición:** Despliegue del servicio `n8n` del `docker-compose.yml`.

**Resultado:** El provisioning queda completamente automático y reproducible: el contenedor arranca
con el owner ya establecido, el import de workflows corre sin intervención, y no queda ningún paso
manual en el camino crítico de un despliegue limpio. Esto es lo que permite que un evaluador levante
el stack y vea la integración funcionando sin instrucciones fuera de banda.

`N8N_INSTANCE_OWNER_PASSWORD_HASH` SHALL recibir un hash **bcrypt**; un valor en texto plano rompe el
login sin error explícito. El correo del owner no puede pertenecer a otro usuario de la instancia.

**Excepciones y limitaciones conocidas:**

- Con `N8N_INSTANCE_OWNER_MANAGED_BY_ENV` en `true`, n8n **sobrescribe los datos del owner en cada
  arranque**, bloquea el control de ese usuario en la UI y rechaza escrituras por API sobre él. Es
  deseable acá —el estado del owner queda declarado en el compose y no deriva—, pero significa que
  el owner deja de ser editable desde la interfaz.
- La corrección de este pin **no se propaga a los registros de medición del Capítulo 5**. Las corridas
  documentadas en `docs/entrega_valores_cap5.md` y `docs/plan_medicion_cap5.md` se ejecutaron contra
  **2.16.1**, y esos documentos registran lo que efectivamente se midió. Reescribirlos convertiría un
  registro en una afirmación falsa. **El cambio de versión debe declararse** en el capítulo, junto con
  la observación ya pendiente de que la Batería 4 se midió contra un receptor de laboratorio y no
  contra n8n.

**Reglas afectadas:** el requisito de versiones pinneadas de la spec `infra-compose` y el §Stack de
`arquitectura_stack.md` pasan a declarar `n8nio/n8n:2.17.8`. La prohibición de `latest` y de rangos
abiertos se mantiene sin cambios.

#### D46 / RN-140: Backend fanotify propio en modo FID; se abandona `pyfanotify`

**Descripción:** La detección de cambios NO usa `pyfanotify`. El agente implementa un backend
propio sobre syscalls crudas (`agent/_fanotify.py`, `ctypes` → glibc) y opera en **modo FID**, con
`FAN_REPORT_DFID_NAME`.

**Motivo — y es una imposibilidad técnica, no una preferencia.** El modo fd clásico
(`FAN_CLASS_NOTIF` sin FID) **no admite** los eventos de entrada de directorio `FAN_CREATE`,
`FAN_DELETE` y `FAN_MOVED_*` sobre una marca de filesystem: el kernel responde `EINVAL`. Como
RN-110 exige exactamente esas máscaras, el requisito previo —que mandaba `pyfanotify` y prohibía
`FAN_REPORT_DFID_NAME`— **se contradecía a sí mismo**: pedía eventos que su propio mecanismo no
puede entregar. No era una decisión superada por el tiempo; era irrealizable desde su redacción.

El modo FID además permite reconstruir el path de un archivo **ya borrado**, porque el kernel
reporta el handle del directorio padre más el nombre — algo imposible cuando sólo se tiene un fd
del objeto, que para entonces ya no existe. Eso es lo que hace viable el evento `file_absent`.

**Condición:** Arranque del detector del agente.

**Resultado:** El detector inicializa el grupo fanotify con `FAN_CLASS_NOTIF | FAN_REPORT_DFID_NAME`
y resuelve los paths vía `open_by_handle_at(2)`.

Consecuencia operativa: `open_by_handle_at(2)` exige **`CAP_DAC_READ_SEARCH` además de
`CAP_SYS_ADMIN`**. La unidad `fim-agent.service` declara
`CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN` en
`AmbientCapabilities` y `CapabilityBoundingSet`; las tres últimas las requieren las acciones de
restauración y cuarentena sobre archivos ajenos.

**Excepciones:** El módulo sólo es funcional en Linux con kernel ≥ 5.1. En otras plataformas la
importación degrada a `_HAS_FAN=False` y el detector lo contempla.

**Por qué esta decisión aparece recién ahora.** El reemplazo se hizo en el commit `f1e8681`
(*feat(agent): backend fanotify propio (ctypes, modo FID) reemplaza pyfanotify*) y **se documentó**
en `docs/operations.md` y en `docs/valores_planillas_cap5.md`. Lo que no se actualizó fueron las
reglas de negocio, el stack de arquitectura y las specs de OpenSpec — y las specs del agente
llevaban meses vaciadas por archives defectuosos (ver D47/RN-141), así que su contradicción con el
código era literalmente invisible para el tooling. El desalineamiento se detectó al recuperarlas.

**Reglas modificadas por esta decisión:** RN-01 y RN-110 dejan de nombrar `pyfanotify` y de
prohibir el reporte FID.

#### D47 / RN-141: Integridad estructural de las main specs de OpenSpec

**Descripción:** Toda main spec bajo `openspec/specs/<capability>/spec.md` SHALL tener título de
nivel 1, sección `## Purpose` y sección `## Requirements`, y SHALL NOT contener encabezados de
delta (`## ADDED Requirements` y equivalentes), que sólo son válidos dentro de
`openspec/changes/<name>/specs/`.

Además, el conjunto de requisitos de una main spec SHALL incluir todo requisito que sus deltas
archivados aportaron y que no fue eliminado con un `## REMOVED Requirements` explícito ni
renombrado de forma declarada.

**Motivo:** un encabezado de delta dentro de una main spec **trunca la sección `## Requirements`**;
el parser deja de ver lo que sigue. Llegó a haber 29 specs así, con 110 requisitos invisibles para
`validate`, `list` y `archive`. Peor: varios archives escribieron la main spec copiando el delta
verbatim, y lo que el delta no mencionaba **desapareció** — 48 requisitos borrados en 9
capabilities, dos de las cuales nunca llegaron a tener main spec. Ninguna herramienta lo señaló: un
`validate` en verde sobre una spec truncada no dice «esto está bien», dice «no vi nada».

**Condición:** Antes de cada `openspec archive`, y en la suite de tests.

**Resultado:** `scripts/check_spec_integrity.py` verifica las invariantes **por archivo** —nunca
sobre un total agregado, donde una pérdida se cancelaría con una ganancia ajena— y falla nombrando
capability y requisito. `backend/tests/test_openspec_artifact_integrity.py` lo ejecuta en la suite.

**Excepciones:** Los renombres hechos vía `MODIFIED` con el header cambiado —el proyecto nunca usó
`## RENAMED Requirements`— se declaran en `CONFIRMED_RENAMES` dentro del script, con evidencia del
delta de origen. Sin ese mapa la guarda exigiría requisitos legítimamente renombrados.

**Nota sobre la causa raíz:** al menos un archive dañino (commit `5355465`) fue **escrito a mano**,
sin invocar el CLI. Por eso la guarda vive fuera del CLI y se corre como paso de proceso: ningún
arreglo de la herramienta habría prevenido ese caso.

#### D49 / RN-143: `process_uid` nulo significa atribución no resuelta, nunca root

**Descripción:** El campo `process_uid` de un evento SHALL valer `null` cuando el agente no pudo
resolver el usuario del proceso causante. El valor `0` SHALL significar exclusivamente que el
proceso causante corría como root. Lo mismo aplica a `process_pid` y `process_exe` en la ruta de
rehidratación, donde el proceso original ya no existe por definición.

**Motivo:** el agente lee el usuario de `/proc/<pid>/status`, y ese archivo desaparece en cuanto el
proceso termina. Entre la detección y el armado del evento hay hasta 150 ms de reintentos de hash,
así que un proceso corto —un editor que escribe y sale, un `install`, un paso de paquete— **ya no
existe** cuando se lo consulta. Devolver `0` en ese caso no es un default conservador: es una
**atribución falsa**, y la más grave posible, porque nombra a root. Un operador que filtra por
`uid = 0` para buscar cambios privilegiados recibe una lista contaminada con todo cambio cuyo autor
el sistema no supo identificar, sin ninguna marca que los distinga. La ruta de rehidratación es peor
todavía: ahí el `0` era incondicional, de modo que **todo** evento recuperado del journal tras un
reinicio se reportaba como hecho por root.

La consecuencia documental es directa: sin esta regla, toda afirmación de la tesis sobre la
fiabilidad de la atribución de procesos sería falsa, porque el sistema no distingue «fue root» de
«no sé quién fue».

**Condición:** Armado de todo evento que lleve contexto de proceso, tanto en la ruta de detección en
vivo como en la rehidratación del journal.

**Resultado:** El agente emite `process_uid: null`. El backend ya lo acepta —la columna es
`int | None`— y la UI ya omite el contexto de proceso cuando los tres campos son nulos, sin
renderizar guiones ni vacíos. No hace falta migración.

**Excepciones:** Ninguna. No existe un valor de reemplazo aceptable: cualquier entero que se elija
colisiona con un uid real.

#### D50 / RN-144: Una brecha de detección del kernel se reporta como evento, no sólo como métrica

**Descripción:** Cuando el kernel notifica desbordamiento de la cola de `fanotify`
(`FAN_Q_OVERFLOW`), el agente SHALL emitir un evento sintético de tipo `detection_gap` por el mismo
stream que los eventos normales, con `path` nulo y la causa en su metadato. El evento SHALL
atravesar el pipeline completo —motor de decisión, backend, UI— de modo que un operador vea que
hubo una ventana en la que el sistema **no puede garantizar cobertura**.

**Motivo:** el desbordamiento de la cola del kernel es el único modo de falla del sistema que es
silencioso por construcción. El kernel descarta eventos y sigue; el agente, que nunca los recibe, no
tiene forma de inferir que faltaron. El contador `event_drops` que ya existe **no cubre esto**: mide
la cola interna del agente, un punto de pérdida posterior, cuando el evento ya salió del kernel.

Reportarlo sólo como métrica del heartbeat no alcanza. Una métrica se mira cuando alguien sospecha;
un evento aparece en la bandeja de trabajo del operador y fuerza el triage. Y la asimetría importa:
un `detection_gap` no dice «cambió un archivo», dice «entre estos dos instantes pude haber perdido
cambios». Es una afirmación sobre la confianza en el resto de la evidencia, y por eso tiene que
viajar por el mismo canal que la evidencia.

**Condición:** Lectura de eventos de `fanotify` en el hilo lector del detector.

**Resultado:** Se emite un evento con `event_type: "detection_gap"`, `path: null`, causa
`fan_q_overflow` y contexto de proceso nulo —no hay proceso causante que atribuir—. El motor de
reglas no puede restaurar ni poner en cuarentena algo sin ruta, de modo que la acción SHALL ser
`alert_only` y el evento SHALL llegar a la UI en estado `alert_only`.

**Deduplicación — por ventana, no por desbordamiento.** Bajo saturación sostenida el kernel emite
`FAN_Q_OVERFLOW` repetidamente. El agente SHALL emitir a lo sumo **un** `detection_gap` por ventana
de 60 segundos, contando los desbordamientos suprimidos y reportando esa cuenta en el evento. Sin
este criterio, la respuesta del sistema a estar bajo presión sería inundar la tabla de eventos justo
cuando menos capacidad hay para procesarla — el evento diagnóstico se volvería una segunda falla.

**Excepciones:** En plataformas sin `fanotify` funcional el detector ya degrada y no emite eventos
de ningún tipo; tampoco emite `detection_gap`.

#### D51 / RN-145: `event_type` persistido, `path` opcional y severidad de eventos sin ruta

**Descripción:** El modelo `Event` del backend SHALL persistir `event_type` con el vocabulario
cerrado que el agente ya emite (`file_created`, `file_modified`, `file_deleted`, `file_absent`,
`detection_gap`), en minúsculas snake_case conforme a RN-71, y SHALL exponerlo en la API y en el
frontend. La columna `path` SHALL admitir nulo. Un evento sin ruta SHALL NOT participar de la
supersesión por path.

**Motivo — hay un campo que ya viaja y el backend lo tira.** El agente emite `event_type` en todo
payload desde siempre; el backend nunca lo persistió y la UI nunca lo vio. No es un campo nuevo: es
dejar de perder uno existente. Mientras todos los eventos hablaban de un archivo concreto, la ruta
alcanzaba como discriminador y la pérdida no se notaba. Un `detection_gap` rompe esa suposición: sin
`event_type` persistido, un evento sin ruta llega a la UI indistinguible de cualquier otro, y la
decisión D50/RN-144 queda sin efecto observable.

**El nulo no puede degradarse a cadena vacía.** La ingesta convertía un `path` ausente en `""`. Esa
cadena vacía no es inerte: es la clave con la que el backend busca el evento `pending` anterior para
supersedirlo. Con `""`, **todos** los `detection_gap` se supersederían entre sí como si fueran el
mismo archivo, y cada nueva brecha borraría la anterior de la vista del operador — exactamente el
dato que la decisión anterior existe para preservar. Por eso el nulo tiene que llegar nulo hasta la
columna, y la supersesión por ruta tiene que excluir explícitamente a los eventos sin ruta.

**Condición:** Ingesta de todo evento en el backend.

**Resultado:** `Event.event_type` es `str` no nulo con default `file_modified` para filas previas a
la migración; `Event.path` es `str | None`; la búsqueda de `pending` por ruta y la compactación de
cadena se saltean cuando la ruta es nula, de modo que cada `detection_gap` sobrevive como registro
independiente.

**Severidad de un evento sin ruta — excepción acotada a D34/RN-128.** El backend sigue siendo la
única autoridad sobre la severidad, y la sigue calculando al ingerir. Pero la lógica vigente la
deriva de las reglas que matchean la ruta, y un evento sin ruta no matchea ninguna: caería en `low`,
que es lo contrario de lo que significa. Un evento sin ruta SHALL recibir severidad `high` de forma
fija, sin consultar el ruleset. La excepción es deliberadamente estrecha —se dispara por ausencia de
ruta, no por tipo de evento— para que no haya que tocarla cada vez que aparezca un tipo nuevo, y
sigue siendo el backend quien decide: el valor que el agente proponga se ignora, igual que hoy.

`high` y no `critical`: una brecha de detección es una pérdida de garantía, no una violación de
integridad confirmada. Reservar `critical` para lo confirmado mantiene informativa a la severidad
máxima.

**Excepciones:** Ninguna. El vocabulario de `event_type` se persiste sin validación contra enum, con
el mismo criterio de tolerancia hacia adelante que `action` y `action_error` (D33, D36/RN-130): un
valor desconocido emitido por un agente más nuevo se guarda tal cual en vez de rechazar el evento.

#### D48 / RN-142: Recuperación administrativa de certificados vencidos

**Descripción:** `POST /agents/renew` acepta únicamente un certificado cliente vigente, firmado por
la CA propia, con CN coincidente y no revocado. El listener conserva `CERT_REQUIRED` y TLS 1.3
mínimo; un certificado vencido se rechaza durante el handshake, sin ventana de gracia.

**Motivo — hoy un agente vencido no tiene camino de vuelta.** Verificado contra el código:

| Camino | Resultado |
|---|---|
| Renovar | El handshake mTLS rechaza el certificado vencido antes de llegar a la aplicación |
| Re-bootstrapear | `bootstrap_agent` destruye el secret al consumirlo (`agents/service.py:80`, `bootstrap_secret_hash = None`) → `401` |
| Re-registrar | `register_agent` devuelve `409` si el agente ya existe (`agents/service.py:35-39`) |

La única recuperación es escribir a mano en la base. Y el fondo es peor que la conectividad: el
`master_secret` **no se persiste en el backend** —vive sólo en `AgentBootstrapResponse`, nunca en la
tabla `Agent`, porque D1 hace al agente custodio único del contenido—, de modo que **el backend no
puede devolver el anterior**. Cualquier re-bootstrap emite uno nuevo, y de ahí sale por HKDF-SHA256
la clave AES-256-GCM del baseline: recuperar así un agente **le destruye la línea base y su historial
de integridad**, obligando a un re-scan donde todo archivo aparece como nuevo.

**Fundamento de seguridad.** La disponibilidad posterior al vencimiento no justifica relajar la
validación del transporte. El agente debe renovar dentro de los 15 días previos al vencimiento. Si
no lo hace, la recuperación es administrativa y fail-closed.

**Condición:** Cada solicitud a `POST /agents/renew`.

**Resultado:** Un certificado vigente dentro del umbral puede renovarse automáticamente. Una vez
vencido, la recuperación exige verificar administrativamente la identidad y preservar el
`master_secret` existente; si se entrega uno nuevo, debe realizarse y documentarse un re-baseline.

**Excepciones:** Ninguna. No se configura `CERT_OPTIONAL` ni una excepción temporal en la aplicación.

**Reglas afectadas:** complementa RN-78 (rotación de certificados) definiendo qué ocurre cuando la
rotación no llegó a tiempo. No altera el período de validez.

#### D52 / RN-146: Bootstrap de agentes en un listener TLS dedicado (8444), sin certificado de cliente

**Descripción:** `POST /agents/bootstrap` SHALL dejar de exponerse en el listener HTTP plano de la
API (puerto 8000). El backend SHALL levantar un tercer listener uvicorn en el puerto 8444,
autenticado únicamente con el certificado de servidor del backend (TLS 1.3, sin exigir certificado
de cliente), y SHALL montar allí el único router que sirve `/agents/bootstrap`. El listener 8443
(`CERT_REQUIRED`) SHALL seguir sirviendo exclusivamente `/agents/renew`. El agente SHALL rechazar,
con `sys.exit(1)` y sin abrir conexión de red, cualquier `backend_url` cuyo esquema no sea `https`.

**Motivo — RN-114 exigía HTTPS, pero el despliegue real servía bootstrap en claro.** `POST
/agents/bootstrap` sólo vivía en el `router` montado sobre la app principal, servida por
`uvicorn app.main:app --port 8000` sin TLS (`backend/Dockerfile`). El listener 8443 exige
`ssl.CERT_REQUIRED`: un agente que recién arranca todavía no tiene certificado propio y no puede
completar ese handshake, así que no podía bootstrapear ahí. Detectado por lectura de código al
preparar el ensayo multi-host A-3, antes de ejecutar ningún bootstrap entre equipos: la respuesta de
bootstrap —que lleva `shared_secret_hex` y `master_secret_hex` (`AgentBootstrapResponse`)— habría
viajado sin cifrar por la LAN. RN-114 exige TLS con `ca_cert_path` como
trust anchor y prohíbe `verify=False`; nada en el código lo hacía cumplir mientras `backend_url`
siguiera apuntando a `http://`.

**Por qué un listener nuevo y no reusar 8443.** Exigir certificado de cliente en el mismo handshake
que emite el primer certificado es circular — el agente todavía no lo tiene. Relajar 8443 a
`CERT_OPTIONAL` degradaría la garantía de RN-78 para `/agents/renew`, que sí debe seguir exigiendo
identidad criptográfica del agente ya enrolado. Un listener separado en 8444, autenticado solo por el
certificado de **servidor**, resuelve la asimetría sin tocar la política de 8443: el canal queda
cifrado y con el backend autenticado —evita MITM pasivo e inyección de un CA ajeno en la respuesta,
mismo razonamiento que D16—, aunque el agente todavía no pueda presentar credencial propia.

**Condición:** Arranque del backend (levanta el listener 8444 si `backend_cert_path` /
`backend_key_path` existen, mismo criterio que 8443) y cada `POST /agents/bootstrap` del agente.

**Resultado:** La app principal (puerto 8000) responde 404/405 a `POST /agents/bootstrap`. La app de
bootstrap (puerto 8444, TLS 1.3, sin certificado de cliente) es la única que la sirve.
`agent/bootstrap.py` valida el esquema de `backend_url` antes de generar el CSR o intentar cualquier
request; con un esquema distinto de `https` termina con `sys.exit(1)` y un mensaje explícito, sin
llamar a `httpx.post`.

**Excepciones:** Ninguna. No se agrega una bandera para reactivar bootstrap en el puerto 8000 ni para
aceptar un `backend_url` que no sea `https`.

**Reglas afectadas:** cierra el incumplimiento de RN-114 (trust anchor TLS del bootstrap) detectado en
el despliegue real; no modifica RN-78 (rotación/mTLS de `/agents/renew`), que sigue en el puerto 8443
con `CERT_REQUIRED`.

**Nota de proceso:** esta decisión y su implementación se ejecutaron inline, sin change de OpenSpec,
por decisión explícita del responsable del proyecto — es una corrección de seguridad acotada sobre un
incumplimiento ya normado (RN-114), no una feature nueva del roadmap.

### Decisiones técnicas referenciadas en otros documentos

Las siguientes decisiones cierran suposiciones del roadmap pero su contenido es puramente técnico/operativo y se documenta en [arquitectura_stack.md](arquitectura_stack.md) bajo el mismo appendix:

- **D3**: Lifespan de FastAPI ejecuta `seed_admin()` y `create_all()`; se elimina el init-container `db-init` del compose.
- **D7**: Cross-cutting (logging sanitizado, rate limiting, `trace_id`) se introduce en el primer change que lo requiere, no se centraliza al final del roadmap.

### Reglas modificadas por este appendix

Este appendix **modifica** el comportamiento descrito en las siguientes reglas previas. Las versiones originales quedan derogadas:

| Regla original | Reemplazada/refinada por |
|----------------|--------------------------|
| RN-17 (approve consulta hash al agente) | D2 (approve usa hash del evento; cadena de eventos garantiza consistencia) |
| RN-86 (referencia a `failed_notifications` separada) | D6 / RN-107 (tabla unificada `alerts`) |
| RN-102 (banner amarillo basado en `failed_notifications`) | D6 / RN-107 (banner amarillo basado en `alerts WHERE delivered_at IS NULL AND failed_at IS NOT NULL`) |
| RN-75 (versión monotónica solamente) | D5 / RN-106 (versión monotónica + `target_agent_id` + semántica de `ruleset_version_applied`) |
| Payload de notificación con `file_path` / `timestamp` (ejemplo de `arquitectura_stack.md`) | D40 / RN-134 (sobre plano; `path` canónico según RN-53; contexto de proceso obligatorio) |
| RN-86 (escalera de reintentos en memoria) | D42 / RN-136 (`next_retry_at` + `attempt` persistidos + barrido en el lifespan) |
**Excepciones:** Si `postgres` está `down`, el backend retorna 503 a la mayoría de endpoints — la UI refleja esto con mensajes inline. Si un agente está `draining`, los botones de re-scan / update config quedan deshabilitados (RN-93).
