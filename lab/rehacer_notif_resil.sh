#!/usr/bin/env bash
# Re-run of the notification and resilience batteries after two harness defects.
#
# 1. The reset wiped the database and the agent queue but not the ingest stream.
#    Events published straight into the stream by the notification battery
#    survived both and were consumed by the resilience runs as if they were
#    theirs: run 01 ended with 3400 events in the database against 2692 in the
#    agent queue. Every reset now purges the stream.
#
# 2. The notification battery dumped a thousand events at once and the chain
#    saturated: 213 delivered of 1000 sequential, none in either concurrent
#    scenario. A single notification costs 302.8 ms on average and 349.4 ms at
#    worst, so the chain is not slow, it is being flooded. The sample is reduced
#    to 300 per scenario and the figure is declared.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
LAB=/home/ezequiel/fim-lab
OUT=$REPO/tesis/cierre/evidencia/v2-eval-20260922T175053Z
RES=$LAB/rehacer.out
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml -f "$LAB/docker-compose.mailpit.yml")
DCX=("${DC[@]}" -f "$LAB/docker-compose.exp.yml")
N=300
cd "$REPO" || exit 1
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }
purgar() { bash "$LAB/purgar_stream.sh" >/dev/null 2>&1; }
mp_count() { curl -s http://127.0.0.1:8025/api/v1/messages 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["messages_count"])' 2>/dev/null || echo 0; }

reset_lab() {
  multipass exec fim-host -- sudo sh /tmp/vm_reset.sh
  "${DC[@]}" exec -T db psql -U fim -d fim -tAc "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
  purgar
  sleep 18
}

say "=== rehaciendo notificacion y resiliencia ==="
say "costo de una notificacion aislada, medido antes: media 302,8 ms / max 349,4 ms (n=10)"
rm -rf "$OUT/notificacion" "$OUT/resiliencia"
mkdir -p "$OUT/notificacion" "$OUT/resiliencia"

# ── notificacion ──────────────────────────────────────────────────────────────
"${DCX[@]}" --profile app up -d backend >/dev/null 2>&1
sleep 25
"${DC[@]}" cp "$LAB/bateria4_publicador.py" backend:/tmp/b4.py >/dev/null 2>&1
{
  echo "muestra_por_escenario=$N  # reducida desde 1000: la cadena satura y el pedido admite declarar el valor usado"
  echo "rate_limit_ingest_events=$("${DCX[@]}" exec -T backend printenv RATE_LIMIT_INGEST_EVENTS | tr -d '\r')"
  echo "canal=mailpit (SMTP real, local)"
  echo "intervalo=events.received_at -> alerts.delivered_at"
  echo "costo_notificacion_aislada_ms=302.8 media / 349.4 max (n=10)"
} > "$OUT/notificacion/procedencia.txt"

notif() {  # $1 etiqueta  $2 concurrencia
  say "escenario $1: $N eventos, concurrencia $2"
  "${DC[@]}" exec -T db psql -U fim -d fim -tAc "DELETE FROM alerts; DELETE FROM events;" >/dev/null 2>&1
  purgar
  curl -s -X DELETE http://127.0.0.1:8025/api/v1/messages >/dev/null 2>&1
  sleep 3
  "${DCX[@]}" exec -T backend sh -c "cd /app && PYTHONPATH=/app python /tmp/b4.py $1 $N $2" >> "$RES" 2>&1
  prev=-1; est=0
  for _ in $(seq 1 120); do
    n=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM alerts WHERE delivered_at IS NOT NULL;" | tr -d ' \r')
    [ "$n" = "$prev" ] && est=$((est+1)) || est=0; prev=$n
    [ "$est" -ge 5 ] && break; sleep 5
  done
  "${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT a.id, EXTRACT(EPOCH FROM (a.delivered_at - e.received_at))*1000 AS notif_ms FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.delivered_at IS NOT NULL) TO STDOUT WITH CSV HEADER" > "$OUT/notificacion/$1.csv" 2>/dev/null
  say "escenario $1: $(( $(wc -l < "$OUT/notificacion/$1.csv") - 1 )) de $N entregadas; correos en mailpit: $(mp_count)"
}
notif secuencial 1
notif conc50 50
notif conc100 100

"$LAB/.venv/bin/python" - "$OUT/notificacion" <<'PY' > "$OUT/notificacion/resumen.txt" 2>&1
import sys, pathlib, pandas as pd
d = pathlib.Path(sys.argv[1])
for e in ("secuencial", "conc50", "conc100"):
    f = d / f"{e}.csv"
    if not f.exists() or f.stat().st_size < 20:
        print(f"{e:11s} sin muestras"); continue
    s = pd.read_csv(f)["notif_ms"]
    print(f"{e:11s} n={len(s):4d} media={s.mean():9.3f} p50={s.quantile(.50):9.3f} "
          f"p95={s.quantile(.95):9.3f} p99={s.quantile(.99):9.3f} max={s.max():9.3f}")
PY
cat "$OUT/notificacion/resumen.txt" | tee -a "$RES"

# ── resiliencia ───────────────────────────────────────────────────────────────
say "--- resiliencia, 3 repeticiones sobre stream purgado ---"
for i in 1 2 3; do
  R=$(printf "run-%02d" "$i"); mkdir -p "$OUT/resiliencia/$R"
  say "repeticion $R"
  reset_lab
  "${DCX[@]}" --profile app up -d backend >/dev/null 2>&1
  sleep 20
  say "$R: stream en $(docker compose -f docker-compose.yml -f docker-compose.tls.yml exec -T valkey sh -c 'valkey-cli --tls --cert /certs/valkey.pem --key /certs/valkey-key.pem --cacert /certs/ca.pem -p 6380 XLEN events' 2>/dev/null | tr -d '\r') antes de empezar"
  DC_OVERRIDE="$LAB/docker-compose.exp.yml" bash "$LAB/bateria5.sh" "$OUT/resiliencia/$R" 100000 "$R"
  "${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT event_id, path, detected_at, received_at FROM events ORDER BY received_at) TO STDOUT WITH CSV HEADER" > "$OUT/resiliencia/$R/eventos.csv" 2>/dev/null
  "${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT json_build_object('eventos', count(*), 'unicos', count(DISTINCT event_id), 'ventana_s', round(EXTRACT(EPOCH FROM (max(received_at)-min(received_at)))::numeric,3)) FROM events;" > "$OUT/resiliencia/$R/counts.json" 2>/dev/null
  multipass exec fim-host -- sudo cp /var/lib/fim-agent/traza_b3.jsonl "/srv/evidencia/traza_$R.jsonl" 2>/dev/null
  multipass exec fim-host -- sudo chmod 644 "/srv/evidencia/traza_$R.jsonl" 2>/dev/null
  multipass transfer "fim-host:/srv/evidencia/traza_$R.jsonl" "$OUT/resiliencia/$R/" 2>/dev/null
  say "$R: $(cat "$OUT/resiliencia/$R/counts.json" 2>/dev/null)"
done

say "restaurando el limite nominal"
"${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
sleep 20
say "resellando el paquete"
cd "$OUT" && rm -f SHA256SUMS && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
say "sellado: $(wc -l < SHA256SUMS) archivos | $(sha256sum -c SHA256SUMS 2>/dev/null | grep -c ': OK$') OK"
say "=== rehecho completo ==="
