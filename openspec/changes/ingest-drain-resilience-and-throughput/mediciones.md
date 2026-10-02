# Measurements — ingest-drain-resilience-and-throughput (D87/RN-181)

> **These are development measurements, not thesis results** (amendment of RN-181). The figure
> that counts for `v5.0-tesis` is the single re-run of the unified harness
> (`lab/corrida_unificada.sh`, Change 61). Nothing here declares an improvement of the thesis
> numbers; it only attributes cost per stage and compares the D87 steps against one yardstick.

## What was and was not measured

| Item | Status |
|---|---|
| In-process micro-benchmark of the consumer drain, ephemeral PostgreSQL + Valkey on localhost | **Measured** (section 1) |
| `lab/bateria4_publicador.py` / `lab/corrida_unificada.sh` on the VM + full stack | **NOT measured — DEFERRED to B-0.** They need the real VM, the `fim-vm` agent, the TLS certificates of the running stack and `docker compose exec backend`; running them would touch the user's `tesis-fim-serio-*` stack. Also, `bateria4_publicador.py` measures notification latency (`alerts.delivered_at - events.received_at`), not ingest ev/s: for the throughput floor a drain-rate run is needed (pre-filled stream, time to N `event_ack`). |
| AOF over an existing RDB snapshot on Valkey 9.0.3 (isolated throwaway compose project `idrt-aof`) | **Measured** (section 2) — **result is negative without a migration step** |
| `docker inspect` of the backend during the Valkey cut (run-03 restart hypothesis) | **NOT measured — DEFERRED to B-0** (needs the lab stack and the cut script). |

## 1. In-process micro-benchmark of the consumer drain (development measurement)

Script: `lab/bench_ingest_consumer.py` (added by this change). Runs the real `run_consumer`
of the backend in-process against ephemeral containers; the stream is pre-filled with N signed
events of one agent and the clock runs until the N `event_ack` replies are in `commands`.
The notification chain is replaced by a no-op (it needs n8n and is not part of the drain lane).
Each configuration emulates the code *before* each D87 step on the same build:

- `baseline`: auth cache disabled (TTL 0) + immediate `event_ack`/`XACK` per event.
- `auth-cache`: cache on + immediate ack per event.
- `batch-ack`: cache on + batched ack (the shipped code).

Per configuration: one warm-up drain (200 events, discarded), 3 timed drains with
`FIM_PROFILE_INGEST` off (ev/s), and one more drain with it on (stage breakdown).
Each drain asserts N distinct rows in `events` and an empty PEL.

| Field | Value |
|---|---|
| Date | 2026-10-02 |
| Commit | `c67dbdf` (working tree clean except the untracked benchmark script) |
| Host | AMD Ryzen 5 5500U, 12 threads, 15 GiB; Docker; same machine runs the benchmark and both services |
| Services | `postgres:18.3` on 55433, `valkey/valkey:9.0.3` on 56379, plain TCP, no TLS, no AOF |
| Command | `BENCH_DATABASE_URL=postgresql+psycopg://fim:test@localhost:55433/fim_bench BENCH_VALKEY_URL=valkey://localhost:56379 backend/.venv/bin/python lab/bench_ingest_consumer.py --events 3000 --repeats 3` |
| Events per drain | 3,000 (rate limit burst raised to 1,000,000 so the limiter is not measured) |

| Configuration | ev/s per run | ev/s median | auth ms/event | validation ms | ingest ms | total ms (to ingest outcome) | ack flush |
|---|---|---|---|---|---|---|---|
| baseline | 102.4 / 96.3 / 100.9 | **100.9** | 2.586 (hit ratio 0.000) | 0.149 | 6.201 | 8.936 | n/a (ack is per event, outside `total`) |
| auth-cache (3.7) | 147.8 / 155.7 / 169.0 | **155.7** | 0.006 (hit ratio 0.999) | 0.123 | 5.499 | 5.628 | n/a |
| batch-ack (4.9) | 191.5 / 194.1 / 171.1 | **191.5** | 0.007 (hit ratio 0.999) | 0.114 | 5.723 | 5.844 | 2.443 ms per batch (0.050 ms per event) |

Stage means come from the profiled drain (one run), so they carry run-to-run noise; they are
for attribution, not for comparison at the 0.1 ms level. Observations:

- The event lane is dominated by the transactional ingest (`SELECT` dedup + `INSERT` + `commit`,
  ~5.5-6.2 ms here), then by the authentication lookup (~2.6 ms) and the per-event ack pipeline
  (a round trip per event that does not appear in the per-event `total`).
- The auth cache removes ~2.6 ms/event; batching the ack removes one Valkey round trip per event
  and replaces it with ~2.4 ms per 50-event batch.
- The baseline on this host is already above the 95 ev/s floor (100.9), unlike the ~76 ev/s seen
  in the lab. The lab run adds the VM, TLS, the real agent and a different DB placement, so the
  absolute figures here are **not** transferable; only the relative ordering is evidence.

## 2. AOF over an existing RDB snapshot — Valkey 9.0.3 (task 6.4)

Isolated throwaway project (`docker compose -p idrt-aof`, no host ports, own network and volume
`idrt-aof_valkey_data`; the user's `tesis-fim-serio-*` stack was never touched; project and volume
removed afterwards). Data: stream `events` with 3 entries, group `fim-backend` with 2 pending.

**Result 1 — direct switch loses the data (negative).** A volume with a `dump.rdb` produced by a
server without AOF, then `docker compose up -d valkey` with the new `command` (`--appendonly yes
--appendfsync everysec`):

```
before:  XLEN events = 3, group fim-backend pending 2   (dump.rdb saved with SAVE)
after:   XLEN events = 0, XINFO GROUPS -> NOGROUP        (log: "Creating AOF base file appendonly.aof.1.base.rdb on server start")
```

With `appendonly yes` the server does not load `dump.rdb`; it creates an empty AOF base and the
snapshot data is gone. The design's Migration Plan step 2 ("`docker compose up -d valkey` recreates
the container with AOF; the volume is kept") is therefore **not sufficient** for a volume that has
data. Per task 6.4 this is documented here and in the `design.md` Migration Plan.

**Result 2 — migration procedure verified (positive).** Start the old (RDB-only) server so it
loads the snapshot, switch AOF on at runtime so Valkey rewrites the dataset into an AOF, wait for
the rewrite, and only then recreate the container with the new `command`:

```
docker exec <valkey> valkey-cli XLEN events                  # 3, loaded from dump.rdb
docker exec <valkey> valkey-cli CONFIG SET appendonly yes    # triggers an AOF rewrite from memory
docker exec <valkey> valkey-cli INFO persistence             # wait: aof_rewrite_in_progress:0, aof_last_bgrewrite_status:ok
docker compose up -d valkey                                  # recreate with --appendonly yes --appendfsync everysec
```

After the recreation: `XLEN events` = 3, `XINFO GROUPS events` lists `fim-backend` (pending 2,
last-delivered-id unchanged), `CONFIG GET appendonly` = `yes`, `appendfsync` = `everysec`.

**Result 3 — restart and recreation with AOF already on (task 6.5, positive).** After one more
`XADD` (4 entries): `docker compose restart valkey` and then `docker compose up -d
--force-recreate valkey` both keep `XLEN events` = 4, the group `fim-backend` and its 2 pending
entries (`XPENDING`), with `appendonly yes` / `appendfsync everysec`.

A fresh volume (no previous snapshot) needs no migration: the first start with AOF is the normal
case. The TLS override was verified only with `docker compose config` (both flags present next to
`--port 0` / `--tls-port 6380`); bringing it up needs `certs-init` and was not done.

## 3. Decision of task 7.1 (batched `INSERT`)

**Provisional, based only on the development micro-benchmark:** with the auth cache and the batched
ack the in-process drain reaches 191.5 ev/s (median of 3, 2026-10-02, `c67dbdf`), above the 95 ev/s
floor and above the 150 ev/s target on this host. The conditional batched `INSERT` is therefore
**not implemented** (7.2 and 7.3 stay unimplemented).

This is **not** the measurement that RN-181 asks for: the floor is defined on the unified harness over
`v5.0-tesis`. The decision must be confirmed with the lab number at B-0. If the lab figure is below
95 ev/s after groups 3-4, 7.2 (addendum before code) and 7.3 become applicable.

## 4. To be measured at B-0 (DEFERRED)

1. Drain throughput on the real stack (VM + TLS + agent `fim-vm`) with `FIM_PROFILE_INGEST=1`:
   baseline (pre-change build), after the auth cache, after the batched ack. Record ev/s and the
   `consumer.timing` stage breakdown, in this file's table format. A drain-rate driver is needed
   (pre-filled stream, time to N `event_ack`); `lab/bateria4_publicador.py` only injects events.
2. The same, if below 95 ev/s, after the batched `INSERT` (task 7.3).
3. `lab/corrida_unificada.sh` over `v5.0-tesis`, recorded as measured, with `docker inspect` of the
   backend during the Valkey cut (confirms or discards the run-03 restart hypothesis); cross-reference
   Change 61 (task 8.4).
4. Apply the AOF migration of section 2 on the real Valkey volume before tagging `v5.0-tesis`.
