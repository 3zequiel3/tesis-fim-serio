#!/bin/sh
echo "== ruta real del agente que corre el servicio:"
ls -d /opt/fim-agent/agent 2>/dev/null || echo "no existe /opt/fim-agent/agent"
find /opt/fim-agent -name "detector.py" -o -name "publisher.py" 2>/dev/null | head -5
echo "== hashes:"
for f in publisher.py detector.py _fanotify.py; do
  p=$(find /opt/fim-agent -name "$f" 2>/dev/null | head -1)
  [ -n "$p" ] && sha256sum "$p"
done
