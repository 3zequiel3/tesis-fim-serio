# agent-command-dispatch Specification

## Purpose
TBD — estructura reparada por el change openspec-main-specs-repair. El archivo se habia escrito con encabezados de delta, que ocultaban sus requisitos al tooling. Actualizar este Purpose con el proposito real de la capability.
## Requirements
### Requirement: Destructive command handlers are registered at startup

The agent SHALL register the command-handler dependencies (baseline engine, agent state, journal, quarantine directory, detector) on the publisher before the command listener starts processing the `commands` stream, so that `baseline_update`, `restore_file`, `quarantine_file`, and `rescan_baseline` are dispatched to their real handlers instead of being silently ignored. (RN-79, RN-83)

#### Scenario: Handlers registered during agent startup

- **WHEN** the agent process starts on Linux and finishes constructing the detector
- **THEN** `publisher.register_command_handlers(engine, state, journal, quarantine_dir, detector)` is called before `publisher.run` begins consuming the `commands` stream
- **AND** the publisher's `_baseline_engine`, `_agent_state`, `_journal`, `_quarantine_dir`, and `_detector` references are all non-null.

#### Scenario: restore_file is executed, not dropped

- **WHEN** the backend publishes a valid `restore_file` command targeted at this agent
- **THEN** the agent dispatches it through `commands.dispatch` and performs the restore
- **AND** the agent does NOT log `publisher.command_handler_not_registered`.

#### Scenario: quarantine_file is executed, not dropped

- **WHEN** the backend publishes a valid `quarantine_file` command targeted at this agent
- **THEN** the agent dispatches it through `commands.dispatch` and quarantines the file.

### Requirement: All inbound commands are HMAC-verified at a single entry point

The agent SHALL verify the HMAC-SHA256 signature of every message read from the `commands` stream through a single entry point before any side effect occurs, rejecting messages whose signature is missing or invalid. No command type — present or future, including `event_ack`, `update_config`, and `rule_sync` — SHALL be acted upon without passing this verification. (RN-79)

#### Scenario: Valid signature is accepted

- **WHEN** a command message arrives with `signature == HMAC-SHA256(shared_secret, canonical_json(payload))`
- **THEN** the single entry point returns the parsed payload
- **AND** the command is processed normally.

#### Scenario: Invalid signature is rejected

- **WHEN** a command message arrives whose `signature` does not match the expected HMAC over its canonical payload
- **THEN** the single entry point returns `None`
- **AND** no handler runs, the offline queue is not modified, fanotify watchers are not reconfigured, and no rules are injected.

#### Scenario: Missing signature is rejected

- **WHEN** a command message arrives with no `signature` field
- **THEN** the single entry point returns `None` and the message is dropped without side effects.

#### Scenario: event_ack without valid signature does not purge the queue

- **WHEN** an `event_ack` message with an invalid signature is written to the `commands` stream
- **THEN** the agent does NOT remove the referenced event from the offline queue and does NOT clear the corresponding pending entry.

#### Scenario: Malformed JSON is rejected

- **WHEN** a message payload is not valid JSON
- **THEN** the entry point returns `None` and the message is dropped without raising.

### Requirement: target_agent_id filtering is preserved after verification

The agent SHALL ignore commands whose `target_agent_id` is set to a value other than this agent's `agent_id`, while still accepting broadcast commands where `target_agent_id` is null or absent. This filtering SHALL apply to every command type. (D5, RN-106)

#### Scenario: Command for another agent is ignored

- **WHEN** a validly signed command arrives with `target_agent_id` not equal to this agent's `agent_id`
- **THEN** the command is ignored with no side effects.

#### Scenario: Broadcast command is accepted

- **WHEN** a validly signed command arrives with `target_agent_id` null or absent
- **THEN** the command is processed normally.

### Requirement: update_config is dispatched only through the versioned handler

The agent SHALL route `update_config` exclusively through `commands.dispatch` → `handle_update_config`, which enforces `ruleset_version` monotonicity and persists the new state. The agent SHALL NOT contain any direct `update_config` branch that reconfigures fanotify watchers while bypassing the version check. (RN-75)

#### Scenario: No duplicated direct update_config branch exists

- **WHEN** the command listener processes an `update_config` command
- **THEN** it reaches `handle_update_config` (which checks `ruleset_version` and persists state)
- **AND** there is no earlier code path that applies `watch_paths` without the version check.

#### Scenario: Stale update_config is rejected by version monotonicity

- **WHEN** a validly signed `update_config` command arrives with a `ruleset_version` less than or equal to the locally persisted `ruleset_version`
- **THEN** the watchers are not reconfigured and the stale command is rejected.

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

