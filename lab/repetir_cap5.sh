#!/usr/bin/env bash
# Chapter 5 re-run against the REBUILT backend image.
#
# The previous package measured fim-backend:dev built on 2026-09-13, four days
# before the candidate — 19 commits touched backend/ in between, including the
# mutual-TLS Valkey connection. Those runs are quarantined, not deleted.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
PAQ=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z
LAB=/home/ezequiel/fim-lab
RES=$LAB/repetir_cap5.out
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
DCX=(docker compose -f docker-compose.yml -f docker-compose.tls.yml -f "$LAB/docker-compose.exp.yml")
cd "$REPO" || exit 1
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

reset_lab() {
  multipass exec fim-host -- sudo sh /tmp/vm_reset.sh
  "${DC[@]}" exec -T db psql -U fim -d fim -tAc \
    "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
  sleep 20
}

say "=== Chapter 5 re-run on the rebuilt image ==="
say "backend tree in container: $("${DC[@]}" exec -T backend sh -c 'cd /app && find app -name "*.py" -exec sha256sum {} \;' | sort -k2 | sha256sum | cut -c1-16)"
say "backend tree in repo:      $(fd -e py . backend/app -x sha256sum | sd 'backend/app/' 'app/' | sort -k2 | sha256sum | cut -c1-16)"

# ── Batteries 3 + 7: same window, as the plan requires (plan:689-690) ─────────
say "--- Batteries 3 and 7 (30-minute window) ---"
reset_lab
mkdir -p "$PAQ/bateria3" "$PAQ/control"
say "starting the control scanner (baseline + 3 diffs every 900 s)"
nohup multipass exec fim-host -- sudo sh /tmp/vm_control.sh > "$PAQ/control/control.log" 2>&1 &
CONTROL_PID=$!
sleep 30
say "starting the Battery 3 generator (500 changes over 30 min)"
multipass exec fim-host -- sudo sh /tmp/vm_gen_b3.sh >> "$PAQ/bateria3/bateria3_generador_stdout.log" 2>&1
say "generator finished; waiting for the last control scan"
wait $CONTROL_PID 2>/dev/null
say "control finished"

sleep 30
"${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT event_id, detected_at, received_at, EXTRACT(EPOCH FROM (received_at - detected_at)) * 1000 AS latencia_ms FROM events ORDER BY received_at) TO STDOUT WITH CSV HEADER" > "$PAQ/bateria3/eventos_backend.csv" 2>/dev/null
"$LAB/.venv/bin/python" "$LAB/latencia.py" "$PAQ/bateria3/eventos_backend.csv" > "$PAQ/bateria3/latencia_resumen.txt" 2>&1
say "Battery 3 summary: $(tr '\n' ' ' < "$PAQ/bateria3/latencia_resumen.txt")"
for f in bateria3_manifiesto.json bateria3_manifiesto.jsonl bateria3_generador.log; do
  multipass transfer "fim-host:/srv/evidencia/$f" "$PAQ/bateria3/" 2>/dev/null
done
for f in bateria7_control.csv control_estado.json; do
  multipass transfer "fim-host:/srv/evidencia/$f" "$PAQ/control/" 2>/dev/null
done

# ── Battery 5: protocol cut (Valkey down), raised limit declared ──────────────
say "--- Battery 5 (protocol cut) ---"
reset_lab
"${DCX[@]}" --profile app up -d backend >/dev/null 2>&1
sleep 25
say "effective ingest limit: $("${DCX[@]}" exec -T backend printenv RATE_LIMIT_INGEST_EVENTS 2>/dev/null | tr -d '\r')"
DC_OVERRIDE="$LAB/docker-compose.exp.yml" bash "$LAB/bateria5.sh" "$PAQ/bateria5" 100000 corte-valkey
mkdir -p "$PAQ/bateria5/corte-valkey"
for f in bateria5_corte-valkey_manifiesto.json bateria5_corte-valkey_manifiesto.jsonl bateria5_corte-valkey_generador.log; do
  multipass transfer "fim-host:/srv/evidencia/$f" "$PAQ/bateria5/corte-valkey/" 2>/dev/null
done
"${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT event_id,path,event_type,status,severity,detected_at,received_at FROM events ORDER BY received_at) TO STDOUT WITH CSV HEADER" > "$PAQ/bateria5/corte-valkey/eventos_backend.csv" 2>/dev/null
"${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT reason, count(*) FROM rejected_events_audit GROUP BY 1) TO STDOUT WITH CSV HEADER" > "$PAQ/bateria5/corte-valkey/rechazos.csv" 2>/dev/null
mv "$PAQ/bateria5/bateria5_corte-valkey.log" "$PAQ/bateria5/corte-valkey/" 2>/dev/null
# Drain measured from the database, not from the polling loop: the loop's
# stability window added ~20 s of its own hysteresis to the previous figure.
say "ingest window from the DB: $("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT round(EXTRACT(EPOCH FROM (max(received_at)-min(received_at)))::numeric,3) || ' s / ' || count(*) || ' events' FROM events;" | tr -d '\r')"

say "restoring the nominal limit"
"${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
sleep 20
say "limit after restore: $("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_EVENTS 2>/dev/null | tr -d '\r')"

say "sealing the package"
cd "$PAQ" && rm -f SHA256SUMS && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
say "files sealed: $(wc -l < SHA256SUMS); verification: $(sha256sum -c SHA256SUMS 2>/dev/null | grep -c ': OK$') OK"
say "=== re-run complete ==="
