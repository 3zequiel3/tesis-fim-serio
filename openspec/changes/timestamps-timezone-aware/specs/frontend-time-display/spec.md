## ADDED Requirements

### Requirement: A single helper owns how an instant is rendered

All rendering of an instant SHALL go through one shared helper module. No component MAY call `toLocaleString` or construct a `Date` for display on its own.

Today the same decision is made independently at nine call sites — `Alerts.tsx:41`, `EventsTable.tsx:156`, `EventDetail.tsx:177,181,186`, `FailedAlerts.tsx:18`, `Dashboard.tsx:91`, `EventTimeline.tsx:55,59` and `AgentCard.tsx:61` — with no shared contract, which is why a three-hour displacement could be uniform across the console and still be nobody's responsibility. Centralising it is what makes the behaviour assertable in a test instead of reviewable by eye.

The helper module lives beside the existing helpers under `frontend/src/utils/`, each with its test alongside it, following the convention already established there by `ackStatus`, `actionError` and `eventFilters`.

#### Scenario: No component formats an instant directly
- **WHEN** the frontend sources are scanned for direct date formatting in components
- **THEN** no component contains a `toLocaleString`, `toLocaleDateString` or `toLocaleTimeString` call on a value derived from the API

### Requirement: An absolute time is always shown together with its zone

Whenever an absolute instant is displayed, the zone it is expressed in SHALL be visible alongside it. An operator correlating the console against `journalctl` or a packet capture needs to know which clock they are reading; a bare wall-clock time cannot be correlated with anything.

The instant SHALL be rendered in the viewer's own zone. The system does not offer a zone selector: it shows the operator their own clock, and labels it.

#### Scenario: A known UTC instant renders as the expected local time, with its zone
- **WHEN** the instant `2026-08-20T19:55:59+00:00` is rendered with the viewer's zone fixed to `America/Argentina/Buenos_Aires`
- **THEN** the output shows 16:55:59 on 2026-08-20 and carries a visible zone indication

#### Scenario: The test that proves this cannot pass under a UTC viewer
- **WHEN** the rendering tests run
- **THEN** the zone is fixed explicitly to one whose offset is not zero, and a test asserts that the effective offset is non-zero — so that losing the configuration breaks the suite rather than silently emptying it of meaning

#### Scenario: An offset-bearing string is not shifted
- **WHEN** an instant arrives from the API with an explicit offset
- **THEN** it is parsed as that instant, and the rendered local time equals the instant converted to the viewer's zone

### Requirement: Relative time accompanies the absolute form and is never negative

Where it helps an operator decide — recency of a heartbeat, age of an alert — the instant SHALL also be offered in relative form ("hace 4 min"). The relative form accompanies the absolute one; it does not replace it, because a relative time cannot be correlated against an external log.

An instant in the future SHALL be rendered as such, and MUST NOT produce a negative elapsed time. A future instant is no longer reachable through the display defect this change removes, but it remains reachable through a desynchronised clock on the agent host — which is precisely the condition RN-90 and RN-131 exist to watch. It is operational information and SHALL be surfaced, not clamped to zero and hidden.

#### Scenario: A fresh heartbeat reads as moments ago, not as a negative interval
- **WHEN** an agent's `last_heartbeat` is a few seconds in the past and the viewer is in a non-UTC zone
- **THEN** the elapsed time shown is a small positive interval

#### Scenario: A future instant is labelled, not negated
- **WHEN** an instant lies in the future relative to the viewer's clock
- **THEN** the output indicates a future instant and no negative interval is produced

#### Scenario: A null instant is rendered as an absent value
- **WHEN** the instant is `null` — an agent that has never sent a heartbeat, an event that is not resolved
- **THEN** the output is an explicit absence, and never `Invalid Date` nor a fabricated instant

#### Scenario: An unparseable value degrades visibly
- **WHEN** the value is present but cannot be parsed as an instant
- **THEN** the output indicates that the value is invalid rather than rendering `Invalid Date` or an empty string
