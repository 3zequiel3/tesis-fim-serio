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
