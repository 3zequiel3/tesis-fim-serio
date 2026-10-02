#!/usr/bin/env bash
# Item 42 — a command queued during the outage is processed BEFORE the queued events.
# The invariant lives in agent/publisher.py:151-156: run() awaits _flush_commands()
# before _drain_queue(). This exercises it end to end.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
OUT=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z/bateria5/item42
LAB=/home/ezequiel/fim-lab
RES=$LAB/item42.out
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
cd "$REPO" || exit 1
mkdir -p "$OUT"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

say "=== item 42 ==="
multipass exec fim-host -- sudo sh /tmp/vm_reset.sh
"${DC[@]}" exec -T db psql -U fim -d fim -tAc "DELETE FROM alerts; DELETE FROM events; DELETE FROM rejected_events_audit;" >/dev/null 2>&1
sleep 15

say "phase 1: cut Valkey"
"${DC[@]}" stop valkey >/dev/null 2>&1

say "phase 2: generate 400 changes so the local queue fills"
multipass exec fim-host -- sudo sh /tmp/vm_gen_i42.sh >> "$OUT/generador.log" 2>&1
say "queue after generating: $(multipass exec fim-host -- sudo sh /tmp/vm_qcount.sh | tr -d '\r')"

say "phase 3: stop the agent, so the command flush happens on its next start"
multipass exec fim-host -- sudo systemctl stop fim-agent

say "phase 4: restore Valkey and enqueue a command while the agent is down"
"${DC[@]}" --profile app up -d valkey backend >/dev/null 2>&1
for _ in $(seq 1 60); do [ "$(ss -lntp 2>/dev/null | grep -c '0.0.0.0:6380')" = "1" ] && break; sleep 1; done
sleep 3
# Copied here, not earlier: bringing the stack back up can replace the container.
"${DC[@]}" cp "$LAB/encolar_comando.py" backend:/tmp/encolar_comando.py >/dev/null 2>&1
"${DC[@]}" exec -T backend sh -c 'cd /app && PYTHONPATH=/app python /tmp/encolar_comando.py' 2>&1 | tee -a "$RES"

say "phase 5: start the agent and watch the order"
T0=$(date -u +%s)
multipass exec fim-host -- sudo systemctl start fim-agent
sleep 90
T1=$(date -u +%s)
multipass exec fim-host -- sudo sh /tmp/vm_journal.sh "$((T0-10))" "$T1" > "$OUT/agente_journal.log" 2>&1
say "=== done ==="
