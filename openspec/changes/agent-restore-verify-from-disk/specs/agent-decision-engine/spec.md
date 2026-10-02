## ADDED Requirements

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

## MODIFIED Requirements

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
