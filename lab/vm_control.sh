#!/bin/sh
# Control group scanner (Battery 7): baseline scan + 3 diff scans every 900 s,
# spanning the same window as the Battery 3 generator.
cd /opt/tesis || exit 1
# Start the CSV fresh. It is appended to and was never truncated, so each
# package shipped every scan since the first run: one evidence package carried
# 418 rows spanning six days presented as that run's control arm. The
# attribution filters by scan interval and the analysis was never wrong, but a
# file that misrepresents its own scope is a problem for whoever audits it.
rm -f /srv/evidencia/bateria7_control.csv
/usr/bin/python3.13 scripts/control_hashing.py \
  --dir /srv/fim-watch --agent-prefix /srv/fim-watch \
  --csv /srv/evidencia/bateria7_control.csv \
  --state /srv/evidencia/control_estado.json \
  --interval 900 --loop --iterations 4 --reset
