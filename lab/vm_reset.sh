#!/bin/sh
# Controlled lab reset on the monitored host (L-11, purge).
#
# Leaves the agent as freshly installed EXCEPT for its identity: secrets/ and
# certs/ are never touched. A reset that only emptied the queue left the
# encrypted baseline and the persisted state behind, so the next repetition did
# not start from zero: the agent reconciled against a stale baseline instead of
# baselining the watched roots again.
#
# What it does, in order:
#   1. stop the agent;
#   2. recreate baseline queue discarded journal quarantine (journal also holds
#      executed_commands.json) with the owner and mode install.sh gives them
#      (fim-agent:fim-agent, 0700);
#   3. remove state.json (it holds initialized_roots: without it the next start
#      silently baselines every root, which is exactly what a purge wants);
#   4. reset /srv/fim-watch and /srv/fim-watch/critico;
#   5. remove the experiment trace (path taken from FIM_EXPERIMENT_TRACE_FILE);
#   6. start the agent and wait up to 60 s for the "agent started" log line;
#   7. print baseline_entries_after_reset=N (count of *.bin) and exit non-zero
#      unless N is 0. The watched directory is empty at this point, so a correct
#      purge has no entries; the check must run BEFORE any generator write.
#
# Exit codes: 0 purged; 2 agent did not log "agent started" in 60 s; 3 baseline
# not empty after the reset.
STATE_DIR=/var/lib/fim-agent
AGENT_USER=fim-agent
WATCH=/srv/fim-watch
DEFAULT_TRACE=/var/lib/fim-agent/traza_b3.jsonl

systemctl stop fim-agent

# Resolve the trace path BEFORE removing anything: from the unit environment
# (drop-in written by vm_trace_on.sh), then from the optional EnvironmentFile.
TRACE=$(systemctl show fim-agent -p Environment --value 2>/dev/null | tr ' ' '\n' \
  | sed -n 's/^FIM_EXPERIMENT_TRACE_FILE=//p' | tr -d '"' | head -n 1)
if [ -z "$TRACE" ] && [ -r /etc/fim-agent/env ]; then
  TRACE=$(sed -n 's/^FIM_EXPERIMENT_TRACE_FILE=//p' /etc/fim-agent/env | tr -d '"' | head -n 1)
fi
[ -n "$TRACE" ] || TRACE=$DEFAULT_TRACE

for d in baseline queue discarded journal quarantine; do
  rm -rf "${STATE_DIR:?}/$d"
  mkdir -p "$STATE_DIR/$d"
  chmod 0700 "$STATE_DIR/$d"
  chown "$AGENT_USER:$AGENT_USER" "$STATE_DIR/$d"
done
# state.json and its atomic-write temporary (state.tmp); secrets/ and certs/ stay.
rm -f "$STATE_DIR/state.json" "$STATE_DIR/state.tmp"

find "$WATCH" -mindepth 1 -delete 2>/dev/null
mkdir -p "$WATCH/critico"

# Truncate the experiment trace while the agent is stopped, so every repetition
# produces its own trace instead of a cumulative file. Copying the cumulative
# file once per repetition made the three per-run traces byte-identical, and
# nothing in the harness noticed. Harmless when tracing is disabled.
rm -f "$TRACE" "$DEFAULT_TRACE"

# `--since @epoch` taken after the stop: the "agent started" of the previous
# run is older than this instant.
T_START=$(date +%s)
systemctl start fim-agent

OK=0
i=0
while [ "$i" -lt 60 ]; do
  if journalctl -u fim-agent --since "@$T_START" --no-pager 2>/dev/null | grep -q "agent started"; then
    OK=1
    break
  fi
  i=$((i + 1))
  sleep 1
done
if [ "$OK" != 1 ]; then
  echo "ABORTED: no 'agent started' in journalctl -u fim-agent within 60 s" >&2
  exit 2
fi

N=$(find "$STATE_DIR/baseline" -maxdepth 1 -type f -name '*.bin' 2>/dev/null | wc -l | tr -d ' ')
echo "baseline_entries_after_reset=$N"
[ "$N" = 0 ] || { echo "ABORTED: baseline not empty after the reset" >&2; exit 3; }
exit 0
