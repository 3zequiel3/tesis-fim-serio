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

Cuando la acción determinada es `auto_restore`, el `DecisionEngine` SHALL leer el `content_b64` del `BaselineEntry` para el path afectado (vía `BaselineEngine.read_entry(path)`), decodificarlo de Base64, escribirlo en el path original (atomicamente via `.tmp`), y verificar, **releyendo el archivo desde disco** después de `os.replace`, que su SHA-256 coincide con el hash esperado de la fuente restaurada —`entry.hash` para el contenido activo, el hash del snapshot elegido en otro caso— según el requisito «La verificación posterior a la restauración relee el archivo desde disco» (RN-30, RN-31, D81/RN-175). El hash del buffer en memoria MUST NOT usarse como hash del archivo restaurado. Si la verificación es exitosa, el evento MUST publicarse con `event_type: "auto_restored"`. Si `content_b64` es `None` (archivo binario u oversize), la acción MUST fallar gracefully con `error: "no_baseline_content"` en el journal (RN-32, RN-33).

#### Scenario: Restauración exitosa — hash verificado

- **WHEN** `/etc/hosts` fue modificado y el baseline tiene `content_b64` válido con hash `abc123`
- **THEN** el archivo es restaurado, su SHA-256 coincide con `abc123`, el journal queda `completed`, y el evento se publica con `event_type: "auto_restored"`

#### Scenario: Restauración con verificación fallida — falla reportada

- **WHEN** el archivo releído desde disco tras la restauración tiene SHA-256 diferente al hash esperado del baseline
- **THEN** el journal queda `failed` con `error: "hash_mismatch_after_restore"` y el evento se publica con `action_failed: true`

#### Scenario: Baseline sin content_b64 — falla graceful

- **WHEN** el baseline para `/bin/ls` tiene `content_b64: null` (archivo binario)
- **THEN** la restauración no se intenta, journal queda `failed` con `error: "no_baseline_content"`, evento publicado con `action_failed: true`

#### Scenario: Archivo ya no existe al restaurar

- **WHEN** el archivo fue eliminado entre la detección y la ejecución de auto_restore
- **THEN** el archivo es creado desde el contenido del baseline, hash verificado, evento publicado con `event_type: "auto_restored"`

#### Scenario: Escritura truncada — la relectura la detecta

- **WHEN** `os.write` escribe sólo la mitad del contenido del baseline en el temporal y el `os.replace` posterior tiene éxito
- **THEN** la acción falla con `hash_mismatch_after_restore`, el journal queda `failed` con esa causa y el evento se publica con `action_failed: true`, no con `event_type: "auto_restored"`

### Requirement: Acción quarantine — aislamiento cifrado local

Cuando la acción determinada es `quarantine`, el `DecisionEngine` SHALL delegar en `quarantine_and_record` (`agent/quarantine.py`), que usa el almacén único de cuarentena para cifrar contenido y metadatos con AES-256-GCM antes de retirar la entrada de origen y, recién después de una cuarentena exitosa, marca la entrada de baseline como `quarantined` conservando la versión aprobada (D82/RN-176). La clave MUST derivarse de `master_secret` con HKDF-SHA256 e `info="quarantine-v1"`, separada de la clave del baseline. El nombre del artefacto MUST ser opaco y determinístico por identidad de acción y ruta, y la identidad de acción MUST ser el `event_id` del agente. Si el archivo no existe, la acción MUST fallar con `error: "file_not_found"`. El evento MUST conservar `action: "quarantine"` y el `quarantine_path` opaco resultante. El paso terminal del journal (`completed`/`failed`) MUST quedar en el `commit_fn` que el detector invoca después de publicar, de modo que un crash entre la acción y la publicación deje la entrada `pending` para la rehidratación.

#### Scenario: Quarantine exitosa

- **WHEN** el archivo `/opt/app/malware.sh` debe ser puesto en cuarentena
- **THEN** existe un artefacto autenticado `0400` bajo `/var/lib/fim-agent/quarantine/`, el nombre original no aparece en el nombre del artefacto, el origen se retira solamente después de verificar el artefacto, la entrada de baseline queda `quarantined` con el contenido aprobado, el evento incluye `quarantine_path`, y el journal queda `completed` después de la publicación

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
- **THEN** journal queda `failed` con `error: "file_not_found"`, evento publicado con `action_failed: true`, y la entrada de baseline no cambia

#### Scenario: La publicación falla después de la cuarentena

- **WHEN** la cuarentena y el marcado `quarantined` tienen éxito pero la publicación del evento falla
- **THEN** el journal sigue `pending` y la rehidratación del próximo arranque reintenta y publica el evento

### Requirement: Retención y migración de cuarentena

El agente SHALL ejecutar mantenimiento de cuarentena al arranque y cada 24 horas hasta el shutdown. La retención SHALL ser configurable, con 30 días por defecto y rango válido de 1 a 365. El mantenimiento MUST migrar primero los formatos plaintext históricos `{event_id}_{basename}` y `{basename}.{YYYYMMDDTHHMMSS}` al `QuarantineStore` cifrado de forma atómica e idempotente, sin sobreescribir artefactos ni seguir symlinks. Los hardlinks MUST fallar cerrados. Como ambos nombres legacy perdieron el directorio original, la metadata MUST declarar `original_path_known: false` en vez de inventar una ruta restaurable. Después MUST borrar únicamente artefactos autenticados que hayan alcanzado el límite de retención. Los artefactos corruptos, no autenticables o legacy desconocidos MUST conservarse y reportarse como estado degradado mediante contadores agregados que no filtren nombres, rutas ni secretos.

#### Scenario: Expiración en el límite

- **WHEN** un artefacto autenticado alcanza exactamente `quarantine_retention_days`
- **THEN** se elimina y se sincroniza el directorio, mientras uno más reciente se conserva

#### Scenario: Corrupción preservada

- **WHEN** un artefacto no supera autenticación AES-GCM
- **THEN** no se elimina, el mantenimiento continúa y reporta estado degradado

#### Scenario: Reinicio durante migración legacy

- **WHEN** el artefacto cifrado quedó durable pero el origen legacy no llegó a retirarse
- **THEN** el siguiente arranque autentica el destino existente, no lo sobreescribe y completa el retiro sólo si la identidad del origen coincide

### Requirement: Rehidratación de journal al arrancar

Al iniciar, el agente SHALL escanear `/var/lib/fim-agent/journal/` y procesar todas las entradas con `state: "pending"` (RN-83). Para cada entrada pendiente con acción `auto_restore` o `quarantine`: MUST reintentarse la acción. Una acción `quarantine` reintentada MUST pasar por `quarantine_and_record`, con la clave de la entrada de journal como identidad de acción, de modo que la entrada de baseline quede `quarantined` aunque el agente haya caído entre el retiro del origen y el marcado (D82/RN-176). Para cada entrada pendiente con acción `manual_review` o `alert_only`: MUST marcarse `state: "failed"` con `error: "rehydrated_without_action"` y re-publicarse como evento `alert_only` para que el backend lo registre. La rehidratación MUST completarse antes de que el detector comience a aceptar nuevos eventos.

#### Scenario: Journal pending auto_restore — reintentado al arrancar

- **WHEN** el agente arranca y encuentra `journal/evt-001.json` con `action: "auto_restore"` y `state: "pending"`
- **THEN** intenta restaurar el archivo, actualiza el journal a `completed` o `failed`, y publica el resultado

#### Scenario: Journal pending manual_review — descartado con aviso

- **WHEN** el agente arranca y encuentra `journal/evt-002.json` con `action: "manual_review"` y `state: "pending"`
- **THEN** marca el journal `failed` con `error: "rehydrated_without_action"` y publica un evento `alert_only` al stream

#### Scenario: Sin entradas pending — arranque limpio

- **WHEN** el agente arranca y no hay entradas `pending` en el journal
- **THEN** la fase de rehidratación termina sin publicar eventos adicionales

#### Scenario: Ventana de crash de la cuarentena

- **WHEN** el agente arranca con una entrada `pending` de `quarantine`, el artefacto autenticado presente, el origen ausente y la entrada de baseline todavía `present`
- **THEN** la rehidratación no crea un artefacto nuevo, deja la entrada de baseline `quarantined` con el contenido aprobado, publica el evento y cierra el journal

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

### Requirement: A successful auto_restore converges in one turn and the event count per path is bounded by the real modifications

The detect → remediate → observe cycle SHALL be a fixed point. When a rule with `action: "auto_restore"` matches a path, N real modifications to that path MUST produce **at most N** published events — never N×k. The restore writes content that RN-32 verifies against the baseline hash and RN-33 declares identical to it, so the `FAN_MOVED_TO` that `os.replace` delivers on the final path is observed as "no change" and discarded by the detector. The engine itself is unchanged: it neither tracks how many times it restored a path nor refuses to act.

Rules are evaluated by path, not by event type — `RulesCache.evaluate` matches the path against glob patterns and never receives the `event_type`. Therefore **any** `auto_restore` rule covering the path is sufficient to close the cycle; no special `file_created` rule is required, contrary to what D19 / RN-117 assumed when it described the loop. The bound above MUST hold for the ordinary `auto_restore` rule that RN-30 describes as the normal case.

The event that survives is the one describing the tampering, not the one describing the repair: the `file_modified` event carries `action: "auto_restore"` and, per D35 / RN-129, is ingested as `auto_restored`. The restore emits nothing of its own.

#### Scenario: One tamper under an auto_restore rule produces exactly one event
- **WHEN** a monitored file covered by an `auto_restore` rule is modified once and the engine restores it successfully
- **THEN** exactly one event is published, with `event_type: "file_modified"`, `action: "auto_restore"` and `action_failed: false`

#### Scenario: N tampers produce at most N events
- **WHEN** the same path is modified N times in sequence, each followed by a successful restore and by the `MOVED_TO` the kernel delivers for it
- **THEN** the total number of published events is at most N

#### Scenario: The restore is observable on the real filesystem
- **WHEN** the engine restores a tampered file
- **THEN** the file's on-disk content equals the known-good baseline content, its mode, uid and gid are the ones recorded in the baseline entry (D36 / RN-130), and the journal entry for the event reaches its completed state

#### Scenario: A failed restore emits once and does not loop either
- **WHEN** the engine attempts an `auto_restore` that fails (for example `no_restorable_content`)
- **THEN** exactly one event is published with `action_failed: true`, no filesystem mutation reaches the monitored path, and no further events follow

#### Scenario: The baseline is not rewritten by the restore round trip
- **WHEN** a tamper-and-restore cycle completes
- **THEN** the baseline entry for that path still holds the original known-good hash, content and metadata, so a later restore has the same source available (RN-33)

### Requirement: The decision engine never overwrites event_type with the action result

`_auto_restore` (`agent/decision.py`) SHALL NOT overwrite `payload["event_type"]` with the literal `"auto_restored"`. That field has a declared closed vocabulary — `file_modified | file_absent | file_deleted | file_created` (`agent/detector.py:66`) — and overwriting it violates the RN-71 canonical lexicon by mixing a filesystem operation type with an action outcome. The asymmetry is itself evidence of the defect: `_quarantine` never performed the symmetric overwrite, so `event_type` could not be a reliable carrier of the action result in the first place. After this change `event_type` SHALL always carry the filesystem operation type, and the outcome of the automatic action SHALL travel exclusively in `action` and `action_failed`. No symmetric overwrite SHALL be added to `_quarantine` or to any other action handler. (D35 / RN-129, RN-71)

#### Scenario: Auto-restored event keeps its filesystem operation type
- **WHEN** the decision engine auto-restores a modified file
- **THEN** the published payload has `event_type = "file_modified"` and `action = "auto_restore"`, and `event_type` is never set to `"auto_restored"`

#### Scenario: Quarantined event keeps its filesystem operation type
- **WHEN** the decision engine quarantines a file
- **THEN** the published payload keeps its original `event_type` and carries `action = "quarantine"`, with no new overwrite introduced

#### Scenario: Detector logging observes the real operation type
- **WHEN** the detector logs the enriched payload after `evaluate_and_act`
- **THEN** the logged `event_type` is the real filesystem operation type rather than the action outcome

### Requirement: Journal rehydration produces a payload consistent with the status derivation

The journal rehydration path (`agent/decision.py`, `rehydrate`) hand-builds its event payload as a dict literal rather than deriving it from a `DetectedChange`, and sets `action` on it directly. That payload SHALL carry `action` and `action_failed` with the same semantics as the normal path, so that the backend derivation of D35/RN-129 yields the same status for a rehydrated event as it would have for the original one. Because rehydration calls `_auto_restore`, it inherits the removal of the `event_type` overwrite and MUST NOT reintroduce it: its `event_type` SHALL remain the value the journal entry carries. This path executes only after an agent crash and has no contract coverage, so conformance SHALL be established by test rather than by inspection. (D35 / RN-129, RN-75)

#### Scenario: Rehydrated auto_restore entry yields the same status as the normal path
- **WHEN** a pending journal entry with `action = "auto_restore"` is rehydrated and republished after an agent restart
- **THEN** the backend derives `auto_restored` for it, identically to an event produced by the normal detection path

#### Scenario: Rehydrated failed entry yields pending
- **WHEN** a rehydrated entry sets `action_failed = true`
- **THEN** the backend derives `pending` for it, keeping the incident in the operator queue

#### Scenario: Rehydrated payload does not carry a polluted event_type
- **WHEN** a rehydrated entry passes through `_auto_restore`
- **THEN** its `event_type` retains the journal entry's value and is not overwritten with `"auto_restored"`

### Requirement: Automatic restore reproduces the baseline mode, uid and gid

`_auto_restore` SHALL restore the file's mode, owner and group from the baseline entry, not only its content. The baseline already records `mode` (as the octal string produced by `oct(S_IMODE(...))`), `uid` and `gid` on every entry write, and nothing has ever read them back — `chown` does not appear anywhere in the agent today.

This is a precondition for granting the write capabilities, not a completeness extra. The temporary file is created owned by the service user with a mode derived from the umask; without metadata restoration a "successful" restore of a system binary would leave it owned by the service user at a permissive mode, converting a broken feature into a privilege escalation for anyone holding that uid.

The sequence SHALL be: create the temporary file in the destination's own directory with `O_CREAT | O_WRONLY | O_EXCL` and a restrictive initial mode; write and fsync the content; apply the owner and group; apply the mode; close; then `os.replace` onto the destination.

**The owner SHALL be applied before the mode.** On Linux, changing a file's owner clears its setuid and setgid bits, and the stored mode covers the full permission word including setuid, setgid and sticky. Applying the mode first would produce a restore that reports success while silently stripping the setuid bit from a privileged binary. Both operations SHALL be performed through the open file descriptor rather than by path, which removes the time-of-check/time-of-use window on the temporary path and guarantees the file never exists at its final path with the wrong ownership, because all metadata is applied before the atomic replace.

`O_EXCL` SHALL be used so that an orphaned temporary file from a previous attempt is detected rather than truncated and reused.

The content may be selected from a snapshot while mode, uid and gid always come from the entry, since snapshots do not record them. That asymmetry is accepted and documented: the entry's metadata is the most recently observed and is the best approximation available. (D36 / RN-130, RN-30, RN-31, RN-32, RN-33)

#### Scenario: Restored file recovers its baseline mode

- **WHEN** a file whose baseline entry records a mode is auto-restored
- **THEN** the file on disk carries that mode after the restore

#### Scenario: Owner is applied before mode

- **WHEN** the restore applies the baseline metadata to the temporary file
- **THEN** the owner change is performed before the mode change

#### Scenario: A setuid binary keeps its setuid bit

- **WHEN** a setuid binary is auto-restored from a baseline entry recording the setuid bit
- **THEN** the restored file still carries the setuid bit

#### Scenario: An orphaned temporary file does not get reused

- **WHEN** a temporary restore file from a previous attempt already exists next to the destination
- **THEN** the attempt fails rather than truncating and reusing it

#### Scenario: Metadata is applied before the file reaches its final path

- **WHEN** the restore completes
- **THEN** the destination path is never observable with the temporary file's default ownership — the replace is the first moment the destination changes

### Requirement: A restore whose baseline metadata is incomplete fails instead of completing partially

When the baseline entry lacks `mode`, `uid` or `gid`, or its recorded mode cannot be parsed, the restore SHALL fail with the reason `no_baseline_metadata`, SHALL remove the temporary file, and SHALL leave the original file untouched.

The case is real rather than hypothetical: entries produced when a path is marked absent carry all three as null. Publishing a system file owned by the service user with a umask-derived mode is worse than not restoring it, because it hands that uid the ability to rewrite a privileged binary. A visible failure is preferable to a restore that degrades the host's security posture while reporting success.

Mode parsing SHALL be a pure function accepting both the prefixed form produced by `oct()` and a bare octal string, and returning no value for anything else, so that a malformed mode routes to the same failure rather than to a silent default. (D36 / RN-130, RN-30)

#### Scenario: Missing owner metadata aborts the restore

- **WHEN** the baseline entry has restorable content but a null `uid`
- **THEN** the restore fails with `no_baseline_metadata` and the file on disk is unchanged

#### Scenario: Unparseable mode aborts the restore

- **WHEN** the baseline entry records a mode that does not parse as octal
- **THEN** the restore fails with `no_baseline_metadata` and no temporary file remains

#### Scenario: The failure is distinguishable from a content problem

- **WHEN** a restore fails for missing metadata
- **THEN** the reason is `no_baseline_metadata`, distinct from `no_baseline_content` and `no_restorable_content`

### Requirement: Action failures carry a closed-vocabulary cause that distinguishes deployment from data problems

Action failure reasons SHALL come from a closed lowercase snake_case vocabulary (RN-71): `read_only_mount`, `permission_denied`, `no_baseline_content`, `no_restorable_content`, `no_baseline_metadata`, `file_not_found`, `hash_mismatch_after_restore`, `verify_failed`, `write_failed`, `move_failed`.

The first two are the point of this requirement: an operator MUST be able to tell a deployment problem — the path is not writable — from a data problem — the baseline is missing or unusable — by looking at the event. Today the reason is written only to the host-local journal and the backend sees nothing but a boolean.

Mapping from the underlying error SHALL be a pure function: a read-only filesystem error maps to `read_only_mount`; a permission or operation-not-permitted error maps to `permission_denied`; anything else maps to the site's fallback (`write_failed` for restore, `move_failed` for quarantine). The reread of the restored file after `os.replace` is not a write site and SHALL NOT go through this mapping: any operating system error at that point SHALL produce `verify_failed`, because the write already succeeded and a permission or read-only error on the reread does not describe a deployment barrier on the write (D81 / RN-175). The published reason SHALL be the stable literal with no interpolation of the operating system's message, which today embeds the file path into the reason string; the errno and message SHALL go to structured log fields instead.

**The action SHALL NOT consult the preflight result before attempting.** The preflight is the reporting view; the error classification at the attempt site is the truth of that attempt. Gating the action on a cached preflight would introduce a stale-state failure: a path that became writable between startup and the event would be refused without being tried. The two views may disagree transiently, which is correct, because they mean different things.

The reason SHALL travel in the published event payload alongside the existing failure flag, and SHALL NOT be written on the success path, so every consumer reads it defensively. The journal SHALL continue to receive the same reason. The manual command handlers SHALL use the same mapping and the same literals, so the event path and the command-ack path speak one vocabulary rather than two dialects. (D36 / RN-130, D35 / RN-129, RN-71)

#### Scenario: A read-only filesystem produces read_only_mount

- **WHEN** an automatic restore fails because the destination filesystem is mounted read-only
- **THEN** the published payload carries the failure flag and the reason `read_only_mount`

#### Scenario: A denied permission produces permission_denied

- **WHEN** an automatic restore fails because the process lacks write permission on the destination directory
- **THEN** the published payload carries the reason `permission_denied`

#### Scenario: A missing baseline still produces its own data-side reason

- **WHEN** an automatic restore fails because no baseline entry exists
- **THEN** the reason is `no_baseline_content`, unchanged by this requirement

#### Scenario: The reason does not leak the host path

- **WHEN** any action fails with an operating system error
- **THEN** the published reason is a bare vocabulary literal with no interpolated error message or path

#### Scenario: Success does not emit the key

- **WHEN** an automatic action completes successfully
- **THEN** the published payload contains no failure reason key at all

#### Scenario: The action is attempted even when the preflight said the path was not writable

- **WHEN** the cached preflight classified a path as non-writable but the path is writable at the moment of the event
- **THEN** the restore is attempted and succeeds

#### Scenario: Manual command handlers use the same vocabulary

- **WHEN** a manual restore command fails because the destination is on a read-only mount
- **THEN** the acknowledgement carries the same `read_only_mount` literal used on the event path

#### Scenario: A reread failure after the replace is not classified as a deployment barrier

- **WHEN** the restore's write and `os.replace` succeed and reopening the restored path for verification fails with a permission error
- **THEN** the published reason is `verify_failed`, not `permission_denied`

### Requirement: La verificación posterior a la restauración relee el archivo desde disco

Tras `os.replace`, todo camino de restauración del agente —`DecisionEngine._auto_restore`, que también usa la rehidratación del journal, y `handle_restore_file`— SHALL verificar el resultado con un **único helper compartido** definido en `agent/decision.py`. El helper SHALL abrir el path restaurado con `O_RDONLY | O_NOFOLLOW | O_CLOEXEC`, calcular el SHA-256 de lo que **lee del disco** y compararlo contra el hash esperado de la fuente restaurada; si la fuente no tiene hash esperado (cadena vacía), SHALL compararlo contra el SHA-256 de los bytes escritos. La verificación MUST NOT omitirse en ningún caso.

Cualquier `OSError` al abrir o leer el path restaurado —incluido `ELOOP` cuando el path es un symlink— SHALL producir `verify_failed`; un hash distinto SHALL producir `hash_mismatch_after_restore`. Ambos son literales del vocabulario cerrado, sin interpolación de path ni mensaje del sistema operativo; el `errno` SHALL ir a un campo estructurado del log.

La comparación del buffer en memoria consigo mismo MUST NOT considerarse verificación (D81/RN-175). Ante una falla de verificación, el archivo SHALL quedar tal como quedó en disco y la falla SHALL reportarse por el canal del camino que restauró: evento con `action_failed: true` en el motor de decisión, `event_ack` con `status=error` en el handler de comandos.

#### Scenario: Una escritura truncada se detecta como discrepancia

- **WHEN** `os.write` escribe en el temporal sólo la mitad de los bytes del baseline y el `os.replace` posterior tiene éxito
- **THEN** la restauración falla con `_ActionFailed("hash_mismatch_after_restore")`

#### Scenario: Un archivo alterado después del reemplazo se detecta

- **WHEN** el contenido escrito es correcto pero el path restaurado es sobrescrito con otros bytes entre `os.replace` y la verificación
- **THEN** la restauración falla con `hash_mismatch_after_restore`, aunque el hash del buffer en memoria coincida con el esperado

#### Scenario: Un error al releer produce verify_failed

- **WHEN** la escritura y el `os.replace` tienen éxito y la apertura del path restaurado para verificarlo levanta `OSError`
- **THEN** la restauración falla con `verify_failed` y la causa publicada no contiene el path ni el mensaje del error

#### Scenario: Un symlink en el path restaurado no se sigue

- **WHEN** entre `os.replace` y la verificación el path restaurado es reemplazado por un symlink a un archivo cuyo contenido coincide con el baseline
- **THEN** la apertura falla por `O_NOFOLLOW` y la restauración falla con `verify_failed`, sin leer el destino del symlink

#### Scenario: Sin hash esperado se compara contra los bytes escritos

- **WHEN** la fuente restaurada no tiene hash esperado y `os.write` escribe sólo la mitad de los bytes
- **THEN** la restauración falla con `hash_mismatch_after_restore` en lugar de omitir la verificación

#### Scenario: Una restauración correcta sigue verificándose con éxito

- **WHEN** el archivo restaurado en disco es idéntico al contenido del baseline y su hash coincide con el esperado
- **THEN** la verificación no reporta falla y el evento se publica con `event_type: "auto_restored"`

#### Scenario: El camino del operador usa el mismo helper

- **WHEN** `handle_restore_file` restaura un archivo y la relectura desde disco no coincide con el hash esperado
- **THEN** el `event_ack` publica `error="hash_mismatch_after_restore"`, el mismo literal que el camino de eventos

### Requirement: La cuarentena tiene una única implementación compartida por ambos caminos

`quarantine_and_record` (`agent/quarantine.py`) SHALL ser la única implementación de la cuarentena, usada por `DecisionEngine._quarantine` (camino automático y rehidratación) y por `handle_quarantine_file` (camino del operador) (D82/RN-176, residual §9). Su orden SHALL ser: (1) entrada `pending` en el journal para la identidad de acción, sin pisar una entrada `pending` que el llamador ya haya escrito; (2) `QuarantineStore.quarantine(action_id, path)`; (3) sólo si (2) tuvo éxito, `BaselineEngine.mark_quarantined(path, action_id)`; (4) devolver al llamador el artefacto o la causa de falla. MUST NOT escribir el paso terminal del journal: lo hace el llamador. MUST NOT propagar excepciones por fallas esperadas: toda falla se devuelve como causa del vocabulario cerrado. Si (3) falla, la causa SHALL ser `baseline_mark_failed` y el artefacto SHALL conservarse.

#### Scenario: Los dos caminos producen el mismo efecto observable

- **WHEN** el mismo archivo con la misma versión aprobada se pone en cuarentena una vez por el camino automático y otra por el camino del operador (prueba parametrizada sobre ambos caminos)
- **THEN** en los dos casos existe un artefacto autenticado direccionado por el `event_id` del agente, el origen no existe, la entrada de baseline es `quarantined` y `select_restorable_content` devuelve los bytes aprobados

#### Scenario: El marcado del baseline falla

- **WHEN** la cuarentena tiene éxito pero la escritura de la entrada `quarantined` levanta un error
- **THEN** la causa devuelta es `baseline_mark_failed`, el artefacto existe y el llamador cierra el journal como `failed`

### Requirement: Las fallas de cuarentena usan un único vocabulario en ambos caminos

Las causas de falla de una cuarentena SHALL ser literales en minúsculas snake_case (RN-71), idénticos en el evento publicado, en el journal y en el `command_ack`: la `reason` de `QuarantineError` (por ejemplo `file_not_found`, `hardlink_not_isolatable`, `unsupported_file_type`, `quarantine_source_changed`, `quarantine_identity_missing`, `quarantine_identity_mismatch`), `quarantine_store_unavailable` cuando no hay almacén utilizable, el resultado de `action_error_from_oserror` con fallback `move_failed` para un `OSError`, `baseline_mark_failed` cuando falla el marcado, y `quarantine_failed` para cualquier otra excepción. La causa MUST NOT interpolar el mensaje del sistema operativo ni la ruta; el detalle va a campos estructurados del log.

#### Scenario: Una excepción inesperada no filtra su mensaje

- **WHEN** la cuarentena del camino del operador levanta una excepción no prevista cuyo mensaje contiene la ruta del archivo
- **THEN** el `command_ack` y el journal llevan `quarantine_failed` y no contienen la ruta

#### Scenario: Misma causa en ambos caminos

- **WHEN** se intenta poner en cuarentena un archivo regular con dos hardlinks por cada uno de los dos caminos
- **THEN** ambos reportan `hardlink_not_isolatable`

