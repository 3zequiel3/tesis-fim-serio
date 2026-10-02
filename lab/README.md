# lab/ — evaluation harness

This directory holds the experiment harness exactly as it was used for the
`v3.0-tesis` and `v4.0-tesis` evaluation runs. It was copied verbatim from
`~/fim-lab/` (scripts and compose overrides only; run outputs, generated
certificates and private keys were excluded).

Absolute paths inside the scripts (`/home/ezequiel/...`, `~/fim-lab`) are kept
on purpose so this commit records what actually ran. Later commits adapt the
harness for the `v5.0-tesis` candidate (see `tesis/cierre/` lab guide, items
L-11 to L-14).

## Schema registry (D84/RN-178)

`corrida_unificada.sh` no reapplies migrations with a `psql` loop anymore: it runs
`scripts/migrar.py` (apply pending) and `scripts/migrar.py --verificar` before the
backend starts, and aborts the run if either fails. The column comparison against the
model is kept as a second, independent check.

One-off step before the first run with `v5.0-tesis` on the **persistent** lab database,
which has migrations applied by hand and no registry yet (the harness never runs
`--marcar-hasta`: registering automatically would hide the drift the guard exists to show):

```bash
python3 scripts/migrar.py -f docker-compose.yml -f docker-compose.tls.yml \
  -f lab/docker-compose.mailpit.yml --marcar-hasta 22
```

Mark the highest version actually applied; when in doubt mark a lower one and let a plain
run apply the rest (the migrations are idempotent). Tags older than this change do not
ship `scripts/migrar.py`, so the corrected harness only works with `v5.0-tesis` onwards.

## v5.0-tesis harness changes (L-11 to L-14, A-2, A-3, B-1, B-3, B-5b)

Scripts run from `~/fim-lab`: copy `lib_arnes.sh` and every `vm_*.sh` there after pulling
(the harness transfers the `vm_*.sh` helpers to the guest on each run).

- **L-11 purge.** `vm_reset.sh` stops the agent, recreates `baseline queue discarded journal
  quarantine` (`fim-agent:fim-agent`, 0700), removes `state.json` (and `state.tmp`), resets
  `/srv/fim-watch` (+`critico`), removes the trace file named by `FIM_EXPERIMENT_TRACE_FILE`,
  starts the agent, waits up to 60 s for `agent started` and prints
  `baseline_entries_after_reset=N`; it exits non-zero unless N is 0. `secrets/` and `certs/`
  are never touched. `reset_servidor` (in `lib_arnes.sh`) runs `TRUNCATE events, alerts,
  rejected_events_audit RESTART IDENTITY CASCADE` and `XTRIM events MAXLEN 0`; `audit_log` and
  `published_commands` are kept on purpose. A failed reset aborts the run.
- **L-12.** Battery 3 (latency + control) runs three repetitions with seeds 20261001/2/3. The
  control phase is `random.Random(SEED).randrange(900)` s between the immediate baseline scan and
  `control_hashing.py --loop --interval 900`; seed and `fase_control_s` go to
  `latencia/run-0N/condiciones.txt`. The control CSV is recreated on every run.
- **L-13.** Every battery takes `TAG` (required, no default). `procedencia_exigir` aborts unless
  HEAD is the tag's commit and `git diff --quiet -- agent backend frontend n8n` (working tree and
  index) passes, and writes `env/procedencia.txt` with `tag=` and `commit=`. The tag must therefore
  be **checked out** in the repository before a run.
- **L-14.** Preflight guards (`preflight_*` in `lib_arnes.sh`): schema (`migrar.py --verificar`),
  clock (`chronyc` System time <= 0.005 s on host and guest), SMTP sink (`/api/v1/info`), baseline
  purged, ingest limit equal to the product defaults unless `RATE_LIMIT_VARIANT="<text>"` declares
  a variant, and Valkey `appendonly yes` (prints the safe AOF migration when it is not).
- **A-2/A-3.** The unified run writes `resiliencia/run-0N/metricas.json` (out-of-order count and
  drain decomposition) before sealing; Battery 5 logs `INICIO_CORTE`/`FIN_CORTE` and stores
  `backend_inspect_{pre,post}.txt` and the backend logs since the cut.
- **B-1** `vm_strace_gen.sh` (generator under strace, 100 modifications at 10/s); **B-3**
  `exportar_notif.sh` (`export` and `barrido` over `notify_max_concurrent_deliveries`
  8/16/32/64); **B-5b** `b5b_reconciliacion.sh` (startup reconciliation, 10 repetitions).
