#!/bin/sh
# Control group scanner (Battery 7), one fresh series per run, phase drawn from the
# run's seed (L-12).
#   $1 = SEED (required)
#   $2 = control phase in seconds (optional; default random.Random(SEED).randrange(900))
#
# Timeline: the baseline scan runs immediately (before the generator, as
# control_hashing.py requires), then the script waits `fase_control_s` seconds and
# starts `control_hashing.py --loop --interval 900`. The first loop scan therefore
# lands fase_control_s after the baseline, and the scan grid is offset from the
# generator start by a seed-dependent phase instead of always being the same.
# The number of loop scans is chosen so that the LAST one falls after the generator
# ends (GEN_WINDOW_S seconds after this script starts; default 1830 = 30 s head
# start + 1800 s of generation).
SEED=${1:?usage: vm_control.sh <seed> [fase_s]}
FASE=${2:-$(/usr/bin/python3.13 -c 'import random, sys; print(random.Random(int(sys.argv[1])).randrange(900))' "$SEED")}
GEN_WINDOW_S=${GEN_WINDOW_S:-1830}
CSV=/srv/evidencia/bateria7_control.csv
STATE=/srv/evidencia/control_estado.json
cd /opt/tesis || exit 1
# Start the CSV fresh. It is appended to and was never truncated, so each
# package shipped every scan since the first run: one evidence package carried
# 418 rows spanning six days presented as that run's control arm. The
# attribution filters by scan interval and the analysis was never wrong, but a
# file that misrepresents its own scope is a problem for whoever audits it.
rm -f "$CSV" "$STATE"
echo "seed=$SEED fase_control_s=$FASE"
/usr/bin/python3.13 scripts/control_hashing.py \
  --dir /srv/fim-watch --agent-prefix /srv/fim-watch \
  --csv "$CSV" --state "$STATE" --reset
sleep "$FASE"
N=$(( (GEN_WINDOW_S - FASE) / 900 + 2 ))
echo "loop_scans=$N"
/usr/bin/python3.13 scripts/control_hashing.py \
  --dir /srv/fim-watch --agent-prefix /srv/fim-watch \
  --csv "$CSV" --state "$STATE" \
  --interval 900 --loop --iterations "$N"
