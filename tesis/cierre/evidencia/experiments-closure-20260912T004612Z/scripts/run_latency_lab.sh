#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ROOT=${ROOT:?}; SNAP=${SNAP:?}; EVID=${EVID:?}; ABS_EVID="$ROOT/$EVID"
STAMP=$(basename "$EVID" | tr -cd '[:alnum:]' | tr A-Z a-z)
export FIM_LAB_PROJECT="fimlat${STAMP:0:36}"
export FIM_LAB_API_PORT=19421 FIM_LAB_MTLS_PORT=19821 FIM_LAB_FRONTEND_PORT=19481
export FIM_LAB_DB_PASSWORD=$(openssl rand -hex 24); export FIM_LAB_JWT_CURRENT=$(openssl rand -hex 32); export FIM_LAB_JWT_PREVIOUS=
export FIM_LAB_ADMIN_USERNAME="latency-admin"; export FIM_LAB_ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -d '/+='); export FIM_LAB_ADMIN_PASSWORD_FINAL=$(openssl rand -base64 24 | tr -d '/+=')
export FIM_LAB_BOOTSTRAP_SECRET=$(openssl rand -hex 24); export FIM_LAB_AGENT_ID="latency-agent"
LAB=$(mktemp -d /tmp/fim-latency-lab-XXXXXX); export FIM_LAB_WATCH_DIR="$LAB/watch" FIM_LAB_AGENT_CONFIG="$LAB/agent-config.yaml"
export FIM_EXPERIMENT_RUN_ID="$STAMP" FIM_EXPERIMENT_EVIDENCE_DIR="$ABS_EVID"
mkdir -p "$FIM_LAB_WATCH_DIR"; for i in $(seq 0 99); do printf -v j '%03d' "$i"; printf 'baseline-%s\n' "$j" > "$FIM_LAB_WATCH_DIR/latency-ext-$j.txt"; done
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
dc(){ docker compose -p "$FIM_LAB_PROJECT" -f "$SNAP/docker-compose.acceptance-lab.yml" -f "$ABS_EVID/scripts/latency.override.yml" "$@"; }
status=1
cleanup(){ set +e; dc exec -T agent chmod 644 /evidence/latency/agent-trace.jsonl >/dev/null 2>&1; dc ps --format json > "$ABS_EVID/raw/latency-services-before-teardown.jsonl" 2>/dev/null; dc logs --no-color --tail 300 backend agent > "$ABS_EVID/raw/latency-runtime.log" 2>&1; dc down -v --remove-orphans --timeout 10 > "$ABS_EVID/raw/latency-teardown.log" 2>&1; remc=$(docker ps -a --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l); remv=$(docker volume ls --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l); remn=$(docker network ls --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l); rm -rf "$LAB"; printf '{"containers_remaining":%s,"volumes_remaining":%s,"networks_remaining":%s,"temporary_root_removed":%s}\n' "$remc" "$remv" "$remn" "$([[ ! -e "$LAB" ]] && echo true || echo false)" > "$ABS_EVID/latency/teardown-result.json"; exit $status; }
trap cleanup EXIT INT TERM
printf 'project=%s\ntopology=single physical host; isolated Compose network, volumes and containers\napi_port=%s\nmtls_port=%s\nplanned=100\nrate_operations_s=10\nstart_observer=strace -ttt -T -yy close(2) completion\nend_observer=PostgreSQL events.received_at\n' "$FIM_LAB_PROJECT" "$FIM_LAB_API_PORT" "$FIM_LAB_MTLS_PORT" > "$ABS_EVID/latency/conditions.txt"
dc build backend agent > "$ABS_EVID/raw/latency-compose-build.log" 2>&1
dc up -d db valkey backend > "$ABS_EVID/raw/latency-compose-up.log" 2>&1
for _ in $(seq 1 90); do curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null && break; sleep 1; done
curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null
cookie="$LAB/cookie"; login="$LAB/login.json"
curl -fsS -c "$cookie" -H 'Content-Type: application/json' -d "{\"username\":\"$FIM_LAB_ADMIN_USERNAME\",\"password\":\"$FIM_LAB_ADMIN_PASSWORD\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/auth/login" > "$login"
token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["access_token"])' "$login")
curl -fsS -b "$cookie" -H "Authorization: Bearer $token" -H 'Content-Type: application/json' -d "{\"new_password\":\"$FIM_LAB_ADMIN_PASSWORD_FINAL\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/users/change-password" >/dev/null
login2="$LAB/login2.json"; curl -fsS -H 'Content-Type: application/json' -d "{\"username\":\"$FIM_LAB_ADMIN_USERNAME\",\"password\":\"$FIM_LAB_ADMIN_PASSWORD_FINAL\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/auth/login" > "$login2"; token=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["access_token"])' "$login2")
curl -fsS -H "Authorization: Bearer $token" -H 'Content-Type: application/json' -d "{\"agent_id\":\"$FIM_LAB_AGENT_ID\",\"bootstrap_secret\":\"$FIM_LAB_BOOTSTRAP_SECRET\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/agents/register" >/dev/null
dc up -d agent > "$ABS_EVID/raw/latency-agent-up.log" 2>&1
for _ in $(seq 1 120); do c=$(dc exec -T agent sh -c 'find /var/lib/fim-agent/baseline -type f -name "*.bin" 2>/dev/null | wc -l' 2>/dev/null | tr -d '\r'); [ "${c:-0}" -ge 100 ] && break; sleep 1; done
c=$(dc exec -T agent sh -c 'find /var/lib/fim-agent/baseline -type f -name "*.bin" | wc -l' | tr -d '\r'); printf 'baseline_files_before=%s\n' "$c" >> "$ABS_EVID/latency/conditions.txt"; [ "$c" -ge 100 ]
strace -ttt -T -yy -e trace=openat,write,fsync,close -o "$ABS_EVID/latency/generator.strace" python3 "$ABS_EVID/scripts/latency_generator.py" --dir "$FIM_LAB_WATCH_DIR" --count 100 --rate 10 --manifest "$ABS_EVID/latency/generator-manifest.jsonl" > "$ABS_EVID/raw/latency-generator.stdout.log" 2> "$ABS_EVID/raw/latency-generator.stderr.log"
for _ in $(seq 1 120); do c=$(dc exec -T db psql -U fim -d fim -Atc "select count(*) from events where path like '/watch/latency-ext-%';" | tr -d '\r'); [ "${c:-0}" -ge 100 ] && break; sleep 1; done
dc exec -T db psql -U fim -d fim --csv -c "select path,event_id,detected_at,received_at,hash_detected,status,severity from events where path like '/watch/latency-ext-%' order by path,received_at;" > "$ABS_EVID/latency/backend-events.csv"
python3 "$ABS_EVID/scripts/analyze_external_latency.py" "$ABS_EVID/latency/generator.strace" "$ABS_EVID/latency/backend-events.csv" "$ABS_EVID/latency" > "$ABS_EVID/raw/latency-analysis.stdout.log"
printf 'finished_at_utc=%s\n' "$(date -u +%FT%TZ)" >> "$ABS_EVID/latency/conditions.txt"
status=0
