# Measurements — ingest-batched-persistence (D87/RN-181, amplification of 2026-10-03)

> **These are development measurements, not thesis results.** The figure that counts for
> `v5.1-tesis` is the Battery 5 run inside the unified harness (task 8.4, DEFERRED). Nothing here
> declares an improvement of the thesis numbers; it attributes cost and compares steps against one
> yardstick on the same host.

## 1. Baseline, before any ingest change (tasks 1.6 and 1.7)

Script: `lab/bench_ingest_consumer.py` with the new `--notify {stub,real}` and `--paths N`
(task 1.1-1.3) and `commit_ms` in the per-event `consumer.timing` (task 1.4). Ingest code is the one
of `devel` at `32d9e5d`, untouched; the only working-tree difference is the instrumentation
committed as `7c2b270`.

| Field | Value |
|---|---|
| Date | 2026-10-03 |
| Commit | `32d9e5d` + instrumentation (`7c2b270`) |
| Host | AMD Ryzen 5 5500U, 12 threads, 15 GiB, kernel 7.0.0-34; the user's `tesis-fim-serio-*` stack and other containers were running on the same machine during the runs (idle) |
| Services | ephemeral `postgres:18.3` on 55433 (default config, `synchronous_commit=on`), `valkey/valkey:9.0.3` on 56379; plain TCP, no TLS, no AOF; sink = subprocess HTTP server persisting one row per request in `bench_n8n` of the same instance |
| Events per drain | 3,000 (rate limit burst raised to 1,000,000) |
| Runs | one warm-up (200 events), 3 timed drains with `FIM_PROFILE_INGEST` off, one profiled drain |
| Configuration | `batch-ack` (the shipped code) |

Commands (`BENCH_DATABASE_URL=postgresql+psycopg://fim:test@localhost:55433/fim_bench BENCH_VALKEY_URL=valkey://localhost:56379`):

- stub: `backend/.venv/bin/python lab/bench_ingest_consumer.py --notify stub --events 3000 --repeats 3 --configs batch-ack`
- real: `backend/.venv/bin/python lab/bench_ingest_consumer.py --notify real --paths 600 --events 3000 --repeats 3 --configs batch-ack`

| Mode | ev/s per run (to last `event_ack`) | median | `ingest_ms` | `commit_ms` | `commit_ms` / `ingest_ms` | `validation_ms` | ack flush / batch |
|---|---|---|---|---|---|---|---|
| stub (series 1) | 176.7 / 189.0 / 177.9 | **177.9** | 5.909 | 0.794 | 13.4 % | 0.110 | 2.457 ms |
| stub (series 2, repeat) | 165.1 / 169.5 / 177.0 | **169.5** | 5.050 | 0.712 | 14.1 % | 0.100 | 2.315 ms |
| real, `--paths 600` | 61.5 / 62.1 / 62.0 | **62.0** (delivery rate: 61.4 / 62.0 / 61.9, median 61.9) | 15.848 | 1.085 | **6.8 %** | 0.058 | 3.434 ms |

Each drain asserted N distinct rows in `events`, an empty PEL and (real) N delivered alerts and N rows in
the sink. Stage means come from the single profiled drain.

### Contrast with the attribution of `design.md` (task 1.7)

What the measurement confirms:

- `--notify real` reproduces the lab shape: ingest rate collapses from ~170-178 ev/s to 62 ev/s and
  `ingest_ms` goes from 5.1-5.9 ms to 15.8 ms (lab: 12.27 ms mean, 76.6 ev/s). The lab slowdown is
  reproducible in development without n8n.

What the measurement contradicts:

- The stop condition of 1.7 holds: **`commit_ms` is marginal.** In `real` mode it is 1.085 ms, 6.8 % of
  `ingest_ms`, and it grew only ~0.3-0.4 ms against `stub` (0.71-0.79 ms) while `ingest_ms` grew
  ~10 ms. The extra cost sits in the other statements of `_ingest_event_outcome` (pre-ping, dedup,
  pending, rules, INSERT), not in the `COMMIT`.
- Attribution to `COMMIT`/WAL contention does not hold. Diagnostic one-off runs, `real --paths 600`,
  3,000 events x 2 repeats, same host:

  | Diagnostic | ev/s (median) | `ingest_ms` | `commit_ms` |
  |---|---|---|---|
  | none (reference, above) | 62.0 | 15.848 | 1.085 |
  | `synchronous_commit=off` on `fim_bench` and `bench_n8n` (no fsync wait) | 61.9 | 16.204 | 0.809 |
  | `sys.setswitchinterval(1e-4)` (GIL handoff 50x faster) | 59.6 | 16.554 | 0.896 |
  | `httpx.AsyncClient(verify=False)` patched in (no CA bundle load / SSL context per call) | **81.4** | **11.959** | 1.242 |

  Removing the fsync wait changes nothing, so the WAL is not the shared resource. A faster GIL switch
  interval changes nothing. Removing the per-call SSL context creation of `send_n8n`
  (`alerts/notifier.py:45`, a new `httpx.AsyncClient` per delivery) recovers +31 % ev/s and -3.9 ms of
  `ingest_ms`. The residual gap to `stub` (~12 vs ~5.5 ms) is still outside the `COMMIT`.
  Working reading (a hypothesis, not proven): the executor thread of the ingest lane loses time to CPU
  work held on the process by the notification lane (SSL context creation, alert row, SSE, JSON), which
  is per-statement, so it scales with round trips and not with `COMMIT`. A single `COMMIT` per batch
  removes ~1 ms of ~16, and the benefit of fewer round trips under that contention is not established
  by this baseline.

### Conclusion of task 1.7

**STOP before group 2.** The design attributes the lab gap to contention in the `COMMIT` and in the GIL
against the notification lane and to ~7 round trips; the baseline shows the `COMMIT` is 6.8 % of
`ingest_ms` and not the contended resource, and that a large share of the slowdown comes from the
notification lane's per-delivery SSL context. The design must be reopened (decision for the
orchestrator/user): either keep batching with a revised expectation (the 1.5x threshold of D-9 may be
unreachable by `COMMIT` reduction alone), or add the notification-lane CPU cost (`send_n8n` client
reuse, today a Non-Goal) to scope. No ingest code has been changed.


## 2. After phase A: one long-lived httpx client (tasks 4.1 and 4.2)

Same host, services, parameters and commands as section 1 (3,000 events, 3 repeats + 1 profiled,
`batch-ack`); code = `046b716` (shared client in `alerts/notifier.py`). Date 2026-10-03.

| Mode | ev/s per run | median | `ingest_ms` | `commit_ms` | `commit_ms` / `ingest_ms` | delivery rate (median) |
|---|---|---|---|---|---|---|
| stub | 184.4 / 179.3 / 164.3 | **179.3** | 5.902 | 0.822 | 13.9 % | n/a |
| real, `--paths 600` | 86.3 / 86.0 / 84.7 | **86.0** | 11.202 | 1.222 | 10.9 % | 85.9 |

Versus the baseline of section 1 (`real`: 62.0 ev/s, `ingest_ms` 15.848): +38.7 % ev/s (1.39x),
`ingest_ms` -4.65 ms. Stub is unchanged (177.9 / 169.5 before; 179.3 now), as expected: stub does not
reach the notification lane. The `verify=False` diagnostic of section 1 (81.4 ev/s) is bettered by the
real change (86.0) because it also removes the transport construction and the TCP handshake per
delivery, with TLS verification kept on.

### Decision of task 4.2

Threshold: 1.5 x 62.0 = **93 ev/s**. Phase A reaches **86.0 ev/s (1.39x): below the threshold.**
**Phase B (group 5) is needed** and proceeds in order, starting with 5.0 (delta restored). `real`
`ingest_ms` is still 11.2 ms against ~5.9 ms in `stub`: the notification lane still costs ~5 ms per
event on the ingest lane.


## 3. After phase B: one transaction per consumer batch (tasks 5.26 and 5.27)

Same host, services, parameters and commands as sections 1 and 2; code = `330a6de` (phase A + phase B).
Date 2026-10-03. Each drain asserted N distinct rows, an empty PEL and (real) N delivered alerts and
N rows in the sink.

| Mode | ev/s per run (to last `event_ack`) | median | `ingest_ms` per event (its share of the batch transaction) | batch `ingest_db_ms` | batch `commit_ms` | ack flush / batch | delivery rate (median) |
|---|---|---|---|---|---|---|---|
| stub | 780.7 / 770.0 / 778.9 | **778.9** | 0.869 | 53.0 ms (50 candidates) | 0.996 ms | 2.398 ms | n/a |
| real, `--paths 600` | 184.3 / 176.2 / 179.4 | **179.4** | 2.691 | 150.4 ms (50 candidates) | 1.797 ms | 62.3 ms | **109.4** (112.9 / 109.4 / 109.2) |

Progression of `real --paths 600` (3,000 events, median of 3):

| Step | Code | ev/s (last `event_ack`) | vs baseline | delivery ev/s | `ingest_ms` |
|---|---|---|---|---|---|
| Baseline (1.6) | `32d9e5d` | 62.0 | 1.00x | 61.9 | 15.848 |
| Phase A | `046b716` | 86.0 | 1.39x | 85.9 | 11.202 |
| Phase A + B | `330a6de` | **179.4** | **2.89x** | **109.4** | 2.691 |

`stub` went from 179.3 (phase A) to 778.9 ev/s: with one COMMIT and ~1 round trip per event the
ingest lane is no longer the bottleneck of the stub bench. Caveats, so the number is read correctly:

- In `real` mode the ingest lane (179.4 ev/s) now outruns the notification lane: end-to-end the
  alerts are delivered at 109.4 ev/s, and the drain is only complete when the last alert is delivered.
  The ingest rate (to the last `event_ack`) is what the Battery 5 consumption window measures; the
  delivery rate is the real end-to-end limit of the unstubbed chain and is also above the threshold.
- Per-batch `ack_flush_ms` in `real` mode is 62 ms (2.4 ms in `stub`): the flush competes with the
  notification coroutines for the event loop while the lane is saturated. It was 3.0 ms with phase A.
- These are development figures on one host with the user's stack idle alongside; they do not predict the
  laboratory number (the previous step's 191.5 ev/s in development was 76.6 in the lab).

### Decision of task 5.27 (D-9, `Alert` row inside the batch transaction)

Threshold: >= 93 ev/s (1.5 x 62.0). Phase A + B reach **179.4 ev/s to the last `event_ack` (2.89x)** and
**109.4 ev/s to the last delivery (1.77x)**; both are above the threshold. **B-6 (tasks 5.28 and 5.29) is
not applicable** (2026-10-03): the `Alert` row stays in the notification lane, `specs/backend-notifications`
keeps only the phase A requirement, and D76/RN-170 is not amended.

## 4. Closing checks (task 6.3)

- Baseline (1.6): section 1. Phase A (4.1) and the 4.2 decision: section 2. Phase B (5.26) and the 5.27
  decision: section 3. B-6 not applied, so there is no 5.29 measurement.
- The 1.5x threshold (>= 93 ev/s) is met by phase A + B before proposing the `v5.1-tesis` tag.
- Laboratory confirmation (>= 95 ev/s consumption window) remains DEFERRED (task 6.4): nothing here
  claims a laboratory improvement.
