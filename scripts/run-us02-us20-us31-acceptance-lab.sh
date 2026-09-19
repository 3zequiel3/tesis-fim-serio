#!/usr/bin/env bash
# Disposable real-stack acceptance laboratory for US-02, US-20 and US-31.
set -Eeuo pipefail
umask 077

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
STAMP=${FIM_LAB_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
export FIM_LAB_PROJECT="fimaccept-ui-${STAMP,,}-$$"
export FIM_LAB_API_PORT=${FIM_LAB_API_PORT:-18100}
export FIM_LAB_MTLS_PORT=${FIM_LAB_MTLS_PORT:-18543}
export FIM_LAB_FRONTEND_PORT=${FIM_LAB_FRONTEND_PORT:-18180}
export FIM_LAB_DB_PASSWORD=$(openssl rand -hex 24)
export FIM_LAB_JWT_CURRENT=$(openssl rand -hex 32)
export FIM_LAB_JWT_PREVIOUS=
export FIM_LAB_ADMIN_USERNAME="lab-admin-$STAMP"
export FIM_LAB_ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')
export FIM_LAB_BOOTSTRAP_SECRET=$(openssl rand -hex 24)
LAB_ROOT=$(mktemp -d "/tmp/fim-acceptance-ui-${STAMP}-XXXXXX")
RUN_ROOT="$LAB_ROOT/candidate"
mkdir -p "$RUN_ROOT"
# Bind-mounted init files must remain traversable by the non-root database
# process inside Docker. The random directory name and 0600 secret files keep
# lab credentials private while execute permission exposes no directory list.
chmod 711 "$LAB_ROOT"
chmod 755 "$RUN_ROOT"
tar -C "$ROOT" \
  --exclude='.git' \
  --exclude='backend/.venv' \
  --exclude='backend/.pytest_cache' \
  --exclude='frontend/node_modules' \
  --exclude='frontend/dist' \
  --exclude='frontend/test-results' \
  --exclude='tesis/cierre/evidencia' \
  -cf - backend frontend agent db scripts docker-compose.us02-us20-us31-lab.yml \
  | tar -C "$RUN_ROOT" -xf -
COMPOSE="$RUN_ROOT/docker-compose.us02-us20-us31-lab.yml"
export FIM_LAB_WATCH_DIR="$LAB_ROOT/watch"
export FIM_LAB_AGENT_CONFIG="$LAB_ROOT/unused-agent-config.yaml"
export FIM_LAB_BASE_URL="http://127.0.0.1:$FIM_LAB_FRONTEND_PORT"
export FIM_E2E_COMPOSE_PROJECT="$FIM_LAB_PROJECT"
export FIM_E2E_COMPOSE_FILE="$COMPOSE"
EVIDENCE="$ROOT/tesis/cierre/evidencia/us02-us20-us31-fixed-${STAMP}"
mkdir -p "$FIM_LAB_WATCH_DIR" "$EVIDENCE"
printf 'unused: true\n' > "$FIM_LAB_AGENT_CONFIG"

# Freeze and inventory the executable candidate before any build/test command.
(cd "$RUN_ROOT" && find backend frontend agent db scripts -type f -print0 | sort -z | xargs -0 sha256sum) \
  > "$EVIDENCE/candidate-files.sha256"
(cd "$RUN_ROOT" && find backend frontend agent db scripts -type f -printf '%m\t%p\n' | sort) \
  > "$EVIDENCE/candidate-modes.tsv"
sha256sum "$RUN_ROOT/docker-compose.us02-us20-us31-lab.yml" \
  | sed "s#$RUN_ROOT/##" >> "$EVIDENCE/candidate-files.sha256"
printf '%s\n' "$(git -C "$ROOT" rev-parse HEAD)" > "$EVIDENCE/source-head.commit"
sha256sum "$EVIDENCE/candidate-files.sha256" | sed "s#  $EVIDENCE/#  #" \
  > "$EVIDENCE/candidate-manifest.sha256"
ln -s "$ROOT/frontend/node_modules" "$RUN_ROOT/frontend/node_modules"

dc() { docker compose -p "$FIM_LAB_PROJECT" -f "$COMPOSE" "$@"; }
main_before=$(docker ps --filter label=com.docker.compose.project=tesis-fim-serio --format '{{.ID}}:{{.Names}}:{{.Status}}' | sort)
status=1
cleanup() {
  local final_status=$status
  local sanitize_status=0
  local scan_status=0
  set +e
  dc logs --no-color --tail 250 db valkey backend sse-proxy frontend \
    | sed -E 's/(Bearer )[A-Za-z0-9._-]+/\1[REDACTED]/g; s#eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+#[REDACTED-JWT]#g; s/[A-Fa-f0-9]{48,}/[REDACTED-OPAQUE]/g' \
    > "$EVIDENCE/runtime-sanitized.log" 2>&1
  dc down -v --remove-orphans --timeout 10 > "$EVIDENCE/teardown.log" 2>&1
  remaining_containers=$(docker ps -a --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l)
  remaining_volumes=$(docker volume ls --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l)
  remaining_networks=$(docker network ls --filter "label=com.docker.compose.project=$FIM_LAB_PROJECT" -q | wc -l)
  main_after=$(docker ps --filter label=com.docker.compose.project=tesis-fim-serio --format '{{.ID}}:{{.Names}}:{{.Status}}' | sort)
  cat > "$EVIDENCE/teardown-result.json" <<JSON
{"lab_containers_remaining":$remaining_containers,"lab_volumes_remaining":$remaining_volumes,"lab_networks_remaining":$remaining_networks,"temporary_root_removed":$([[ ! -e "$LAB_ROOT" ]] && echo true || echo false),"main_stack_unchanged":$([[ "$main_before" == "$main_after" ]] && echo true || echo false)}
JSON
  python3 "$RUN_ROOT/scripts/sanitize-playwright-artifacts.py" "$EVIDENCE" \
    > "$EVIDENCE/sanitizer.log" 2>&1 || sanitize_status=$?
  python3 - "$EVIDENCE" <<'PY' > "$EVIDENCE/secret-scan.log" 2>&1 || scan_status=$?
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
patterns = {
    "jwt": re.compile(rb"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    "bearer": re.compile(rb"Bearer\s+(?!\[REDACTED\])[^\s\"']+", re.I),
}
matches = []
for path in root.rglob("*"):
    if not path.is_file() or path.name in {"SHA256SUMS", "secret-scan.log"}:
        continue
    if path.suffix.lower() in {".png", ".webm", ".zip"}:
        matches.append(f"unexpected binary artifact: {path.relative_to(root)}")
        continue
    data = path.read_bytes()
    for name, pattern in patterns.items():
        if pattern.search(data):
            matches.append(f"{name}: {path.relative_to(root)}")
if matches:
    print("\n".join(matches))
    raise SystemExit(1)
print("0 secret-pattern matches; 0 retained binary browser artifacts")
PY
  cat > "$EVIDENCE/sanitization-result.json" <<JSON
{"sanitizer_exit":$sanitize_status,"secret_scan_exit":$scan_status,"ran_on_failure_path":true}
JSON
  rm -rf "$LAB_ROOT"
  cat > "$EVIDENCE/teardown-result.json" <<JSON
{"lab_containers_remaining":$remaining_containers,"lab_volumes_remaining":$remaining_volumes,"lab_networks_remaining":$remaining_networks,"temporary_root_removed":$([[ ! -e "$LAB_ROOT" ]] && echo true || echo false),"main_stack_unchanged":$([[ "$main_before" == "$main_after" ]] && echo true || echo false)}
JSON
  if [[ $sanitize_status -ne 0 || $scan_status -ne 0 ]]; then final_status=1; fi
  find "$EVIDENCE" -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum | sed "s#  $EVIDENCE/#  #" > "$EVIDENCE/SHA256SUMS"
  exit "$final_status"
}
trap cleanup EXIT INT TERM

cat > "$EVIDENCE/environment.json" <<JSON
{"result_label":"EXECUTED — REAL ISOLATED STACK","candidate":"frozen pre-build filesystem snapshot with SHA-256 inventory","topology":"single-host Compose lab with isolated containers, network, database, Valkey and a disposable SSE-only proxy","api_port":$FIM_LAB_API_PORT,"frontend_port":$FIM_LAB_FRONTEND_PORT,"agent_started":false,"external_notifications_configured":false,"sse_interruption":"real stop/start of lab-only SSE proxy; backend/auth remain available"}
JSON

echo '[1/6] Build frontend and isolated images'
(cd "$RUN_ROOT/frontend" && pnpm run build) > "$EVIDENCE/frontend-build.log" 2>&1
dc build backend frontend > "$EVIDENCE/compose-build.log" 2>&1

echo '[2/6] Start isolated DB, Valkey, backend, SSE proxy and frontend'
dc up -d db valkey backend sse-proxy frontend > "$EVIDENCE/compose-up.log" 2>&1
for _ in $(seq 1 90); do curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null && break; sleep 1; done
curl -fsS "http://127.0.0.1:$FIM_LAB_API_PORT/health" >/dev/null
curl -fsS "http://127.0.0.1:$FIM_LAB_FRONTEND_PORT" >/dev/null

run_story() {
  local name=$1
  local file=$2
  export FIM_E2E_RUN_DIR="$EVIDENCE/$name"
  mkdir -p "$FIM_E2E_RUN_DIR"
  (cd "$RUN_ROOT/frontend" && pnpm exec playwright test --config playwright.us02-us20-us31-lab.config.ts "$file") \
    > "$EVIDENCE/playwright-$name.log" 2>&1
}

echo '[3/6] Run each story independently'
run_story us02 e2e/us02-logout.spec.ts
run_story us31 e2e/us31-superseded-toggle.spec.ts
run_story us20-run1 e2e/us20-realtime-alerts.spec.ts
run_story us20-run2 e2e/us20-realtime-alerts.spec.ts

echo '[4/6] Run the three-story combined suite twice'
for run in 1 2; do
  export FIM_E2E_RUN_DIR="$EVIDENCE/combined-run$run"
  mkdir -p "$FIM_E2E_RUN_DIR"
  (cd "$RUN_ROOT/frontend" && pnpm exec playwright test --config playwright.us02-us20-us31-lab.config.ts) \
    > "$EVIDENCE/playwright-combined-run$run.log" 2>&1
done

echo '[5/6] Capture bounded diagnostics and sanitize artifacts'
dc ps --format json | python3 -c 'import json,sys; rows=[]
for line in sys.stdin:
 d=json.loads(line); rows.append({k:d.get(k) for k in ("Service","State","Health")})
print(json.dumps(rows,indent=2))' > "$EVIDENCE/services-before-teardown.json"
echo '[6/6] Structural checks'
git -C "$ROOT" diff --check > "$EVIDENCE/git-diff-check.log" 2>&1
cat > "$EVIDENCE/RESULTADO.md" <<'MD'
# US-02, US-20 and US-31 real-stack acceptance result

- US-02 exercises browser logout, authenticated backend revocation, cookie removal, access/refresh rejection and Back navigation.
- US-20 exercises the real Valkey → consumer → database Alert → SSE → toast chain. Reconnection is tested by stopping only a disposable lab SSE proxy, observing the original SSE request close, proving API health and refresh remain HTTP 200, restarting the proxy, waiting for the second successful SSE response before publishing, and then receiving one newly published event without reloading.
- US-31 exercises the real include-superseded filter and requires `parent_event_id` as visible linked text.
- No route interception, mocked network response, synthetic SSE response, external notification channel, or shared application state is used.
- The retained closure package is text-only: Playwright traces, screenshots and videos are disabled because binary browser artifacts cannot be reliably sanitized. JUnit, JSON, bounded logs and domain-specific JSON observations remain available.
- Tests and image builds run only from the frozen candidate snapshot inventoried by `candidate-files.sha256`; the mutable worktree is not the certified input.
MD
cat > "$EVIDENCE/COMMANDS.md" <<'MD'
# Exact reproduction

```bash
scripts/run-us02-us20-us31-acceptance-lab.sh
```
MD
status=0
