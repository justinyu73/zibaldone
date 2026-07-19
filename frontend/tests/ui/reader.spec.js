import { test, expect } from '@playwright/test'
import { makeVault, openApp } from './fixture.js'

let fixture
test.beforeAll(() => { fixture = makeVault('ytapp-e2e-reader') })
test.afterAll(() => fixture.cleanup())

test('library reading view renders markdown as HTML (callout/table/code/details)', async ({ page }) => {
  await openApp(page, fixture)
  await page.click('nav.side-nav button[aria-label="筆記庫"]')
  await page.locator('.library-workbench .list-item', { hasText: 'E2E 測試影片筆記' }).click()

  const reader = page.locator('.library-workbench .note-reader')
  await expect(reader).toBeVisible()
  await expect(reader.locator('.md-callout')).toBeVisible()
  await expect(reader.locator('table td').first()).toHaveText('A')
  await expect(reader.locator('pre code')).toContainText('print')
  const summary = reader.locator('details summary')
  await expect(summary).toHaveText('英文逐字稿')
  await summary.click()
  await expect(reader.locator('details')).toContainText('transcript body')

  // toggle back to the structured-fields view
  await page.click('.library-workbench button:has-text("欄位")')
  await expect(page.locator('.library-workbench .read-view')).toBeVisible()
})
