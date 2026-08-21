## ADDED Requirements

### Requirement: Any classification that yields a hash discards the event when neither the hash nor the object type changed

The detector SHALL treat "no real change, no event" as a property of the detector, not of one branch. For **every** event classification that produces a `current_hash` — `file_modified`, `file_absent`, and `file_created` (which covers both `FAN_CREATE` and `FAN_MOVED_TO`) — the detector MUST discard the event without publishing when both of the following hold:

- `current_hash is not None` and `current_hash` equals the hash recorded in the baseline entry for that path, **and**
- the object type did not change: the path is a symlink now if and only if the baseline entry records it as a symlink (`entry.symlink_target is not None`).

A `MOVED_TO` whose resulting hash equals the baseline hash is not an integrity violation. RN-32 requires a restore to be verified against the baseline hash and RN-33 states that after a successful restore the baseline "already contains the correct hash, which is the same as the restored file's" — so reporting that file as a change contradicts rules the agent already implements. This closes the second half of the mechanism D19 / RN-117 describes: the `.fim_restore_tmp` suffix filter suppresses the temporary file's own events, and this discard suppresses the `FAN_MOVED_TO` that `os.replace` delivers on the **final** path, which never carries the suffix.

The discard MUST happen after `current_hash` is computed and **before** the event reserves an `event_id` or mutates the pending/reverse indices, so that a discarded event leaves no trace in the supersession bookkeeping. A discarded event MUST NOT write a baseline entry, add a snapshot, or mark the path absent.

The `file_deleted` classification is explicitly outside this requirement: it produces no hash, and the absence of a file is never "no change".

Object-type identity is required in addition to hash equality because a type change is itself an integrity violation (D33 / RN-127, symlink-as-object). Requiring it can only make the discard stricter, never more permissive. The symlink hash remains `sha256(os.readlink(path))` — the hash of the target **string**, never of its content.

#### Scenario: A MOVED_TO landing baseline-identical content produces no event
- **WHEN** a rename delivers `FAN_MOVED_TO` on a monitored path whose baseline entry records hash `H`, and the file's content now hashes to `H`
- **THEN** no event is published, no `event_id` is reserved, and the baseline entry is left untouched

#### Scenario: A FAN_CREATE landing baseline-identical content produces no event
- **WHEN** `FAN_CREATE` arrives for a path whose baseline entry is `present` with hash `H`, and the file hashes to `H`
- **THEN** no event is published

#### Scenario: A MOVED_TO landing different content still produces exactly one file_created event
- **WHEN** a rename delivers `FAN_MOVED_TO` on a monitored path whose baseline entry records hash `H`, and the file now hashes to `H2 != H`
- **THEN** exactly one event with `event_type: "file_created"` is published

#### Scenario: A type change is not suppressed even when the hashes coincide
- **WHEN** `FAN_MOVED_TO` arrives for a path whose baseline entry records a `symlink_target`, the path is now a regular file, and its content hash equals the baseline hash
- **THEN** the event is published, because the object type changed

#### Scenario: Recreating a previously deleted path is never suppressed
- **WHEN** a path was marked absent (baseline `status: "absent"`, `hash: null`) and a file is then created at that path
- **THEN** the event is published, because a null baseline hash equals no real hash

#### Scenario: A discarded event does not supersede the pending event for that path
- **WHEN** a `file_modified` event `e1` is pending for path `p` and a subsequent `MOVED_TO` on `p` is discarded by this requirement
- **THEN** `e1` remains the pending event registered for `p`, and no new `event_id` is mapped to it

#### Scenario: The suffix filter keeps working for the temporary file itself
- **WHEN** any fanotify event arrives for a path ending in `.fim_restore_tmp`
- **THEN** it is discarded at the top of processing, before classification, exactly as D19 / RN-117 already requires

### Requirement: The discard invariant is verified against a real filesystem, never a mocked one

The tests that cover this invariant SHALL exercise a real `BaselineEngine` over a real temporary directory and a real `DecisionEngine` performing real `os.open` / `os.replace` calls. Mocking the filesystem or the baseline is what allowed the feedback loop to survive a 417-test agent suite: the loop is a property of the coupling between the detector and the decision engine, and every unit was individually green while the coupling was broken. Only the network publisher and the arrival of kernel events may be simulated.

A test asserting that no event is published MUST first assert that the restore actually took effect — the restored file's content on disk and a journal entry in its completed state. "No event was published" is also true when the restore **fails**, which is the state the system was in for its entire life before change 41 (`agent-deployment-caps`) granted the write capabilities and derived `ReadWritePaths`. A test that only counts events would have passed green throughout that period without executing a single line of the path under test.

Every suppression scenario MUST have a symmetric scenario that asserts an event **is** published, so that a filter which suppresses too much is distinguishable from a correct one.

#### Scenario: The restore is proven to have happened before suppression is asserted
- **WHEN** the integration test drives a tamper-then-restore cycle
- **THEN** it asserts the file's on-disk content matches the known-good baseline content and the journal entry reached `completed`, and only then asserts that the resulting `MOVED_TO` published nothing

#### Scenario: The event pump terminates under a hard ceiling
- **WHEN** the regression test re-injects the `MOVED_TO` the kernel would deliver after each restore the engine actually performs
- **THEN** the pump runs under a fixed iteration ceiling that fails the test if reached, so a reintroduced loop is a legible failure rather than a hung CI job
