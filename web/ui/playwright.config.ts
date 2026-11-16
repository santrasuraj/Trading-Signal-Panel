// End-to-end browser tests (e2e/): the built dashboard served by the real API on its own port, driven in the Chrome (or
// Microsoft Edge) installed on this PC, so no browser download is needed. Read-only against your data: they open
// pages and dialogs but never place an order, save a drawing or finish a replay with trades.
//   npm run build            (the tests use web/ui/dist)
//   npm run e2e              (QD_E2E_CHANNEL=msedge / chrome to pick the browser)
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from '@playwright/test'

const PORT = Number(process.env.QD_E2E_PORT || 8620)
const root = resolve(process.cwd(), '..', '..')                     // the checkout (web/ui -> ../..)
const chrome = ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe']
  .some((p) => existsSync(p))
const python = [resolve(root, '.venv/Scripts/python.exe'), resolve(root, '../../.venv/Scripts/python.exe')]
  .find((p) => existsSync(p)) ?? 'python'

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: process.env.QD_E2E_CHANNEL || (chrome ? 'chrome' : 'msedge'),
    headless: true,
    viewport: { width: 1400, height: 900 },
  },
  webServer: {
    command: `"${python}" -m uvicorn web.api.main:app --host 127.0.0.1 --port ${PORT} --app-dir "${root}"`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: true,
    timeout: 180_000,
  },
})
