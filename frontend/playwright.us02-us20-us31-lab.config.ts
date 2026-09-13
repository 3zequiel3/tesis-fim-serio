import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'

if (!process.env.FIM_LAB_BASE_URL || !process.env.FIM_E2E_RUN_DIR) {
  throw new Error('FIM_LAB_BASE_URL and FIM_E2E_RUN_DIR are required')
}

export default defineConfig({
  testDir: './e2e',
  testMatch: [
    'us02-logout.spec.ts',
    'us20-realtime-alerts.spec.ts',
    'us31-superseded-toggle.spec.ts',
  ],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 150_000,
  expect: { timeout: 20_000 },
  outputDir: path.join(path.resolve(process.env.FIM_E2E_RUN_DIR), 'artifacts'),
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(path.resolve(process.env.FIM_E2E_RUN_DIR), 'playwright-results.json') }],
    ['junit', { outputFile: path.join(path.resolve(process.env.FIM_E2E_RUN_DIR), 'playwright-junit.xml') }],
  ],
  use: {
    baseURL: process.env.FIM_LAB_BASE_URL,
    // Closure evidence intentionally retains text reporters only. Browser
    // traces, screenshots and video can persist ephemeral fixture identifiers
    // in binary resources that cannot be audited or redacted reliably.
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    ...devices['Desktop Chrome'],
  },
})
