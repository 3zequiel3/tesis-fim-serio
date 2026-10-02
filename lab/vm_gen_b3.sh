#!/bin/sh
# Battery 3 load generator: 500 changes sustained over 30 minutes.
cd /opt/tesis || exit 1
/usr/bin/python3.13 scripts/generador_carga.py \
  --dir /srv/fim-watch --agent-prefix /srv/fim-watch --seed 20260917 \
  --rate 0.2778 --count 500 --mix 20/70/10 \
  --critical-subdir critico --critical-frac 0.2 \
  --manifest /srv/evidencia/bateria3_manifiesto.json \
  --log /srv/evidencia/bateria3_generador.log
