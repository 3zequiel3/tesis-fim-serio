#!/usr/bin/env bash
# Huella de backend/app de una etiqueta (tesis, Anexo L.1).
#
# Reproduce el cálculo que lab/corrida_unificada.sh ejecuta dentro del
# contenedor: el SHA-256 de cada .py de backend/app, ordenado por ruta, y el
# SHA-256 de esa lista. El orden depende de la colación, así que el valor
# depende del locale:
#
#   LC_ALL=C            981dc0f3fef006afb842c5d9ff38a66af37452547abc66e39ef6ee9578597325
#   LC_ALL=es_AR.UTF-8  4749b8a59d02458bd3992a2d0c76bc0e05b7e8676173481c14a2972e95375a56
#                       (igual a backend_tree_container de v5-eval-20261003T102313Z)
#
# Uso, desde la raíz del clon:
#   scripts/huella_backend.sh [--tag v5.1-tesis] [--locale C]
#
# Con un locale distinto de C, la colación debe estar generada en el equipo
# (locale -a). En Windows conviene usar C: la colación de Git Bash no es la de
# glibc y no reproduce el valor es_AR.UTF-8.
set -euo pipefail

tag="v5.1-tesis"
loc="C"
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) tag="$2"; shift 2 ;;
    --locale) loc="$2"; shift 2 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "argumento desconocido: $1" >&2; exit 2 ;;
  esac
done

if [ "$loc" != "C" ] && [ "$loc" != "POSIX" ]; then
  norm() { printf '%s' "$1" | tr 'A-Z' 'a-z' | tr -d '-'; }
  if ! locale -a 2>/dev/null | while read -r l; do [ "$(norm "$l")" = "$(norm "$loc")" ] && echo si; done | grep -q si; then
    echo "la colación $loc no está generada en este equipo (locale -a)" >&2
    exit 3
  fi
fi

git rev-parse -q --verify "refs/tags/$tag" >/dev/null || { echo "no existe la etiqueta $tag" >&2; exit 4; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
# Sin conversión de fin de línea: la huella es sobre los bytes de la etiqueta.
git -c core.autocrlf=false archive "$tag" backend/app | tar -x -C "$tmp"

# sha256sum separa hash y ruta con dos espacios; en Git Bash (Windows) usa
# " *", la marca de modo binario. Se normaliza para que la lista sea la misma.
huella="$(
  cd "$tmp/backend"
  export LC_ALL="$loc"
  find app -name '*.py' -exec sha256sum {} \; \
    | sed 's/^\([0-9a-f]\{64\}\) \*/\1  /' \
    | sort -k2 | sha256sum | cut -d' ' -f1
)"
echo "huella de backend/app en $tag con LC_ALL=$loc: $huella"
