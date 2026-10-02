#!/usr/bin/env bash
# B-5b: startup reconciliation, 10 repetitions (D80/RN-174).
#
# Per repetition: 10 baselined files; the agent is stopped; 4 are modified, 3 deleted and
# 3 deleted and recreated with identical bytes; the agent is started. Expected: 4
# file_modified + 3 file_deleted, all with detected_offline=true, and NOTHING for the 3
# identical ones (nor for any other path). The guest side is lab/vm_reconciliacion.sh.
#
# Usage: TAG=<tag> bash b5b_reconciliacion.sh <output_dir> [repetitions=10]
# Output: <out>/rep-NN.csv (events found), <out>/resumen.csv (one row per repetition),
# <out>/resumen.txt, <out>/env/procedencia.txt. Exit 1 if any repetition deviates.
# It truncates events/alerts/rejected_events_audit and the stream on every repetition
# (reset_servidor): run it on the lab stack only, never during another battery.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
LAB=/home/ezequiel/fim-lab
OUT=${1:?usage: TAG=<tag> b5b_reconciliacion.sh <output_dir> [repetitions]}
REPS=${2:-10}
COMPOSE_FILES=(docker-compose.yml docker-compose.tls.yml "$LAB/docker-compose.mailpit.yml")
DC=(docker compose)
for f in "${COMPOSE_FILES[@]}"; do DC+=(-f "$f"); done
cd "$REPO" || exit 1
# shellcheck source=lib_arnes.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib_arnes.sh"
procedencia_exigir "${TAG:-}" "$OUT/env" || exit 1
preflight_esquema || exit 1
preflight_rate_limit || exit 1
preflight_aof || exit 1
mkdir -p "$OUT"
multipass transfer "$LAB/vm_reconciliacion.sh" fim-host:/tmp/vm_reconciliacion.sh >/dev/null 2>&1 \
  || { echo "ABORTA: no se pudo transferir vm_reconciliacion.sh" >&2; exit 1; }

echo "rep,modificados_ok,borrados_ok,identicos_con_evento,inesperados,todos_offline,valido" > "$OUT/resumen.csv"
MALAS=0
for i in $(seq 1 "$REPS"); do
  R=$(printf "%02d" "$i")
  reset_servidor || { echo "ABORTA: reset del servidor (rep $R)" >&2; exit 1; }
  if ! SAL=$(multipass exec fim-host -- sudo sh /tmp/vm_reconciliacion.sh 2>&1); then
    echo "rep $R: la preparacion en la VM fallo: $SAL" >&2
    echo "$R,,,,,,no" >> "$OUT/resumen.csv"; MALAS=$((MALAS+1)); continue
  fi
  # Wait (bounded) for the findings: the count must stay unchanged for 10 s.
  prev=-1; est=0
  for _ in $(seq 1 45); do
    n=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM events;" 2>/dev/null | tr -d ' \r')
    [ "$n" = "$prev" ] && est=$((est+1)) || est=0; prev=$n
    [ "$est" -ge 5 ] && [ "${n:-0}" -gt 0 ] && break
    sleep 2
  done
  "${DC[@]}" exec -T db psql -U fim -d fim -c "\copy (SELECT path, event_type, detected_offline FROM events ORDER BY path, detected_at) TO STDOUT WITH CSV HEADER" > "$OUT/rep-$R.csv" 2>/dev/null
  python3 - "$OUT/rep-$R.csv" "$R" >> "$OUT/resumen.csv" <<'PY'
import csv, sys
filas = list(csv.DictReader(open(sys.argv[1])))
tipo = lambda p: [(f["event_type"], f["detected_offline"]) for f in filas if f["path"] == p]
mod = [f"/srv/fim-watch/r{n:02d}" for n in (1, 2, 3, 4)]
bor = [f"/srv/fim-watch/r{n:02d}" for n in (5, 6, 7)]
idn = [f"/srv/fim-watch/r{n:02d}" for n in (8, 9, 10)]
off = lambda v: v in ("t", "true", "True")
mod_ok = sum(1 for p in mod if [t for t, _ in tipo(p)] == ["file_modified"] and all(off(o) for _, o in tipo(p)))
bor_ok = sum(1 for p in bor if [t for t, _ in tipo(p)] == ["file_deleted"] and all(off(o) for _, o in tipo(p)))
idn_ev = sum(len(tipo(p)) for p in idn)
esperadas = set(mod + bor + idn)
inesp = sum(1 for f in filas if f["path"] not in set(mod + bor))
todos_off = all(off(f["detected_offline"]) for f in filas) if filas else False
valido = mod_ok == 4 and bor_ok == 3 and idn_ev == 0 and inesp == 0 and todos_off
print(f"{sys.argv[2]},{mod_ok},{bor_ok},{idn_ev},{inesp},{'si' if todos_off else 'no'},{'si' if valido else 'no'}")
PY
  tail -n 1 "$OUT/resumen.csv" | rg -q ',si$' || MALAS=$((MALAS+1))
  echo "rep $R: $(tail -n 1 "$OUT/resumen.csv")"
done
{
  echo "repeticiones=$REPS conformes=$((REPS-MALAS)) desviadas=$MALAS"
  echo "esperado por repeticion: 4 file_modified + 3 file_deleted (detected_offline=true), 0 para los 3 identicos"
  echo "columnas: rep,modificados_ok,borrados_ok,identicos_con_evento,inesperados,todos_offline,valido"
} | tee "$OUT/resumen.txt"
[ "$MALAS" = "0" ]
