#!/usr/bin/env bash
# Battery 4 — notification time (items 11-22). Interval per plan_medicion_cap5.md:
# backend receives the event -> successful webhook emission, read from the
# database as alerts.delivered_at - events.received_at. Happy path, first
# attempt: the retry ladder would make the 5 s threshold unfalsifiable.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
OUT=$REPO/tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/bateria4
LAB=/home/ezequiel/fim-lab
RES=$LAB/bateria4.out
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
cd "$REPO" || exit 1
mkdir -p "$OUT"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

say "=== Battery 4 on candidate v1.0-tesis ==="
{
  echo "candidate_commit=$(git rev-parse 7a906c2)"
  echo "candidate_tag=v1.0-tesis"
  echo "backend_tree_sha256=$(docker compose -f docker-compose.yml -f docker-compose.tls.yml exec -T backend sh -c 'cd /app && find app -name "*.py" -exec sha256sum {} \;' | sort -k2 | sha256sum | cut -d' ' -f1)"
  echo "rate_limit_ingest_rate_per_s=$("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_RATE_PER_S | tr -d '\r')  # product default, D85/RN-179"
  echo "rate_limit_ingest_burst=$("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_BURST | tr -d '\r')  # product default, D85/RN-179"
  echo "n8n_channel=email (slack y ticketing deshabilitados a proposito)"
  echo "smtp=smtp.gmail.com:587 STARTTLS, canal real"
  echo "interval=events.received_at -> alerts.delivered_at"
} > "$OUT/procedencia.txt"
cat "$OUT/procedencia.txt" | tee -a "$RES"

corrida() {  # $1 etiqueta  $2 total  $3 concurrencia
  say "--- escenario $1: $2 eventos, concurrencia $3 ---"
  "${DC[@]}" exec -T db psql -U fim -d fim -tAc "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
  sleep 3
  "${DC[@]}" exec -T backend sh -c "cd /app && PYTHONPATH=/app python /tmp/b4.py $1 $2 $3" >> "$RES" 2>&1
  # Wait for the notification chain to settle: stable delivered count.
  prev=-1; estable=0
  for _ in $(seq 1 120); do
    n=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM alerts WHERE delivered_at IS NOT NULL;" | tr -d ' \r')
    [ "$n" = "$prev" ] && estable=$((estable+1)) || estable=0
    prev=$n
    [ "$estable" -ge 4 ] && break
    sleep 5
  done
  "${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT a.id, EXTRACT(EPOCH FROM (a.delivered_at - e.received_at))*1000 AS notif_ms FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.delivered_at IS NOT NULL) TO STDOUT WITH CSV HEADER" > "$OUT/bateria4_$1.csv" 2>/dev/null
  say "escenario $1: $(( $(wc -l < "$OUT/bateria4_$1.csv") - 1 )) muestras"
}

corrida secuencial 1000 1
corrida conc50 1000 50
corrida conc100 1000 100

say "--- agregacion con pandas ---"
"$LAB/.venv/bin/python" - "$OUT" <<'PY' | tee -a "$RES" | tee "$OUT/resumen.txt"
import sys, pathlib, pandas as pd
out = pathlib.Path(sys.argv[1])
for etiqueta in ("secuencial", "conc50", "conc100"):
    f = out / f"bateria4_{etiqueta}.csv"
    if not f.exists():
        print(f"{etiqueta}: ausente"); continue
    d = pd.read_csv(f)["notif_ms"]
    print(f"{etiqueta:11s} n={len(d):5d} media={d.mean():9.3f} p50={d.quantile(.50):9.3f} "
          f"p95={d.quantile(.95):9.3f} p99={d.quantile(.99):9.3f} max={d.max():9.3f}")
PY
say "=== battery 4 done ==="
