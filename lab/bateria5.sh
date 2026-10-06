#!/usr/bin/env bash
# Battery 5 — offline resilience and drain after reconnection (items 36-43, D38/RN-132).
# Runs on the central server; the load generator is invoked on the VM through multipass.
# TAG (env, required) names the candidate; the repository must be checked out at it (L-13).
set -uo pipefail

REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
OUT=${1:?usage: TAG=<tag> bateria5.sh <output_dir> <label>   (DC_FILES="<compose files>" optional)}
ETIQUETA=${2:?}
LOG="$OUT/bateria5_${ETIQUETA}.log"
mkdir -p "$OUT"
cd "$REPO" || exit 1
# shellcheck source=lib_arnes.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib_arnes.sh"

# Marcas de tiempo con Python: la utilidad date del anfitrión omite el cero inicial de la
# fracción de segundo cuando es menor a 0,1 s (56.080 se escribía 56.80); ver tesis, apartado 6.4.
ts() { python3 -c 'import datetime as d; print(d.datetime.now(d.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))'; }
epoch() { python3 -c 'import time; print(f"{time.time():.6f}")'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

# The caller provides the COMPLETE list of compose files (DC_FILES, space separated):
# exactly the set it used to bring the backend up. Compose recreates any service whose
# effective configuration differs from the running container's, so a different file set
# here (e.g. without docker-compose.mailpit.yml, which changes the backend environment)
# can recreate the backend in the middle of the measurement (D85/RN-179, D-9).
# Base + TLS are ALWAYS required: the TLS file publishes Valkey over TLS on 6380.
# Omitting it recreates the services without TLS and the agent loses the transport
# (invalid attempt of 2026-09-17T22:41:18Z).
read -r -a COMPOSE_FILES <<<"${DC_FILES:-docker-compose.yml docker-compose.tls.yml}"
for required in docker-compose.yml docker-compose.tls.yml; do
  printf '%s\n' "${COMPOSE_FILES[@]}" | rg -q -x "(.*/)?${required//./\\.}" \
    || { echo "ABORTED: DC_FILES must include $required (got: ${COMPOSE_FILES[*]})" >&2; exit 1; }
done
DC=(docker compose)
for f in "${COMPOSE_FILES[@]}"; do DC+=(-f "$f"); done

# VM-side probes MUST go through transferred scripts: multipass exec re-parses
# inline quoting, so `bash -c 'ls <dir> | wc -l'` ran `bash -c ls` in the working
# directory and reported a constant 21 instead of the queue depth.
q_events()   { "${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM events;" 2>/dev/null | tr -d ' \r'; }
q_counts()   { multipass exec fim-host -- sudo sh /tmp/vm_qcount.sh 2>/dev/null | tr -d '\r'; }
q_queue()    { q_counts | awk '{print $1}'; }
q_discard()  { q_counts | awk '{print $2}'; }
q_valkey()   { ss -lntp 2>/dev/null | grep -c '0.0.0.0:6380'; }

backend_id() { "${DC[@]}" --profile app ps -q backend 2>/dev/null | tr -d '\r'; }

# Effective ingest limit, read from the running backend (D38/RN-132, D85/RN-179).
# The removed variables are only reported: they are ignored by the backend.
log "=== Battery 5 — label=$ETIQUETA ==="
log "compose_files=${COMPOSE_FILES[*]}"
log "ingest_rate_limit: rate_per_s=$("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_RATE_PER_S 2>/dev/null | tr -d '\r') burst=$("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_BURST 2>/dev/null | tr -d '\r')"
log "legacy_RATE_LIMIT_INGEST_EVENTS='$("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_EVENTS 2>/dev/null | tr -d '\r')' legacy_RATE_LIMIT_INGEST_WINDOW_SECONDS='$("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_WINDOW_SECONDS 2>/dev/null | tr -d '\r')'"
BACKEND_ID_BEFORE=$(backend_id)
log "backend_container_id_before=$BACKEND_ID_BEFORE"
# L-13: TAG required, HEAD must be the tag's commit, agent/backend/frontend/n8n clean.
# Writes $OUT/env/procedencia.txt (tag=, commit=).
# Called directly, never in a pipeline or $(...): both run it in a subshell, so COMMIT
# (set by the guard) would never reach this shell and `set -u` killed the script on the
# next line without a word in the log. Exit 2 = setup abort, distinct from 3 = invalid cut.
mkdir -p "$OUT/env"
if ! procedencia_exigir "${TAG:-}" "$OUT/env" > "$OUT/env/procedencia_guard.log" 2>&1; then
  log "ABORTED by provenance: $(cat "$OUT/env/procedencia_guard.log")"; exit 2
fi
log "candidate=$COMMIT tree=$(git rev-parse HEAD^{tree}) tag=$TAG"
log "initial: events=$(q_events) queue+discarded=$(q_counts) valkey_6380=$(q_valkey)"

# L-14: preflight guards (schema registry, clock on host and VM, SMTP sink, baseline
# purged, ingest limit == product defaults unless RATE_LIMIT_VARIANT is declared,
# Valkey AOF on). Any failure aborts BEFORE the cut and before any generator write.
if ! PF=$(preflight_todo "$OUT/env" 2>&1); then
  log "ABORTED by preflight: $PF"; exit 2
fi
log "preflight ok: $(tr '\n' ' ' < "$OUT/env/preflight.txt")"
BACKEND_CID=$(backend_id)
docker inspect -f 'id={{.Id}} started_at={{.State.StartedAt}} restart_count={{.RestartCount}}' "$BACKEND_CID" > "$OUT/backend_inspect_pre.txt" 2>&1
log "backend_inspect_pre: $(cat "$OUT/backend_inspect_pre.txt")"

# Protocol cut (plan_medicion_cap5.md:338): connectivity with Valkey is severed, not the
# backend. Stopping the backend instead leaves Valkey up, the agent keeps XADDing during the
# outage, and events age past the 300 s skew window inside the stream — that measures a
# different scenario (backend down, broker up) and must be labelled as such.
log "--- phase 1: stop Valkey (5-minute outage, service down) ---"
INICIO_CORTE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
log "INICIO_CORTE t=$INICIO_CORTE"
"${DC[@]}" stop valkey >/dev/null 2>&1
log "valkey stopped; valkey_6380=$(q_valkey)"

log "--- phase 2: generate 3000 changes at 10/s over 300 s ---"
multipass exec fim-host -- sudo sh /tmp/vm_gen.sh "$ETIQUETA" >> "$LOG" 2>&1
log "generator finished; queue+discarded=$(q_counts)"

log "--- phase 3: restore Valkey and time the drain ---"
# Restore ONLY Valkey and never recreate: the backend was not stopped by the cut, so it is
# not named here, and --no-recreate keeps a configuration difference from replacing a
# running container mid-measurement (D85/RN-179, D-9).
"${DC[@]}" --profile app up -d --no-recreate valkey >/dev/null 2>&1
# FIN_CORTE: the restore command has returned. scripts/descomponer_drenaje.py (A-3) takes
# t0 from this line; "valkey up (t0)" below is the later instant the TLS port answered.
log "FIN_CORTE t=$(ts)"
# t0 is the instant connectivity is actually restored: the TLS port serving again.
for _ in $(seq 1 60); do [ "$(q_valkey)" = "1" ] && break; sleep 1; done
T0=$(epoch)
log "valkey up (t0); valkey_6380=$(q_valkey)"

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
    T1=$(epoch)
    log "DRAIN COMPLETE: events=$EV queue=$QS discarded=$DS"
    log "drain_duration_s=$(echo "$T1 - $T0" | bc)"
    log "throughput_ev_s=$(echo "scale=4; $EV / ($T1 - $T0)" | bc)"
    log "delivered_of_3000=$EV discarded=$DS"
    break
  fi
  if [ "$STABLE" -ge 120 ]; then
    T1=$(epoch)
    log "STALLED 10 min without progress: events=$EV queue=$QS discarded=$DS"
    log "duration_to_stall_s=$(echo "$T1 - $T0" | bc)"
    break
  fi
  sleep 5
done

# The backend container must be the same one that was running before phase 1: a
# recreation during the cut refills the token bucket and restarts the consumer, so the
# repetition would not measure the product's drain (D85/RN-179, D-9).
BACKEND_ID_AFTER=$(backend_id)
log "backend_container_id_after=$BACKEND_ID_AFTER"
# docker inspect pre/post and the backend logs since the cut began: they confirm or
# discard the "the backend restarted during the cut" hypothesis (run-03).
docker inspect -f 'id={{.Id}} started_at={{.State.StartedAt}} restart_count={{.RestartCount}}' "${BACKEND_ID_AFTER:-$BACKEND_CID}" > "$OUT/backend_inspect_post.txt" 2>&1
log "backend_inspect_post: $(cat "$OUT/backend_inspect_post.txt")"
"${DC[@]}" logs --no-color --since "$INICIO_CORTE" backend > "$OUT/backend_logs_desde_inicio_corte.log" 2>&1
log "backend logs since INICIO_CORTE: $(wc -l < "$OUT/backend_logs_desde_inicio_corte.log") lines"
INVALID=0
if [ "$BACKEND_ID_BEFORE" != "$BACKEND_ID_AFTER" ]; then
  INVALID=1
  log "INVALID: the backend container was recreated during the run (id before != after)"
  touch "$OUT/INVALID_${ETIQUETA}"
fi

log "--- summary ---"
log "final: events=$(q_events) queue+discarded=$(q_counts)"
"${DC[@]}" exec -T db psql -U fim -d fim -c "SELECT count(*) AS events, count(DISTINCT event_id) AS unique_events FROM events;" >> "$LOG" 2>&1
"${DC[@]}" exec -T db psql -U fim -d fim -c "SELECT reason, count(*) FROM rejected_events_audit GROUP BY 1;" >> "$LOG" 2>&1
# Consumption window (change ingest-batched-persistence, D87/RN-181): the drain rate as the
# number of drained events over the span between the first and the last `received_at`, the
# same quantity the v5.0-tesis diagnosis computed from eventos.csv. It excludes the wait for
# the Valkey restore and the stability polling above, which `throughput_ev_s` includes.
read -r CW_EVENTS CW_SECONDS <<<"$("${DC[@]}" exec -T db psql -U fim -d fim -tAF' ' -c "SELECT count(*), COALESCE(EXTRACT(EPOCH FROM (max(received_at) - min(received_at))), 0) FROM events;" 2>/dev/null | tr -d '\r')"
if [ -n "${CW_SECONDS:-}" ] && [ "$(echo "${CW_SECONDS} > 0" | bc)" = "1" ]; then
  log "consumption_window_s=$CW_SECONDS"
  log "consumption_ev_s=$(echo "scale=4; $CW_EVENTS / $CW_SECONDS" | bc)"
else
  log "consumption_window_s=n/a (events=${CW_EVENTS:-?} window=${CW_SECONDS:-?})"
fi
log "=== end ==="
[ "$INVALID" = "0" ] || exit 3
