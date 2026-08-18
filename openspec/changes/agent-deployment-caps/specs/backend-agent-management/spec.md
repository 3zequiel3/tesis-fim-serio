## ADDED Requirements

### Requirement: The heartbeat consumer persists the per-path write status on the Agent model

The `Agent` model SHALL gain a nullable JSON column holding the map of watch path to write classification reported by the agent's heartbeat, added by an idempotent raw SQL migration following the project's convention. The model already stores `watch_paths` as a JSON column, so this follows an established precedent in the same table rather than introducing a new persistence pattern.

The heartbeat consumer SHALL read the status map from the heartbeat payload and persist it. The consumer applies no schema and no allowlist to heartbeat payloads today — it reads the fields it needs and ignores the rest — so reading one more key requires no change to signature verification.

Tolerance SHALL work in both directions:

- when the key is **absent**, the stored column SHALL be left untouched, so a heartbeat from an older agent does not erase the last known status;
- when the value is **not a mapping of strings**, it SHALL be ignored with a warning and the heartbeat SHALL still be processed normally. A malformed extra field must never make an agent appear offline.

The agent responses returned by the list and detail endpoints SHALL expose the stored map. Both endpoints serialize through a single conversion function, so the change has one point of application. (D36 / RN-130, RN-92, RN-93)

#### Scenario: A reported status map is persisted

- **WHEN** a signed heartbeat carrying a watch path status map is consumed
- **THEN** the map is persisted on the agent row and the usual heartbeat side effects still occur

#### Scenario: An older agent does not erase the stored status

- **WHEN** a heartbeat arrives with no status map key
- **THEN** the previously stored map is retained unchanged

#### Scenario: A malformed status value does not break the heartbeat

- **WHEN** a heartbeat carries a status value that is not a mapping of strings
- **THEN** the value is ignored with a warning, the stored map is retained, and the agent's liveness and queue pressure are still updated

#### Scenario: The list endpoint exposes the status map

- **WHEN** the agent list is requested
- **THEN** each agent carries its watch path status map

#### Scenario: The detail endpoint exposes the status map

- **WHEN** a single agent is requested by identifier
- **THEN** the response carries its watch path status map

#### Scenario: An agent that never reported has a null map

- **WHEN** an agent registered before this change is returned
- **THEN** its status map is null rather than an empty object misread as "all paths writable"
