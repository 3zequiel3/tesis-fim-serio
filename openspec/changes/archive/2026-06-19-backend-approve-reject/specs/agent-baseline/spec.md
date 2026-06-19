# Spec: agent-baseline (delta)

Capability: Delta sobre el motor de baseline del agente — agrega el code path de actualización por comando externo `baseline_update` (D1: el baseline puede ser actualizado tanto por el scan inicial como por instrucciones del backend tras un approve humano).

---

## ADDED Requirements

### Requirement: Actualización de baseline desde comando baseline_update externo

El motor de baseline SHALL exponer una función `update_from_command(path: str, hash: str | None, baseline_status: "present" | "absent")` que puede ser llamada por `agent/commands.py` cuando llega un comando `baseline_update` del backend. Esta función MUST seguir el mismo mecanismo de cifrado AES-256-GCM con HKDF que el scan inicial (C07): misma clave derivada, nuevo nonce por escritura, mismo layout de blob en disco. Si `baseline_status="absent"`, MUST escribir la entrada con `hash=null` y `status=absent`. Si ya existía una entrada para ese `path`, MUST sobrescribirla (upsert).

#### Scenario: update_from_command escribe entrada cifrada present
- **WHEN** se llama `update_from_command("/etc/passwd", "abc123", "present")`
- **THEN** existe un archivo de baseline cifrado para `/etc/passwd`
- **AND** descifrar el blob con la clave HKDF retorna los datos con `hash="abc123"` y `status="present"`

#### Scenario: update_from_command escribe entrada absent
- **WHEN** se llama `update_from_command("/etc/deleted_file", None, "absent")`
- **THEN** existe un archivo de baseline cifrado para `/etc/deleted_file` con `status="absent"` y `hash=null`

#### Scenario: update_from_command sobreescribe entrada existente
- **WHEN** ya existe una entrada cifrada para `path` con `hash="old_hash"` y se llama `update_from_command(path, "new_hash", "present")`
- **THEN** descifrar el blob retorna `hash="new_hash"`
- **AND** el nonce del nuevo blob es distinto al del blob anterior (no reutiliza nonce)

#### Scenario: Clave usada en update_from_command es la misma que en el scan inicial
- **WHEN** el scan inicial y `update_from_command` cifran datos para el mismo `path` en el mismo agente
- **THEN** ambos blobs pueden descifrase con la misma clave HKDF derivada (misma `master_secret` + `agent_id`)
