#!/bin/sh
# Load generator for Battery 5. $1 = run label.
cd /opt/tesis || exit 1
/usr/bin/python3.13 scripts/generador_carga.py \
  --dir /srv/fim-watch --agent-prefix /srv/fim-watch --seed 20260917 \
  --rate 10 --count 3000 --mix 20/70/10 \
  --critical-subdir critico --critical-frac 0.2 \
  --manifest "/srv/evidencia/bateria5_$1_manifiesto.json" \
  --log "/srv/evidencia/bateria5_$1_generador.log"
