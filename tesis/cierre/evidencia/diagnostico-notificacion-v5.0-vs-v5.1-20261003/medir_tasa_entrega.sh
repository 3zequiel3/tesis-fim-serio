#!/usr/bin/env bash
# usage: _notif_rate.sh <label> ; measures absolute notification delivery rate for 1000 events, conc 50
set -uo pipefail
cd /home/ezequiel/Facultad/tesis/tesis-fim-serio
F=(-f docker-compose.yml -f docker-compose.tls.yml -f /home/ezequiel/fim-lab/docker-compose.mailpit.yml)
DC=(docker compose "${F[@]}")
"${DC[@]}" exec -T db psql -U fim -d fim -tAc "TRUNCATE events, alerts, rejected_events_audit RESTART IDENTITY CASCADE;" >/dev/null
"${DC[@]}" --profile app up -d --force-recreate --no-deps backend >/dev/null 2>&1
until docker logs tesis-fim-serio-backend-1 2>&1 | grep -q consumer.started; do sleep 2; done
"${DC[@]}" cp /home/ezequiel/fim-lab/bateria4_publicador.py backend:/tmp/b4.py >/dev/null 2>&1
"${DC[@]}" exec -T backend sh -c "cd /app && PYTHONPATH=/app python /tmp/b4.py rate 1000 50" 2>&1 | tail -1
sleep 30; for i in $(seq 1 120); do n=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM alerts a JOIN events e ON e.id=a.event_id WHERE a.delivered_at IS NOT NULL AND e.path LIKE '%/b4_%'" | tr -d ' \r'); [ "$n" -ge 1000 ] && break; sleep 2; done
"${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT '$1', count(*), round(extract(epoch from max(e.received_at)-min(e.received_at))::numeric,2) AS ingest_span_s, round(extract(epoch from max(a.delivered_at)-min(e.received_at))::numeric,2) AS end_to_end_s, round(count(*)/extract(epoch from max(a.delivered_at)-min(e.received_at))::numeric,1) AS deliv_per_s, round(count(*)/extract(epoch from max(a.delivered_at)-min(a.delivered_at))::numeric,1) AS deliv_rate_window FROM alerts a JOIN events e ON e.id=a.event_id WHERE a.delivered_at IS NOT NULL AND e.path LIKE '%/b4_%'"
