## ADDED Requirements

### Requirement: release_quarantine se despacha por el whitelist y la verificación HMAC única

El publisher SHALL incluir `release_quarantine` en el conjunto de tipos que entrega a
`commands.dispatch`, y `commands.dispatch` SHALL enrutarlo a `handle_release_quarantine` con el
journal y el `QuarantineStore` registrados. Como todo comando, MUST pasar el filtro de
`target_agent_id` y la verificación HMAC-SHA256 antes de cualquier efecto; un `release_quarantine`
con firma ausente o inválida MUST descartarse sin tocar el filesystem, el baseline, el artefacto ni
el registro de comandos ejecutados. (D83/RN-177, RN-79)

#### Scenario: release_quarantine válido llega al handler
- **WHEN** el backend publica un `release_quarantine` firmado dirigido a este agente
- **THEN** `commands.dispatch` invoca `handle_release_quarantine`
- **AND** el agente no registra `publisher.command_handler_not_registered` ni `commands.dispatch.unknown_type`

#### Scenario: Firma inválida
- **WHEN** llega un `release_quarantine` cuya firma no valida
- **THEN** no se ejecuta ningún handler, el artefacto sigue existiendo y el path no cambia

#### Scenario: Otro agente destino
- **WHEN** llega un `release_quarantine` con `target_agent_id` de otro agente
- **THEN** se ignora sin efectos
