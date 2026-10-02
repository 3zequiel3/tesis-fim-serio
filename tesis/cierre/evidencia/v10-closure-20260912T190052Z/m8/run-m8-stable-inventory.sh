#!/usr/bin/env bash
# M-8 re-run: execute the unmodified US-02/20/31 lab while recording raw external inventories.
# The lab script keeps its own main_stack_unchanged (ID:Names:Status); this wrapper adds a
# stable inventory (ID:Names:Image) plus StartedAt/RestartCount so any difference can be classified.
set -Euo pipefail
ROOT=/home/ezequiel/Facultad/tesis/tesis-fim-serio
OUT="$ROOT/docs/cierre/evidencia/v10-closure-20260912T190052Z/m8"
STAMP=v10m8$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$OUT"
inventory() {
  local tag=$1
  docker ps --filter label=com.docker.compose.project=tesis-fim-serio --format '{{.ID}}:{{.Names}}:{{.Status}}' | sort > "$OUT/main-status-$tag.txt"
  docker ps --filter label=com.docker.compose.project=tesis-fim-serio --format '{{.ID}}:{{.Names}}:{{.Image}}' | sort > "$OUT/main-stable-$tag.txt"
  docker ps -q --filter label=com.docker.compose.project=tesis-fim-serio | xargs -r docker inspect \
    --format '{{.Id}} {{.Name}} started={{.State.StartedAt}} restarts={{.RestartCount}}' | sort > "$OUT/main-started-$tag.txt"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/inventory-$tag.utc"
}
inventory before
printf 'lab_run_id=%s\n' "$STAMP" > "$OUT/run.env"
FIM_LAB_RUN_ID="$STAMP" "$ROOT/scripts/run-us02-us20-us31-acceptance-lab.sh" > "$OUT/lab.stdout.log" 2> "$OUT/lab.stderr.log"
echo $? > "$OUT/lab-exit-code.txt"
inventory after
cmp -s "$OUT/main-status-before.txt" "$OUT/main-status-after.txt" && s1=true || s1=false
cmp -s "$OUT/main-stable-before.txt" "$OUT/main-stable-after.txt" && s2=true || s2=false
cmp -s "$OUT/main-started-before.txt" "$OUT/main-started-after.txt" && s3=true || s3=false
printf '{"lab_run_id":"%s","status_inventory_unchanged":%s,"stable_id_name_image_unchanged":%s,"started_at_restart_count_unchanged":%s}\n' \
  "$STAMP" "$s1" "$s2" "$s3" > "$OUT/inventory-comparison.json"
diff "$OUT/main-status-before.txt" "$OUT/main-status-after.txt" > "$OUT/main-status.diff" || true
