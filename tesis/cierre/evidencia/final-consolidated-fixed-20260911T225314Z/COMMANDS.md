# Comandos reproducidos sobre el candidato congelado

```bash
PYTHONPATH="$SNAPSHOT" pytest agent/tests --junitxml=agent.xml --cov=agent --cov-config="$AGENT_COVERAGERC" --cov-report=xml:agent-coverage.xml --cov-report=json:agent-coverage.json
TEST_DATABASE_URL='postgresql+psycopg://fim:[TEST_PASSWORD]@127.0.0.1:55442/fim_test' TEST_VALKEY_URL='valkey://127.0.0.1:56382' PYTHONPATH="$SNAPSHOT/backend" pytest backend/tests --junitxml=backend.xml --cov=backend/app --cov-report=xml:backend-coverage.xml --cov-report=json:backend-coverage.json
cd frontend
pnpm exec vitest run --coverage --coverage.reporter=text --coverage.reporter=json-summary --coverage.reporter=json --coverage.reporter=lcov --reporter=default --reporter=junit --outputFile.junit=frontend.xml
pnpm run typecheck
pnpm run build
python3 scripts/check_spec_integrity.py --json
scripts/run-us02-us20-us31-acceptance-lab.sh
scripts/run-isolated-acceptance-lab.sh
```

Las contraseñas efímeras no se archivan. Los puertos, nombres y versiones no secretos constan en `metadata/`. No se instaló ninguna dependencia durante esta verificación.

## Recuperación del candidato autocontenido

```bash
git bundle verify custody/candidate.bundle
git clone -b evidence-candidate custody/candidate.bundle recovered-candidate
git -C recovered-candidate checkout --detach 7df4935f769a2e393a5e6a6330df605c77592e52
git -C recovered-candidate cat-file -t 7df4935f769a2e393a5e6a6330df605c77592e52
git -C recovered-candidate rev-parse 'HEAD^{tree}'
git -C recovered-candidate status --porcelain=v1
(cd recovered-candidate && sha256sum -c ../metadata/candidate-files.sha256)
```

Recuperación alternativa del árbol, sin metadatos Git:

```bash
mkdir recovered-archive
tar -xzf custody/candidate-tree.tar.gz -C recovered-archive
(cd recovered-archive/candidate && sha256sum -c ../../metadata/candidate-files.sha256)
```
