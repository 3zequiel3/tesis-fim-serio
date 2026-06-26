## ADDED Requirements

### Requirement: Signal handlers are registered only after queue and publisher exist

The agent main entrypoint SHALL initialize `queue` and `publisher` to `None`, construct them, and only THEN register the `SIGTERM`/`SIGINT` handlers via `loop.add_signal_handler`. The `_shutdown` callback MUST early-return when `queue` or `publisher` is still `None`, so a signal delivered during startup is a safe no-op rather than a `NoneType` access. (FA1)

#### Scenario: Signal during startup before publisher exists is a safe no-op
- **WHEN** a `SIGTERM` is delivered after handlers are registered but `publisher` is still `None`
- **THEN** `_shutdown` early-returns without raising, leaving the process to finish startup or exit cleanly

#### Scenario: Handlers are registered after queue and publisher construction
- **WHEN** the agent main coroutine sets up signal handling
- **THEN** `loop.add_signal_handler(SIGTERM/SIGINT, ...)` is invoked only after `queue = EventQueue(...)` and `publisher = Publisher(...)` have been assigned

### Requirement: Shutdown closes the fanotify fd and joins the reader thread

On shutdown the agent SHALL, in its `finally` block, call `detector.close()` before the process exits. `detector.close()` MUST close the fanotify file descriptor — which unblocks the `fan-reader` thread parked in the blocking `read()` syscall — and then `join()` that thread with a 5-second timeout. The agent MUST NOT leak the fanotify fd or leave an orphaned reader thread on exit. (FA4)

#### Scenario: Clean shutdown unblocks and joins the reader thread
- **WHEN** the agent receives `SIGTERM` while the `fan-reader` thread is blocked in `read()`
- **THEN** `detector.close()` closes the fanotify fd, the `read()` syscall returns/raises, and the thread is joined within the 5-second timeout

#### Scenario: No fanotify fd leak on exit
- **WHEN** the agent process terminates through its normal shutdown path
- **THEN** the fanotify fd has been explicitly closed by `detector.close()` and is not relying on process teardown
