# agent-decision-engine Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.

## Requirements

### Requirement: Cache local de reglas con evaluación glob y negación

El agente SHALL mantener una cache local de reglas de decisión (`RulesCache`) que se actualiza al recibir un comando `rule_sync` firmado con HMAC y `ruleset_version` monotónico mayor o igual al aplicado actualmente; una versión igual a la aplicada es un replay seguro e idempotente y MUST reaplicarse sin error. Solo se descartan comandos con `ruleset_version` estrictamente menor al aplicado (RN-75: «descarta mensajes con versión menor»). Esto alinea la cache de reglas con la ruta de comandos (`agent/commands.py`, que ya usa `<`) y garantiza idempotencia ante re-entregas (RN-75, RN-79). La cache MUST persistirse bajo la clave `"rules"` en `/var/lib/fim-agent/state.json` (escritura atómica via `.tmp` + `os.replace()`). Al evaluar un evento, el sistema SHALL iterar las reglas en orden de declaración usando `fnmatch.fnmatch`: si alguna regla con prefijo `!` matchea el path, el resultado es `alert_only` sin importar las reglas inclusivas previas (exclusiva gana, RN-65). Si solo reglas inclusivas matchean, la primera en orden determina la acción. Si ninguna matchea, el resultado es `alert_only` (RN-06). La cache MUST ser thread-safe para lecturas concurrentes.

#### Scenario: Regla inclusiva matchea — acción aplicada

- **WHEN** el path `/etc/hosts` se evalúa contra la regla `{"pattern": "/etc/**", "action": "auto_restore"}`
- **THEN** la evaluación retorna `action: "auto_restore"`

#### Scenario: Regla exclusiva matchea — alert_only

- **WHEN** el path `/etc/mtab` se evalúa contra reglas `[{"pattern": "/etc/**", "action": "auto_restore"}, {"pattern": "!/etc/mtab", "negated": true}]`
- **THEN** la evaluación retorna `action: "alert_only"` porque la regla exclusiva gana

#### Scenario: Sin regla que matchee — default alert_only

- **WHEN** el path `/tmp/foo.txt` se evalúa y no hay regla que lo cubra
- **THEN** la evaluación retorna `action: "alert_only"` (RN-06)

#### Scenario: rule_sync con versión menor descartado

- **WHEN** el agente tiene `ruleset_version: 5` y recibe un `rule_sync` con `ruleset_version: 3`
- **THEN** el comando es descartado sin actualizar la cache y sin confirmar vía `event_ack`

#### Scenario: rule_sync con versión igual reaplicado idempotentemente

- **WHEN** el agente tiene `ruleset_version: 5` y recibe un `rule_sync` re-entregado con `ruleset_version: 5` y HMAC válido
- **THEN** el comando NO es rechazado: la cache se reaplica con las mismas reglas, `ruleset_version` permanece en 5, y el agente confirma vía `event_ack` (replay idempotente, RN-75)

#### Scenario: rule_sync válido — cache actualizada y persistida

- **WHEN** el agente recibe un `rule_sync` con `ruleset_version: 6` (mayor al actual) y HMAC válido
- **THEN** la cache se reemplaza con las nuevas reglas, `ruleset_version` en `state.json` se actualiza a 6, y el agente publica `event_ack`

#### Scenario: Cache vacía al arrancar — alert_only por defecto

- **WHEN** el agente arranca sin `rules` en `state.json`
- **THEN** todos los eventos se evalúan como `alert_only` hasta recibir el primer `rule_sync`

### Requirement: Motor de decisión con journal transaccional pre/post-acción

El `DecisionEngine` SHALL evaluar cada `DetectedChange` contra la `RulesCache`, ejecutar la acción correspondiente y registrar el resultado en el journal. Antes de ejecutar cualquier acción (incluido `alert_only`), MUST escribirse una entrada de journal con `state: "pending"` en `/var/lib/fim-agent/journal/{event_id}.json`. Tras ejecutar la acción física, `evaluate_and_act` MUST NOT marcar el estado terminal del journal de forma inmediata: en su lugar retorna, junto al payload del evento, un callable `commit_fn` que aplica la transición terminal (`completed` o `failed`). El caller (detector) MUST invocar `commit_fn()` únicamente después de que `await publisher.publish(...)` retorne sin excepción. Si el publish falla, la entrada permanece `pending` y se rehidrata al reiniciar (FA3, RN-75). El evento MUST publicarse al stream (vía publisher) independientemente del resultado de la acción. Si la acción falla, el payload del evento MUST incluir `action_failed: true`.

#### Scenario: Evaluación y acción completan exitosamente

- **WHEN** un evento con path `/etc/hosts` (acción `auto_restore`) es procesado por el motor
- **THEN** se escribe journal `{state: "pending"}`, se ejecuta la restauración, se retorna `commit_fn`, el detector publica el evento con `action: "auto_restore"`, y solo tras un publish exitoso `commit_fn()` marca journal `{state: "completed"}`

#### Scenario: Publish falla — la entrada permanece pending y se rehidrata

- **WHEN** la acción física completa pero `publisher.publish(...)` lanza excepción antes de invocar `commit_fn`
- **THEN** la entrada de journal permanece `{state: "pending"}` y es devuelta por `load_pending` al reiniciar para re-publicación

#### Scenario: Acción falla — journal failed tras publish, evento publicado igual

- **WHEN** la restauración de `/etc/passwd` falla porque `content_b64` es `None` en baseline
- **THEN** el evento se publica con `action_failed: true` y, tras el publish exitoso, `commit_fn()` marca el journal `{state: "failed", error: "no_baseline_content"}`

#### Scenario: alert_only — journal y publicación sin acción física

- **WHEN** un evento para `/var/log/app.log` es evaluado y no hay regla (default `alert_only`)
- **THEN** se escribe journal `{state: "pending"}` sin ejecutar acción física, el evento se publica normalmente, y tras el publish exitoso `commit_fn()` marca el journal `{state: "completed"}`

### Requirement: Acción auto_restore — restauración desde baseline

Cuando la acción determinada es `auto_restore`, el `DecisionEngine` SHALL leer el `content_b64` del `BaselineEntry` para el path afectado (vía `BaselineEngine.read_entry(path)`), decodificarlo de Base64, escribirlo en el path original (atomicamente via `.tmp`), y verificar que el SHA-256 del archivo restaurado coincide con `entry.hash` (RN-30, RN-31). Si la verificación es exitosa, el evento MUST publicarse con `event_type: "auto_restored"`. Si `content_b64` es `None` (archivo binario u oversize), la acción MUST fallar gracefully con `error: "no_baseline_content"` en el journal (RN-32, RN-33).

#### Scenario: Restauración exitosa — hash verificado

- **WHEN** `/etc/hosts` fue modificado y el baseline tiene `content_b64` válido con hash `abc123`
- **THEN** el archivo es restaurado, su SHA-256 coincide con `abc123`, el journal queda `completed`, y el evento se publica con `event_type: "auto_restored"`

#### Scenario: Restauración con verificación fallida — falla reportada

- **WHEN** el archivo restaurado tiene SHA-256 diferente al `entry.hash` del baseline
- **THEN** el journal queda `failed` con `error: "hash_mismatch_after_restore"` y el evento se publica con `action_failed: true`

#### Scenario: Baseline sin content_b64 — falla graceful

- **WHEN** el baseline para `/bin/ls` tiene `content_b64: null` (archivo binario)
- **THEN** la restauración no se intenta, journal queda `failed` con `error: "no_baseline_content"`, evento publicado con `action_failed: true`

#### Scenario: Archivo ya no existe al restaurar

- **WHEN** el archivo fue eliminado entre la detección y la ejecución de auto_restore
- **THEN** el archivo es creado desde el contenido del baseline, hash verificado, evento publicado con `event_type: "auto_restored"`

### Requirement: Acción quarantine — aislamiento cifrado local

Cuando la acción determinada es `quarantine`, el `DecisionEngine` SHALL usar el almacén único de cuarentena para cifrar contenido y metadatos con AES-256-GCM antes de retirar la entrada de origen. La clave MUST derivarse de `master_secret` con HKDF-SHA256 e `info="quarantine-v1"`, separada de la clave del baseline. El nombre del artefacto MUST ser opaco y determinístico por identidad de acción y ruta. Si el archivo no existe, la acción MUST fallar con `error: "file_not_found"`. El evento MUST conservar `action: "quarantine"` y el `quarantine_path` opaco resultante.

#### Scenario: Quarantine exitosa

- **WHEN** el archivo `/opt/app/malware.sh` debe ser puesto en cuarentena
- **THEN** existe un artefacto autenticado `0400` bajo `/var/lib/fim-agent/quarantine/`, el nombre original no aparece en el nombre del artefacto, el origen se retira solamente después de verificar el artefacto, journal queda `completed`, y el evento incluye `quarantine_path`

#### Scenario: Reintento idempotente

- **WHEN** el artefacto autenticado de la misma acción ya existe por una interrupción previa
- **THEN** no se crea un duplicado y sólo se retira el origen si su identidad todavía coincide con la capturada

#### Scenario: Enlaces

- **WHEN** el origen es un enlace simbólico
- **THEN** se cifra el target textual sin seguirlo y no se conserva un enlace vivo en cuarentena
- **WHEN** el archivo regular tiene más de un hardlink
- **THEN** la acción falla con `hardlink_not_isolatable` y no afirma aislamiento del inode

#### Scenario: Archivo ya eliminado — falla graceful

- **WHEN** el archivo `/opt/app/gone.sh` no existe al momento de ejecutar quarantine
- **THEN** journal queda `failed` con `error: "file_not_found"`, evento publicado con `action_failed: true`

### Requirement: Rehidratación de journal al arrancar

Al iniciar, el agente SHALL escanear `/var/lib/fim-agent/journal/` y procesar todas las entradas con `state: "pending"` (RN-83). Para cada entrada pendiente con acción `auto_restore` o `quarantine`: MUST reintentarse la acción. Para cada entrada pendiente con acción `manual_review` o `alert_only`: MUST marcarse `state: "failed"` con `error: "rehydrated_without_action"` y re-publicarse como evento `alert_only` para que el backend lo registre. La rehidratación MUST completarse antes de que el detector comience a aceptar nuevos eventos.

#### Scenario: Journal pending auto_restore — reintentado al arrancar

- **WHEN** el agente arranca y encuentra `journal/evt-001.json` con `action: "auto_restore"` y `state: "pending"`
- **THEN** intenta restaurar el archivo, actualiza el journal a `completed` o `failed`, y publica el resultado

#### Scenario: Journal pending manual_review — descartado con aviso

- **WHEN** el agente arranca y encuentra `journal/evt-002.json` con `action: "manual_review"` y `state: "pending"`
- **THEN** marca el journal `failed` con `error: "rehydrated_without_action"` y publica un evento `alert_only` al stream

#### Scenario: Sin entradas pending — arranque limpio

- **WHEN** el agente arranca y no hay entradas `pending` en el journal
- **THEN** la fase de rehidratación termina sin publicar eventos adicionales

### Requirement: Comportamiento offline — acciones automáticas con reglas cacheadas

Cuando el backend no está disponible (Valkey inaccesible o sin conectividad), el agente SHALL continuar evaluando y ejecutando acciones automáticas (`auto_restore`, `quarantine`) usando las reglas persistidas localmente en `state.json`. Los eventos MUST encolarse en la cola persistente local y publicarse al backend cuando la conectividad se restaure (RN-42). El agente NO MUST descartar reglas cacheadas por ausencia de conectividad.

#### Scenario: auto_restore offline ejecutado correctamente

- **WHEN** el backend está inalcanzable y se detecta un cambio en `/etc/hosts` con regla `auto_restore`
- **THEN** el archivo se restaura desde el baseline local, el evento se encola localmente, y cuando el backend vuelva, el evento se publica

#### Scenario: Caché de reglas persiste entre reinicios

- **WHEN** el agente se reinicia sin haber recibido un nuevo `rule_sync`
- **THEN** las reglas del último `rule_sync` se cargan de `state.json` y están disponibles para evaluación

### Requirement: auto_restore cae a snapshots cuando el contenido activo es nulo

Al ejecutar `auto_restore`, si la entrada de baseline tiene `content_b64` nulo (típicamente porque el archivo está en estado `absent`), el motor de decisión SHALL buscar el snapshot más reciente cuyo `content_b64` no sea nulo, descomprimirlo si `gzip=True`, y usar ese contenido para restaurar el archivo. El motor MUST verificar el SHA-256 del contenido restaurado contra el hash del snapshot usado. Si no existe ningún snapshot utilizable, el motor MUST fallar con el error `no_restorable_content` (RN-30–33, F3).

#### Scenario: Restauración desde snapshot cuando el contenido activo es nulo

- **WHEN** se gatilla `auto_restore` sobre un path cuya entrada de baseline tiene `content_b64=None` pero existe un snapshot con contenido
- **THEN** el motor restaura el archivo desde el snapshot más reciente con contenido y verifica el hash

#### Scenario: Snapshot comprimido se descomprime antes de restaurar

- **WHEN** el snapshot seleccionado tiene `gzip=True`
- **THEN** el motor descomprime el contenido antes de escribirlo y verificar el hash

#### Scenario: Sin contenido restaurable falla con error claro

- **WHEN** se gatilla `auto_restore` y ni el contenido activo ni ningún snapshot tienen contenido
- **THEN** el motor falla la acción con el error `no_restorable_content` y journaliza el fallo

#### Scenario: Contenido activo presente conserva el comportamiento previo

- **WHEN** se gatilla `auto_restore` y la entrada de baseline tiene `content_b64` no nulo
- **THEN** el motor restaura desde el contenido activo sin consultar snapshots
