## ADDED Requirements

### Requirement: A wire contract is asserted from both sides against one versioned artifact

For every request shape covered by this capability, the repository SHALL hold a single JSON fixture under `contracts/`, and **both** sides SHALL assert against that same file: the frontend that the body its real HTTP client emits equals the fixture, the backend that the fixture is accepted by the real schema and the real endpoint.

The fixture SHALL live at the repository root, not under `frontend/` or `backend/`. Placing it under either side would make it "that side's belief, which the other consumes" — the original problem with a shared file on top of it. At the root it is what it is, and neither side owns it.

This exists because of a failure that two green test suites did not see. `frontend/src/api/actions.ts:64-66` sent `{items:[{event_id, version}], action}` with the action at the top level; `backend/app/modules/actions/schemas.py:57-61` requires it inside each item; every bulk reject returned 422 for the entire life of the project. Facing it, `backend/tests/test_actions_router.py:405` is named `test_bulk_reject_uses_items_contract_with_per_item_action` and passes. **Two suites, two incompatible contracts, zero shared assertions.** Each side verified its own belief and neither observed the other's.

Mock depth is not the fix, and the distinction matters. `bulkReject` calls `apiClient.post(url, body)`, so even the project's existing convention of mocking `@/api/client` captures the body object; a test written at the time would have asserted the wrong shape — written by the same person, from the same mental model that produced the code — and passed. What was missing was not a lower mock. It was any artifact that both sides answer to.

#### Scenario: The client's serialized body matches the fixture
- **WHEN** the frontend API function is invoked through the real HTTP client
- **THEN** the captured request body, parsed from its serialized form, deep-equals the fixture

#### Scenario: The backend schema accepts the fixture
- **WHEN** the backend validates the fixture against the request model for that endpoint
- **THEN** validation succeeds

#### Scenario: The backend endpoint accepts the fixture
- **WHEN** the fixture is posted to the real endpoint by an authorised caller
- **THEN** the response is not a 422 validation error

#### Scenario: A change on either side alone turns something red
- **WHEN** the frontend client's body shape changes without the fixture changing
- **THEN** the frontend assertion fails
- **AND WHEN** the backend request model changes without the fixture changing
- **THEN** the backend assertion fails

---

### Requirement: Every contract assertion is paired with its negative case

For each fixture, both sides SHALL also assert that the **superseded or malformed** shape is rejected.

A guard that has never been run against its own negative case is not known to be a guard. This project has already paid for that lesson once: `test_fix09_no_utcnow_in_production_modules` was a green test whose name asserted the absence of the very defect that was in production, because its predicate was never exercised against a failing input. Without the negative case here, someone could empty the fixture and both assertions would keep passing over nothing.

#### Scenario: The superseded bulk-reject shape is rejected by the backend
- **WHEN** a body carrying the reject action at the top level, and absent from each item, is posted to `POST /actions/bulk-reject`
- **THEN** the response is 422, and the validation error names the missing per-item `action`

#### Scenario: The frontend assertion can distinguish the two shapes
- **WHEN** the captured body is compared against a body carrying the action at the top level
- **THEN** the comparison fails, demonstrating the assertion is capable of detecting the regression

---

### Requirement: The capability covers the boundaries that have diverged, not every call

This change SHALL introduce the capability with the bulk-reject request body and the `GET /events` severity query, and SHALL NOT retrofit the frontend client's remaining calls.

The value of this technique is concentrated where two sides could drift apart. Writing fixtures in bulk now would mean authoring them by reading the backend's code — producing copies of the backend's belief, without the tension that makes the mechanism useful. The severity query is included because it crosses the boundary that just failed and because a repeatable array in a query string is precisely the kind of detail a module mock does not observe: `{severity: ['critical','high']}` is a plausible object that serialises three different ways, and only one is what the backend accepts.

The rule this establishes for new tests: **an assertion about the shape of a request body or query string goes against the shared fixture; an assertion about transformation logic may keep mocking the module.** The existing date-conversion test (`frontend/src/api/events.test.ts`) asserts a transformation property, not a contract, and stays as it is.

#### Scenario: The severity query is emitted as a repeatable parameter
- **WHEN** the events client is called with more than one severity selected
- **THEN** the emitted query string carries one `severity` parameter per value, in the form the backend accepts

#### Scenario: The severity query is asserted against the shared fixture
- **WHEN** the emitted query string is compared to the fixture for that request
- **THEN** they are equal, and the backend asserts the same fixture is accepted by `GET /events`
