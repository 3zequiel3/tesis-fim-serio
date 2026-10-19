#!/usr/bin/env bash
# Recalcula el Capítulo 5 desde la evidencia y lo compara con la tesis (P-10).
# Envoltorio de scripts/recalcular_cap5.py; ver su ayuda (--help).
#
# Uso, desde la raíz del clon:
#   scripts/recalcular_cap5.sh [--solo-diferencias]
#
# Sale con código 0 si todos los valores coinciden con
# tesis/cierre/valores_esperados.json, y con 1 si alguno difiere o falta.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys' >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || { echo "no se encontró Python" >&2; exit 3; }
export PYTHONIOENCODING=utf-8
exec "$PY" scripts/recalcular_cap5.py "$@"
