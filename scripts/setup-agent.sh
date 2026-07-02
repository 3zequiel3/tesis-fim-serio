#!/usr/bin/env bash
# Registra el agente de test 'docker-agent' contra el backend para que pueda
# hacer bootstrap mTLS. Corré esto DESPUÉS de entrar al frontend con admin/admin
# y cambiar la contraseña.
#
# Uso:
#   scripts/setup-agent.sh <password_actual_del_admin>
#
# El bootstrap_secret debe coincidir con FIM_BOOTSTRAP_SECRET del servicio
# `agent` en docker-compose.yml (default: docker-bootstrap-secret).
set -euo pipefail

API="${API:-http://localhost:8000}"
ADMIN_USER="${ADMIN_USER:-admin}"
PASS="${1:?Uso: scripts/setup-agent.sh <password_actual_del_admin>}"
AGENT_ID="${AGENT_ID:-docker-agent}"
SECRET="${FIM_BOOTSTRAP_SECRET:-docker-bootstrap-secret}"

echo "1) Login como '$ADMIN_USER' en $API ..."
TOKEN=$(curl -fsS -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$PASS\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

echo "2) Registrando agente '$AGENT_ID' ..."
curl -fsS -X POST "$API/agents/register" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"$AGENT_ID\",\"bootstrap_secret\":\"$SECRET\"}"
echo ""

echo "3) Reiniciando el contenedor del agente para que haga bootstrap ..."
docker compose --profile app restart agent 2>/dev/null || \
  echo "   (reiniciá manualmente: docker compose --profile app restart agent)"

echo ""
echo "Listo. Agente '$AGENT_ID' registrado y reiniciado."
echo "Seguí los logs con:  docker compose --profile app logs -f agent"
