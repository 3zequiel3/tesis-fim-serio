## ADDED Requirements

### Requirement: Detector discards events outside the configured watch_path scope

Because the detector marks the whole filesystem (`FAN_MARK_FILESYSTEM`), it MUST enforce RN-04 ("only configured paths generate events; everything else is ignored; exceptions: none") in software. In `_read_loop`, before constructing the internal `FanotifyEvent`, the detector SHALL resolve the event path with `os.path.realpath()` and discard the event when that real path is NOT `is_relative_to` any canonicalized `watch_path`. The check MUST run at the read stage (before enqueueing into the bounded `_raw_queue`), NOT only at the `_process_event` classification stage, so the bounded queue never absorbs out-of-scope noise. The `watch_paths` SHALL be canonicalized to `realpath` exactly once — in `start()`, `reload_paths()`, and `reload_watch_paths()` — and cached; canonicalization MUST NOT run per event. A `watch_path` that is itself a symlink is canonicalized once and that `realpath` defines its containment boundary. This reuses the `realpath` containment pattern already validated in D18/RN-116 (`agent/commands.py`). (D31 / RN-125)

#### Scenario: Event whose real path is inside a watch_path is processed
- **WHEN** a fanotify event arrives whose `os.path.realpath()` is relative to a canonicalized `watch_path`
- **THEN** the detector builds the `FanotifyEvent` and enqueues it for processing

#### Scenario: Event whose real path is outside every watch_path is dropped at read time
- **WHEN** a fanotify event arrives whose `os.path.realpath()` is not relative to any canonicalized `watch_path`
- **THEN** the detector discards it in `_read_loop` without constructing a `FanotifyEvent` and without enqueueing it into `_raw_queue`

#### Scenario: watch_paths are canonicalized once, not per event
- **WHEN** the detector starts or reloads its watch paths via `start()`, `reload_paths()`, or `reload_watch_paths()`
- **THEN** each `watch_path` is resolved to `realpath` a single time and the cached values are used for every subsequent scope check

#### Scenario: A watch_path that is itself a symlink defines its boundary by realpath
- **WHEN** a configured `watch_path` is a symlink and an event occurs under its resolved target
- **THEN** the event is treated as in-scope because containment is evaluated against the canonicalized `watch_path`

### Requirement: Out-of-scope drop counter is surfaced via heartbeat

The detector SHALL maintain a monotonic `out_of_scope_drops` counter that increments each time an event is discarded for falling outside the configured `watch_paths`, analogous to the existing `event_drops` counter. The current count MUST be readable by the heartbeat publisher and included in the `agent_heartbeat` payload as the field `out_of_scope_drops`. This is the only operational visibility into how much filesystem-wide traffic `FAN_MARK_FILESYSTEM` is discarding. (D31 / RN-125)

#### Scenario: Dropping an out-of-scope event increments the counter
- **WHEN** the detector discards an event because its real path is outside every `watch_path`
- **THEN** `out_of_scope_drops` is incremented by one and a warning is logged

#### Scenario: Out-of-scope drop counter is exposed in the heartbeat
- **WHEN** the heartbeat publisher builds its periodic payload
- **THEN** the payload includes an `out_of_scope_drops` field reflecting the detector's current cumulative out-of-scope drop count

#### Scenario: In-scope traffic does not increment the counter
- **WHEN** all incoming events resolve inside the configured `watch_paths`
- **THEN** `out_of_scope_drops` remains unchanged
