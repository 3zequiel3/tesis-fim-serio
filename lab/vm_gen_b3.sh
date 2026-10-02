#!/bin/sh
# Battery 3 load generator: 500 changes sustained over 30 minutes (0.2778 ch/s,
# unchanged from the original runs). $1 = SEED (required): each repetition of the
# battery uses its own seed (L-12: 20261001, 20261002, 20261003).
SEED=${1:?usage: vm_gen_b3.sh <seed>}
cd /opt/tesis || exit 1
# The manifest and the log belong to this run only.
rm -f /srv/evidencia/bateria3_manifiesto.json /srv/evidencia/bateria3_manifiesto.jsonl /srv/evidencia/bateria3_generador.log
/usr/bin/python3.13 scripts/generador_carga.py \
  --dir /srv/fim-watch --agent-prefix /srv/fim-watch --seed "$SEED" \
  --rate 0.2778 --count 500 --mix 20/70/10 \
  --critical-subdir critico --critical-frac 0.2 \
  --manifest /srv/evidencia/bateria3_manifiesto.json \
  --log /srv/evidencia/bateria3_generador.log
