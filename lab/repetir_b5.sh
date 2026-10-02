#!/usr/bin/env bash
# Espera a que drene la cola del intento inválido, deja el laboratorio en cero
# y repite la Batería 5 con el arnés corregido.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
D=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z/bateria5
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
cd "$REPO" || exit 1

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
echo "[$(ts)] esperando drenaje del intento inválido..."
for i in $(seq 1 120); do
  q=$(multipass exec fim-host -- sudo bash -c 'ls /var/lib/fim-agent/queue 2>/dev/null | wc -l' | tr -d ' \r')
  e=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM events;" 2>/dev/null | tr -d ' \r')
  [ "${q:-1}" = "0" ] && { echo "[$(ts)] cola vacía; eventos=$e"; break; }
  [ "$((i % 10))" = "0" ] && echo "[$(ts)] cola=$q eventos=$e"
  sleep 30
done

echo "[$(ts)] reinicio controlado del laboratorio"
multipass exec fim-host -- sudo systemctl stop fim-agent
multipass exec fim-host -- sudo find /srv/fim-watch -mindepth 1 -delete
multipass exec fim-host -- sudo mkdir -p /srv/fim-watch/critico
multipass exec fim-host -- sudo find /var/lib/fim-agent/queue -mindepth 1 -delete 2>/dev/null
"${DC[@]}" exec -T db psql -U fim -d fim -tAc "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
multipass exec fim-host -- sudo systemctl start fim-agent
sleep 20
echo "[$(ts)] estado inicial: eventos=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc 'SELECT count(*) FROM events;' | tr -d ' ') valkey6380=$(ss -lntp 2>/dev/null | grep -c '0.0.0.0:6380')"

# Measurement protocol (D85/RN-179, D-9): start with the ingest token bucket full by
# recreating the backend BEFORE the battery (never during the Valkey cut), and wait
# (bounded) until its consumer is running again.
SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
"${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
echo "[$(ts)] backend recreado id=$("${DC[@]}" --profile app ps -q backend | tr -d '\r')"
for _ in $(seq 1 60); do
  "${DC[@]}" logs --since "$SINCE" backend 2>/dev/null | rg -q 'consumer\.started' && break
  sleep 2
done

echo "[$(ts)] lanzando Batería 5 (límite por defecto del producto, D85/RN-179)"
bash /home/ezequiel/fim-lab/bateria5.sh "$D" nominal
echo "[$(ts)] fin"
