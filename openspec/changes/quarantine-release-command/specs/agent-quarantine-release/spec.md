## ADDED Requirements

### Requirement: release_quarantine autentica el artefacto antes de cualquier efecto

El handler `handle_release_quarantine` SHALL localizar el artefacto en
`QuarantineStore.artifact_path(agent_event_id, path)` y autenticarlo con `read_artifact` antes de
modificar el filesystem, el baseline o el estado del agente, en los tres modos. El handler SHALL
validar primero que `path` esté contenido en `watch_paths` (D18/RN-116). La metadata autenticada
MUST tener `action_id == agent_event_id` y `original_path == abspath(path)`, y su `sha256` MUST
coincidir con `expected_sha256` del comando. Los fallos SHALL reportarse con códigos cerrados en
minúsculas snake_case (RN-71): `path_outside_watch_paths`, `artifact_not_found`,
`artifact_integrity_failed`, `artifact_identity_mismatch`, `artifact_hash_mismatch`. Un artefacto
eliminado por `cleanup_expired` o nombrado por `command_id` (anterior a D82/RN-176) SHALL reportarse
como `artifact_not_found`. (D83/RN-177)

#### Scenario: Artefacto vencido
- **WHEN** el agente recibe un `release_quarantine` válido cuyo artefacto ya fue eliminado por retención
- **THEN** publica `command_ack` con `status = "error"` y `error = "artifact_not_found"`
- **AND** el path, el baseline y `state.ruleset_version` no cambian

#### Scenario: Hash del artefacto distinto del esperado
- **WHEN** el artefacto autentica pero su `sha256` difiere de `expected_sha256`
- **THEN** publica `command_ack` con `error = "artifact_hash_mismatch"` y el artefacto se conserva

#### Scenario: Artefacto manipulado
- **WHEN** el archivo `.fimq` fue alterado y AES-GCM no autentica
- **THEN** publica `command_ack` con `error = "artifact_integrity_failed"` sin escribir en el path

#### Scenario: Artefacto heredado nombrado por command_id
- **WHEN** existe un artefacto cuyo `action_id` es el `command_id` de un `quarantine_file` anterior a D82 y no existe artefacto con `action_id = agent_event_id`
- **THEN** publica `command_ack` con `error = "artifact_not_found"`

### Requirement: restore_original aprueba y reubica el contenido cuarentenado sin sobrescribir

En modo `restore_original` el agente SHALL: aplicar la guarda de obsolescencia de `baseline_update`
(`ruleset_version` del comando menor que `state.ruleset_version` → `stale_ruleset_version`);
rechazar un artefacto `symlink` con `unsupported_file_type`; fallar con `path_occupied` si el path
existe; adoptar en el baseline el contenido, hash y metadata del artefacto con estado `present`
**antes** de reubicar; escribir un temporal `.fim_restore_tmp` con `O_EXCL`, `fchown` antes que
`fchmod` y modo sin `S_ISUID` ni `S_ISGID`; publicarlo con una operación que MUST NOT sobrescribir un
destino existente (`path_occupied`); verificar releyendo desde disco con el helper de D81/RN-175
(`verify_failed`, `hash_mismatch_after_restore`); eliminar el artefacto; y fijar
`state.ruleset_version` al del comando. Ante cualquier fallo posterior a la adopción, la entrada de
baseline SHALL volver a su estado previo y el artefacto SHALL conservarse. (D83/RN-177)

#### Scenario: restore_original exitoso
- **WHEN** el agente recibe `restore_original` para un evento en cuarentena y el path está libre
- **THEN** el path contiene el contenido del artefacto, con `uid`/`gid` del artefacto y sin bits setuid/setgid
- **AND** la entrada de baseline queda `present` con `hash = expected_sha256`
- **AND** el artefacto ya no existe y `state.ruleset_version` es el del comando
- **AND** se publica `command_ack` con `status = "ok"`

#### Scenario: Path ocupado
- **WHEN** existe un archivo en el path al ejecutar `restore_original`
- **THEN** el archivo existente no se modifica, el artefacto se conserva, la entrada de baseline vuelve a `quarantined` y el ack lleva `error = "path_occupied"`

#### Scenario: Path ocupado entre la comprobación y la publicación
- **WHEN** el path se crea después del `lstat` y antes de publicar el temporal
- **THEN** la publicación falla sin sobrescribir, el temporal se elimina y el ack lleva `error = "path_occupied"`

#### Scenario: Comando obsoleto
- **WHEN** `ruleset_version` del comando es menor que `state.ruleset_version`
- **THEN** no hay efecto alguno y el ack lleva `error = "stale_ruleset_version"`

#### Scenario: Verificación desde disco falla
- **WHEN** la relectura del path tras publicarlo no coincide con `expected_sha256`
- **THEN** el ack lleva `error = "hash_mismatch_after_restore"`, la entrada de baseline vuelve a `quarantined` y el artefacto se conserva

#### Scenario: La escritura propia no se reporta como detección
- **WHEN** `restore_original` termina con éxito
- **THEN** el `FAN_CREATE` sobre el path no publica ningún evento de integridad

### Requirement: restore_baseline restaura la versión aprobada sin sobrescribir

En modo `restore_baseline` el agente SHALL autenticar el artefacto, fallar con `path_occupied` si el
path existe, obtener el contenido con `select_restorable_content` sobre la entrada `quarantined`
(`no_restorable_content` si no hay), escribirlo con la metadata de la entrada de baseline y la misma
publicación sin sobrescritura, verificarlo desde disco (D81/RN-175), pasar la entrada a `present` y
eliminar el artefacto. MUST NOT modificar `state.ruleset_version`. (D83/RN-177, D82/RN-176)

#### Scenario: restore_baseline exitoso
- **WHEN** el agente recibe `restore_baseline` para un evento en cuarentena y el path está libre
- **THEN** el path contiene el contenido aprobado del baseline y la entrada queda `present`
- **AND** el artefacto ya no existe y el ack lleva `status = "ok"`

#### Scenario: restore_baseline con path ocupado
- **WHEN** existe un archivo en el path
- **THEN** el archivo no se modifica, el artefacto se conserva y el ack lleva `error = "path_occupied"`

#### Scenario: La escritura de restore_baseline no se reporta como detección
- **WHEN** `restore_baseline` termina con éxito
- **THEN** el `FAN_CREATE` sobre el path no publica ningún evento de integridad

### Requirement: discard elimina sólo el artefacto autenticado

En modo `discard` el agente SHALL autenticar el artefacto y eliminarlo, revalidando identidad y hash
bajo el lock del store inmediatamente antes del `unlink`. El baseline, el path y
`state.ruleset_version` MUST NOT cambiar. (D83/RN-177)

#### Scenario: discard exitoso
- **WHEN** el agente recibe `discard` para un evento en cuarentena
- **THEN** el artefacto ya no existe, la entrada de baseline sigue `quarantined` y el ack lleva `status = "ok"`

### Requirement: La re-entrega de un release_quarantine es idempotente

El agente SHALL escribir journal `pending` con clave `command_id` y acción `release_quarantine` antes
del primer efecto (RN-83) y SHALL registrar cada `release_quarantine` ejecutado en un registro local
durable de comandos destructivos ejecutados, **antes** de publicar su `command_ack`. Un comando cuyo
`command_id` ya figura en el registro MUST NOT ejecutarse de nuevo: el agente SHALL re-publicar el
mismo resultado. `DecisionEngine.rehydrate` MUST NOT republicar una entrada de journal
`release_quarantine` como evento de integridad. (D83/RN-177)

#### Scenario: Re-entrega tras ejecución completa
- **WHEN** el agente recibe por segunda vez un `release_quarantine` con un `command_id` ya registrado
- **THEN** no modifica el filesystem ni el baseline y publica un ack con el mismo `status` y `error` que la primera vez

#### Scenario: Re-entrega tras caída posterior al efecto
- **WHEN** el agente cayó después de publicar el archivo y eliminar el artefacto de un `restore_original` pero antes de registrar el comando, y el comando se re-entrega
- **THEN** el agente detecta que el path tiene el hash esperado y la entrada está `present` con ese hash, y publica ack `ok` sin escribir de nuevo

#### Scenario: Rehidratación no fabrica eventos
- **WHEN** el agente arranca con una entrada de journal `pending` de acción `release_quarantine`
- **THEN** `rehydrate` no publica ningún evento para esa entrada
