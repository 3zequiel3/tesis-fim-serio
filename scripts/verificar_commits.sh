#!/usr/bin/env bash
# Comprueba que los identificadores de commit que cita la tesis existan
# (tesis, Anexos F.1 y L.7).
#
# 1. Incorpora los bundles de custodia de tesis/cierre/evidencia/ en
#    refs/custodia/<paquete>/*, porque varios commits de septiembre solo se
#    conservan en ellos (Tabla 34).
# 2. Extrae del .docx los hexadecimales de 7 a 40 caracteres que combinan
#    letras y dígitos.
# 3. Clasifica cada uno: commit existente (git cat-file -e), ausente
#    declarado (--ausentes), prefijo de un SHA-256 (seguido de "…" o inicio
#    de un SHA-256 completo del texto) o FALTANTE.
#
# Uso, desde la raíz del clon:
#   scripts/verificar_commits.sh <documento.docx> [--ausentes "6e81ccf"]
#
# Sale con código 1 si hay algún FALTANTE. PYTHON elige el intérprete.
set -euo pipefail

docx=""
ausentes="6e81ccf"
while [ $# -gt 0 ]; do
  case "$1" in
    --ausentes) ausentes="$2"; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    -*) echo "argumento desconocido: $1" >&2; exit 2 ;;
    *) docx="$1"; shift ;;
  esac
done
[ -n "$docx" ] && [ -f "$docx" ] || { echo "uso: $0 <documento.docx> [--ausentes \"h1 h2\"]" >&2; exit 2; }

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys' >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
[ -n "$PY" ] || { echo "no se encontró Python" >&2; exit 3; }
export PYTHONIOENCODING=utf-8

# 1. Bundles de custodia.
nb=0
while IFS= read -r b; do
  pkg="$(basename "$(dirname "$(dirname "$b")")")"
  if ! git bundle verify -q "$b" >/dev/null 2>&1; then echo "bundle inválido: $b" >&2; exit 5; fi
  git fetch -q "$b" "+refs/heads/*:refs/custodia/$pkg/*"
  nb=$((nb + 1))
done < <(find tesis/cierre/evidencia -name '*.bundle' | sort)
echo "bundles incorporados: $nb"

# 2. Identificadores del documento, con su clase textual.
lista="$("$PY" - "$docx" <<'PYEOF'
import re, sys, zipfile
from html import unescape
xml = zipfile.ZipFile(sys.argv[1]).read("word/document.xml").decode("utf-8")
texto = unescape(re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml)))
completos = set(re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", texto))
vistos = {}
for m in re.finditer(r"(?<![0-9a-zA-Z])([0-9a-f]{7,40})(?![0-9a-zA-Z])", texto):
    h = m.group(1)
    if not (re.search(r"[a-f]", h) and re.search(r"[0-9]", h)):
        continue
    sha = texto[m.end():m.end() + 1] == "…" or any(c.startswith(h) for c in completos)
    vistos[h] = vistos.get(h, False) or sha
for h in sorted(vistos):
    print(h, "sha256" if vistos[h] else "candidato")
PYEOF
)"

# 3. Clasificación.
n_commit=0; n_aus=0; n_sha=0; n_falt=0
while read -r h clase; do
  # En Windows, Python escribe sus líneas con CRLF: se quita el CR final.
  h="${h%$'\r'}"; clase="${clase%$'\r'}"
  [ -n "$h" ] || continue
  if git cat-file -e "$h^{commit}" 2>/dev/null; then
    n_commit=$((n_commit + 1)); continue
  fi
  declarado=no
  for a in $ausentes; do case "$h" in "$a"*) declarado=si ;; esac; done
  if [ "$declarado" = si ]; then
    n_aus=$((n_aus + 1)); echo "  ausente declarado: $h"
  elif [ "$clase" = sha256 ]; then
    n_sha=$((n_sha + 1)); echo "  prefijo de SHA-256, no es commit: $h"
  else
    n_falt=$((n_falt + 1)); echo "  FALTANTE: $h"
  fi
done <<< "$lista"

total=$((n_commit + n_aus + n_sha + n_falt))
echo "identificadores: $total; commits existentes: $n_commit; ausentes declarados: $n_aus; prefijos de SHA-256: $n_sha; faltantes: $n_falt"
[ "$n_falt" -eq 0 ]
