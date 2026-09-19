# Battery 7 — control group, items 45, 47, 49 and 50

The control group is a periodic hashing scanner (`scripts/control_hashing.py`), the stand-in for a
classic cron-driven integrity checker such as AIDE. It ran over the same watched directory and in
the same window as Battery 3, as `docs/plan_medicion_cap5.md:689-690` requires.

## Declarations the chapter requires

| Declaration | Value |
|---|---|
| Attribution criterion | **`primer_cambio`** — each detection is attributed to the first real change of that path in the interval |
| Comparison | **hash only**, no metadata (`incluir_metadatos: false` in `control_estado.json`) |
| Scan interval | 900 s (15 min): baseline at 02:11:15Z, diffs at 02:26:15Z, 02:41:15Z and 02:56:15Z |
| Coverage | 2026-09-18T02:11:15.836633Z .. 2026-09-18T02:56:15.844890Z |
| FIM figures used for the ratio | median 35.594 ms, P99 42.602 ms (items 44 and 46, Battery 3 on the rebuilt image) |

## Results

| # | Item | Value |
|---|---|---|
| 45 | Median control latency | **591 050.981 ms** (9 min 51 s) |
| 47 | P99 control latency | **898 842.935 ms** (14 min 59 s) |
| 49 | Changes the scanner never reported | **422 of 500 — 84.4 %** |
| 50 | Improvement factor, median | **16 605.4×** |
| 50 | Improvement factor, P99 | **21 098.6×** |

Mean 540 324.506 ms, sample standard deviation (ddof=1) 275 684.939 ms, minimum 2 425.099 ms,
maximum 898 899.327 ms, n = 78 attributed detections.

The P99 of 14 min 59 s is one scan interval, as expected: a change made just after a scan waits the
full period. The distribution of a periodic checker is bounded by its interval, which is exactly the
structural difference the chapter argues.

Of the 422 changes the scanner missed, 242 were collapsed — a later change to the same path inside
the same interval hid the earlier one — and 180 were never visible to it at all. By pattern: 265
simple, 69 reverted, 68 collapsed and 20 ephemeral. A file created and deleted between two scans
leaves no trace for a hashing scanner, while the agent reports both operations.

## A contamination that was found and removed

`scripts/control_hashing.py` appends to its CSV, and `--reset` discards the state snapshot but not
the accumulated rows. `bateria7_control.csv` therefore held 184 rows: 106 from the run quarantined
in `../invalido-imagen-desactualizada/` (2026-09-17T22:07Z onwards) and 78 from this one.

Because the generator uses a fixed seed, both runs produce the same paths and the same content
hashes, so a stale row could in principle be attributed to a change of this run. The analysis was
re-run against `bateria7_control_corrida_valida.csv`, filtered to `ts_scan_utc >= 2026-09-18T02:11:15`.

Items 45, 47, 49 and 50 are identical under both inputs — the stale rows never got attributed — but
the filtered input is what these figures come from, and the coverage window now starts at this run's
baseline instead of the quarantined one. The unfiltered CSV is kept alongside it.

## Files

| File | Content |
|---|---|
| `bateria7_control.csv` | Raw scanner output, cumulative, both runs |
| `bateria7_control_corrida_valida.csv` | Rows of this run only — the input behind the figures above |
| `bateria7_latencias.csv` | One row per attributed detection |
| `control.log` | Scanner log: baseline plus three diffs |
| `control_estado.json` | Final snapshot, the equivalent of the AIDE database |
