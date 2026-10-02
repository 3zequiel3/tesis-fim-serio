#!/usr/bin/env bash
# Unattended Chapter 5 closure: nominal Battery 5, then the experimental variant
# (D38/RN-132: the effective ingest limit is declared per run), then sealing.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
PAQ=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z
LAB=/home/ezequiel/fim-lab
RES=$LAB/cierre_cap5.out
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
DCX=(docker compose -f docker-compose.yml -f docker-compose.tls.yml -f "$LAB/docker-compose.exp.yml")
cd "$REPO" || exit 1
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

reset_lab() {
  say "controlled lab reset"
  multipass exec fim-host -- sudo sh /tmp/vm_reset.sh
  "${DC[@]}" exec -T db psql -U fim -d fim -tAc \
    "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
  sleep 20
  say "initial state: events=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc 'SELECT count(*) FROM events;' | tr -d ' \r') queue+discarded=$(multipass exec fim-host -- sudo sh /tmp/vm_qcount.sh | tr -d '\r') valkey_6380=$(ss -lntp 2>/dev/null | grep -c '0.0.0.0:6380')"
}

collect() {  # $1 = label
  mkdir -p "$PAQ/bateria5/$1"
  for f in "bateria5_$1_manifiesto.json" "bateria5_$1_manifiesto.jsonl" "bateria5_$1_generador.log"; do
    multipass transfer "fim-host:/srv/evidencia/$f" "$PAQ/bateria5/$1/" 2>/dev/null
  done
  "${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT event_id,path,event_type,status,severity,detected_at,received_at FROM events ORDER BY received_at) TO STDOUT WITH CSV HEADER" > "$PAQ/bateria5/$1/eventos_backend.csv" 2>/dev/null
  "${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT reason, count(*) FROM rejected_events_audit GROUP BY 1) TO STDOUT WITH CSV HEADER" > "$PAQ/bateria5/$1/rechazos.csv" 2>/dev/null
  mv "$PAQ/bateria5/bateria5_$1.log" "$PAQ/bateria5/$1/" 2>/dev/null
  say "artifacts collected for $1: $(ls "$PAQ/bateria5/$1" | tr '\n' ' ')"
}

say "=== Chapter 5 closure chain (corrected harness) ==="

reset_lab
say "nominal effective limit: $("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_EVENTS 2>/dev/null | tr -d '\r')"
say "launching Battery 5 nominal"
bash "$LAB/bateria5.sh" "$PAQ/bateria5" 100 nominal
say "nominal finished"
collect nominal

reset_lab
say "applying experimental limit 100000/60 s to the backend"
"${DCX[@]}" --profile app up -d backend >/dev/null 2>&1
sleep 25
say "experimental effective limit: $("${DCX[@]}" exec -T backend printenv RATE_LIMIT_INGEST_EVENTS 2>/dev/null | tr -d '\r')"
say "launching Battery 5 experimental"
DC_OVERRIDE="$LAB/docker-compose.exp.yml" bash "$LAB/bateria5.sh" "$PAQ/bateria5" 100000 experimental
say "experimental finished"
collect experimental

say "restoring the nominal limit"
"${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
sleep 20
say "effective limit after restore: $("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_EVENTS 2>/dev/null | tr -d '\r')"

say "sealing the evidence package"
cd "$PAQ" && rm -f SHA256SUMS && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
say "files sealed: $(wc -l < SHA256SUMS); verification: $(sha256sum -c SHA256SUMS 2>/dev/null | grep -c ': OK$') OK"
say "=== closure complete ==="
