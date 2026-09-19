import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'

const evidenceRoot = process.env.FIM_E2E_RUN_DIR
  ? path.resolve(process.env.FIM_E2E_RUN_DIR)
  : path.resolve('../tesis/cierre/evidencia/playwright-local')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  expect: { timeout: 8_000 },
  outputDir: path.join(evidenceRoot, 'artifacts'),
  webServer: {
    command: 'VITE_API_URL=/api pnpm exec vite --config e2e/vite.e2e.config.ts --host 127.0.0.1 --port 4173',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false,
    timeout: 30_000,
  },
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(evidenceRoot, 'playwright-results.json') }],
    ['junit', { outputFile: path.join(evidenceRoot, 'playwright-junit.xml') }],
  ],
  use: {
    baseURL: process.env.FIM_E2E_BASE_URL ?? 'http://127.0.0.1:4173',
    trace: 'on',
    screenshot: 'on',
    video: 'on',
    actionTimeout: 8_000,
    navigationTimeout: 15_000,
    ...devices['Desktop Chrome'],
  },
})
