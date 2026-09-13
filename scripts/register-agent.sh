#!/usr/bin/env bash
# register-agent.sh — server-side agent registration in a single step
# (D56/RN-150, design D-8 of vps-deployment-readiness).
#
# Usage:
#   scripts/register-agent.sh <agent_id>
#
# Runs entirely against the already-running backend container — no admin
# password required (D56: this step needs Docker access on the server,
# already a stronger privilege than the admin console). It generates a
# single-use bootstrap secret, registers the agent with the same
# service-layer logic POST /agents/register uses, and prints the
# FIM_PUBLIC_HOSTS entries, the CA's SHA-256 fingerprint, the secret, and a
# suggested agent/install.sh command with the secret intentionally left out.
#
# Also exports the CA certificate to ./fim-ca.pem in the current directory,
# which agent/install.sh's --ca-cert expects.
set -euo pipefail

AGENT_ID="${1:?Usage: scripts/register-agent.sh <agent_id>}"

COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.tls.yml)

echo "[register-agent] Registering '${AGENT_ID}' against the running backend..."
docker compose "${COMPOSE_FILES[@]}" exec -T backend \
    python -m app.modules.agents.cli register --agent-id "${AGENT_ID}"

echo ""
echo "[register-agent] Exporting the CA certificate to ./fim-ca.pem ..."
docker compose "${COMPOSE_FILES[@]}" cp backend:/certs/ca.pem ./fim-ca.pem

echo "[register-agent] Done. Use ./fim-ca.pem with --ca-cert when running agent/install.sh on the monitored host."
