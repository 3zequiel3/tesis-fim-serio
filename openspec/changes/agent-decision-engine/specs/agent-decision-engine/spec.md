## ADDED Requirements

### Requirement: Cache local de reglas con evaluación glob y negación

El agente SHALL mantener una cache local de reglas de decisión (`RulesCache`) que se actualiza únicamente al recibir un comando `rule_sync` firmado con HMAC y `ruleset_version` monotónico mayor al aplicado actualmente (RN-75, RN-79). La cache MUST persistirse bajo la clave `"rules"` en `/var/lib/fim-agent/state.json` (escritura atómica via `.tmp` + `os.replace()`). Al evaluar un evento, el sistema SHALL iterar las reglas en orden de declaración usando `fnmatch.fnmatch`: si alguna regla con prefijo `!` matchea el path, el resultado es `alert_only` sin importar las reglas inclusivas previas (exclusiva gana, RN-65). Si solo reglas inclusivas matchean, la primera en orden determina la acción. Si ninguna matchea, el resultado es `alert_only` (RN-06). La cache MUST ser thread-safe para lecturas concurrentes.

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

#### Scenario: rule_sync válido — cache actualizada y persistida

- **WHEN** el agente recibe un `rule_sync` con `ruleset_version: 6` (mayor al actual) y HMAC válido
- **THEN** la cache se reemplaza con las nuevas reglas, `ruleset_version` en `state.json` se actualiza a 6, y el agente publica `event_ack`

#### Scenario: Cache vacía al arrancar — alert_only por defecto

- **WHEN** el agente arranca sin `rules` en `state.json`
- **THEN** todos los eventos se evalúan como `alert_only` hasta recibir el primer `rule_sync`

### Requirement: Motor de decisión con journal transaccional pre/post-acción

El `DecisionEngine` SHALL evaluar cada `DetectedChange` contra la `RulesCache`, ejecutar la acción correspondiente y registrar el resultado en el journal. Antes de ejecutar cualquier acción (incluido `alert_only`), MUST escribirse una entrada de journal con `state: "pending"` en `/var/lib/fim-agent/journal/{event_id}.json`. Tras completar la acción, el journal MUST actualizarse a `state: "completed"` o `state: "failed"` con campo `error` opcional (RN-83). El evento MUST publicarse al stream (vía publisher) independientemente del resultado de la acción. Si la acción falla, el payload del evento MUST incluir `action_failed: true`.

#### Scenario: Evaluación y acción completan exitosamente

- **WHEN** un evento con path `/etc/hosts` (acción `auto_restore`) es procesado por el motor
- **THEN** se escribe journal `{state: "pending"}`, se ejecuta la restauración, se actualiza journal a `{state: "completed"}`, y el evento se publica con `action: "auto_restore"`

#### Scenario: Acción falla — journal failed, evento publicado igual

- **WHEN** la restauración de `/etc/passwd` falla porque `content_b64` es `None` en baseline
- **THEN** el journal queda `{state: "failed", error: "no_baseline_content"}` y el evento se publica con `action_failed: true`

#### Scenario: alert_only — journal y publicación sin acción física

- **WHEN** un evento para `/var/log/app.log` es evaluado y no hay regla (default `alert_only`)
- **THEN** se escribe journal `{state: "completed"}` sin ejecutar ninguna acción física, y el evento se publica normalmente

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

### Requirement: Acción quarantine — movimiento a directorio de cuarentena

Cuando la acción determinada es `quarantine`, el `DecisionEngine` SHALL mover el archivo afectado a `/var/lib/fim-agent/quarantine/{event_id}_{basename}` usando `shutil.move()` (RN-34, RN-35). Si el archivo ya no existe al momento de ejecutar la cuarentena, la acción MUST fallar gracefully con `error: "file_not_found"` (RN-36). El evento MUST publicarse con `action: "quarantine"` y el `quarantine_path` resultante en el payload (RN-37).

#### Scenario: Quarantine exitosa

- **WHEN** el archivo `/opt/app/malware.sh` debe ser puesto en cuarentena
- **THEN** el archivo se mueve a `/var/lib/fim-agent/quarantine/{event_id}_malware.sh`, journal queda `completed`, y el evento incluye `quarantine_path`

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
