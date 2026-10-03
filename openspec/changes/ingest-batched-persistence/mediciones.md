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
