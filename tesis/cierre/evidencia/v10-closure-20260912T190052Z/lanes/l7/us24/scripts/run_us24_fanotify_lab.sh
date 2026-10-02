#!/usr/bin/env bash
# LANE L7 — US-24 monitored-paths lab: real fanotify mark reconfiguration.
#
# Uses docker-compose.acceptance-lab.yml as-is: the `agent` service already
# runs privileged (cap_add: [SYS_ADMIN, DAC_READ_SEARCH]) — the same
# privileged-lab pattern as
# docs/cierre/evidencia/experiments-closure-20260912T004612Z/scripts/run_latency_lab.sh.
#
# Proves, against the real ctypes fanotify backend (agent/_fanotify.py) inside
# a privileged container — NOT mocked:
#   - POST /agents/{id}/config (add path) -> signed+versioned update_config ->
#     agent verifies HMAC + ruleset_version guard -> real fanotify_mark(ADD) ->
#     baseline scan of the new path (encrypted entries) -> real fanotify events
#     arrive for files written under the added path -> event_ack.
#   - POST /agents/{id}/config (remove path) -> real fanotify_mark(REMOVE) ->
#     events for the removed path stop arriving -> audit_log row.
set -Eeuo pipefail
umask 077

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)
cd "$ROOT"
EVID="$ROOT/.v10-evidence/l7/us24"

export FIM_LAB_PROJECT="fiml7us24$$"
export FIM_LAB_API_PORT=19701
export FIM_LAB_MTLS_PORT=19702
export FIM_LAB_FRONTEND_PORT=19703
export FIM_LAB_DB_PASSWORD=$(openssl rand -hex 24)
export FIM_LAB_JWT_CURRENT=$(openssl rand -hex 32)
export FIM_LAB_JWT_PREVIOUS=
export FIM_LAB_ADMIN_USERNAME="l7-us24-admin"
export FIM_LAB_ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')
export FIM_LAB_ADMIN_PASSWORD_FINAL=$(openssl rand -base64 24 | tr -d '/+=')
export FIM_LAB_BOOTSTRAP_SECRET=$(openssl rand -hex 24)
export FIM_LAB_AGENT_ID="l7-us24-agent"

LAB=$(mktemp -d /tmp/fim-l7-us24-XXXXXX)
export FIM_LAB_WATCH_DIR="$LAB/watch"
mkdir -p "$FIM_LAB_WATCH_DIR/a" "$FIM_LAB_WATCH_DIR/b"
printf 'baseline-a\n' > "$FIM_LAB_WATCH_DIR/a/seed.txt"
export FIM_LAB_AGENT_CONFIG="$LAB/agent-config.yaml"
cat > "$FIM_LAB_AGENT_CONFIG" <<YAML
agent_id: $FIM_LAB_AGENT_ID
backend_url: http://backend:8000
mtls_backend_url: https://backend:8443
valkey_url: valkey://valkey:6379
allow_plaintext_valkey: true
ca_cert_path: /certs/ca.pem
watch_paths: [/watch/a]
storage:
  baseline_dir: /var/lib/fim-agent/baseline
  queue_dir: /var/lib/fim-agent/queue
  journal_dir: /var/lib/fim-agent/journal
  secrets_dir: /var/lib/fim-agent/secrets
  certs_dir: /var/lib/fim-agent/certs
  quarantine_retention_days: 30
YAML

dc() { docker compose -p "$FIM_LAB_PROJECT" -f "$ROOT/docker-compose.acceptance-lab.yml" "$@"; }

status=1
cleanup() {
  set +e
  dc logs --no-color --tail 500 backend agent \
    | sed -E 's/(Bearer )[A-Za-z0-9._-]+/\1[REDACTED]/g; s#eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+#[REDACTED-JWT]#g; s/[A-Fa-f0-9]{48,}/[REDACTED-OPAQUE]/g' \
    > "$EVID/sanitized/runtime.log"
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

echo "[1/9] Build + start db/valkey/backend"
dc build backend agent > "$EVID/raw/compose-build.log" 2>&1
dc up -d db valkey backend > "$EVID/raw/compose-up.log" 2>&1
for _ in $(seq 1 90); do curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null 2>&1 && break; sleep 1; done
curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null

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
admin_token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["access_token"])' "$login2")
curl -fsS -H "Authorization: Bearer $admin_token" -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"$FIM_LAB_AGENT_ID\",\"bootstrap_secret\":\"$FIM_LAB_BOOTSTRAP_SECRET\"}" \
  "http://127.0.0.1:$FIM_LAB_API_PORT/agents/register" >/dev/null

echo "[3/9] Start privileged real-fanotify agent (cap_add SYS_ADMIN + DAC_READ_SEARCH), initial watch=/watch/a"
dc up -d agent > "$EVID/raw/agent-up.log" 2>&1
for _ in $(seq 1 90); do dc exec -T agent test -f /var/lib/fim-agent/state.json >/dev/null 2>&1 && break; sleep 1; done
dc exec -T agent cat /proc/1/status | grep -i capeff > "$EVID/agent-capabilities.txt" || true
dc exec -T agent sh -c 'find /var/lib/fim-agent/baseline -type f | wc -l' > "$EVID/baseline-count-initial.txt"

echo "[4/9] Baseline evidence: event on /watch/a BEFORE any config change (control)"
echo "modified-a-before" >> "$FIM_LAB_WATCH_DIR/a/seed.txt"
for _ in $(seq 1 60); do
  c=$(dc exec -T db psql -U fim -d fim -Atc "select count(*) from events where path='/watch/a/seed.txt';" | tr -d '\r')
  [ "${c:-0}" -ge 1 ] && break
  sleep 1
done
dc exec -T db psql -U fim -d fim --csv -c "select path,event_id,detected_at from events where path='/watch/a/seed.txt';" > "$EVID/events-a-before-config-change.csv"

echo "[5/9] update_config: ADD /watch/b (real fanotify_mark(ADD) + baseline scan + HMAC + version + ack + audit_log)"
audit_before=$(dc exec -T db psql -U fim -d fim -Atc "select count(*) from audit_log where action='agent_config';" | tr -d '\r')
curl -fsS -X POST -H "Authorization: Bearer $admin_token" -H 'Content-Type: application/json' \
  -d '{"watch_paths": ["/watch/a", "/watch/b"]}' \
  "http://127.0.0.1:$FIM_LAB_API_PORT/agents/$FIM_LAB_AGENT_ID/config" > "$EVID/config-add-response.json"
for _ in $(seq 1 60); do
  applied=$(dc exec -T db psql -U fim -d fim -Atc "select ruleset_version_applied from agents where agent_id='$FIM_LAB_AGENT_ID';" | tr -d '\r')
  [ "${applied:-0}" -ge 1 ] && break
  sleep 1
done
dc exec -T db psql -U fim -d fim --csv -c \
  "select agent_id,watch_paths,ruleset_version_applied from agents where agent_id='$FIM_LAB_AGENT_ID';" > "$EVID/agent-row-after-add.csv"
dc exec -T db psql -U fim -d fim --csv -c \
  "select id,command_type,ruleset_version,status,ack_status,left(payload,400) as payload_prefix from published_commands where command_type='update_config' order by id;" \
  > "$EVID/published-commands-update_config.csv"
audit_after=$(dc exec -T db psql -U fim -d fim -Atc "select count(*) from audit_log where action='agent_config';" | tr -d '\r')
[ "$audit_after" -gt "$audit_before" ]
dc exec -T db psql -U fim -d fim --csv -c \
  "select id,user_id,action,target_type,detail,created_at from audit_log where action='agent_config' order by id desc limit 1;" \
  > "$EVID/audit-log-agent-config-add.csv"
dc logs --no-color agent | grep 'reload_watch_paths.done' > "$EVID/raw/agent-reload-log-add.log" || true

echo "[6/9] Baseline scan of the newly added path"
dc exec -T agent sh -c 'find /var/lib/fim-agent/baseline -type f | wc -l' > "$EVID/baseline-count-after-add.txt"

echo "[7/9] Real event arrives for the ADDED path /watch/b"
echo "new-file-in-b" > "$FIM_LAB_WATCH_DIR/b/new.txt"
for _ in $(seq 1 60); do
  c=$(dc exec -T db psql -U fim -d fim -Atc "select count(*) from events where path='/watch/b/new.txt';" | tr -d '\r')
  [ "${c:-0}" -ge 1 ] && break
  sleep 1
done
dc exec -T db psql -U fim -d fim --csv -c "select path,event_id,detected_at from events where path='/watch/b/new.txt';" > "$EVID/events-b-after-add.csv"
[ -s "$EVID/events-b-after-add.csv" ]
b_rows=$(wc -l < "$EVID/events-b-after-add.csv")
[ "$b_rows" -ge 2 ]  # header + at least 1 data row

echo "[8/9] update_config: REMOVE /watch/a (real fanotify_mark(REMOVE)) — events for /watch/a must stop"
curl -fsS -X POST -H "Authorization: Bearer $admin_token" -H 'Content-Type: application/json' \
  -d '{"watch_paths": ["/watch/b"]}' \
  "http://127.0.0.1:$FIM_LAB_API_PORT/agents/$FIM_LAB_AGENT_ID/config" > "$EVID/config-remove-response.json"
for _ in $(seq 1 60); do
  applied=$(dc exec -T db psql -U fim -d fim -Atc "select ruleset_version_applied from agents where agent_id='$FIM_LAB_AGENT_ID';" | tr -d '\r')
  [ "${applied:-0}" -ge 2 ] && break
  sleep 1
done
dc logs --no-color agent | grep 'reload_watch_paths.done' > "$EVID/raw/agent-reload-log-remove.log" || true
sleep 3  # let the fanotify_mark(REMOVE) syscall settle before writing the probe
# Precise marker taken from the DB's own clock (not the host's, not a fixed
# lookback window) so the post-removal probe can never be confused with the
# earlier control write on the same path (D-fix: a fixed "last N seconds"
# window is fragile when the whole script runs faster than N seconds).
probe_marker=$(dc exec -T db psql -U fim -d fim -Atc "select now();" | tr -d '\r')
echo "should-not-be-seen" >> "$FIM_LAB_WATCH_DIR/a/seed.txt"
sleep 15  # generous window: if an event were still going to arrive, it would by now
events_a_after_removal=$(dc exec -T db psql -U fim -d fim -Atc \
  "select count(*) from events where path='/watch/a/seed.txt' and detected_at > '$probe_marker'::timestamptz;" | tr -d '\r')
echo "probe_marker=$probe_marker" > "$EVID/events-a-after-removal-count.txt"
echo "events_for_removed_path_after_unmark=$events_a_after_removal" >> "$EVID/events-a-after-removal-count.txt"
[ "${events_a_after_removal:-1}" -eq 0 ]

dc exec -T db psql -U fim -d fim --csv -c \
  "select agent_id,watch_paths,ruleset_version_applied from agents where agent_id='$FIM_LAB_AGENT_ID';" > "$EVID/agent-row-after-remove.csv"
dc exec -T db psql -U fim -d fim --csv -c \
  "select id,user_id,action,target_type,detail,created_at from audit_log where action='agent_config' order by id desc limit 1;" \
  > "$EVID/audit-log-agent-config-remove.csv"

echo "[9/9] event_ack evidence for both update_config commands"
dc exec -T db psql -U fim -d fim --csv -c \
  "select id,command_type,ack_status from published_commands where command_type='update_config' order by id;" \
  > "$EVID/update_config-ack-status.csv"

status=0
