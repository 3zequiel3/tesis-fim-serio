# Spec: agent-approve-reject-handler

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: Dispatch de comandos entrantes por tipo

El agente SHALL implementar `agent/commands.py` con una función `dispatch(command: dict)` que enruta los mensajes del stream `commands` según `command["type"]`. Los tipos soportados en este change son `"baseline_update"`, `"restore_file"` y `"quarantine_file"`. Para cualquier tipo desconocido SHALL emitir un log de advertencia y no lanzar excepción (no bloquear el consumer loop). El loop existente en `agent/publisher.py` MUST llamar a `dispatch` para cada mensaje del stream `commands` que no sea `rule_sync`.

#### Scenario: Comando baseline_update es despachado
- **WHEN** el agente recibe un mensaje `{"type": "baseline_update", ...}` en el stream `commands`
- **THEN** `dispatch` llama al handler de `baseline_update`

#### Scenario: Tipo desconocido no bloquea el loop
- **WHEN** el agente recibe un mensaje con `type="unknown_command_xyz"`
- **THEN** el agente emite un log de warning y continúa procesando el siguiente mensaje sin lanzar excepción

### Requirement: Verificación de firma HMAC en todos los comandos

Antes de ejecutar cualquier handler, el agente SHALL verificar la firma HMAC-SHA256 del comando usando el `shared_secret` almacenado en `/var/lib/fim-agent/secrets/shared_secret`. La verificación se realiza sobre el JSON canónico del payload (claves ordenadas, sin el campo `signature`). Si la verificación falla MUST descartar el comando, emitir un log de error de seguridad y NO ejecutar ninguna acción.

#### Scenario: Comando con firma válida es procesado
- **WHEN** el agente recibe un comando cuya firma verifica correctamente con el `shared_secret`
- **THEN** el handler correspondiente se ejecuta

#### Scenario: Comando con firma inválida es descartado
- **WHEN** el agente recibe un comando cuya firma HMAC-SHA256 no coincide
- **THEN** el comando es descartado sin ejecutar acción
- **AND** se emite un log de error de nivel `security`

### Requirement: Filtro de target_agent_id

El agente SHALL ignorar silenciosamente cualquier comando cuyo `target_agent_id` no coincida con el `agent_id` propio y no sea `null`. Si `target_agent_id` es `null`, el comando aplica a todos los agentes (broadcast). Si `target_agent_id` coincide con el `agent_id` del agente, el comando aplica solo a este agente.

#### Scenario: Comando dirigido a otro agente
- **WHEN** el agente recibe un comando con `target_agent_id` que no coincide con su propio `agent_id`
- **THEN** el agente ignora el comando sin log (o log de nivel debug) y sin ejecutar acción

#### Scenario: Comando broadcast (target_agent_id null)
- **WHEN** el agente recibe un comando con `target_agent_id=null`
- **THEN** el agente lo procesa como si fuera dirigido a él

### Requirement: Handler baseline_update — re-cifrado de baseline local

El handler de `baseline_update` SHALL: verificar que `ruleset_version` del comando es mayor o igual al `ruleset_version` almacenado localmente (ignorar comandos con versión menor); obtener la clave de cifrado via HKDF (mismo mecanismo que C07); escribir la nueva entrada de baseline cifrada AES-256-GCM con los datos `{path, hash, baseline_status}` del comando; actualizar el `ruleset_version` almacenado; publicar un `event_ack` al stream `event_ack` de Valkey.

#### Scenario: baseline_update present — baseline local actualizado
- **WHEN** el agente recibe `{"type": "baseline_update", "path": "/etc/passwd", "hash": "abc123", "baseline_status": "present", "ruleset_version": 5, ...}`
- **THEN** existe un archivo de baseline cifrado para `/etc/passwd` con el hash `abc123` en `status=present`
- **AND** el `ruleset_version` local es 5
- **AND** se publicó un `event_ack` confirmando el `command_id`

#### Scenario: baseline_update absent — baseline local marca absent
- **WHEN** el agente recibe `{"type": "baseline_update", "path": "/etc/deleted", "hash": null, "baseline_status": "absent", ...}`
- **THEN** la entrada de baseline para `/etc/deleted` tiene `status=absent` y `hash=null`
- **AND** se publicó `event_ack`

#### Scenario: Versión de ruleset menor que la local
- **WHEN** el agente tiene `ruleset_version=10` almacenado y recibe un `baseline_update` con `ruleset_version=7`
- **THEN** el comando es ignorado (log de debug) y el baseline local no cambia

### Requirement: Handler restore_file — restauración desde baseline con journal

El handler de `restore_file` SHALL: escribir un journal pre-acción en `/var/lib/fim-agent/journal/` antes de ejecutar; descifrar el contenido baseline del archivo indicado en `path`; sobrescribir el archivo en el filesystem con el contenido descifrado; verificar, releyendo el archivo desde disco después de `os.replace`, que su SHA-256 coincide con el hash almacenado en el baseline (o, si no lo hay, con el de los bytes escritos); escribir un journal post-acción con resultado; publicar `event_ack`.

El handler MUST verificar con el mismo helper que `DecisionEngine._auto_restore` (`agent/decision.py`), definido por el requisito «La verificación posterior a la restauración relee el archivo desde disco» de `agent-decision-engine`, y MUST NOT mantener una comparación propia. Un `OSError` en la relectura SHALL publicarse como `verify_failed` y una discrepancia como `hash_mismatch_after_restore`, los mismos literales que el camino de eventos (D81/RN-175, D36/RN-130).

#### Scenario: Restore exitoso
- **WHEN** el agente recibe `{"type": "restore_file", "path": "/etc/passwd", ...}` y existe baseline para ese path
- **THEN** el archivo en `/etc/passwd` contiene el contenido del baseline
- **AND** el SHA-256 del archivo releído desde disco coincide con el hash del baseline
- **AND** existe una entrada en el journal con `action=restore`, `status=success`
- **AND** se publicó `event_ack`

#### Scenario: Restore fallido — no existe baseline para el path
- **WHEN** el agente recibe `restore_file` para un `path` sin baseline
- **THEN** el restore no se ejecuta
- **AND** se escribe journal con `status=error` y razón `no_baseline`
- **AND** se publica `event_ack` con `status=error`

#### Scenario: Journal pre-acción escrito antes de ejecutar
- **WHEN** el handler de restore recibe el comando
- **THEN** el archivo de journal para esa acción existe en disco antes de que el archivo sea sobrescrito

#### Scenario: Restore con escritura truncada — ack de error
- **WHEN** el agente recibe un `restore_file` válido y `os.write` escribe sólo la mitad del contenido antes de un `os.replace` exitoso
- **THEN** el journal queda `failed` con razón `hash_mismatch_after_restore`
- **AND** se publica `event_ack` con `status=error` y `error="hash_mismatch_after_restore"`

#### Scenario: Restore con relectura fallida — ack de error
- **WHEN** el agente recibe un `restore_file` válido, la escritura y el `os.replace` tienen éxito y la apertura del path restaurado para verificarlo levanta `OSError`
- **THEN** el journal queda `failed` con razón `verify_failed`
- **AND** se publica `event_ack` con `status=error` y `error="verify_failed"`

### Requirement: Handler quarantine_file — cuarentena con journal

El handler de `quarantine_file` SHALL delegar en `quarantine_and_record` (`agent/quarantine.py`), la misma implementación que usa el `DecisionEngine` (D82/RN-176): journal `pending` → artefacto cifrado y autenticado en el almacén único de cuarentena (`/var/lib/fim-agent/quarantine/`, nombre opaco, permisos `0400`, RN-34–RN-36) → retiro del origen → entrada de baseline `quarantined` que conserva la versión aprobada. El handler SHALL cerrar el journal (`completed`/`failed`) y después publicar `event_ack`. La identidad de acción y la clave de journal SHALL ser el `agent_event_id` del comando —el `event_id` UUID que el agente emitió para el evento rechazado—, nunca el `command_id`. Un comando sin `agent_event_id` MUST NOT ejecutar la cuarentena ni escribir journal, y SHALL publicar `event_ack` con error `quarantine_identity_missing`. Las validaciones previas de ruta (`no_watch_paths_configured`, `path_outside_watch_paths`, D18/RN-116) no cambian. El dispatcher SHALL pasar al handler el `BaselineEngine` que ya recibe.

#### Scenario: Quarantine exitoso
- **WHEN** el agente recibe `{"type": "quarantine_file", "path": "/etc/malicious", "agent_event_id": "<uuid>", ...}` y el archivo existe
- **THEN** el archivo ya no existe en `/etc/malicious`
- **AND** existe en `/var/lib/fim-agent/quarantine/` un artefacto autenticado `0400` direccionado por `<uuid>` y la ruta
- **AND** la entrada de baseline de `/etc/malicious` es `quarantined` y conserva el contenido aprobado
- **AND** la entrada de journal de clave `<uuid>` tiene `action=quarantine` y `state=completed`
- **AND** se publicó `event_ack` con `status=ok`

#### Scenario: Quarantine de archivo inexistente
- **WHEN** el agente recibe `quarantine_file` para un `path` que no existe en el filesystem
- **THEN** el journal queda `failed` con razón `file_not_found`
- **AND** la entrada de baseline no cambia
- **AND** se publica `event_ack` con `status=error`

#### Scenario: Comando sin agent_event_id
- **WHEN** el agente recibe un `quarantine_file` firmado sin el campo `agent_event_id`
- **THEN** el archivo no se toca, no se escribe journal y se publica `event_ack` con error `quarantine_identity_missing`

### Requirement: event_ack publicado tras ejecutar cada comando

Tras ejecutar cualquier comando (exitoso o fallido), el agente SHALL publicar en el stream `event_ack` de Valkey un mensaje con: `command_id` (del comando original), `command_type`, `event_id`, `agent_id`, `status` ("ok" | "error"), `error` (null si ok, string con razón si error), `timestamp` (ISO8601 UTC).

#### Scenario: event_ack exitoso publicado
- **WHEN** el agente ejecuta `baseline_update` exitosamente
- **THEN** existe un mensaje en el stream `event_ack` con `command_id` del comando y `status="ok"`

#### Scenario: event_ack de error publicado
- **WHEN** el agente falla al ejecutar `restore_file` (baseline ausente)
- **THEN** existe un mensaje en el stream `event_ack` con `status="error"` y `error` describiendo la razón

### Requirement: An operator-initiated restore does not report its own write as a detection

`handle_restore_file` performs the same atomic write as `DecisionEngine._auto_restore` — a `.fim_restore_tmp` file opened with `O_EXCL`, `fchown` before `fchmod` (D36 / RN-130), then `os.replace` onto the final path — and therefore delivers the same `FAN_MOVED_TO` on that final path. The agent SHALL NOT publish an integrity event for that write. The guarantee is inherited from the detector's discard invariant and requires no separate mechanism in the command handler; the outcome of the command already reaches the backend through the handler's `event_ack`, carrying its reason in the closed vocabulary of D36 / RN-130. A second `file_created` event for the same path would be a duplicate notification of the same fact, presented as if it were a detection.

Because the write path is duplicated between `agent/decision.py` and `agent/commands.py` — deliberately, and documented as such — this guarantee MUST be asserted by a test rather than deduced from the duplication. A future divergence between the two copies, such as a different temporary suffix, would otherwise break it silently.

#### Scenario: A successful restore_file publishes an ack and no integrity event
- **WHEN** the agent handles a valid `restore_file` command for a monitored path and the restore succeeds
- **THEN** the file's on-disk content matches the baseline content, an `event_ack` reporting success is published, and the resulting `FAN_MOVED_TO` on that path publishes no event

#### Scenario: A failed restore_file still publishes only its ack
- **WHEN** the agent handles a `restore_file` command that fails before `os.replace` (for example `no_baseline_content` or a write error)
- **THEN** an `event_ack` reporting the failure reason is published, the monitored path is unmodified, and no integrity event is published

### Requirement: quarantine_file preserva la versión aprobada y su propio unlink no produce evento

Tras un `quarantine_file` exitoso, el evento de filesystem que el retiro del origen produce sobre la ruta (`FAN_MOVED_FROM` o `FAN_DELETE`) MUST NOT publicar evento alguno, MUST NOT escribir journal y MUST NOT mutar la entrada de baseline, cualquiera sea la regla que cubra la ruta (`alert_only`, `manual_review`, `quarantine` o `auto_restore`). En particular, una regla `auto_restore` sobre la ruta MUST NOT convertir el rechazo con cuarentena del operador en una restauración no pedida (D82/RN-176).

#### Scenario: El eco del operador no publica nada y deja el baseline restaurable
- **WHEN** el agente ejecuta un `quarantine_file` exitoso y luego recibe el `FAN_MOVED_FROM` sobre la ruta
- **THEN** primero se verifica que la acción ocurrió (artefacto presente, journal `completed`, origen ausente)
- **AND** no se publicó ningún payload de evento
- **AND** la entrada de baseline es `quarantined` y `select_restorable_content` devuelve los bytes aprobados

#### Scenario: Una regla auto_restore no deshace el rechazo con cuarentena
- **WHEN** una regla `auto_restore` cubre la ruta y el agente ejecuta un `quarantine_file` exitoso seguido del eco
- **THEN** el archivo sigue ausente, no se publica evento y la entrada sigue `quarantined`

### Requirement: restore_file devuelve una entrada quarantined a present

Cuando `handle_restore_file` restaura un path cuya entrada de baseline es `quarantined` y la verificación desde disco (D81/RN-175) tiene éxito, el handler SHALL devolver la entrada a `present` conservando los campos preservados y limpiando `quarantine_action_id`, antes de publicar `event_ack`. Si la restauración o la verificación fallan, la entrada MUST seguir `quarantined`. El evento de filesystem que produce el `os.replace` de la restauración SHALL seguir descartándose por igualdad de hash.

#### Scenario: Restaurar desde quarantined
- **WHEN** el agente recibe `restore_file` para un path con entrada `quarantined` y contenido aprobado
- **THEN** el archivo en disco es byte a byte el contenido aprobado con su `mode`, `uid` y `gid`
- **AND** la entrada queda `present` con `quarantine_action_id: null`
- **AND** el `FAN_MOVED_TO` de la restauración no publica evento

#### Scenario: Restauración fallida desde quarantined
- **WHEN** la restauración de un path con entrada `quarantined` termina en `hash_mismatch_after_restore` o `verify_failed`
- **THEN** la entrada sigue `quarantined` y el `event_ack` lleva el error

