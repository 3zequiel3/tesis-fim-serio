#!/usr/bin/env bash
# Siembra las reglas de severidad del laboratorio — precondición P6 del Cap. 5.
#
# POR QUÉ
#   Solo los eventos de severidad `critical` y `high` generan una fila `Alert`
#   (RN-52, backend/app/modules/alerts/service.py). Sin reglas que hagan
#   `high`/`critical` a lo que pasa en el directorio vigilado, la Batería 4
#   (ítems 11-22, tiempos de notificación) mide exactamente CERO.
#
# QUÉ ÍTEMS DEL CAP. 5 DESBLOQUEA
#   11-22  — Tabla 12, tiempo de notificación (los tres escenarios).
#   Indirectamente 23, en cuanto a evidencia de la cascada de notificación.
#
# QUÉ HACE
#   Crea (o actualiza, si ya existen) dos reglas vía la API REST — el mismo
#   camino que usa la UI, de modo que también se dispara el `rule_sync` hacia el
#   agente (H6/D9) y el laboratorio queda consistente:
#
#     1)  <WATCH_PREFIX>/*                     severidad high      accion alert_only
#     2)  <WATCH_PREFIX>/<CRITICAL_SUBDIR>/*   severidad critical  accion alert_only
#
#   El match es `fnmatch` sobre `event.path` (rules/service.py::determine_severity_for_path)
#   y `*` cruza barras, así que `/watch/*` cubre también los subdirectorios.
#   Gana la severidad más alta entre las reglas que matchean, por eso la regla 2
#   convive con la 1 sin conflicto.
#
# POR QUÉ `alert_only` Y NO `auto_restore` / `quarantine`
#   La acción es ortogonal a la severidad (RN-52 mira solo la severidad). Con
#   `auto_restore` o `quarantine` el agente reescribiría o movería los archivos
#   durante la corrida: inyectaría cambios que no están en el manifiesto del
#   generador y arruinaría los ítems 9, 45, 47 y 49. Para medir, `alert_only`.
#   Si se quiere ejercitar la acción automática, hacerlo en una corrida aparte
#   y declararla como tal (ACTION=auto_restore).
#
# USO
#   Correr DESPUÉS de entrar al frontend con admin/admin y cambiar la contraseña
#   (mismo prerrequisito que scripts/setup-agent.sh):
#
#     scripts/seed-reglas-lab.sh <password_actual_del_admin>
#
#   Variables de entorno (todas opcionales):
#     API=http://localhost:8000     endpoint del backend
#     ADMIN_USER=admin              usuario administrador
#     WATCH_PREFIX=/watch           prefijo con el que el agente ve el dir vigilado
#     CRITICAL_SUBDIR=critico       subdirectorio que se marca como critical
#     SEVERITY=high                 severidad de la regla base
#     ACTION=alert_only             accion de ambas reglas
#     DRY_RUN=1                     imprime lo que haria y no toca nada
#
#   Verificación:  curl -s -H "Authorization: Bearer <token>" $API/rules | python3 -m json.tool
#
# NOTAS
#   No requiere root. Solo curl + python3 (igual que scripts/setup-agent.sh).
#   Es idempotente: si el patrón ya existe, actualiza la regla en vez de duplicarla.
set -euo pipefail

API="${API:-http://localhost:8000}"
ADMIN_USER="${ADMIN_USER:-admin}"
PASS="${1:?Uso: scripts/seed-reglas-lab.sh <password_actual_del_admin>}"
WATCH_PREFIX="${WATCH_PREFIX:-/watch}"
CRITICAL_SUBDIR="${CRITICAL_SUBDIR:-critico}"
SEVERITY="${SEVERITY:-high}"
ACTION="${ACTION:-alert_only}"
DRY_RUN="${DRY_RUN:-0}"

WATCH_PREFIX="${WATCH_PREFIX%/}"
PATRON_BASE="${WATCH_PREFIX}/*"
PATRON_CRITICO="${WATCH_PREFIX}/${CRITICAL_SUBDIR}/*"

echo "Reglas a sembrar (P6):"
echo "  1) ${PATRON_BASE}  -> ${SEVERITY} / ${ACTION}"
echo "  2) ${PATRON_CRITICO}  -> critical / ${ACTION}"
echo ""

if [ "$DRY_RUN" = "1" ]; then
  echo "DRY_RUN=1: no se llamó a la API."
  exit 0
fi

echo "1) Login como '$ADMIN_USER' en $API ..."
TOKEN=$(curl -fsS -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$PASS\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

echo "2) Leyendo reglas existentes ..."
REGLAS=$(curl -fsS "$API/rules" -H "Authorization: Bearer $TOKEN")

# Devuelve el id de la regla con ese patrón, o vacío si no existe.
buscar_id() {
  printf '%s' "$REGLAS" | python3 -c '
import sys, json
patron = sys.argv[1]
for r in json.load(sys.stdin):
    if r["pattern"] == patron:
        print(r["id"])
        break
' "$1"
}

sembrar() {
  local patron="$1" severidad="$2" accion="$3"
  local id body
  id=$(buscar_id "$patron")
  body=$(python3 -c '
import sys, json
print(json.dumps({"pattern": sys.argv[1], "severity": sys.argv[2], "action": sys.argv[3]}))
' "$patron" "$severidad" "$accion")

  if [ -n "$id" ]; then
    echo "   actualizando regla id=$id  '$patron' -> $severidad / $accion"
    curl -fsS -X PUT "$API/rules/$id" \
      -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' \
      -d "$body" > /dev/null
  else
    echo "   creando regla       '$patron' -> $severidad / $accion"
    curl -fsS -X POST "$API/rules" \
      -H "Authorization: Bearer $TOKEN" \
      -H 'Content-Type: application/json' \
      -d "$body" > /dev/null
  fi
}

echo "3) Sembrando ..."
sembrar "$PATRON_BASE" "$SEVERITY" "$ACTION"
sembrar "$PATRON_CRITICO" "critical" "$ACTION"

echo ""
echo "4) Reglas vigentes:"
curl -fsS "$API/rules" -H "Authorization: Bearer $TOKEN" \
  | python3 -c '
import sys, json
for r in json.load(sys.stdin):
    print("   id={:<4} {:<9} {:<14} {}".format(
        r["id"], r["severity"], r["action"], r["pattern"]))
'

echo ""
echo "Listo. La Batería 4 ya tiene con qué generar Alerts (RN-52)."
echo "Para poblar el subdirectorio critical, corré el generador con:"
echo "  --critical-subdir ${CRITICAL_SUBDIR} --critical-frac 0.2"
