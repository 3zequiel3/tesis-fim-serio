#!/usr/bin/env bash
# B-3: notification export and notify_max_concurrent_deliveries sweep.
#
#   TAG=<tag> bash exportar_notif.sh export <out.csv>
#       Export the alerts currently in the database with BOTH intervals:
#       ms_aceptacion (channel_accepted_at - received_at, D77/RN-171) and
#       ms_entrega (delivered_at - received_at). Read-only.
#
#   TAG=<tag> bash exportar_notif.sh barrido <out_dir> [N1 N2 ...]
#       Sweep of notify_max_concurrent_deliveries (default 8 16 32 64; D76/RN-170).
#       For each value: recreate the backend with that limit (compose override written
#       into <out_dir>, since docker-compose.yml does not forward the variable), publish
#       100 events at concurrency 100 with lab/bateria4_publicador.py, wait for the chain
#       to settle and export the CSV + a pandas summary. The default (32) backend is
#       restored at the end. NEVER run this during a Valkey cut (it recreates the backend).
#       The sweep clears alerts/events/Mailpit before each value.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
LAB=/home/ezequiel/fim-lab
COMPOSE_FILES=(docker-compose.yml docker-compose.tls.yml "$LAB/docker-compose.mailpit.yml")
DC_BASE=(docker compose)
for f in "${COMPOSE_FILES[@]}"; do DC_BASE+=(-f "$f"); done
DC=("${DC_BASE[@]}")
cd "$REPO" || exit 1
# shellcheck source=lib_arnes.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib_arnes.sh"

modo=${1:?usage: TAG=<tag> exportar_notif.sh export <out.csv> | barrido <out_dir> [N...]}
shift

esperar_consumo() {  # $1 since
  for _ in $(seq 1 60); do
    "${DC[@]}" logs --since "$1" backend 2>/dev/null | rg -q 'consumer\.started' && return 0
    sleep 2
  done
  return 1
}

case "$modo" in
  export)
    salida=${1:?usage: export <out.csv>}
    exportar_notif_csv > "$salida"
    echo "rows=$(( $(wc -l < "$salida") - 1 )) -> $salida"
    ;;
  barrido)
    out=${1:?usage: barrido <out_dir> [N...]}; shift
    valores=("$@"); [ "${#valores[@]}" -gt 0 ] || valores=(8 16 32 64)
    N_NOTIF=100
    procedencia_exigir "${TAG:-}" "$out/env" || exit 1
    preflight_esquema && preflight_sumidero && preflight_rate_limit || exit 1
    for n in "${valores[@]}"; do
      ov="$out/override_notify_$n.yml"
      printf 'services:\n  backend:\n    environment:\n      NOTIFY_MAX_CONCURRENT_DELIVERIES: "%s"\n' "$n" > "$ov"
      DC=("${DC_BASE[@]}" -f "$ov")
      since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      "${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
      esperar_consumo "$since" || { echo "ABORTA: el backend no volvio a consumir (N=$n)" >&2; exit 1; }
      efectivo=$("${DC[@]}" exec -T backend printenv NOTIFY_MAX_CONCURRENT_DELIVERIES 2>/dev/null | tr -d '\r')
      [ "$efectivo" = "$n" ] || { echo "ABORTA: el backend tiene NOTIFY_MAX_CONCURRENT_DELIVERIES='$efectivo', no $n" >&2; exit 1; }
      "${DC[@]}" exec -T db psql -U fim -d fim -tAc "DELETE FROM alerts; DELETE FROM events;" >/dev/null 2>&1
      curl -s -X DELETE http://127.0.0.1:8025/api/v1/messages >/dev/null 2>&1
      "${DC[@]}" cp "$LAB/bateria4_publicador.py" backend:/tmp/b4.py >/dev/null 2>&1
      "${DC[@]}" exec -T backend sh -c "cd /app && PYTHONPATH=/app python /tmp/b4.py barrido_$n $N_NOTIF $N_NOTIF" > "$out/publicador_$n.log" 2>&1
      prev=-1; est=0
      for _ in $(seq 1 120); do
        c=$("${DC[@]}" exec -T db psql -U fim -d fim -tAc "SELECT count(*) FROM alerts WHERE delivered_at IS NOT NULL;" | tr -d ' \r')
        [ "$c" = "$prev" ] && est=$((est+1)) || est=0; prev=$c
        [ "$est" -ge 5 ] && break; sleep 5
      done
      exportar_notif_csv > "$out/notif_max_$n.csv"
      echo "N=$n muestras=$(( $(wc -l < "$out/notif_max_$n.csv") - 1 )) de $N_NOTIF"
    done
    python3 - "$out" "${valores[@]}" <<'PY' | tee "$out/resumen.txt"
import sys, pathlib, pandas as pd
d = pathlib.Path(sys.argv[1])
for n in sys.argv[2:]:
    f = d / f"notif_max_{n}.csv"
    if not f.exists() or f.stat().st_size < 20:
        print(f"max={n}: sin muestras"); continue
    t = pd.read_csv(f)
    for col in ("ms_aceptacion", "ms_entrega"):
        s = t[col].dropna()
        print(f"max={n:>3s} {col:13s} n={len(s):4d} media={s.mean():9.3f} p50={s.quantile(.50):9.3f} p95={s.quantile(.95):9.3f} p99={s.quantile(.99):9.3f} max={s.max():9.3f}")
PY
    # Restore the default backend (no override).
    DC=("${DC_BASE[@]}")
    since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    "${DC[@]}" --profile app up -d --force-recreate backend >/dev/null 2>&1
    esperar_consumo "$since" && echo "backend restaurado al limite por defecto" \
      || echo "ATENCION: el backend restaurado no reanudo el consumo" >&2
    ;;
  *) echo "modo desconocido: $modo" >&2; exit 2 ;;
esac
