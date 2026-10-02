#!/usr/bin/env bash
# Battery 5 re-run with the protocol cut (Valkey down), raised ingest limit.
# Decides whether the clock_skew rejections are an artefact of cutting the backend
# instead of the broker.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
PAQ=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z
LAB=/home/ezequiel/fim-lab
RES=$LAB/corte_valkey.out
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
DCX=(docker compose -f docker-compose.yml -f docker-compose.tls.yml -f "$LAB/docker-compose.exp.yml")
cd "$REPO" || exit 1
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

say "controlled lab reset"
multipass exec fim-host -- sudo sh /tmp/vm_reset.sh
"${DC[@]}" exec -T db psql -U fim -d fim -tAc \
  "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
sleep 20
say "applying experimental limit"
"${DCX[@]}" --profile app up -d backend >/dev/null 2>&1
sleep 25
say "effective limit: $("${DCX[@]}" exec -T backend printenv RATE_LIMIT_INGEST_EVENTS 2>/dev/null | tr -d '\r')"
say "launching Battery 5 with the protocol cut (valkey down)"
DC_OVERRIDE="$LAB/docker-compose.exp.yml" bash "$LAB/bateria5.sh" "$PAQ/bateria5" 100000 corte-valkey
say "finished"
mkdir -p "$PAQ/bateria5/corte-valkey"
for f in bateria5_corte-valkey_manifiesto.json bateria5_corte-valkey_manifiesto.jsonl bateria5_corte-valkey_generador.log; do
  multipass transfer "fim-host:/srv/evidencia/$f" "$PAQ/bateria5/corte-valkey/" 2>/dev/null
done
"${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT reason, count(*) FROM rejected_events_audit GROUP BY 1) TO STDOUT WITH CSV HEADER" > "$PAQ/bateria5/corte-valkey/rechazos.csv" 2>/dev/null
mv "$PAQ/bateria5/bateria5_corte-valkey.log" "$PAQ/bateria5/corte-valkey/" 2>/dev/null
say "restoring nominal limit"
"${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
sleep 15
say "=== corte-valkey complete ==="
