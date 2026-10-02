#!/usr/bin/env bash
# Battery 5 re-run with the protocol cut (Valkey down), at the product's default ingest limit (D85/RN-179).
# Decides whether the clock_skew rejections are an artefact of cutting the backend
# instead of the broker.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
PAQ=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z
LAB=/home/ezequiel/fim-lab
RES=$LAB/corte_valkey.out
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

say "controlled lab reset"
multipass exec fim-host -- sudo sh /tmp/vm_reset.sh
"${DC[@]}" exec -T db psql -U fim -d fim -tAc \
  "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
sleep 20
recreate_backend || exit 1
say "effective ingest limit (rate_per_s burst): $("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_RATE_PER_S RATE_LIMIT_INGEST_BURST 2>/dev/null | tr '\n' ' ')"
say "launching Battery 5 with the protocol cut (valkey down)"
bash "$LAB/bateria5.sh" "$PAQ/bateria5" corte-valkey
say "finished"
mkdir -p "$PAQ/bateria5/corte-valkey"
for f in bateria5_corte-valkey_manifiesto.json bateria5_corte-valkey_manifiesto.jsonl bateria5_corte-valkey_generador.log; do
  multipass transfer "fim-host:/srv/evidencia/$f" "$PAQ/bateria5/corte-valkey/" 2>/dev/null
done
"${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT reason, count(*) FROM rejected_events_audit GROUP BY 1) TO STDOUT WITH CSV HEADER" > "$PAQ/bateria5/corte-valkey/rechazos.csv" 2>/dev/null
mv "$PAQ/bateria5/bateria5_corte-valkey.log" "$PAQ/bateria5/corte-valkey/" 2>/dev/null
say "=== corte-valkey complete ==="
