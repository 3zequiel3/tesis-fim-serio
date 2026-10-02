#!/usr/bin/env bash
# Battery 5 — offline resilience and drain after reconnection (items 36-43, D38/RN-132).
# Runs on the central server; the load generator is invoked on the VM through multipass.
set -uo pipefail

REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
OUT=${1:?usage: bateria5.sh <output_dir> <rate_limit_events> <label>}
LIMIT=${2:?}
ETIQUETA=${3:?}
LOG="$OUT/bateria5_${ETIQUETA}.log"
COMPOSE=${DC_OVERRIDE:-}
mkdir -p "$OUT"
cd "$REPO" || exit 1

# ALWAYS both compose files: the override publishes Valkey over TLS on 6380.
# Omitting it recreates the services without TLS and the agent loses the transport
# (invalid attempt of 2026-09-17T22:41:18Z).
DC=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
[ -n "$COMPOSE" ] && DC+=(-f "$COMPOSE")

ts() { date -u +%Y-%m-%dT%H:%M:%S.%6NZ; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

# VM-side probes MUST go through transferred scripts: multipass exec re-parses
# inline quoting, so `bash -c 'ls <dir> | wc -l'` ran `bash -c ls` in the working
# directory and reported a constant 21 instead of the queue depth.
q_events()   { "${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM events;" 2>/dev/null | tr -d ' \r'; }
q_counts()   { multipass exec fim-host -- sudo sh /tmp/vm_qcount.sh 2>/dev/null | tr -d '\r'; }
q_queue()    { q_counts | awk '{print $1}'; }
q_discard()  { q_counts | awk '{print $2}'; }
q_valkey()   { ss -lntp 2>/dev/null | grep -c '0.0.0.0:6380'; }

log "=== Battery 5 — label=$ETIQUETA rate_limit=${LIMIT}/60s ==="
log "candidate=$(git rev-parse HEAD) tree=$(git rev-parse HEAD^{tree}) tag=v1.0-tesis"
log "initial: events=$(q_events) queue+discarded=$(q_counts) valkey_6380=$(q_valkey)"

# Protocol cut (plan_medicion_cap5.md:338): connectivity with Valkey is severed, not the
# backend. Stopping the backend instead leaves Valkey up, the agent keeps XADDing during the
# outage, and events age past the 300 s skew window inside the stream — that measures a
# different scenario (backend down, broker up) and must be labelled as such.
log "--- phase 1: stop Valkey (5-minute outage, service down) ---"
"${DC[@]}" stop valkey >/dev/null 2>&1
log "valkey stopped; valkey_6380=$(q_valkey)"

log "--- phase 2: generate 3000 changes at 10/s over 300 s ---"
multipass exec fim-host -- sudo sh /tmp/vm_gen.sh "$ETIQUETA" >> "$LOG" 2>&1
log "generator finished; queue+discarded=$(q_counts)"

log "--- phase 3: restore Valkey and time the drain ---"
"${DC[@]}" --profile app up -d valkey backend >/dev/null 2>&1
# t0 is the instant connectivity is actually restored: the TLS port serving again.
for _ in $(seq 1 60); do [ "$(q_valkey)" = "1" ] && break; sleep 1; done
T0=$(date -u +%s.%N)
log "valkey+backend up (t0); valkey_6380=$(q_valkey)"

PREV=-1; STABLE=0
for i in $(seq 1 1400); do
  read -r QS DS <<<"$(q_counts)"
  EV=$(q_events); VK=$(q_valkey)
  if [ "$VK" = "0" ]; then log "ABORTED: Valkey stopped publishing 6380 (harness defect)"; break; fi
  if [ "$((i % 12))" = "0" ]; then log "progress: events=$EV queue=$QS discarded=$DS"; fi
  if [ "$EV" = "$PREV" ]; then STABLE=$((STABLE+1)); else STABLE=0; fi
  PREV=$EV
  # The run closes when the agent queue is empty and the backend count has settled:
  # under the nominal budget the agent discards after max_attempts, so events may
  # legitimately end below 3000 — that outcome is the measurement, not a failure.
  if [ "${QS:-1}" = "0" ] && [ "$STABLE" -ge 3 ]; then
    T1=$(date -u +%s.%N)
    log "DRAIN COMPLETE: events=$EV queue=$QS discarded=$DS"
    log "drain_duration_s=$(echo "$T1 - $T0" | bc)"
    log "throughput_ev_s=$(echo "scale=4; $EV / ($T1 - $T0)" | bc)"
    log "delivered_of_3000=$EV discarded=$DS"
    break
  fi
  if [ "$STABLE" -ge 120 ]; then
    T1=$(date -u +%s.%N)
    log "STALLED 10 min without progress: events=$EV queue=$QS discarded=$DS"
    log "duration_to_stall_s=$(echo "$T1 - $T0" | bc)"
    break
  fi
  sleep 5
done

log "--- summary ---"
log "final: events=$(q_events) queue+discarded=$(q_counts)"
"${DC[@]}" exec -T db psql -U fim -d fim -c "SELECT count(*) AS events, count(DISTINCT event_id) AS unique_events FROM events;" >> "$LOG" 2>&1
"${DC[@]}" exec -T db psql -U fim -d fim -c "SELECT reason, count(*) FROM rejected_events_audit GROUP BY 1;" >> "$LOG" 2>&1
log "=== end ==="
