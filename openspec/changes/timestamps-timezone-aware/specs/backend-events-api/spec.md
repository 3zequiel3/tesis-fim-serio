## ADDED Requirements

### Requirement: Every instant the API emits carries an explicit UTC offset

Every timestamp field in every API response SHALL be serialized as ISO-8601 with an explicit offset — `2026-08-20T19:55:59.641248+00:00`. No response MAY contain a date-time string without a time zone designator.

This is not a formatting preference. ECMAScript requires a date-time string with no designator to be interpreted as **local time**, so `new Date(iso)` in a browser shifts the instant by the viewer's offset. Emitting the offset is what makes the value mean the same thing to every consumer.

The requirement covers every endpoint that returns an instant, including the event listing and detail, the alert feed, the agent listing and the health report — not only the events routes.

#### Scenario: A listed event carries the offset
- **WHEN** `GET /events` returns any event
- **THEN** `detected_at`, `received_at` and `created_at` each end in an explicit offset, and `resolved_at` does too when it is not null

#### Scenario: The serialized form is rejected when the offset is absent
- **WHEN** a serialized timestamp is examined
- **THEN** parsing it yields a time-zone-aware value, and the check MUST interrogate that the parsed value carries a zone — not merely that the string parses, since a naive string parses just as well

#### Scenario: A null instant stays null
- **WHEN** an event has no `resolved_at`
- **THEN** the field is `null`, not an empty string and not a fabricated instant

#### Scenario: A round trip through the API preserves the instant
- **WHEN** an event is stored with a known, literal UTC instant and then read back through the API
- **THEN** the value returned denotes that same instant, compared against the known constant rather than against another value produced by the same path

### Requirement: Date range filters are interpreted as instants

`GET /events` SHALL accept `date_from` and `date_to` as ISO-8601 values carrying an explicit offset, and SHALL interpret them as instants when comparing against `created_at`.

A value that arrives without an offset SHALL be interpreted as UTC, so that the endpoint keeps a defined meaning for existing links rather than depending on server-side configuration. The endpoint MUST NOT interpret an incoming value in the server's local zone.

The filtered range MUST be the range the caller asked for. Today the frontend sends the browser's raw local wall-clock string and the backend compares it against UTC columns, so in a UTC−3 zone the window queried is displaced three hours from the window requested.

#### Scenario: An offset-bearing range selects by instant
- **WHEN** `GET /events` is called with `date_from` and `date_to` carrying explicit offsets
- **THEN** exactly the events whose `created_at` falls within that interval of instants are returned, independently of the server's session zone

#### Scenario: Two equivalent ranges expressed in different zones select the same events
- **WHEN** the same interval is expressed once with a `+00:00` offset and once with a `-03:00` offset denoting the same instants
- **THEN** both calls return the same events

#### Scenario: A range without an offset is read as UTC
- **WHEN** `GET /events` is called with `date_from` written without an offset
- **THEN** it is interpreted as UTC, and the response is identical to the same call with an explicit `+00:00`

#### Scenario: Boundary events are included
- **WHEN** an event's `created_at` equals `date_from` exactly, and another equals `date_to` exactly
- **THEN** both are returned, preserving the inclusive bounds the endpoint already had
