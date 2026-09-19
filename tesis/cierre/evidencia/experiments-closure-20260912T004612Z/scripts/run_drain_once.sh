#!/usr/bin/env bash
set -uo pipefail
n=${1:?run number}
ROOT=${ROOT:?}; SNAP=${SNAP:?}; EVID=${EVID:?}; PGPORT=${PGPORT:?}; VKPORT=${VKPORT:?}
out="$ROOT/$EVID/drain/run-$n"; mkdir -p "$out"
cp "$ROOT/docs/cierre/evidencia/drenaje-20260910-run4-unit1/run_profile.py" "$out/run_profile.py"
printf 'run=%s\nstarted_at_utc=%s\ncount=3000\ntimeout_s=300\nrate_limit_events=100000\nrate_limit_window_s=60\npostgres=postgres:18.3\nvalkey=valkey/valkey:9.0.3\n' "$n" "$(date -u +%FT%TZ)" > "$out/conditions.txt"
cd "$SNAP"
env PYTHONPATH="$SNAP/backend:$SNAP" DATABASE_URL="postgresql+psycopg://fim:controlled@127.0.0.1:${PGPORT}/fim_drain" VALKEY_URL="valkey://127.0.0.1:${VKPORT}/0" JWT_SECRET_CURRENT=controlled-not-a-production-secret RATE_LIMIT_INGEST_EVENTS=100000 RATE_LIMIT_INGEST_WINDOW_SECONDS=60 FIM_DRAIN_COUNT=3000 FIM_DRAIN_TIMEOUT_S=300 FIM_DRAIN_WORK_DIR="/tmp/fim-exp-drain-$n" "$ROOT/backend/.venv/bin/python" "$out/run_profile.py" > "$out/stdout.log" 2> "$out/stderr.log"
rc=$?
printf '%s\n' "$rc" > "$out/exit-code.txt"; printf 'finished_at_utc=%s\n' "$(date -u +%FT%TZ)" >> "$out/conditions.txt"
python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(sys.argv[2],d.get("completed"),d.get("reconnect_to_queue_empty_seconds"),d.get("persisted_events"),d.get("queue_remaining"))' "$out/summary.json" "run-$n"
exit "$rc"
