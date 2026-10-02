#!/bin/sh
cd /opt/tesis || exit 1
/usr/bin/python3.13 scripts/generador_carga.py \
  --dir /srv/fim-watch --agent-prefix /srv/fim-watch --seed 20260918 \
  --rate 10 --count 400 --mix 20/70/10 \
  --critical-subdir critico --critical-frac 0.2 \
  --manifest /srv/evidencia/item42_manifiesto.json \
  --log /srv/evidencia/item42_generador.log
