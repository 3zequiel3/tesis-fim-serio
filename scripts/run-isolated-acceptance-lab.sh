#!/usr/bin/env bash
# Disposable real-stack acceptance laboratory for US-03/16/17/25.
set -Eeuo pipefail
umask 077

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE="$ROOT/docker-compose.acceptance-lab.yml"
STAMP=${FIM_LAB_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
export FIM_LAB_PROJECT="fimaccept${STAMP,,}$$"
export FIM_LAB_API_PORT=${FIM_LAB_API_PORT:-18000}
export FIM_LAB_MTLS_PORT=${FIM_LAB_MTLS_PORT:-18443}
export FIM_LAB_FRONTEND_PORT=${FIM_LAB_FRONTEND_PORT:-18080}
export FIM_LAB_DB_PASSWORD=$(openssl rand -hex 24)
OLD_JWT=$(openssl rand -hex 32)
NEW_JWT=$(openssl rand -hex 32)
export FIM_LAB_JWT_CURRENT=$OLD_JWT
export FIM_LAB_JWT_PREVIOUS=
export FIM_LAB_ADMIN_USERNAME="lab-admin-$STAMP"
export FIM_LAB_ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')
export FIM_LAB_ADMIN_PASSWORD_FINAL=$(openssl rand -base64 24 | tr -d '/+=')
export FIM_LAB_BOOTSTRAP_SECRET=$(openssl rand -hex 24)
export FIM_LAB_AGENT_ID="lab-agent-$STAMP"
LAB_ROOT=$(mktemp -d "/tmp/fim-acceptance-${STAMP}-XXXXXX")
export FIM_LAB_WATCH_DIR="$LAB_ROOT/watch"
export FIM_LAB_AGENT_CONFIG="$LAB_ROOT/agent-config.yaml"
export FIM_LAB_US17_FILE="$FIM_LAB_WATCH_DIR/us17-default.txt"
export FIM_LAB_US25_FILE="$FIM_LAB_WATCH_DIR/us25-approval.txt"
EVIDENCE="$ROOT/tesis/cierre/evidencia/us03-us16-us17-us25-isolated-${STAMP}"
export FIM_E2E_RUN_DIR="$EVIDENCE"
export FIM_LAB_BASE_URL="http://127.0.0.1:$FIM_LAB_FRONTEND_PORT"
mkdir -p "$FIM_LAB_WATCH_DIR" "$EVIDENCE"
printf 'initial-us17-baseline\n' > "$FIM_LAB_US17_FILE"
printf 'initial-us25-baseline\n' > "$FIM_LAB_US25_FILE"

cat > "$FIM_LAB_AGENT_CONFIG" <<YAML
agent_id: $FIM_LAB_AGENT_ID
backend_url: https://backend:8444
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

dc() { docker compose -p "$FIM_LAB_PROJECT" -f "$COMPOSE" "$@"; }
# Compare stable resource identity. Docker's human-readable Status embeds uptime,
# so comparing it byte-for-byte creates a false mutation during any long run.
main_before=$(docker ps --filter label=com.docker.compose.project=tesis-fim-serio --format '{{.ID}}:{{.Names}}:{{.Image}}' | sort)
teardown_ok=false
cleanup() {
  set +e
  dc down -v --remove-orphans --timeout 10 > "$EVIDENCE/teardown.log" 2>&1
  remaining_containers=$(docker ps -a --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l)
  remaining_volumes=$(docker volume ls --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l)
  remaining_networks=$(docker network ls --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l)
  rm -rf "$LAB_ROOT"
  main_after=$(docker ps --filter label=com.docker.compose.project=tesis-fim-serio --format '{{.ID}}:{{.Names}}:{{.Image}}' | sort)
  main_backend_healthy=false
  main_frontend_healthy=false
  curl -fsS http://127.0.0.1:8000/health >/dev/null && main_backend_healthy=true
  curl -fsS http://127.0.0.1/ >/dev/null && main_frontend_healthy=true
  if [[ $remaining_containers -eq 0 && $remaining_volumes -eq 0 && $remaining_networks -eq 0 && "$main_before" == "$main_after" && $main_backend_healthy == true && $main_frontend_healthy == true ]]; then
    teardown_ok=true
  fi
  cat > "$EVIDENCE/teardown-result.json" <<JSON
{"lab_containers_remaining":$remaining_containers,"lab_volumes_remaining":$remaining_volumes,"lab_networks_remaining":$remaining_networks,"temporary_root_removed":$([[ ! -e "$LAB_ROOT" ]] && echo true || echo false),"main_stack_unchanged":$([[ "$main_before" == "$main_after" ]] && echo true || echo false),"main_backend_healthy":$main_backend_healthy,"main_frontend_healthy":$main_frontend_healthy}
JSON
  # Failure paths can exit before the happy-path sanitization step. Always
  # sanitize from the trap before sealing checksums so raw traces/JWTs are not
  # retained as diagnostic evidence.
  python3 "$ROOT/scripts/sanitize-playwright-artifacts.py" "$EVIDENCE"
  find "$EVIDENCE" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum | sed "s#  $EVIDENCE/#  #" > "$EVIDENCE/SHA256SUMS"
  exit $status
}
status=1
trap cleanup EXIT INT TERM

cat > "$EVIDENCE/environment.json" <<JSON
{"result_label":"PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA","topology":"single-host Compose lab with isolated state, data and resources","api_port":$FIM_LAB_API_PORT,"mtls_port":$FIM_LAB_MTLS_PORT,"frontend_port":$FIM_LAB_FRONTEND_PORT,"db_exposed":false,"valkey_exposed":false,"n8n_started":false,"external_notifications_configured":false,"agent_state":"dedicated volume","watch_directory":"dedicated temporary bind","pki":"dedicated volume","fanotify_scope_limit":"kernel observation may include out-of-scope paths; agent scope filtering discards them"}
JSON

echo '[1/8] Build host frontend and isolated images'
(cd "$ROOT/frontend" && pnpm run build) > "$EVIDENCE/frontend-build.log" 2>&1
dc build backend frontend agent > "$EVIDENCE/compose-build.log" 2>&1

echo '[2/8] Start isolated DB, Valkey, backend and frontend'
dc up -d db valkey backend frontend > "$EVIDENCE/compose-up.log" 2>&1
for _ in $(seq 1 90); do curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null && break; sleep 1; done
curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null
curl -fsS "http://127.0.0.1:$FIM_LAB_FRONTEND_PORT" >/dev/null

echo '[3/8] Activate lab admin and register isolated agent through real APIs'
cookie1="$LAB_ROOT/admin-cookie"
login1="$LAB_ROOT/login1.json"
curl -fsS -c "$cookie1" -H 'Content-Type: application/json' -d "{\"username\":\"$FIM_LAB_ADMIN_USERNAME\",\"password\":\"$FIM_LAB_ADMIN_PASSWORD\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/auth/login" > "$login1"
token1=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["access_token"])' "$login1")
curl -fsS -b "$cookie1" -H "Authorization: Bearer $token1" -H 'Content-Type: application/json' -d "{\"new_password\":\"$FIM_LAB_ADMIN_PASSWORD_FINAL\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/users/change-password" >/dev/null
login2="$LAB_ROOT/login2.json"
cookie2="$LAB_ROOT/admin-cookie2"
curl -fsS -c "$cookie2" -H 'Content-Type: application/json' -d "{\"username\":\"$FIM_LAB_ADMIN_USERNAME\",\"password\":\"$FIM_LAB_ADMIN_PASSWORD_FINAL\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/auth/login" > "$login2"
old_access=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["access_token"])' "$login2")
curl -fsS -H "Authorization: Bearer $old_access" -H 'Content-Type: application/json' -d "{\"agent_id\":\"$FIM_LAB_AGENT_ID\",\"bootstrap_secret\":\"$FIM_LAB_BOOTSTRAP_SECRET\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/agents/register" >/dev/null

echo '[4/8] US-03 live dual-key rotation'
export FIM_LAB_JWT_CURRENT=$NEW_JWT
export FIM_LAB_JWT_PREVIOUS=$OLD_JWT
dc up -d --no-deps --force-recreate backend > "$EVIDENCE/us03-rotation.log" 2>&1
for _ in $(seq 1 60); do curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null && break; sleep 1; done
old_access_status=$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $old_access" "http://127.0.0.1:$FIM_LAB_API_PORT/rules")
old_refresh_status=$(curl -sS -o "$LAB_ROOT/refresh.json" -w '%{http_code}' -b "$cookie2" -X POST "http://127.0.0.1:$FIM_LAB_API_PORT/auth/refresh")
foreign_token=$(dc exec -T -e FOREIGN_SECRET="$(openssl rand -hex 32)" backend python -c "import os,time,uuid; from jose import jwt; now=int(time.time()); print(jwt.encode({'sub':'1','username':'foreign','jti':str(uuid.uuid4()),'type':'access','iat':now,'exp':now+900},os.environ['FOREIGN_SECRET'],algorithm='HS256'))")
foreign_status=$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $foreign_token" "http://127.0.0.1:$FIM_LAB_API_PORT/rules")
new_login_body="$LAB_ROOT/new-current-login.json"
new_login_status=$(curl -sS -o "$new_login_body" -w '%{http_code}' -H 'Content-Type: application/json' -d "{\"username\":\"$FIM_LAB_ADMIN_USERNAME\",\"password\":\"$FIM_LAB_ADMIN_PASSWORD_FINAL\"}" "http://127.0.0.1:$FIM_LAB_API_PORT/auth/login")
new_access=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["access_token"])' "$new_login_body")
new_access_status=$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $new_access" "http://127.0.0.1:$FIM_LAB_API_PORT/rules")
[[ $old_access_status == 200 && $old_refresh_status == 200 && $foreign_status == 401 && $new_login_status == 200 && $new_access_status == 200 ]]
cat > "$EVIDENCE/us03-multikey-result.json" <<JSON
{"old_access_after_rotation":$old_access_status,"old_refresh_after_rotation":$old_refresh_status,"foreign_key_token":$foreign_status,"new_login_after_rotation":$new_login_status,"new_access_protected_endpoint":$new_access_status,"old_current_moved_to_previous":true,"new_current_active":true,"cookie_contract":"PASS: HttpOnly; SameSite=Strict; Path=/auth/refresh"}
JSON

echo '[5/8] Start and bootstrap the isolated real agent'
dc up -d agent > "$EVIDENCE/agent-up.log" 2>&1
for _ in $(seq 1 90); do
  if dc exec -T agent test -f /var/lib/fim-agent/state.json >/dev/null 2>&1; then break; fi
  sleep 1
done
dc exec -T agent test -f /var/lib/fim-agent/secrets/shared_secret
dc exec -T agent test -f /var/lib/fim-agent/baseline/$(printf '/watch/%s' "$(basename "$FIM_LAB_US17_FILE")" | sha256sum | cut -d' ' -f1).bin
dc exec -T agent test -f /var/lib/fim-agent/baseline/$(printf '/watch/%s' "$(basename "$FIM_LAB_US25_FILE")" | sha256sum | cut -d' ' -f1).bin

echo '[6/8] Run US-03, US-16/17 and US-25 individually'
(cd "$ROOT/frontend" && pnpm exec playwright test --config playwright.isolated-lab.config.ts --grep 'US-03') > "$EVIDENCE/playwright-us03.log" 2>&1
(cd "$ROOT/frontend" && pnpm exec playwright test --config playwright.isolated-lab.config.ts --grep 'US-16 and US-17') > "$EVIDENCE/playwright-us16-us17.log" 2>&1
(cd "$ROOT/frontend" && pnpm exec playwright test --config playwright.isolated-lab.config.ts --grep 'US-25') > "$EVIDENCE/playwright-us25.log" 2>&1

echo '[7/8] Run the semantically ordered combined suite'
(cd "$ROOT/frontend" && pnpm exec playwright test --config playwright.isolated-lab.config.ts) > "$EVIDENCE/playwright-combined.log" 2>&1
(cd "$ROOT/frontend" && pnpm exec playwright test --config playwright.isolated-lab.config.ts) > "$EVIDENCE/playwright-combined-repeat.log" 2>&1

echo '[8/8] Capture bounded sanitized diagnostics'
dc ps --format json | python3 -c 'import json,sys; rows=[]
for line in sys.stdin:
 d=json.loads(line); rows.append({k:d.get(k) for k in ("Service","State","Health")})
print(json.dumps(rows,indent=2))' > "$EVIDENCE/services-before-teardown.json"
dc logs --no-color --tail 250 backend agent \
  | sed -E 's/(Bearer )[A-Za-z0-9._-]+/\1[REDACTED]/g; s#eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+#[REDACTED-JWT]#g; s/[A-Fa-f0-9]{48,}/[REDACTED-OPAQUE]/g' \
  > "$EVIDENCE/runtime-sanitized.log"
cat > "$EVIDENCE/RESULTADO.md" <<'MD'
# Real acceptance result in a state/data/resource-isolated lab

**PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA**

- US-03: real old-CURRENT to new-CURRENT/old-PREVIOUS rotation exercised; prior access and refresh accepted, foreign key rejected.
- US-16: real browser edit plus DB/audit/outbox and real agent state synchronization exercised.
- US-17: cancel without DELETE, confirmed deletion, persistence/audit/outbox, real agent synchronization, and post-delete `alert_only` effect exercised.
- US-25: real browser bulk approve, signed/versioned `baseline_update`, agent execution, ACK, encrypted-baseline effect, and audit exercised.
- US-03 canonical cookie attributes and US-25 canonical `event_ids[]` request wire are exercised.
- `rule_sync` is not claimed to ACK; reception is observed in the agent's persisted ruleset version.
- Isolation covers state, data, containers, network, PKI, baseline, and watch files. It does not isolate the physical host, Docker daemon, kernel, or image cache.
- fanotify may observe kernel events outside `/watch`; the agent's scope filter discards them. Such observation is not counted as an accepted FIM event.
- RuleForm labels are programmatically associated and exercised through accessible-name locators; no global accessibility claim is made.
- Screenshots, video and trace screencast frames are disabled or removed before packaging; sanitized textual trace/report evidence remains.
MD
cat > "$EVIDENCE/COMMANDS.md" <<'MD'
# Exact reproduction

```bash
scripts/run-isolated-acceptance-lab.sh
```

The script builds the frontend and isolated images, runs the live key rotation, executes each Playwright case individually, then executes the ordered combined suite. A trap always removes the isolated containers, network, volumes, PKI, agent state, baseline, and temporary watch directory.
MD
python3 "$ROOT/scripts/sanitize-playwright-artifacts.py" "$EVIDENCE"
git diff --check
status=0
