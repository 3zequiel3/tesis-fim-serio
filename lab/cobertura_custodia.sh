#!/usr/bin/env bash
# Cobertura por componente y bundle de custodia del candidato v5.1-tesis (P-8).
#
# Uso, desde la raíz del repositorio:
#   TAG=v5.1-tesis bash lab/cobertura_custodia.sh
#
# Requisitos: Docker; backend/.venv con requirements-dev.txt instalado (trae
# pytest-cov); Node con npm; los puertos 8443 y 8444 libres (el script detiene
# el backend del laboratorio y lo vuelve a levantar al final).
set -uo pipefail
TAG="${TAG:-v5.1-tesis}"
REPO=$(git rev-parse --show-toplevel)
cd "$REPO" || exit 1
git rev-parse -q --verify "$TAG^{commit}" >/dev/null || { echo "ABORTA: no existe la etiqueta $TAG"; exit 1; }
COMMIT=$(git rev-parse "$TAG^{commit}")
TREE=$(git rev-parse "$TAG^{tree}")
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PKG="$REPO/tesis/cierre/evidencia/${TAG}-cobertura-custodia-$STAMP"
WT="$HOME/tesis-worktrees/candidato-$TAG-cov"
CERTS="$PKG/.certs"
PGC=fim-cov-pg; VKC=fim-cov-valkey; PGPORT=55450; VKPORT=55451
DCLAB=(docker compose -f docker-compose.yml -f docker-compose.tls.yml)
PY="$REPO/backend/.venv/bin/pytest"
mkdir -p "$PKG"/{coverage/frontend,suites,custody} "$CERTS"
say() { echo "[$(date -u +%H:%M:%S)] $*"; }

limpiar() {
  docker rm -f "$PGC" "$VKC" >/dev/null 2>&1
  git worktree remove --force "$WT" 2>/dev/null
  rm -rf "$CERTS" "$PKG/.coveragerc"
  # `start`, not `up -d`: the lab backend was brought up with an extra compose file
  # (mailpit); `up` with a different file set would recreate it with another
  # configuration. `start` only restarts the container this script stopped, and is a
  # no-op if the script aborted before stopping it.
  "${DCLAB[@]}" --profile app start backend >/dev/null 2>&1
}
trap limpiar EXIT

say "1. Worktree desacoplado en $TAG ($COMMIT)"
git worktree remove --force "$WT" 2>/dev/null
mkdir -p "$(dirname "$WT")"
git worktree add --detach "$WT" "$TAG" >/dev/null 2>&1 || { say "ABORTA: no se pudo crear el worktree"; exit 1; }
test "$(git -C "$WT" rev-parse 'HEAD^{tree}')" = "$TREE" || { say "ABORTA: el árbol no coincide con la etiqueta"; exit 1; }
{ echo "tag=$TAG"; echo "commit=$COMMIT"; echo "tree=$TREE"; echo "generado_utc=$STAMP"; } > "$PKG/procedencia.txt"

say "2. PostgreSQL y Valkey aislados"
docker rm -f "$PGC" "$VKC" >/dev/null 2>&1
docker run --rm -d --name "$PGC" -e POSTGRES_USER=fim -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=fim_test -p 127.0.0.1:$PGPORT:5432 postgres:18.3 >/dev/null
docker run --rm -d --name "$VKC" -p 127.0.0.1:$VKPORT:6379 valkey/valkey:9.0.3 >/dev/null
for _ in $(seq 1 60); do docker exec "$PGC" pg_isready -U fim -d fim_test >/dev/null 2>&1 && break; sleep 1; done
for _ in $(seq 1 60); do docker exec "$VKC" valkey-cli ping 2>/dev/null | grep -q PONG && break; sleep 1; done

printf '[run]\nomit =\n    */tests/*\n    */test_*.py\n' > "$PKG/.coveragerc"

say "3. Agente: pruebas con cobertura (excluidos los tests)"
(cd "$WT" && PYTHONPATH="$WT" "$PY" -q "$WT/agent/tests" \
  --cov="$WT/agent" --cov-config="$PKG/.coveragerc" \
  --cov-report=xml:"$PKG/coverage/agent-coverage.xml" \
  --cov-report=json:"$PKG/coverage/agent-coverage.json" \
  --junitxml="$PKG/suites/agente.xml") > "$PKG/suites/agente.log" 2>&1
say "   $(tail -1 "$PKG/suites/agente.log")"

say "4. Liberar 8443/8444 (se detiene el backend del laboratorio)"
"${DCLAB[@]}" stop backend >/dev/null 2>&1; sleep 3

say "5. Backend: pruebas con cobertura sobre backend/app"
(cd "$WT/backend" && \
  TEST_DATABASE_URL="postgresql+psycopg://fim:test@127.0.0.1:$PGPORT/fim_test" \
  TEST_VALKEY_URL="valkey://127.0.0.1:$VKPORT" \
  CA_CERT_PATH="$CERTS/ca.pem" CA_KEY_PATH="$CERTS/ca-key.pem" \
  BACKEND_CERT_PATH="$CERTS/backend.pem" BACKEND_KEY_PATH="$CERTS/backend-key.pem" \
  PYTHONPATH="$WT/backend" "$PY" -q "$WT/backend/tests" \
  --cov="$WT/backend/app" --cov-config="$PKG/.coveragerc" \
  --cov-report=xml:"$PKG/coverage/backend-coverage.xml" \
  --cov-report=json:"$PKG/coverage/backend-coverage.json" \
  --junitxml="$PKG/suites/backend.xml") > "$PKG/suites/backend.log" 2>&1
say "   $(tail -1 "$PKG/suites/backend.log")"

say "6. Frontend: dependencias y pruebas con cobertura"
# The frontend is a pnpm project (pnpm-lock.yaml, packageManager pnpm@10.33.0, no
# package-lock.json): `npm ci` refuses to install it. Install output goes to the log.
(cd "$WT/frontend" && pnpm install --frozen-lockfile && \
  pnpm exec vitest run --config vitest.config.ts --coverage \
    --coverage.reporter=json-summary --coverage.reporter=json \
    --coverage.reportsDirectory="$PKG/coverage/frontend" \
    --reporter=default --reporter=junit --outputFile.junit="$PKG/suites/frontend.xml") \
  > "$PKG/suites/frontend.log" 2>&1
say "   $(grep -E 'Tests ' "$PKG/suites/frontend.log" | tail -1)"

for f in coverage/agent-coverage.xml coverage/backend-coverage.xml coverage/frontend/coverage-summary.json \
         suites/agente.xml suites/backend.xml suites/frontend.xml; do
  test -s "$PKG/$f" || { say "ABORTA: falta $f (ver suites/*.log); no se sella un paquete incompleto"; exit 1; }
done

say "7. Bundle y archivo determinista"
git bundle create "$PKG/custody/candidate.bundle" "$TAG" >/dev/null 2>&1
git bundle verify "$PKG/custody/candidate.bundle" >/dev/null 2>&1 || { say "ABORTA: el bundle no verifica"; exit 1; }
git archive --format=tar --prefix=candidate/ "$TAG" | gzip -n -9 > "$PKG/custody/candidate-tree.tar.gz"
TMP=$(mktemp -d); git clone -q "$PKG/custody/candidate.bundle" "$TMP/r" 2>/dev/null
git -C "$TMP/r" checkout -q --detach "$COMMIT"
test "$(git -C "$TMP/r" rev-parse 'HEAD^{tree}')" = "$TREE" && echo "recuperacion_desde_bundle=ok" >> "$PKG/procedencia.txt" \
  || { say "ABORTA: el bundle no recupera el árbol"; rm -rf "$TMP"; exit 1; }
git -C "$TMP/r" archive --format=tar --prefix=candidate/ "$COMMIT" | gzip -n -9 | cmp -s - "$PKG/custody/candidate-tree.tar.gz" \
  && echo "archivo_determinista=ok" >> "$PKG/procedencia.txt"
rm -rf "$TMP"

say "8. Resumen"
python3 - "$PKG" <<'PY' | tee "$PKG/RESUMEN.txt"
import sys, json, pathlib, xml.etree.ElementTree as ET
p = pathlib.Path(sys.argv[1])
for comp in ("agent", "backend"):
    r = ET.parse(p / f"coverage/{comp}-coverage.xml").getroot()
    print(f"{comp:9s} lineas {float(r.get('line-rate'))*100:6.2f} % ({r.get('lines-covered')}/{r.get('lines-valid')})")
s = json.loads((p / "coverage/frontend/coverage-summary.json").read_text())["total"]
for k in ("lines", "statements", "functions", "branches"):
    print(f"frontend  {k:10s} {s[k]['pct']:6.2f} % ({s[k]['covered']}/{s[k]['total']})")
for name in ("agente.xml", "backend.xml", "frontend.xml"):
    root = ET.parse(p / "suites" / name).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    g = lambda k: sum(int(x.get(k) or 0) for x in suites)
    print(f"{name:13s} tests={g('tests')} fallas={g('failures')} errores={g('errors')} omitidos={g('skipped')}")
PY
echo "bundle_sha256=$(sha256sum "$PKG/custody/candidate.bundle" | cut -d' ' -f1)" | tee -a "$PKG/RESUMEN.txt"
echo "archivo_sha256=$(sha256sum "$PKG/custody/candidate-tree.tar.gz" | cut -d' ' -f1)" | tee -a "$PKG/RESUMEN.txt"

say "9. Sello del paquete"
# The custody binaries exceed GitHub's 100 MB per-file limit, so they stay out of git
# (see .gitignore); their SHA-256 values are recorded here and in SHA256SUMS.
cat > "$PKG/custody/CUSTODIA.md" <<EOF2
# Custodia del candidato $TAG

\`candidate.bundle\` y \`candidate-tree.tar.gz\` no se versionan: superan el límite de 100 MB por
archivo de GitHub. Se conservan fuera del repositorio. Sus SHA-256 están en \`../RESUMEN.txt\` y en
\`../SHA256SUMS\`. Para verificar una copia, ubicarla en esta carpeta y correr
\`sha256sum -c SHA256SUMS\` desde la raíz del paquete. La recuperación del árbol \`$TREE\` desde el
bundle y el determinismo del archivo están verificados en \`../procedencia.txt\`.
EOF2
rm -rf "$CERTS" "$PKG/.coveragerc"
(cd "$PKG" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
say "SHA256SUMS: $(sha256sum "$PKG/SHA256SUMS" | cut -d' ' -f1)"
say "Paquete: ${PKG#$REPO/}"
