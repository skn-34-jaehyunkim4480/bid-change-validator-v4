import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  // Keep all mocked-browser suites serial against one vinext dev server in CI.
  workers: process.env.CI ? 1 : undefined,
  retries: 0,
  reporter: [['list']],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://[::1]:3200',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'corepack pnpm dev --host ::1 --port 3200',
    url: 'http://[::1]:3200/login',
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_API_BASE_URL: 'http://[::1]:3200',
      NEXT_PUBLIC_ML_E2E_MOCK: 'true',
    },
  },
});
