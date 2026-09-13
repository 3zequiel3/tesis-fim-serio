#!/usr/bin/env bash
# Ensayo A-3, paso 4.2: registers the PC agent in the backend (POST /agents/register).
#
# Runs on the laptop against the local API (http://127.0.0.1:8000), so the admin password never
# crosses the LAN. The admin password is read without echo; the single-use bootstrap secret is
# typed visibly from the PC screen and confirmed before sending. Neither is stored as evidence.
#
# Usage (on the laptop, from the repository root):
#   bash docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/registrar_agente_a3.sh
set -euo pipefail

API="http://127.0.0.1:8000"
LAPTOP_HOSTNAME="Eze-Linux"
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fase4"

if [[ "$(hostname)" != "${LAPTOP_HOSTNAME}" ]]; then
    echo "ERROR: this is not the laptop ($(hostname)); nothing was sent" >&2
    exit 1
fi
mkdir -p "${OUT_DIR}"

read -r -p "Admin username [admin]: " admin_user </dev/tty
admin_user="${admin_user:-admin}"
read -r -s -p "Admin password: " admin_pass </dev/tty; echo
read -r -p "Agent id [a3-pc-ubuntu]: " agent_id </dev/tty
agent_id="${agent_id:-a3-pc-ubuntu}"
# The secret is typed by hand from the PC screen (no copy/paste between hosts), so it is shown
# while typing. It is single-use and stored Argon2-hashed by the backend. Spaces and dashes used
# to group it are ignored; hex is case-insensitive.
read -r -p "Bootstrap secret shown on the PC (spaces allowed): " secret </dev/tty
secret="$(tr -d ' -' <<<"${secret}" | tr '[:upper:]' '[:lower:]')"

if [[ ! "${secret}" =~ ^[0-9a-f]{16,}$ ]]; then
    echo "ERROR: expected at least 16 hex characters, got ${#secret}; nothing was sent" >&2
    exit 1
fi
grouped="$(sed -E 's/(.{4})/\1 /g; s/ $//' <<<"${secret}")"
echo "Typed secret (${#secret} chars): ${grouped}"
read -r -p "Does it match the PC screen exactly? [y/N] " confirm </dev/tty
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    echo "Cancelled; nothing was sent" >&2
    exit 1
fi
unset grouped

login_body="$(jq -n --arg u "${admin_user}" --arg p "${admin_pass}" '{username: $u, password: $p}')"
unset admin_pass
login_file="$(mktemp)"
login_code="$(curl -sS -o "${login_file}" -w '%{http_code}' -X POST "${API}/auth/login" \
    -H 'Content-Type: application/json' --data-binary @- <<<"${login_body}")"
unset login_body
token="$(jq -r '.access_token // empty' "${login_file}" 2>/dev/null || true)"
rm -f "${login_file}"
if [[ "${login_code}" != "200" || -z "${token}" ]]; then
    case "${login_code}" in
        401) echo "ERROR: login rejected (401): wrong admin username or password; nothing was registered" >&2 ;;
        403) echo "ERROR: login rejected (403): admin account disabled; nothing was registered" >&2 ;;
        429) echo "ERROR: login rate-limited (429): wait before retrying; nothing was registered" >&2 ;;
        *)   echo "ERROR: login failed (HTTP ${login_code}); nothing was registered" >&2 ;;
    esac
    exit 1
fi

register_body="$(jq -n --arg a "${agent_id}" --arg s "${secret}" '{agent_id: $a, bootstrap_secret: $s}')"
unset secret
response_file="$(mktemp)"
http_code="$(curl -sS -o "${response_file}" -w '%{http_code}' -X POST "${API}/agents/register" \
    -H "Authorization: Bearer ${token}" -H 'Content-Type: application/json' --data-binary @- <<<"${register_body}")"
unset register_body token

{
    echo "date=$(date -Is)"
    echo "agent_id=${agent_id}"
    echo "http_code=${http_code}"
    echo "response=$(cat "${response_file}")"
} | tee "${OUT_DIR}/02-registro-agente.txt"
rm -f "${response_file}"

[[ "${http_code}" == "201" ]]
