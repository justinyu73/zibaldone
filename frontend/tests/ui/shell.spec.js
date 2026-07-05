import { test, expect } from '@playwright/test'
import { makeVault, openApp } from './fixture.js'

const TABS = ['收錄', '收件匣', '筆記庫', '成本監控', '退場', '設定']

let fixture
test.beforeAll(() => { fixture = makeVault('ytapp-e2e-shell') })
test.afterAll(() => fixture.cleanup())

test('shell renders all tabs and switches', async ({ page }) => {
  await openApp(page, fixture)
  for (const label of TABS) {
    const btn = page.locator(`nav.side-nav button[aria-label="${label}"]`)
    await expect(btn).toBeVisible()
    await btn.click()
    await expect(page.locator('.content-head h2')).toHaveText(label)
  }
})

// Regression for audit U1: 821–1134px used to overflow horizontally on every tab
// (Tauri minWidth 980 sat inside the band).
for (const width of [980, 1280]) {
  test(`no horizontal overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await openApp(page, fixture)
    for (const label of TABS) {
      await page.click(`nav.side-nav button[aria-label="${label}"]`)
      await page.waitForTimeout(150)
      const m = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        client: document.documentElement.clientWidth,
      }))
      expect(m.scroll, `${label} @${width}px`).toBeLessThanOrEqual(m.client)
    }
  })
}
