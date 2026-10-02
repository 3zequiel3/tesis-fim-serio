#!/usr/bin/env bash
# Purge the ingest stream. Wiping the database and the agent queue is not enough:
# events published straight into the stream by another battery survive both, and
# a later run consumes them as if they were its own. Run 01 of the resilience
# battery ended with 3400 events in the database against 2692 in the agent queue,
# and the 708 extra came from exactly that.
set -uo pipefail
cd /home/ezequiel/Facultad/tesis/tesis-fim-serio || exit 1
docker compose -f docker-compose.yml -f docker-compose.tls.yml exec -T valkey sh -c \
  'valkey-cli --tls --cert /certs/valkey.pem --key /certs/valkey-key.pem --cacert /certs/ca.pem -p 6380 XTRIM events MAXLEN 0' 2>/dev/null
echo "stream events purgado; largo ahora: $(docker compose -f docker-compose.yml -f docker-compose.tls.yml exec -T valkey sh -c 'valkey-cli --tls --cert /certs/valkey.pem --key /certs/valkey-key.pem --cacert /certs/ca.pem -p 6380 XLEN events' 2>/dev/null | tr -d '\r')"
