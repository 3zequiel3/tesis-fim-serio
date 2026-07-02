## MODIFIED Requirements

### Requirement: Detector discards events outside the configured watch_path scope

Because the detector marks the whole filesystem (`FAN_MARK_FILESYSTEM`), it MUST enforce RN-04 ("only configured paths generate events; everything else is ignored; exceptions: none") in software. Scope containment is evaluated **by the location of the path itself, not by its resolved target**: in `_read_loop`, before constructing the internal `FanotifyEvent`, the detector SHALL call a new `_path_location_in_scope(path, watch_paths)` that canonicalizes ONLY the parent directory (`os.path.realpath(os.path.dirname(path))`) and compares the literal `basename` against the canonicalized `watch_paths`, WITHOUT resolving (without following) the final path component even when it is a symlink. The detector SHALL discard the event when this location check is not satisfied. This replaces the previous full-`realpath` containment (D31), which dereferenced the final component and therefore hid an in-scope symlink whose target resolved out of scope. The previous full-`realpath` helper is renamed `_target_in_scope` and retained ONLY for metadata checks that need to know whether the resolved target falls in scope; it MUST NOT be used at the discard point. The check MUST run at the read stage (before enqueueing into the bounded `_raw_queue`), NOT only at the `_process_event` classification stage, so the bounded queue never absorbs out-of-scope noise. The `watch_paths` SHALL be canonicalized to `realpath` exactly once — in `start()`, `reload_paths()`, and `reload_watch_paths()` — and cached; canonicalization MUST NOT run per event. A `watch_path` that is itself a symlink is canonicalized once and that `realpath` defines its containment boundary (D31 behavior preserved). (D31 / RN-125, refined by D33 / RN-127)

#### Scenario: Event whose parent directory is inside a watch_path is processed
- **WHEN** a fanotify event arrives whose parent directory `os.path.realpath(os.path.dirname(path))` is relative to a canonicalized `watch_path`
- **THEN** the detector builds the `FanotifyEvent` and enqueues it for processing, regardless of whether the final component is a symlink pointing out of scope

#### Scenario: Escape symlink created inside a watch_path is no longer invisible
- **WHEN** a symlink `/etc/evil -> /root/.ssh/authorized_keys` is created inside a configured `watch_path` and its resolved target is out of scope
- **THEN** the detector treats the event as in-scope because the link's parent directory is in scope, and it does NOT discard the event

#### Scenario: Event whose parent directory is outside every watch_path is dropped at read time
- **WHEN** a fanotify event arrives whose parent directory realpath is not relative to any canonicalized `watch_path`
- **THEN** the detector discards it in `_read_loop` without constructing a `FanotifyEvent` and without enqueueing it into `_raw_queue`

#### Scenario: Deleting a regular file inside scope is still published
- **WHEN** a regular file inside a `watch_path` is deleted (its final component no longer exists, but its parent directory does)
- **THEN** `_path_location_in_scope` resolves the still-existing parent directory, the event is kept, and the `file_deleted` event is published (no regression of the C35 legitimate-delete trap)

#### Scenario: watch_paths are canonicalized once, not per event
- **WHEN** the detector starts or reloads its watch paths via `start()`, `reload_paths()`, or `reload_watch_paths()`
- **THEN** each `watch_path` is resolved to `realpath` a single time and the cached values are used for every subsequent scope check

#### Scenario: A watch_path that is itself a symlink defines its boundary by realpath
- **WHEN** a configured `watch_path` is a symlink and an event occurs under its resolved target
- **THEN** the event is treated as in-scope because containment is evaluated against the canonicalized `watch_path`

## ADDED Requirements

### Requirement: In-scope symlinks are reported as filesystem objects, never followed

For any path whose final component is a symlink and whose location is in scope (per `_path_location_in_scope`), the detector SHALL treat the symlink as a filesystem object in its own right and MUST NEVER follow it: it MUST NOT open, hash, or encrypt the content of the symlink target, whether that target is inside or outside scope. In `_process_event`, the symlink branch SHALL use `os.lstat`/`os.readlink` only. The event MUST be reported using the existing RN-71 canonical lexicon (`file_created` / `file_deleted` / `file_modified`) — NO new `event_type` is introduced. The reported `hash_detected` SHALL be `sha256(os.readlink(path))` (a hash of the target string, not of the target's content), and the content `diff` SHALL be `None`. Re-pointing an existing symlink to a different target SHALL be detected as `file_modified` because the `readlink` string changes. The event payload SHALL carry `is_symlink=true` and `symlink_target` (the `readlink` string); backend consumers that ignore unknown keys are unaffected. (D33 / RN-127)

#### Scenario: Creating an in-scope symlink reports file_created with target-string hash
- **WHEN** a symlink is created inside a `watch_path`
- **THEN** the detector reports `file_created`, sets `hash_detected = sha256(os.readlink(path))`, leaves the content diff as `None`, and never reads the target's bytes

#### Scenario: Re-pointing an existing symlink reports file_modified
- **WHEN** an existing in-scope symlink is changed to point at a different target
- **THEN** the detector reports `file_modified` because the `readlink` string (and therefore its hash) changed

#### Scenario: Symlink target content is never read regardless of target scope
- **WHEN** an in-scope symlink points at a target that is out of scope (e.g. `/root/.ssh/authorized_keys`) or in scope
- **THEN** the detector uses `os.lstat`/`os.readlink` only and never opens, hashes, or encrypts the target's content

#### Scenario: Symlink event payload carries symlink metadata
- **WHEN** the detector publishes an event for an in-scope symlink
- **THEN** the payload includes `is_symlink=true` and `symlink_target` set to the `readlink` string

#### Scenario: Deleting an in-scope symlink reports a real file_deleted, not a spurious one
- **WHEN** an in-scope symlink that was previously reported and baselined is deleted
- **THEN** the detector reports a real `file_deleted` (the baseline entry exists to distinguish it from a `file_absent`), resolving the LOW-1 spurious-delete finding as a consequence

### Requirement: Optional hardlink_suspected detective counter in heartbeat

Hardlinks are a known unresolved limitation: `os.path.realpath`/`os.lstat` cannot distinguish a hardlink from a regular file, and determining whether another name of the same inode falls out of scope would require a full-filesystem scan incompatible with the agent's bounded-queue reactive design. As a cheap detective signal with NO change of behavior, the detector MAY maintain a monotonic `hardlink_suspected` counter that increments when a regular file is created in scope with `st_nlink >= 2`, and expose it in the `agent_heartbeat` payload. This counter MUST NOT alter classification, hashing, encryption, or event publication. (D33 / RN-127)

#### Scenario: Creating an in-scope regular file with st_nlink >= 2 increments the counter
- **WHEN** a regular file is created inside a `watch_path` and its `st_nlink >= 2`
- **THEN** `hardlink_suspected` is incremented by one and the event is otherwise processed exactly as a normal regular-file create

#### Scenario: hardlink_suspected is surfaced in the heartbeat without changing behavior
- **WHEN** the heartbeat publisher builds its periodic payload
- **THEN** the payload MAY include a `hardlink_suspected` field reflecting the current count, and no detection, hashing, or publication behavior is altered by its presence
