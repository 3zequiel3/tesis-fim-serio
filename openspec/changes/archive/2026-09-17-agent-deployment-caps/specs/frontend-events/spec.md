## ADDED Requirements

### Requirement: The event detail explains why an automatic remediation failed

The event detail view SHALL show the cause of a failed automatic action in prose, qualifying the remediation-failure indicator introduced by D35 / RN-129. The purpose is the one D36 states directly: an operator MUST be able to tell a deployment problem — the path was not writable — from a data problem — the baseline was missing or unusable — without leaving the interface.

The mapping SHALL be a pure function returning a label and a style, or nothing when there is no cause, following the isolated-and-tested mapper pattern already established in the frontend. Known values SHALL map to prose. An unknown value SHALL fall back to rendering the raw literal rather than being hidden, so an agent newer than the frontend degrades to "less readable" instead of "silently missing".

The events **table** SHALL NOT change. The remediation-failure indicator there already communicates the fact; the cause is second-level information that does not justify another column in an already dense table. (D36 / RN-130, D35 / RN-129, RN-71)

#### Scenario: A deployment cause reads as a deployment problem

- **WHEN** an event detail is opened for a failed remediation whose cause is a read-only mount
- **THEN** the view shows prose identifying it as a write-access problem on the host, distinct from a baseline problem

#### Scenario: A data cause reads as a data problem

- **WHEN** the cause is a missing baseline
- **THEN** the view shows prose identifying it as a baseline problem

#### Scenario: An unknown cause falls back to the raw value

- **WHEN** the cause is a literal the frontend does not recognize
- **THEN** the raw literal is displayed rather than nothing

#### Scenario: An event with no cause shows no extra element

- **WHEN** an event has no failure cause
- **THEN** no cause element is rendered and the existing badges are unaffected

#### Scenario: The events table is unchanged

- **WHEN** the events table is rendered after this change
- **THEN** it carries the same columns as before, with the remediation-failure indicator unchanged
