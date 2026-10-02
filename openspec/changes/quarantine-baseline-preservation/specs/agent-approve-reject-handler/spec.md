## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: quarantine_file keeps reporting the absence it creates

**Reason**: D82/RN-176 invierte el comportamiento que este requisito fijaba. El `FAN_MOVED_FROM`/`FAN_DELETE` del propio `unlink` de la cuarentena vaciaba la entrada de baseline (`mark_absent`) y destruía la versión aprobada; la ausencia ya está informada por el `command_ack` del `quarantine_file` y por el evento rechazado. El eco se suprime por estado (`quarantined_by_agent`) y la entrada queda `quarantined`, no `absent`.

**Migration**: Reemplazado por «quarantine_file preserva la versión aprobada y su propio unlink no produce evento» (abajo) y por «El eco de la cuarentena propia no genera eventos» en `agent-fanotify-detector`. `test_quarantine_still_reports_the_absence` (`agent/tests/test_restore_feedback_loop.py`) se reescribe para afirmar cero payloads y la entrada `quarantined` con contenido.

## ADDED Requirements

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
