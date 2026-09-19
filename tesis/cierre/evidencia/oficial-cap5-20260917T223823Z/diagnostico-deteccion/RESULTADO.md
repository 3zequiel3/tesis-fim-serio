# Item 9 — the unreported operations are baseline-match suppressions, not lost events

Battery 3 persisted fewer events than the generator performed: 480 of 500 in the sealed run,
481 of 500 here. This run instruments the agent to establish where the difference comes from.

## Method

The agent carries an experiment trace (`agent/experiment_trace.py`) that appends one JSONL record
per pipeline stage, enabled by `FIM_EXPERIMENT_TRACE_FILE` and `FIM_EXPERIMENT_RUN_ID`. It was
enabled through a systemd drop-in, Battery 3 was repeated in full (500 changes over 30 minutes,
03:55:28Z to 04:25:25Z), and the trace was correlated against the generator manifest and the
persisted events. The drop-in was removed afterwards, so the agent runs its normal configuration.

## Result

| Stage | Records |
|---|---|
| `kernel_received` | 513 |
| `baseline_read` | 513 |
| `change_classified` | 481 |
| `decision_evaluated` | 481 |
| `queue_enqueue_persisted` | 481 |
| `xadd_succeeded` | 481 |
| `ack_valid` | 481 |
| `decision_suppressed` | 31 |

The kernel delivered 513 in-scope events for 500 operations — some operations produce two, a
creation followed by its `close_write`. Nothing was dropped: no overflow, no unresolved path, no
out-of-scope discard on these paths. Every one of the 31 suppressions carries
`reason: matches_active_baseline` with `baseline_status: present`.

Correlating by path and timestamp, all 19 operations without a persisted event are explained by a
suppression, and in all 19 the `hash_after` the agent recorded equals the `hash_despues` the
generator recorded. There is no race and no late read: the agent hashed exactly the content the
operation wrote, and that content equalled the path's active baseline.

## Reading

The platform reports deviation from a baseline, not I/O activity. A write whose resulting content
is identical to the active baseline is not an integrity deviation, and suppressing it is the
documented behaviour — the same mechanism recorded as `suppressed_by_active_baseline` in
`../../absence-20260910T052521Z-r2/RESULTADO.md`.

**Item 9 (lost events) is 0**, and it is now backed by the agent's own instrumentation rather than
inferred from a raw 480/500 count.

## A defect this investigation did surface

`agent/heartbeat.py:120` reports `null_path_drops` in every heartbeat. No file under `backend/`
reads or persists it: the `agents` table stores `out_of_scope_drops` and not this one. A path that
the kernel reports but the agent cannot resolve is the one signal that would reveal a genuine
coverage gap, and the server discards it.

## Files

| File | Content |
|---|---|
| `traza_b3.jsonl` | 3462 trace records for the run |
| `bateria3_manifiesto.json` / `.jsonl` | The 500 operations the generator performed |
| `eventos_backend.csv` | The 481 events the backend persisted |
| `bateria3_generador.log` | Generator log |
| `agente_journal.log` | Agent journal bounded to the run window |
