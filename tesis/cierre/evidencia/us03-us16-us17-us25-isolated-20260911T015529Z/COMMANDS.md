# Exact reproduction

```bash
scripts/run-isolated-acceptance-lab.sh
```

The script builds the frontend and isolated images, runs the live key rotation, executes each Playwright case individually, then executes the ordered combined suite. A trap always removes the isolated containers, network, volumes, PKI, agent state, baseline, and temporary watch directory.

Directed checks captured in this package:

```bash
TEST_DATABASE_URL='postgresql+psycopg://fim:test@127.0.0.1:<ephemeral-port>/fim_test' backend/.venv/bin/pytest -q backend/tests/test_auth.py backend/tests/test_actions.py backend/tests/test_actions_router.py
cd frontend && pnpm exec vitest run src/api/auth.test.ts src/api/actions.test.ts src/components/ui/BulkActionBar.test.tsx src/components/ui/RuleForm.test.tsx src/stores/auth.store.test.ts src/components/layout/Navbar.test.tsx src/config/viteProxy.test.ts
cd frontend && pnpm run build
```
