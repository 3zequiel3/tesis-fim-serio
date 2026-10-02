#!/usr/bin/env bash
# Battery 5 after D75/RN-169 (Change 58 applied, not committed).
# Protocol cut: Valkey down. Raised ingest limit, declared per D38/RN-132.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
PAQ=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z
OUT=$PAQ/bateria5/corte-valkey-post-d75
LAB=/home/ezequiel/fim-lab
RES=$LAB/b5_post_d75.out
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
DCX=(docker compose -f docker-compose.yml -f docker-compose.tls.yml -f "$LAB/docker-compose.exp.yml")
cd "$REPO" || exit 1
mkdir -p "$OUT"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

say "=== Battery 5 after D75/RN-169 ==="
{
  echo "candidate_commit=$(git rev-parse HEAD)"
  echo "candidate_tag=v1.0-tesis"
  echo "git_status_clean=no"
  echo "uncommitted_change=ingest-offload-blocking-db (Change 58, D75/RN-169)"
  echo "backend_tree_sha256=$(fd -e py . backend/app -x sha256sum | sd 'backend/app/' 'app/' | sort -k2 | sha256sum | cut -d' ' -f1)"
  echo "modified_files:"
  git status --porcelain | sed 's/^/  /'
} > "$OUT/procedencia.txt"
say "provenance recorded"

multipass exec fim-host -- sudo sh /tmp/vm_reset.sh
"${DC[@]}" exec -T db psql -U fim -d fim -tAc "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
sleep 20
"${DCX[@]}" --profile app up -d backend >/dev/null 2>&1
sleep 25
say "effective ingest limit: $("${DCX[@]}" exec -T backend printenv RATE_LIMIT_INGEST_EVENTS 2>/dev/null | tr -d '\r')"
say "pool/executor: $("${DCX[@]}" exec -T backend sh -c 'cd /app && PYTHONPATH=/app python -c "
from app.core.config import s" 2>/dev/null || true')"

DC_OVERRIDE="$LAB/docker-compose.exp.yml" bash "$LAB/bateria5.sh" "$PAQ/bateria5" 100000 corte-valkey-post-d75
mv "$PAQ/bateria5/bateria5_corte-valkey-post-d75.log" "$OUT/" 2>/dev/null
for f in bateria5_corte-valkey-post-d75_manifiesto.json bateria5_corte-valkey-post-d75_manifiesto.jsonl bateria5_corte-valkey-post-d75_generador.log; do
  multipass transfer "fim-host:/srv/evidencia/$f" "$OUT/" 2>/dev/null
done
"${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT event_id,path,detected_at,received_at FROM events ORDER BY received_at) TO STDOUT WITH CSV HEADER" > "$OUT/eventos_backend.csv" 2>/dev/null
"${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT reason, count(*) FROM rejected_events_audit GROUP BY 1) TO STDOUT WITH CSV HEADER" > "$OUT/rechazos.csv" 2>/dev/null

# Item 43 is measured from the database, not from the harness polling loop.
say "--- item 43, measured from received_at ---"
"${DC[@]}" exec -T db psql -U fim -d fim -c \
  "SELECT count(*) AS eventos, count(DISTINCT event_id) AS unicos, min(received_at) AS primero, max(received_at) AS ultimo, round(EXTRACT(EPOCH FROM (max(received_at)-min(received_at)))::numeric,3) AS ventana_s, round((count(*) / EXTRACT(EPOCH FROM (max(received_at)-min(received_at))))::numeric,2) AS ev_s FROM events;" \
  2>&1 | tee -a "$RES" | tee "$OUT/item43.txt"

say "restoring the nominal limit"
"${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
sleep 20
say "=== done ==="
