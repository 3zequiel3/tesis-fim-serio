#!/usr/bin/env bash
# Inventario de código de una etiqueta (tesis, Anexo L.2 y Tabla 14).
#
# Cuenta los .py de agent/ y backend/app/, sin los directorios de pruebas:
# archivos, líneas (wc -l) y líneas de código según pygount 3.2.0. Lista,
# además, los módulos de dominio de backend/app/modules/. Para v5.1-tesis:
#
#   agent        25 archivos   9.343 líneas   5.992 de código
#   backend/app  64 archivos  11.332 líneas   6.180 de código
#   módulos      actions agents alerts audit auth events rules users
#
# Uso, desde la raíz del clon:
#   scripts/inventario_codigo.sh [--tag v5.1-tesis]
#
# Requiere pygount 3.2.0 (pip install pygount==3.2.0) para la columna de
# código; sin él, informa archivos y líneas. PYTHON elige el intérprete.
set -euo pipefail

tag="v5.1-tesis"
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) tag="$2"; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "argumento desconocido: $1" >&2; exit 2 ;;
  esac
done

git rev-parse -q --verify "refs/tags/$tag" >/dev/null || { echo "no existe la etiqueta $tag" >&2; exit 4; }

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys' >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
export PYTHONIOENCODING=utf-8

pygount_ok=no
if [ -n "$PY" ] && v="$("$PY" -c 'import pygount; print(pygount.__version__)' 2>/dev/null)"; then
  if [ "$v" = "3.2.0" ]; then pygount_ok=si
  else echo "aviso: pygount $v instalado; la Tabla 14 se calculó con 3.2.0" >&2; pygount_ok=si; fi
else
  echo "aviso: pygount no está instalado; se omite la columna de código" >&2
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git -c core.autocrlf=false archive "$tag" agent backend/app | tar -x -C "$tmp"
cd "$tmp"

echo "Inventario de código en $tag (sin directorios de pruebas)"
for d in agent backend/app; do
  archivos="$(find "$d" -name '*.py' -not -path '*/tests/*' | wc -l | tr -d ' ')"
  lineas="$(find "$d" -name '*.py' -not -path '*/tests/*' -exec cat {} + | wc -l | tr -d ' ')"
  codigo="-"
  if [ "$pygount_ok" = si ]; then
    codigo="$("$PY" - "$d" <<'PYEOF'
import contextlib, io, json, sys
from pygount.command import pygount_command
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    pygount_command(["--format=json", "--suffix=py", "--folders-to-skip=tests,[...]", sys.argv[1]])
print(json.loads(buf.getvalue())["summary"]["totalCodeCount"])
PYEOF
)"
  fi
  printf '  %-12s %4s archivos  %6s líneas  %6s de código\n' "$d" "$archivos" "$lineas" "$codigo"
done
printf '  módulos     '
for m in backend/app/modules/*/; do printf ' %s' "$(basename "$m")"; done
echo
