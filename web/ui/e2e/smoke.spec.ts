// Smoke tests of the whole dashboard in a real browser (playwright.config.ts). Read-only: nothing is saved or sent.
import { expect, test, type Page } from '@playwright/test'

const PAGES: [string, RegExp][] = [
  ['/', /Overview|Market/i], ['/today', /Today/], ['/watchlist', /Watchlist/], ['/scans', /Scans/], ['/builder', /Strategy builder/],
  ['/chart/RELIANCE', /RELIANCE/], ['/charts', /Multi-chart/], ['/portfolio', /Portfolio/], ['/orders', /Orders/],
  ['/sim', /Practice/], ['/replay', /Replay/], ['/coach', /Coach/], ['/paper', /Paper/], ['/benchmarks', /Benchmarks/],
  ['/strategies', /Strategies/], ['/signals', /Signals/], ['/calendar', /Market calendar/], ['/tax', /Tax harvesting/],
  ['/risk', /Portfolio risk/], ['/option-builder', /Option strategy builder/], ['/setups', /Live setups/], ['/journal', /Trade journal/],
  ['/options-backtest', /Options backtester/],
]

async function open(page: Page, path: string) {
  await page.addInitScript(() => { try { localStorage.setItem('qd.disclaimerSeen', 'true') } catch { /* private mode */ } })
  await page.goto(path)
}

test('every page renders without a script error', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(`${page.url()}: ${e.message}`))
  for (const [path, title] of PAGES) {
    await open(page, path)
    await expect(page.locator('main')).toContainText(title, { timeout: 30_000 })
  }
  expect(errors).toEqual([])
})

test('replay reveals one bar at a time', async ({ page }) => {
  await open(page, '/replay')
  await page.getByRole('button', { name: 'Start' }).click()
  await expect(page.locator('main')).toContainText(/bar 1 of \d+/, { timeout: 30_000 })
  for (let i = 0; i < 3; i++) await page.keyboard.press('ArrowRight')
  await expect(page.locator('main')).toContainText(/bar 4 of \d+/)
})

test('chart types switch to Renko and back', async ({ page }) => {
  await open(page, '/chart/RELIANCE')
  await expect(page.locator('main canvas').first()).toBeVisible({ timeout: 30_000 })   // the daily chart has loaded
  const type = page.getByRole('combobox', { name: 'Chart type' })
  await type.selectOption('renko')
  await expect(page.locator('main')).toContainText(/Renko: a \d% brick/, { timeout: 20_000 })
  await type.selectOption('candles')
})

test('the practice order ticket opens without sending anything', async ({ page }) => {
  await open(page, '/sim')
  await page.getByRole('textbox', { name: 'Stock' }).fill('RELIANCE')
  await page.getByRole('button', { name: 'Buy', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('practice')
  await expect(dialog.getByRole('radio', { name: /Practice/ })).toHaveAttribute('aria-checked', 'true')
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toHaveCount(0)
})

test('the strategy builder tests the sample strategy', async ({ page }) => {
  await open(page, '/builder')
  await page.getByRole('button', { name: 'Test 8 years' }).click()
  await expect(page.locator('main')).toContainText('Test result', { timeout: 80_000 })
  await expect(page.locator('main')).toContainText(/CAGR/)
})
