#!/bin/sh
# B-5b, guest side: prepare ONE repetition of the startup-reconciliation experiment.
# Run as root through a transferred script (multipass exec re-parses inline quoting).
#
#   sudo sh /tmp/vm_reconciliacion.sh
#
# 1. stop the agent and purge its state like vm_reset.sh (baseline queue discarded journal
#    quarantine, state.json; secrets/ and certs/ kept) and empty /srv/fim-watch;
# 2. create 10 files (r01..r10) BEFORE the agent starts, so the first start baselines them
#    (no state.json: every root is baselined silently, D80/RN-174);
# 3. start the agent, wait for "agent started" and for exactly 10 baseline entries;
# 4. stop the agent and, while it is down:
#      r01-r04  modify (append)
#      r05-r07  delete
#      r08-r10  delete and recreate with IDENTICAL bytes (and mode)
# 5. start the agent again and wait for "agent started". Reconciliation findings are
#    emitted right after; the host side polls the database for them.
#
# Prints key=value lines (baseline_entries=, t_restart_epoch=, ...). Exit codes: 0 ready;
# 2 the agent did not log "agent started" in 60 s; 3 baseline did not reach 10 entries.
STATE_DIR=/var/lib/fim-agent
AGENT_USER=fim-agent
WATCH=/srv/fim-watch

espera_inicio() {  # $1 = epoch taken before `systemctl start`
  i=0
  while [ "$i" -lt 60 ]; do
    journalctl -u fim-agent --since "@$1" --no-pager 2>/dev/null | grep -q "agent started" && return 0
    i=$((i + 1)); sleep 1
  done
  return 1
}

systemctl stop fim-agent
for d in baseline queue discarded journal quarantine; do
  rm -rf "${STATE_DIR:?}/$d"
  mkdir -p "$STATE_DIR/$d"
  chmod 0700 "$STATE_DIR/$d"
  chown "$AGENT_USER:$AGENT_USER" "$STATE_DIR/$d"
done
rm -f "$STATE_DIR/state.json" "$STATE_DIR/state.tmp"
find "$WATCH" -mindepth 1 -delete 2>/dev/null
mkdir -p "$WATCH/critico"

for n in 01 02 03 04 05 06 07 08 09 10; do
  printf 'contenido-original-%s\n' "$n" > "$WATCH/r$n"
  chmod 0644 "$WATCH/r$n"
done

T=$(date +%s)
systemctl start fim-agent
espera_inicio "$T" || { echo "ABORTED: no 'agent started' (first start)" >&2; exit 2; }
i=0; N=0
while [ "$i" -lt 60 ]; do
  N=$(find "$STATE_DIR/baseline" -maxdepth 1 -type f -name '*.bin' | wc -l | tr -d ' ')
  [ "$N" = 10 ] && break
  i=$((i + 1)); sleep 1
done
echo "baseline_entries=$N"
[ "$N" = 10 ] || { echo "ABORTED: baseline has $N entries, expected 10" >&2; exit 3; }

systemctl stop fim-agent
for n in 01 02 03 04; do printf 'modificado-offline\n' >> "$WATCH/r$n"; done
for n in 05 06 07; do rm -f "$WATCH/r$n"; done
for n in 08 09 10; do
  rm -f "$WATCH/r$n"
  printf 'contenido-original-%s\n' "$n" > "$WATCH/r$n"
  chmod 0644 "$WATCH/r$n"
done

T=$(date +%s)
echo "t_restart_epoch=$T"
systemctl start fim-agent
espera_inicio "$T" || { echo "ABORTED: no 'agent started' (second start)" >&2; exit 2; }
echo "restarted=ok"
exit 0
