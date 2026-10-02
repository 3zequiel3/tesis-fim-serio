#!/bin/sh
# B-1 variant: the Battery 3 generator under strace, 100 modifications at 10/s.
#
# strace sits on the GENERATOR, not on the agent: it records, per operation, the exact
# openat / write / close sequence and its timestamps, so a modification that produced no
# event can be classified by what the generator actually did at the syscall level
# (close order, short writes, the fd closed before the write).
#   strace -f -ttt -T -yy -e trace=close,openat,write
#     -f   follow threads/children   -ttt absolute epoch with microseconds
#     -T   time spent in each call   -yy  decode fds to paths
#
# Usage (on the VM, as root; transfer it with the other vm_*.sh helpers):
#   sudo sh /tmp/vm_strace_gen.sh <label> [seed]       seed defaults to 20261001
# Output in /srv/evidencia: b1_strace_<label>.txt, b1_strace_<label>_manifiesto.json(.jsonl),
# b1_strace_<label>_generador.log.
#
# 100 modifications exactly: the generator needs creations to have files to modify, so the
# run is --count 125 --mix 20/80/0 = 25 creates + 100 modifies spread over 25 files, with
# the reversion, burst and ephemeral patterns off (--revert-frac 0 --burst-frac 0
# --ephemeral-frac 0) so every modification is a plain open/write/close of an existing
# file. Rate 10/s, as Battery 5.
LABEL=${1:?usage: vm_strace_gen.sh <label> [seed]}
SEED=${2:-20261001}
command -v strace >/dev/null 2>&1 || { echo "ABORTED: strace is not installed on the guest (apt install strace)" >&2; exit 1; }
cd /opt/tesis || exit 1
P=/srv/evidencia/b1_strace_$LABEL
rm -f "$P.txt" "${P}_manifiesto.json" "${P}_manifiesto.jsonl" "${P}_generador.log"
strace -f -ttt -T -yy -e trace=close,openat,write -o "$P.txt" \
  /usr/bin/python3.13 scripts/generador_carga.py \
  --dir /srv/fim-watch --agent-prefix /srv/fim-watch --seed "$SEED" \
  --rate 10 --count 125 --mix 20/80/0 \
  --revert-frac 0 --burst-frac 0 --ephemeral-frac 0 \
  --critical-subdir critico --critical-frac 0.2 \
  --manifest "${P}_manifiesto.json" \
  --log "${P}_generador.log"
RC=$?
echo "strace_lines=$(wc -l < "$P.txt") rc=$RC"
exit "$RC"
