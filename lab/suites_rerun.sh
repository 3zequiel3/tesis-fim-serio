#!/usr/bin/env bash
# Re-run of the backend and frontend suites with the harness defects fixed:
# the backend bootstraps its TLS material into /certs, which is the container
# path and is not writable on the host; and the frontend junit reporter alone
# swallowed the run summary.
set -uo pipefail
REPO=/home/ezequiel/Facultad/tesis/tesis-fim-serio
WT=/home/ezequiel/tesis-worktrees/candidato-v1.0
OUT=$REPO/docs/cierre/evidencia/oficial-cap5-20260917T223823Z/suites
CERTS=/home/ezequiel/fim-lab/suites_certs
RES=/home/ezequiel/fim-lab/suites_rerun.out
PGC=fim-suites-pg
cd "$REPO" || exit 1
mkdir -p "$CERTS"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

say "=== suites re-run ==="
git worktree remove --force "$WT" 2>/dev/null
git worktree add --detach "$WT" 7a906c2 >/dev/null 2>&1 || { say "WORKTREE FAILED"; exit 1; }
docker rm -f "$PGC" >/dev/null 2>&1
docker run --rm -d --name "$PGC" -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=fim_test -p 127.0.0.1:55440:5432 postgres:18.3 >/dev/null 2>&1
for _ in $(seq 1 60); do docker exec "$PGC" pg_isready -U fim -d fim_test >/dev/null 2>&1 && break; sleep 1; done

say "--- backend suite, TLS material redirected to a writable directory ---"
TEST_DATABASE_URL='postgresql+psycopg://fim:test@127.0.0.1:55440/fim_test' \
CA_CERT_PATH="$CERTS/ca.pem" CA_KEY_PATH="$CERTS/ca-key.pem" \
BACKEND_CERT_PATH="$CERTS/backend.pem" BACKEND_KEY_PATH="$CERTS/backend-key.pem" \
PYTHONPATH="$WT/backend" "$REPO/backend/.venv/bin/pytest" -q \
  --junitxml="$OUT/backend.xml" "$WT/backend/tests" > "$OUT/backend.log" 2>&1
say "backend: $(grep -E '^[0-9]+ (passed|failed)|passed|failed' "$OUT/backend.log" | tail -1)"

say "--- frontend suite, default reporter alongside junit ---"
cd "$REPO/frontend" && npx vitest run --config vitest.config.ts \
  --reporter=default --reporter=junit --outputFile.junit="$OUT/frontend.xml" \
  > "$OUT/frontend.log" 2>&1
say "frontend: $(grep -E 'Test Files|Tests ' "$OUT/frontend.log" | tr '\n' ' ')"

cd "$REPO"
docker rm -f "$PGC" >/dev/null 2>&1
git worktree remove --force "$WT" 2>/dev/null
say "=== rerun done ==="
