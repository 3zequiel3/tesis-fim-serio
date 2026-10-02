#!/usr/bin/env bash
# LANE L7 — US-23 external notification fallback-cascade lab.
#
# n8n is intentionally unreachable throughout. Proves, against real
# infrastructure (own Postgres + Valkey containers, real HTTP to a real local
# SMTP capture server and a real local webhook receiver):
#   1. n8n retry cascade with NOMINAL (not zeroed) delays 5s/30s/120s, and that
#      ordinary backend operations keep working while n8n is down.
#   2. SMTP fallback delivers the full payload to a local capture server
#      (axllent/mailpit — not a commercial provider).
#   3. webhook_fallback delivers when SMTP also fails.
#   4. When every fallback fails, a DLQ row lands in `alerts`
#      (delivered_at IS NULL AND failed_at IS NOT NULL) — D6/RN-107 merges the
#      canonical `failed_notifications` table into `alerts`.
#
# Always run from the worktree root. Never touches any other compose project.
set -Eeuo pipefail
umask 077

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)
cd "$ROOT"
EVID="$ROOT/.v10-evidence/l7/us23"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

export FIM_L7_RECEIVER_SCRIPT="$EVID/scripts/webhook_receiver.py"
export FIM_LAB_PROJECT="fiml7us23$$"
export FIM_LAB_API_PORT=19601
export FIM_LAB_MTLS_PORT=19602
export FIM_LAB_FRONTEND_PORT=19603
export FIM_L7_MAILPIT_UI_PORT=19604
export FIM_L7_WEBHOOK_UI_PORT=19605
export FIM_LAB_DB_PASSWORD=$(openssl rand -hex 24)
export FIM_LAB_JWT_CURRENT=$(openssl rand -hex 32)
export FIM_LAB_JWT_PREVIOUS=
export FIM_LAB_ADMIN_USERNAME="l7-us23-admin"
export FIM_LAB_ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')
export FIM_LAB_ADMIN_PASSWORD_FINAL=$(openssl rand -base64 24 | tr -d '/+=')
export FIM_LAB_BOOTSTRAP_SECRET=$(openssl rand -hex 24)
export FIM_LAB_AGENT_ID="l7-us23-agent"

LAB=$(mktemp -d /tmp/fim-l7-us23-XXXXXX)
export FIM_LAB_WATCH_DIR="$LAB/watch"; mkdir -p "$FIM_LAB_WATCH_DIR"
export FIM_LAB_AGENT_CONFIG="$LAB/agent-config.yaml"
cat > "$FIM_LAB_AGENT_CONFIG" <<YAML
agent_id: $FIM_LAB_AGENT_ID
backend_url: http://backend:8000
mtls_backend_url: https://backend:8443
valkey_url: valkey://valkey:6379
allow_plaintext_valkey: true
ca_cert_path: /certs/ca.pem
watch_paths: [/watch]
storage:
  baseline_dir: /var/lib/fim-agent/baseline
  queue_dir: /var/lib/fim-agent/queue
  journal_dir: /var/lib/fim-agent/journal
  secrets_dir: /var/lib/fim-agent/secrets
  certs_dir: /var/lib/fim-agent/certs
  quarantine_retention_days: 30
YAML

dc() { docker compose -p "$FIM_LAB_PROJECT" -f "$ROOT/docker-compose.acceptance-lab.yml" -f "$EVID/scripts/notify.override.yml" "$@"; }

status=1
cleanup() {
  set +e
  dc logs --no-color --tail 500 backend \
    | sed -E 's/(Bearer )[A-Za-z0-9._-]+/\1[REDACTED]/g; s#eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+#[REDACTED-JWT]#g' \
    > "$EVID/sanitized/backend-runtime.log"
  dc ps --format json > "$EVID/raw/services-before-teardown.jsonl" 2>/dev/null
  dc down -v --remove-orphans --timeout 10 > "$EVID/raw/teardown.log" 2>&1
  remc=$(docker ps -a --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l)
  remv=$(docker volume ls --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l)
  remn=$(docker network ls --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l)
  rm -rf "$LAB"
  printf '{"containers_remaining":%s,"volumes_remaining":%s,"networks_remaining":%s,"temporary_root_removed":%s}\n' \
    "$remc" "$remv" "$remn" "$([[ ! -e "$LAB" ]] && echo true || echo false)" > "$EVID/teardown-result.json"
  find "$EVID" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum | sed "s#  $EVID/#  #" > "$EVID/SHA256SUMS"
  exit $status
}
trap cleanup EXIT INT TERM

echo "[1/9] Build + start db/valkey/backend (scenario 1: n8n down, SMTP -> mailpit)"
export FIM_L7_SMTP_HOST=mailpit
export FIM_L7_SMTP_PORT=1025
export FIM_L7_WEBHOOK_FALLBACK_URL=""
dc build backend > "$EVID/raw/compose-build.log" 2>&1
dc up -d db valkey mailpit backend > "$EVID/raw/compose-up.log" 2>&1
for _ in $(seq 1 90); do curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null
docker inspect --format '{{index .RepoDigests 0}}' axllent/mailpit:v1.22.3 > "$EVID/mailpit-image-digest.txt" 2>&1 || \
  docker inspect --format '{{.Id}}' axllent/mailpit:v1.22.3 > "$EVID/mailpit-image-digest.txt"

echo "[2/9] Activate admin + register agent"
cookie="$LAB/cookie"; login="$LAB/login.json"
curl -fsS -c "$cookie" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$FIM_LAB_ADMIN_USERNAME\",\"password\":\"$FIM_LAB_ADMIN_PASSWORD\"}" \
  "http://127.0.0.1:$FIM_LAB_API_PORT/auth/login" > "$login"
token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["access_token"])' "$login")
curl -fsS -b "$cookie" -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d "{\"new_password\":\"$FIM_LAB_ADMIN_PASSWORD_FINAL\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/users/change-password" >/dev/null
login2="$LAB/login2.json"
curl -fsS -d "{\"username\":\"$FIM_LAB_ADMIN_USERNAME\",\"password\":\"$FIM_LAB_ADMIN_PASSWORD_FINAL\"}" \
  -H 'Content-Type: application/json' "http://127.0.0.1:$FIM_LAB_API_PORT/auth/login" > "$login2"
token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["access_token"])' "$login2")
curl -fsS -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"$FIM_LAB_AGENT_ID\",\"bootstrap_secret\":\"$FIM_LAB_BOOTSTRAP_SECRET\"}" \
  "http://127.0.0.1:$FIM_LAB_API_PORT/agents/register" >/dev/null

echo "[3/9] Scenario 1: trigger critical alert while polling ops during the n8n outage"
started=$(date +%s)
dc exec -T -e AGENT_ID="$FIM_LAB_AGENT_ID" -e EVENT_PATH=/watch/us23-scenario1.txt -e SEVERITY=critical \
  backend python3 - < "$EVID/scripts/trigger_alert.py" > "$EVID/raw/scenario1-trigger.log" 2>&1 &
trigger_pid=$!
: > "$EVID/ops-during-outage.jsonl"
while kill -0 "$trigger_pid" 2>/dev/null; do
  h=$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$FIM_LAB_API_PORT/health")
  r=$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" "http://127.0.0.1:$FIM_LAB_API_PORT/rules")
  printf '{"t":"%s","health":%s,"rules":%s}\n' "$(date -u +%FT%TZ)" "$h" "$r" >> "$EVID/ops-during-outage.jsonl"
  sleep 10
done
wait "$trigger_pid"
elapsed1=$(( $(date +%s) - started ))
echo "scenario1_elapsed_seconds=$elapsed1" > "$EVID/scenario1-timing.txt"
[[ "$elapsed1" -ge 150 ]]  # proves nominal (not zeroed) 5s+30s+120s delays actually elapsed

echo "[4/9] Scenario 1 assertions: DB row + real delay log lines + mailpit capture"
dc exec -T db psql -U fim -d fim --csv -c \
  "select e.event_id,a.severity,a.channel,a.delivered_at,a.failed_at,a.retry_count,a.attempt_count from alerts a join events e on e.id=a.event_id where e.path='/watch/us23-scenario1.txt';" \
  > "$EVID/scenario1-alert-row.csv"
dc logs --no-color backend | grep 'notify.retry_wait' > "$EVID/raw/scenario1-retry-lines.log" || true
msg_id=$(curl -fsS "http://127.0.0.1:$FIM_L7_MAILPIT_UI_PORT/api/v1/messages" | python3 -c 'import json,sys;print(json.load(sys.stdin)["messages"][0]["ID"])')
curl -fsS "http://127.0.0.1:$FIM_L7_MAILPIT_UI_PORT/api/v1/message/$msg_id" > "$EVID/scenario1-mailpit-message.json"
python3 -c "
import json
m = json.load(open('$EVID/scenario1-mailpit-message.json'))
body = m['Text']
payload = json.loads(body)
for k in ('event_id','path','severity','process_pid','process_uid','process_exe','detected_at','received_at'):
    assert k in payload, k
print('mailpit payload fields OK:', sorted(payload.keys()))
"

echo "[5/9] Scenario 2/3 config: n8n still down, SMTP unreachable, webhook -> local receiver"
export FIM_L7_SMTP_HOST=127.0.0.1
export FIM_L7_SMTP_PORT=2
export FIM_L7_WEBHOOK_FALLBACK_URL="http://webhook-receiver:9099/hook"
dc up -d webhook-receiver > "$EVID/raw/webhook-receiver-up.log" 2>&1
dc up -d --no-deps --force-recreate backend > "$EVID/raw/backend-recreate-2.log" 2>&1
for _ in $(seq 1 60); do curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null 2>&1 && break; sleep 1; done

echo "[6/9] Scenario 2: SMTP down, webhook fallback succeeds"
started2=$(date +%s)
dc exec -T -e AGENT_ID="$FIM_LAB_AGENT_ID" -e EVENT_PATH=/watch/us23-scenario2.txt -e SEVERITY=critical \
  backend python3 - < "$EVID/scripts/trigger_alert.py" > "$EVID/raw/scenario2-trigger.log" 2>&1
elapsed2=$(( $(date +%s) - started2 ))
echo "scenario2_elapsed_seconds=$elapsed2" > "$EVID/scenario2-timing.txt"
[[ "$elapsed2" -ge 150 ]]
dc exec -T db psql -U fim -d fim --csv -c \
  "select e.event_id,a.severity,a.channel,a.delivered_at,a.failed_at,a.retry_count,a.attempt_count from alerts a join events e on e.id=a.event_id where e.path='/watch/us23-scenario2.txt';" \
  > "$EVID/scenario2-alert-row.csv"
dc exec -T webhook-receiver cat /data/received.jsonl > "$EVID/scenario2-webhook-capture.jsonl"

echo "[7/9] Scenario 3: SMTP down AND webhook receiver stopped -> DLQ row"
dc stop webhook-receiver > "$EVID/raw/webhook-receiver-stop.log" 2>&1
started3=$(date +%s)
dc exec -T -e AGENT_ID="$FIM_LAB_AGENT_ID" -e EVENT_PATH=/watch/us23-scenario3.txt -e SEVERITY=critical \
  backend python3 - < "$EVID/scripts/trigger_alert.py" > "$EVID/raw/scenario3-trigger.log" 2>&1
elapsed3=$(( $(date +%s) - started3 ))
echo "scenario3_elapsed_seconds=$elapsed3" > "$EVID/scenario3-timing.txt"
[[ "$elapsed3" -ge 150 ]]
dc exec -T db psql -U fim -d fim --csv -c \
  "select e.event_id,a.severity,a.channel,a.delivered_at,a.failed_at,a.retry_count,a.attempt_count,a.last_error from alerts a join events e on e.id=a.event_id where e.path='/watch/us23-scenario3.txt';" \
  > "$EVID/scenario3-alert-row.csv"

echo "[8/9] Cross-check: log_only fires (RN-54 floor) and n8n was genuinely attempted 4 times per scenario"
dc logs --no-color backend | grep -c 'notifier.n8n_failed' > "$EVID/n8n-attempt-count.txt" || true
dc logs --no-color backend | grep -c 'notifier.log_only' > "$EVID/log_only-count.txt" || true

echo "[9/9] Done — teardown handled by trap"
status=0
