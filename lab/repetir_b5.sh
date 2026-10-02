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

echo "[$(ts)] lanzando Batería 5 (nominal, 100/60 s)"
bash /home/ezequiel/fim-lab/bateria5.sh "$D" 100 nominal
echo "[$(ts)] fin"
