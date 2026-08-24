import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig, devices } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const rootDir = path.resolve(__dirname, '..')

export default defineConfig({
  testDir: './tests',
  timeout: 60000,
  use: {
    baseURL: 'http://127.0.0.1:8092',
    trace: 'retain-on-failure',
  },
  webServer: {
    command:
      "bash -lc '. .venv/bin/activate && EVENT_RADAR_START_COLLECTORS=false EVENT_RADAR_APP_PORT=8092 EVENT_RADAR_DATABASE_PATH=var/event_radar_playwright.db python -m uvicorn event_radar.main:app --host 127.0.0.1 --port 8092'",
    cwd: rootDir,
    url: 'http://127.0.0.1:8092/healthz',
    reuseExistingServer: true,
    timeout: 120000,
  },
  projects: [
    { name: 'chromium-1728x827', use: { ...devices['Desktop Chrome'], viewport: { width: 1728, height: 827 } } },
    { name: 'chromium-2304x1151', use: { ...devices['Desktop Chrome'], viewport: { width: 2304, height: 1151 } } },
    { name: 'chromium-3096x1151', use: { ...devices['Desktop Chrome'], viewport: { width: 3096, height: 1151 } } },
    { name: 'firefox-tablet', use: { ...devices['Desktop Firefox'], viewport: { width: 1024, height: 900 } } },
    { name: 'webkit-mobile', use: { ...devices['iPhone 13'] } },
  ],
})
