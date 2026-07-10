import os from 'os'
import path from 'path'
import { test, expect } from '@playwright/test'
import { makeVault, openApp } from './fixture.js'

test('cost monitor switches one range at a time and reveals custom dates on demand', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-cost')
  try {
    await page.setViewportSize({ width: 980, height: 800 })
    await openApp(page, fixture)
    await page.click('nav.side-nav button[aria-label="成本監控"]')
    const monitor = page.locator('.cost-monitor')

    await expect(monitor.getByRole('button', { name: '當月' })).toHaveAttribute('aria-pressed', 'true')
    await expect(monitor.locator('.cost-kpis')).toHaveCount(1)
    await expect(monitor.locator('.cost-viewbar')).toHaveCount(1)
    await expect(monitor.getByLabel('起始日')).toHaveCount(0)

    await monitor.getByRole('button', { name: '當天' }).click()
    await expect(monitor.getByRole('button', { name: '當天' })).toHaveAttribute('aria-pressed', 'true')
    await expect(monitor.locator('.cost-kpis')).toHaveCount(1)

    await monitor.getByRole('button', { name: '自訂' }).click()
    await expect(monitor.getByLabel('起始日')).toBeVisible()
    await expect(monitor.getByLabel('結束日')).toBeVisible()
    await monitor.getByLabel('起始日').fill('2026-06-01')
    await monitor.getByLabel('結束日').fill('2026-07-01')
    await monitor.getByRole('button', { name: '查詢' }).click()
    await expect(monitor.locator('.cost-kpis')).toHaveCount(1)
    await expect(monitor.locator('.cost-viewbar')).toContainText('自訂 2026-06-01 至 2026-07-01')
    await page.screenshot({ path: path.join(os.tmpdir(), 'ytapp-cost-range-980.png'), fullPage: true })
  } finally { fixture.cleanup() }
})
