## ADDED Requirements

### Requirement: release_quarantine es confirmable y reconcilia al aprobar

`release_quarantine` SHALL tratarse como comando confirmable: persiste su `command_id` con
`ack_status = pending` al encolarse y participa del barrido de timeout. Al recibir un `command_ack`
`ok` de un `release_quarantine`, el consumer SHALL leer `mode` y `ruleset_version` del payload
persistido en la fila (nunca del ack) y, sólo si `mode = restore_original`, SHALL reconciliar
`baseline_entries` con `event.hash_detected` y estado `present` (D1/RN-104) y avanzar
`ruleset_version_applied` de forma monotónica (D5/RN-106). Los modos `restore_baseline` y `discard`
MUST NOT modificar `baseline_entries`. Un ack `error` MUST NOT reconciliar nada. (D83/RN-177)

#### Scenario: ack ok de restore_original
- **WHEN** llega un `command_ack` `ok` firmado para un `release_quarantine` con `mode = restore_original`
- **THEN** la fila queda `acked` y `baseline_entries` del path y agente queda `present` con `hash = event.hash_detected`
- **AND** `ruleset_version_applied` del agente avanza al `ruleset_version` del comando si era menor

#### Scenario: ack ok de discard
- **WHEN** llega un `command_ack` `ok` para un `release_quarantine` con `mode = discard`
- **THEN** la fila queda `acked` y `baseline_entries` no cambia

#### Scenario: ack de error
- **WHEN** llega un `command_ack` `error` con `error = "path_occupied"` para un `restore_original`
- **THEN** la fila queda `failed` con ese error y `baseline_entries` no cambia

#### Scenario: Sin confirmación
- **WHEN** un `release_quarantine` no recibe `command_ack` dentro del plazo del barrido
- **THEN** la fila pasa a `timeout`
