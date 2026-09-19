#!/usr/bin/env bash
# Ensayo A-3, paso 3.7: allows 6380 (Valkey TLS), 8443 (backend mTLS renew) and 8444 (backend TLS
# bootstrap) only from the monitored PC.
#
# Docker-published ports bypass ufw, so the filter goes in the DOCKER-USER chain.
#   -i wlp2s0        only LAN traffic; backend -> valkey inside Docker is unaffected.
#   --ctorigdstport  matches the original port, before Docker's DNAT.
#
# Usage (on the laptop, from the repository root):
#   sudo bash docs/cierre/evidencia/v10-closure-20260912T190052Z/a3-multihost/aplicar_firewall_a3.sh
# Remove the rules:
#   sudo bash <this file> --remove
set -euo pipefail

LAPTOP_HOSTNAME="Eze-Linux"
LAN_IF="wlp2s0"
ALLOWED_SRC="192.168.1.36"
PORTS=(6380 8443 8444)
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fase3"
# Timestamped names: a re-run must never overwrite the evidence of a previous run.
RUN_TS="$(date +%Y%m%dT%H%M%S)"

if [[ "$(hostname)" != "${LAPTOP_HOSTNAME}" ]]; then
    echo "ERROR: this is not the laptop ($(hostname)); nothing was applied" >&2
    exit 1
fi
if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: run with sudo" >&2
    exit 1
fi
mkdir -p "${OUT_DIR}"

v4_rule() { echo "DOCKER-USER -i ${LAN_IF} -p tcp -m conntrack --ctorigdstport $1 --ctdir ORIGINAL ! -s ${ALLOWED_SRC} -j DROP"; }
v6_rule() { echo "DOCKER-USER -i ${LAN_IF} -p tcp -m conntrack --ctorigdstport $1 --ctdir ORIGINAL -j DROP"; }

snapshot() {
    {
        date -Is
        iptables -L DOCKER-USER -v -n --line-numbers
        ip6tables -L DOCKER-USER -v -n --line-numbers 2>&1 || true
    } | tee "$1"
}

if [[ "${1:-}" == "--remove" ]]; then
    for p in "${PORTS[@]}"; do
        # shellcheck disable=SC2046
        while iptables -C $(v4_rule "$p") 2>/dev/null; do iptables -D $(v4_rule "$p"); done
        # shellcheck disable=SC2046
        while ip6tables -C $(v6_rule "$p") 2>/dev/null; do ip6tables -D $(v6_rule "$p"); done
    done
    snapshot "${OUT_DIR}/07-firewall-quitado-${RUN_TS}.txt"
    exit 0
fi

snapshot "${OUT_DIR}/07-firewall-antes-${RUN_TS}.txt"
for p in "${PORTS[@]}"; do
    # Idempotent: insert only when the rule is not already present.
    # shellcheck disable=SC2046
    iptables -C $(v4_rule "$p") 2>/dev/null || iptables -I $(v4_rule "$p")
    if ip6tables -S DOCKER-USER >/dev/null 2>&1; then
        # shellcheck disable=SC2046
        ip6tables -C $(v6_rule "$p") 2>/dev/null || ip6tables -I $(v6_rule "$p")
    fi
done
snapshot "${OUT_DIR}/07-firewall-despues-${RUN_TS}.txt"
