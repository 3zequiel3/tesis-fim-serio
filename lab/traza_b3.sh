#!/usr/bin/env bash
# Traced re-run of Battery 3 to locate the detection gap mechanism.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
OUT=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z/diagnostico-deteccion
LAB=/home/ezequiel/fim-lab
RES=$LAB/traza_b3.out
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
cd "$REPO" || exit 1
mkdir -p "$OUT"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

say "reset with the trace enabled"
multipass exec fim-host -- sudo sh /tmp/vm_reset.sh
"${DC[@]}" exec -T db psql -U fim -d fim -tAc "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
sleep 20
say "running the generator (500 changes over 30 min)"
T0=$(date -u +%s)
multipass exec fim-host -- sudo sh /tmp/vm_gen_b3.sh >> "$OUT/generador_stdout.log" 2>&1
T1=$(date -u +%s)
say "generator finished; settling"
sleep 45
"${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT event_id, path, detected_at, received_at FROM events ORDER BY received_at) TO STDOUT WITH CSV HEADER" > "$OUT/eventos_backend.csv" 2>/dev/null
for f in bateria3_manifiesto.json bateria3_manifiesto.jsonl bateria3_generador.log; do
  multipass transfer "fim-host:/srv/evidencia/$f" "$OUT/" 2>/dev/null
done
multipass exec fim-host -- sudo cp /var/lib/fim-agent/traza_b3.jsonl /srv/evidencia/traza_b3.jsonl
multipass exec fim-host -- sudo chmod 644 /srv/evidencia/traza_b3.jsonl
multipass transfer fim-host:/srv/evidencia/traza_b3.jsonl "$OUT/" 2>/dev/null
multipass exec fim-host -- sudo sh /tmp/vm_journal.sh "$((T0-60))" "$((T1+120))" > "$OUT/agente_journal.log" 2>&1
say "events=$(wc -l < "$OUT/eventos_backend.csv") trace_records=$(wc -l < "$OUT/traza_b3.jsonl" 2>/dev/null || echo 0)"
say "=== traced run complete ==="
