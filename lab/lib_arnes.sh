#!/usr/bin/env bash
# Shared harness guards for the v5.0-tesis evaluation batteries (L-11, L-13, L-14).
# Sourced, never executed. The caller defines before calling any function:
#   REPO          repository root (cd'ed into it)
#   DC            docker compose command as an array, e.g. DC=(docker compose -f ... -f ...)
#   COMPOSE_FILES the same files, one element each (only for migrar.py)
# Every function prints one "ABORTA: ..." line to stderr and returns 1 on
# failure; the caller decides to exit. Nothing here starts a battery.

# Product defaults of the ingest rate limit (docker-compose.yml, D85/RN-179).
RATE_LIMIT_DEFAULT_RATE_PER_S=1.6666666666666667
RATE_LIMIT_DEFAULT_BURST=3000

_aborta() { echo "ABORTA: $*" >&2; return 1; }

# ── L-13: provenance ──────────────────────────────────────────────────────────
# Usage: procedencia_exigir <TAG> <env_dir>
# TAG is required (no default: a harness that hardcodes one tag silently measures
# the wrong tree). Aborts unless HEAD IS the tag's commit and agent/backend/
# frontend/n8n have no uncommitted change. Writes <env_dir>/procedencia.txt with
# tag= and commit= (it truncates; later steps append). Sets COMMIT.
procedencia_exigir() {
  local tag=${1:-} envdir=${2:-}
  [ -n "$tag" ] || { _aborta "TAG is required (e.g. TAG=v5.0-tesis)"; return 1; }
  [ -n "$envdir" ] || { _aborta "procedencia_exigir: env_dir missing"; return 1; }
  git -C "$REPO" rev-parse -q --verify "refs/tags/$tag" >/dev/null \
    || { _aborta "the tag $tag does not exist"; return 1; }
  COMMIT=$(git -C "$REPO" rev-list -n 1 "$tag")
  local head
  head=$(git -C "$REPO" rev-parse HEAD)
  [ "$head" = "$COMMIT" ] \
    || { _aborta "HEAD ($head) is not the commit of $tag ($COMMIT): check out the tag first"; return 1; }
  # `git diff` alone misses staged changes, so the index is checked as well.
  { git -C "$REPO" diff --quiet -- agent backend frontend n8n \
    && git -C "$REPO" diff --cached --quiet -- agent backend frontend n8n; } \
    || { _aborta "agent/ backend/ frontend/ n8n/ have uncommitted changes"; return 1; }
  mkdir -p "$envdir"
  { echo "tag=$tag"; echo "commit=$COMMIT"; } > "$envdir/procedencia.txt"
}

# ── L-14: preflight guards ────────────────────────────────────────────────────
# Schema registry reaches the candidate tree (change 66, D84/RN-178).
preflight_esquema() {
  local f=() out c
  for c in "${COMPOSE_FILES[@]}"; do f+=(-f "$c"); done
  out=$(cd "$REPO" && python3 scripts/migrar.py "${f[@]}" --verificar 2>&1) \
    || { _aborta "migrar.py --verificar failed: $out"; return 1; }
}

# chrony "System time" offset in microseconds; empty if chronyc does not answer.
# The command arrives as separate arguments (word splitting differs bash/zsh).
_desvio_us() {
  "$@" 2>/dev/null | tr -d '\r' | awk '/^System time/ {printf "%d", $4 * 1000000; exit}'
}
# Clock offset <= CLOCK_MAX_US (default 5000 us = 0.005 s) on host AND VM.
# NTPSynchronized=yes is NOT a guard: see corrida_unificada.sh. Sets HOST_US, VM_US.
preflight_reloj() {
  local max=${CLOCK_MAX_US:-5000}
  HOST_US=$(_desvio_us chronyc tracking)
  VM_US=$(_desvio_us multipass exec fim-host -- chronyc tracking)
  [ -n "$HOST_US" ] || { _aborta "chronyc does not answer on the host"; return 1; }
  [ -n "$VM_US" ] || { _aborta "chronyc does not answer on the guest (install chrony)"; return 1; }
  if [ "$HOST_US" -gt "$max" ] || [ "$VM_US" -gt "$max" ]; then
    _aborta "clock offset too large: host ${HOST_US} us, guest ${VM_US} us (ceiling ${max} us)"; return 1
  fi
}

# The SMTP sink answers (Mailpit): without it every delivery fails identically
# and a slow chain is indistinguishable from a missing one.
preflight_sumidero() {
  curl -sf --max-time 10 http://127.0.0.1:8025/api/v1/info >/dev/null 2>&1 \
    || { _aborta "mailpit does not answer on /api/v1/info (8025)"; return 1; }
}

# The agent holds zero baseline entries. Must hold BEFORE any generator write.
preflight_baseline_purgada() {
  local n
  n=$(multipass exec fim-host -- sudo sh /tmp/vm_baseline_count.sh 2>/dev/null | tr -d '\r' | sd '.*=' '')
  [ "$n" = "0" ] || { _aborta "baseline not purged: baseline_entries=${n:-unknown} (expected 0)"; return 1; }
}

# Backend ingest limit equals the product defaults, unless the battery declares a
# variant: RATE_LIMIT_VARIANT="<text>" skips the equality and is recorded.
preflight_rate_limit() {
  local rate burst
  rate=$("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_RATE_PER_S 2>/dev/null | tr -d '\r')
  burst=$("${DC[@]}" exec -T backend printenv RATE_LIMIT_INGEST_BURST 2>/dev/null | tr -d '\r')
  RATE_LIMIT_OBSERVED="rate_per_s=$rate burst=$burst"
  if [ -n "${RATE_LIMIT_VARIANT:-}" ]; then
    echo "rate_limit_variant=$RATE_LIMIT_VARIANT ($RATE_LIMIT_OBSERVED)" >&2
    return 0
  fi
  awk -v r="$rate" -v b="$burst" -v dr="$RATE_LIMIT_DEFAULT_RATE_PER_S" -v db="$RATE_LIMIT_DEFAULT_BURST" \
    'BEGIN { exit !(r != "" && b != "" && (r-dr < 1e-6 && dr-r < 1e-6) && b == db) }' \
    || { _aborta "ingest limit ($RATE_LIMIT_OBSERVED) differs from the product defaults ($RATE_LIMIT_DEFAULT_RATE_PER_S / $RATE_LIMIT_DEFAULT_BURST); declare RATE_LIMIT_VARIANT to run a variant"; return 1; }
}

# valkey-cli inside the valkey container, over the mutual-TLS port (same args as
# purgar_stream.sh). Arguments are the Valkey command.
valkey_tls() {
  "${DC[@]}" exec -T valkey valkey-cli --tls --cert /certs/valkey.pem --key /certs/valkey-key.pem \
    --cacert /certs/ca.pem -p 6380 "$@" 2>/dev/null | tr -d '\r'
}

# Valkey runs with AOF (D87/RN-181). On a volume that already holds an RDB
# snapshot a direct switch LOSES the stream and the groups (mediciones.md §2), so
# the safe migration is printed when the guard fails.
preflight_aof() {
  local v
  v=$(valkey_tls CONFIG GET appendonly | sed -n 2p)
  [ "$v" = "yes" ] && return 0
  cat >&2 <<'MSG'
ABORTA: Valkey is running with appendonly != yes.
Safe AOF migration on a volume that already has data (design.md Migration Plan;
mediciones.md §2: `up -d valkey` straight onto an RDB volume starts an EMPTY AOF
and loses the stream and the consumer groups). With the OLD server still running:
  1. valkey-cli (TLS args as in lab/purgar_stream.sh) CONFIG SET appendonly yes
  2. wait until INFO persistence shows aof_rewrite_in_progress:0 and
     aof_last_bgrewrite_status:ok
  3. docker compose ... up -d valkey      # recreates the container with AOF; volume kept
  4. valkey_tls CONFIG GET appendonly -> yes; XLEN events unchanged
A fresh volume with no snapshot needs no migration.
MSG
  return 1
}

# All guards a battery runs before touching the generator. Records the observed
# values in <env_dir>/preflight.txt.
preflight_todo() {
  local envdir=${1:?env_dir}
  mkdir -p "$envdir"
  preflight_esquema || return 1
  preflight_reloj || return 1
  preflight_sumidero || return 1
  preflight_baseline_purgada || return 1
  preflight_rate_limit || return 1
  preflight_aof || return 1
  {
    echo "preflight=ok"
    echo "schema=migrar.py --verificar ok"
    echo "host_clock_offset_us=$HOST_US"
    echo "vm_clock_offset_us=$VM_US"
    echo "sink=mailpit /api/v1/info ok"
    echo "baseline_entries=0"
    echo "rate_limit=$RATE_LIMIT_OBSERVED variant=${RATE_LIMIT_VARIANT:-none}"
    echo "valkey_appendonly=yes"
  } > "$envdir/preflight.txt"
}

# ── L-11: server-side reset ───────────────────────────────────────────────────
# Usage: reset_servidor    (after vm_reset.sh succeeded)
# TRUNCATE events, alerts, rejected_events_audit RESTART IDENTITY CASCADE, and
# XTRIM events MAXLEN 0. audit_log and published_commands are deliberately KEPT:
# they are not part of the measured lane (neither references events/alerts, so
# CASCADE does not reach them) and published_commands carries the registered
# agent's command history.
reset_servidor() {
  "${DC[@]}" exec -T db psql -U fim -d fim -v ON_ERROR_STOP=1 -tAc \
    "TRUNCATE events, alerts, rejected_events_audit RESTART IDENTITY CASCADE;" >/dev/null 2>&1 \
    || { _aborta "TRUNCATE of events/alerts/rejected_events_audit failed"; return 1; }
  valkey_tls XTRIM events MAXLEN 0 >/dev/null
  local ev xl
  ev=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM events;" 2>/dev/null | tr -d ' \r')
  xl=$(valkey_tls XLEN events)
  [ "$ev" = "0" ] && [ "$xl" = "0" ] \
    || { _aborta "server reset incomplete: events=${ev:-?} stream_len=${xl:-?}"; return 1; }
}

# Whole lab reset (VM purge + server reset). vm_reset.sh exits non-zero unless the
# baseline holds 0 entries; that aborts the run.
reset_laboratorio() {
  local out
  out=$(multipass exec fim-host -- sudo sh /tmp/vm_reset.sh 2>&1) \
    || { echo "$out" >&2; _aborta "vm_reset.sh failed (baseline not purged or agent did not start)"; return 1; }
  echo "$out" | rg -N 'baseline_entries_after_reset=' || true
  reset_servidor
}
