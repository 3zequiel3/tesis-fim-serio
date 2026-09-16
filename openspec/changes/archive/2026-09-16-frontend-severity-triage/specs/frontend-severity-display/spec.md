## ADDED Requirements

### Requirement: A single shared contract for severity presentation

The frontend SHALL expose one module (`frontend/src/utils/severity.ts`) that owns every presentational fact about `critical | high | medium | low`, following the helper convention the project already uses for exactly this problem (`utils/ackStatus.ts`, `utils/actionFailed.ts`, `utils/timeDisplay.ts`).

Today the same four-entry palette is copied verbatim in three files — `pages/Alerts.tsx:28-33`, `pages/Rules.tsx:12-17`, `pages/FailedAlerts.tsx:11-16` — and is absent from the one screen where it matters most. Adding a fourth copy would consolidate the mistake; the three existing copies SHALL be replaced by the shared module as part of this change, because leaving them in place would produce four sources of truth instead of the three that exist today.

The module SHALL expose, for each level: the text class used when the value is rendered as a word, the edge-band class used when the value is rendered as a scan cue, and a numeric precedence rank ordering `critical > high > medium > low`. The rank is domain knowledge — "which severity is higher" — that is currently written nowhere in the frontend, and that any future comparison would otherwise have to reconstruct from a map of Tailwind class names.

All four levels SHALL be defined even though the live ruleset currently produces only three (`medium` matches zero events). A level that only appears once someone writes the first `medium` rule is a level that would be discovered as a defect.

#### Scenario: Every severity level resolves to a distinct treatment
- **WHEN** the presentation for each of `critical`, `high`, `medium`, `low` is requested
- **THEN** each yields a text class and an edge-band class, and no two levels share the same text class or the same edge-band class

#### Scenario: An unknown value degrades instead of crashing
- **WHEN** presentation is requested for a value outside the four known levels
- **THEN** a neutral fallback treatment is returned, and nothing throws

#### Scenario: Precedence orders the levels as the domain does
- **WHEN** the four levels are sorted by their rank
- **THEN** the order is `critical`, `high`, `medium`, `low`

#### Scenario: The three migrated screens render exactly what they rendered before
- **WHEN** the alerts list, the rules list and the failed-alerts list render a severity after migrating to the shared module
- **THEN** the resulting text class for each level is identical to the one the local copy produced, so the migration is observably a no-op on those screens

---

### Requirement: Severity is encoded twice — as a scan cue and as a readable value

Wherever a list row carries a severity, that severity SHALL be encoded in two independent channels: a **colour band on the row's leading edge**, and the **canonical value rendered as text**.

The two channels answer different questions and neither substitutes for the other. The band answers "where should I look" across a long list without fixating on any row, and it occupies a visual channel that is otherwise empty — unlike a badge, which would compete with the badges the row already carries. The text answers "what is this", which is what US-06 actually requires: a colour band does not *show* a value, it suggests one. Colour alone is also not an accessible encoding (WCAG 1.4.1), and `critical` against `high` is red against orange — adjacent in the spectrum and the exact pair a red-green colour-blind operator cannot separate.

The text SHALL be low-chroma: the level's colour on the page background, without a filled or bordered chip. A chip would reintroduce the competition the band exists to avoid.

The value SHALL be rendered in lowercase, matching how `Alerts.tsx:142` and `Rules.tsx:183` already render it. C1/RN-71 governs event *status* values and does not speak to severity, so this follows the project's established precedent rather than applying the rule.

#### Scenario: A row carries both encodings
- **WHEN** an event row with severity `critical` is rendered
- **THEN** the row shows the text `critical` and carries the leading-edge band for `critical`

#### Scenario: Different severities are visually distinguishable
- **WHEN** a `critical` row and a `low` row are rendered in the same list
- **THEN** their leading-edge treatments differ

#### Scenario: The value survives with colour removed
- **WHEN** a row is read without any colour information
- **THEN** the severity is still recoverable, because it is present as text
