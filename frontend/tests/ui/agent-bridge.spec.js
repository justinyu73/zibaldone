import { test, expect } from '@playwright/test'
import { makeVault, openApp } from './fixture.js'

let fixture

test.beforeEach(() => { fixture = makeVault('ytapp-e2e-agent-bridge') })
test.afterEach(() => fixture.cleanup())

test('settings generates a local Agent Bridge index without rewriting source notes', async ({ page }) => {
  const original = fixture.read('02_Sources/youtube/e2e_video.md')
  await openApp(page, fixture)
  await page.getByRole('button', { name: '設定' }).click()

  const panel = page.locator('.agent-index-panel')
  await expect(panel).toBeVisible()
  await expect(panel.getByText('尚未建立')).toBeVisible()
  await panel.getByRole('button', { name: '產生／更新 Agent 索引' }).click()

  await expect(panel).toContainText('Agent 索引已更新')
  expect(fixture.exists('_zibaldone/agent-index/index.md')).toBe(true)
  expect(fixture.exists('_zibaldone/agent-index/manifest.json')).toBe(true)
  expect(fixture.read('02_Sources/youtube/e2e_video.md')).toBe(original)
  expect(fixture.read('_zibaldone/agent-index/index.md')).toContain('E2E 測試影片筆記')
})
