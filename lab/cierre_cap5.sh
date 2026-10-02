#!/usr/bin/env bash
# Unattended Chapter 5 closure: Battery 5 at the product's default ingest limit
# (D85/RN-179; D38/RN-132: the effective limit is declared per run), then sealing.
# The former "experimental" variant (limit raised through a compose override)
# is gone: without the override both variants would measure the same thing, so only the
# "nominal" run is kept.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
PAQ=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z
LAB=/home/ezequiel/fim-lab
RES=$LAB/cierre_cap5.out
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
cd "$REPO" || exit 1
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

# Measurement protocol (D85/RN-179, D-9): every measurement starts with the ingest token
# bucket full. The bucket lives in the backend's memory, so the backend container is
# recreated before each battery and the function returns only once the consumer is running
# again (bounded wait, not a fixed sleep). NEVER call this during a Valkey cut.
recreate_backend() {
  local since id
  since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  "${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
  id=$("${DC[@]}" --profile app ps -q backend 2>/dev/null | tr -d '\r')
  say "backend recreated at $since id=$id"
  for _ in $(seq 1 60); do
    "${DC[@]}" logs --since "$since" backend 2>/dev/null | rg -q 'consumer\.started' && return 0
    sleep 2
  done
  say "ABORTED: the backend did not resume consuming after the recreation"
  return 1
}

reset_lab() {
  say "controlled lab reset"
  multipass exec fim-host -- sudo sh /tmp/vm_reset.sh
  "${DC[@]}" exec -T db psql -U fim -d fim -tAc \
    "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
  sleep 20
  recreate_backend || exit 1
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
say "effective ingest limit (rate_per_s burst): $("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_RATE_PER_S RATE_LIMIT_INGEST_BURST 2>/dev/null | tr '\n' ' ')"
say "launching Battery 5 nominal"
bash "$LAB/bateria5.sh" "$PAQ/bateria5" nominal
say "nominal finished"
collect nominal

say "sealing the evidence package"
cd "$PAQ" && rm -f SHA256SUMS && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
say "files sealed: $(wc -l < SHA256SUMS); verification: $(sha256sum -c SHA256SUMS 2>/dev/null | grep -c ': OK$') OK"
say "=== closure complete ==="
