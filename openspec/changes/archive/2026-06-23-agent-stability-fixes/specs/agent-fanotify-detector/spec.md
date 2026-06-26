## ADDED Requirements

### Requirement: Detector exposes close() for deterministic teardown

`FanotifyDetector` SHALL expose a `close()` method that closes the fanotify file descriptor and joins the internal `fan-reader` thread with a bounded timeout (5 seconds). Closing the fd MUST unblock the reader thread parked in the blocking `read()` syscall so the join completes promptly. `close()` MUST be idempotent: calling it when already closed is a safe no-op. (FA4)

#### Scenario: close() unblocks the reader thread and joins it
- **WHEN** `close()` is called while the reader thread is blocked in `read()`
- **THEN** the fanotify fd is closed, the syscall returns, and the thread is joined within 5 seconds

#### Scenario: close() is idempotent
- **WHEN** `close()` is called a second time after the detector is already closed
- **THEN** it returns without raising and without attempting to close an invalid fd

### Requirement: Raw event queue is bounded with a drop counter surfaced via heartbeat

The detector's in-memory raw event queue SHALL be bounded (`asyncio.Queue(maxsize=1000)`) to prevent unbounded memory growth under event storms. Because the producer runs on the `fan-reader` thread via `loop.call_soon_threadsafe`, the enqueue MUST go through a wrapper that catches `asyncio.QueueFull`, increments a monotonic `event_drops` counter, and emits a `warning` log instead of letting the exception be lost. The current `event_drops` count MUST be readable by the heartbeat publisher and included in the `agent_heartbeat` payload as the field `event_drops`. (FA5)

#### Scenario: Enqueue under saturation increments the drop counter
- **WHEN** the raw queue is full and a new fanotify event arrives from the reader thread
- **THEN** the wrapper catches `QueueFull`, increments `event_drops`, logs a warning, and does not propagate the exception

#### Scenario: Drop counter is exposed in the heartbeat
- **WHEN** the heartbeat publisher builds its periodic payload
- **THEN** the payload includes an `event_drops` field reflecting the detector's current cumulative drop count

#### Scenario: Normal enqueue under capacity does not drop
- **WHEN** the raw queue has free capacity and an event arrives
- **THEN** the event is enqueued and `event_drops` is unchanged
