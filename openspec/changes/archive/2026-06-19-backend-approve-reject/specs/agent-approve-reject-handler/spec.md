# Spec: agent-approve-reject-handler

Capability: Handlers del agente FIM para los comandos entrantes desde el backend — `baseline_update` (re-cifrado del baseline local), `restore_file` (restauración con journal) y `quarantine_file` (cuarentena con journal); todos con verificación HMAC, filtro `target_agent_id` y confirmación `event_ack`.

---

## ADDED Requirements

### Requirement: Dispatch de comandos entrantes por tipo

El agente SHALL implementar `agent/commands.py` con una función `dispatch(command: dict)` que enruta los mensajes del stream `commands` según `command["type"]`. Los tipos soportados en este change son `"baseline_update"`, `"restore_file"` y `"quarantine_file"`. Para cualquier tipo desconocido SHALL emitir un log de advertencia y no lanzar excepción (no bloquear el consumer loop). El loop existente en `agent/publisher.py` MUST llamar a `dispatch` para cada mensaje del stream `commands` que no sea `rule_sync`.

#### Scenario: Comando baseline_update es despachado
- **WHEN** el agente recibe un mensaje `{"type": "baseline_update", ...}` en el stream `commands`
- **THEN** `dispatch` llama al handler de `baseline_update`

#### Scenario: Tipo desconocido no bloquea el loop
- **WHEN** el agente recibe un mensaje con `type="unknown_command_xyz"`
- **THEN** el agente emite un log de warning y continúa procesando el siguiente mensaje sin lanzar excepción

---

### Requirement: Verificación de firma HMAC en todos los comandos

Antes de ejecutar cualquier handler, el agente SHALL verificar la firma HMAC-SHA256 del comando usando el `shared_secret` almacenado en `/var/lib/fim-agent/secrets/shared_secret`. La verificación se realiza sobre el JSON canónico del payload (claves ordenadas, sin el campo `signature`). Si la verificación falla MUST descartar el comando, emitir un log de error de seguridad y NO ejecutar ninguna acción.

#### Scenario: Comando con firma válida es procesado
- **WHEN** el agente recibe un comando cuya firma verifica correctamente con el `shared_secret`
- **THEN** el handler correspondiente se ejecuta

#### Scenario: Comando con firma inválida es descartado
- **WHEN** el agente recibe un comando cuya firma HMAC-SHA256 no coincide
- **THEN** el comando es descartado sin ejecutar acción
- **AND** se emite un log de error de nivel `security`

---

### Requirement: Filtro de target_agent_id

El agente SHALL ignorar silenciosamente cualquier comando cuyo `target_agent_id` no coincida con el `agent_id` propio y no sea `null`. Si `target_agent_id` es `null`, el comando aplica a todos los agentes (broadcast). Si `target_agent_id` coincide con el `agent_id` del agente, el comando aplica solo a este agente.

#### Scenario: Comando dirigido a otro agente
- **WHEN** el agente recibe un comando con `target_agent_id` que no coincide con su propio `agent_id`
- **THEN** el agente ignora el comando sin log (o log de nivel debug) y sin ejecutar acción

#### Scenario: Comando broadcast (target_agent_id null)
- **WHEN** el agente recibe un comando con `target_agent_id=null`
- **THEN** el agente lo procesa como si fuera dirigido a él

---

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

---

### Requirement: Handler restore_file — restauración desde baseline con journal

El handler de `restore_file` SHALL: escribir un journal pre-acción en `/var/lib/fim-agent/journal/` antes de ejecutar; descifrar el contenido baseline del archivo indicado en `path`; sobrescribir el archivo en el filesystem con el contenido descifrado; verificar que el SHA-256 del archivo restaurado coincide con el hash almacenado en el baseline; escribir un journal post-acción con resultado; publicar `event_ack`.

El handler MUST reutilizar la misma lógica de restore ya implementada en `agent/actions.py` (C10).

#### Scenario: Restore exitoso
- **WHEN** el agente recibe `{"type": "restore_file", "path": "/etc/passwd", ...}` y existe baseline para ese path
- **THEN** el archivo en `/etc/passwd` contiene el contenido del baseline
- **AND** el SHA-256 del archivo restaurado coincide con el hash del baseline
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

---

### Requirement: Handler quarantine_file — cuarentena con journal

El handler de `quarantine_file` SHALL: escribir journal pre-acción; mover el archivo de `path` a `/var/lib/fim-agent/quarantine/<filename>.<timestamp>`; cambiar permisos del archivo en cuarentena a `0400`; escribir journal post-acción; publicar `event_ack`.

El handler MUST reutilizar la lógica de quarantine ya implementada en `agent/actions.py` (C10).

#### Scenario: Quarantine exitoso
- **WHEN** el agente recibe `{"type": "quarantine_file", "path": "/etc/malicious", ...}` y el archivo existe
- **THEN** el archivo ya no existe en `/etc/malicious`
- **AND** existe un archivo en `/var/lib/fim-agent/quarantine/` con permisos `0400`
- **AND** existe entrada en journal con `action=quarantine`, `status=success`
- **AND** se publicó `event_ack`

#### Scenario: Quarantine de archivo inexistente
- **WHEN** el agente recibe `quarantine_file` para un `path` que no existe en el filesystem
- **THEN** se escribe journal con `status=error` y razón `file_not_found`
- **AND** se publica `event_ack` con `status=error`

---

### Requirement: event_ack publicado tras ejecutar cada comando

Tras ejecutar cualquier comando (exitoso o fallido), el agente SHALL publicar en el stream `event_ack` de Valkey un mensaje con: `command_id` (del comando original), `command_type`, `event_id`, `agent_id`, `status` ("ok" | "error"), `error` (null si ok, string con razón si error), `timestamp` (ISO8601 UTC).

#### Scenario: event_ack exitoso publicado
- **WHEN** el agente ejecuta `baseline_update` exitosamente
- **THEN** existe un mensaje en el stream `event_ack` con `command_id` del comando y `status="ok"`

#### Scenario: event_ack de error publicado
- **WHEN** el agente falla al ejecutar `restore_file` (baseline ausente)
- **THEN** existe un mensaje en el stream `event_ack` con `status="error"` y `error` describiendo la razón
