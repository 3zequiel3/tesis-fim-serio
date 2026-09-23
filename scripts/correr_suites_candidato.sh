#!/usr/bin/env bash
# Consolidated suite run on the frozen candidate (director's route, section 3.1).
#
# agent/ and frontend/ are byte-identical to 7a906c2 in the working tree, so only
# backend/ needs the detached worktree.
#
# The backend suite needs BOTH PostgreSQL and Valkey: the FastAPI lifespan opens
# the consumers at startup, and without a broker that startup fails, the anyio
# portal dies, and every TestClient teardown reports "This portal is not running"
# — 41 failures that say nothing about the code. backend/tests/conftest.py:13
# documents the container it expects. The suite also writes its TLS material to
# /certs, the path inside the container, which is not writable here, so the four
# certificate paths are redirected to a writable directory.
#
# The candidate and the output directory are PARAMETERS. They used to be written
# into the script, pinned to 7a906c2 and to the September package's `suites/`
# folder, so every later run overwrote that package's artifacts and stamped the
# result as v1.0-tesis no matter which candidate was actually being evaluated. A
# unified evaluation of v3.0-tesis therefore shipped suite artifacts belonging to
# v1.0-tesis, correctly labelled but filed under the wrong candidate.
#
#   CAND=<commit-ish> CAND_TAG=<tag> SUITES_OUT=<dir> bash scripts/correr_suites_candidato.sh
#
set -uo pipefail
REPO=$(git rev-parse --show-toplevel)
CAND="${CAND:-7a906c2}"
CAND_TAG="${CAND_TAG:-v1.0-tesis}"
git rev-parse -q --verify "$CAND^{commit}" >/dev/null \
  || { echo "ABORTA: el candidato $CAND no existe"; exit 1; }
WT="${WORKTREE_DIR:-$HOME/tesis-worktrees}/candidato-$CAND_TAG"
OUT="${SUITES_OUT:-$REPO/tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/suites}"
LAB="${LAB_DIR:-$HOME/fim-lab}"
RES=$LAB/suites_candidato.out
CERTS=$LAB/suites_certs
PGC=fim-suites-pg
VKC=fim-suites-valkey
DCLAB=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
PGPORT=55440
VKPORT=55441
cd "$REPO" || exit 1
mkdir -p "$OUT" "$CERTS"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "[$(ts)] $*" | tee -a "$RES"; }

limpiar() {
  docker rm -f "$PGC" "$VKC" >/dev/null 2>&1
  git -C "$REPO" worktree remove --force "$WT" 2>/dev/null
}
trap limpiar EXIT

say "=== consolidated suites on candidate $CAND ($CAND_TAG) ==="
{
  echo "candidate_commit=$(git rev-parse "$CAND")"
  echo "candidate_tag=$CAND_TAG"
  echo "agent_tree_matches_candidate=$(git diff --quiet "$CAND" -- agent/ && echo yes || echo no)"
  echo "frontend_tree_matches_candidate=$(git diff --quiet "$CAND" -- frontend/ && echo yes || echo no)"
  echo "backend_run_from=detached worktree at $CAND"
  echo "postgres=postgres:18.3 on 127.0.0.1:$PGPORT (isolated, not the lab database)"
  echo "valkey=valkey/valkey:9.0.3 on 127.0.0.1:$VKPORT (isolated, plaintext)"
} > "$OUT/procedencia.txt"
cat "$OUT/procedencia.txt" | tee -a "$RES"

say "preparing the worktree"
git worktree remove --force "$WT" 2>/dev/null
mkdir -p "$(dirname "$WT")"
git worktree add --detach "$WT" "$CAND" >/dev/null 2>&1 || { say "WORKTREE FAILED"; exit 1; }

say "starting isolated PostgreSQL and Valkey"
docker rm -f "$PGC" "$VKC" >/dev/null 2>&1
docker run --rm -d --name "$PGC" -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=fim_test -p 127.0.0.1:$PGPORT:5432 postgres:18.3 >/dev/null 2>&1
docker run --rm -d --name "$VKC" -p 127.0.0.1:$VKPORT:6379 valkey/valkey:9.0.3 >/dev/null 2>&1
for _ in $(seq 1 60); do docker exec "$PGC" pg_isready -U fim -d fim_test >/dev/null 2>&1 && break; sleep 1; done
for _ in $(seq 1 60); do docker exec "$VKC" valkey-cli ping 2>/dev/null | grep -q PONG && break; sleep 1; done
say "postgres: $(docker exec "$PGC" pg_isready -U fim -d fim_test 2>&1 | tail -1)"
say "valkey: $(docker exec "$VKC" valkey-cli ping 2>&1 | tail -1)"

say "--- agent suite ---"
PYTHONPATH="$REPO" "$REPO/backend/.venv/bin/pytest" -q \
  --junitxml="$OUT/agente.xml" "$REPO/agent/tests" > "$OUT/agente.log" 2>&1
say "agent: $(tail -1 "$OUT/agente.log")"

# The test app binds the mTLS server on 8443 during its lifespan, and the lab
# backend holds that port. Without this the bind fails, the anyio portal dies and
# 41 TestClient teardowns fail on "This portal is not running" — an error that
# names neither the port nor the conflict. 8443 is fixed in pki.py, so the port
# has to be freed rather than moved.
say "stopping the lab backend to free 8443/8444"
"${DCLAB[@]}" stop backend >/dev/null 2>&1
sleep 3
say "8443 libre: $(ss -lnt 2>/dev/null | grep -c ':8443' | sed 's/^0$/si/;s/^[1-9].*/NO/')"

say "--- backend suite (from the candidate worktree) ---"
TEST_DATABASE_URL="postgresql+psycopg://fim:test@127.0.0.1:$PGPORT/fim_test" \
TEST_VALKEY_URL="valkey://127.0.0.1:$VKPORT" \
CA_CERT_PATH="$CERTS/ca.pem" CA_KEY_PATH="$CERTS/ca-key.pem" \
BACKEND_CERT_PATH="$CERTS/backend.pem" BACKEND_KEY_PATH="$CERTS/backend-key.pem" \
PYTHONPATH="$WT/backend" "$REPO/backend/.venv/bin/pytest" -q \
  --junitxml="$OUT/backend.xml" "$WT/backend/tests" > "$OUT/backend.log" 2>&1
say "backend: $(tail -1 "$OUT/backend.log")"

say "restoring the lab backend"
"${DCLAB[@]}" --profile app up -d backend >/dev/null 2>&1

say "--- frontend suite ---"
cd "$REPO/frontend" && npx vitest run --config vitest.config.ts \
  --reporter=default --reporter=junit --outputFile.junit="$OUT/frontend.xml" \
  > "$OUT/frontend.log" 2>&1
say "frontend: $(grep -E 'Tests ' "$OUT/frontend.log" | tail -1)"

cd "$REPO"
# Counts come from the root <testsuites> element: reading the first <testsuite>
# reports only the first file, which is how a 260-test frontend run looked like 3.
say "--- counts from the JUnit files ---"
python3 - "$OUT" <<'PY' | tee -a "$RES"
import sys, pathlib, xml.etree.ElementTree as ET
out = pathlib.Path(sys.argv[1])
for name in ("agente.xml", "backend.xml", "frontend.xml"):
    f = out / name
    if not f.exists():
        print(f"  {name:14s} ausente"); continue
    root = ET.parse(f).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    g = lambda k: sum(int(s.get(k) or 0) for s in suites)
    print(f"  {name:14s} tests={g('tests'):5d} fallas={g('failures')} errores={g('errors')} omitidos={g('skipped')}")
PY
say "=== suites done ==="
