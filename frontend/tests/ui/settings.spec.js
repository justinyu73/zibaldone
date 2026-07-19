import { test, expect } from '@playwright/test'
import { makeVault, openApp } from './fixture.js'

test('settings explains why subscription CLI models are hidden', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-cli-guidance')
  try {
    await openApp(page, fixture)
    await page.getByRole('button', { name: '設定' }).click()

    const runtime = page.locator('.cost-panel')
    await expect(runtime.locator('.cli-model-notice')).toContainText('目前未啟用')
    await expect(runtime.locator('.cli-model-notice')).toContainText('CLI 不會出現在上方的翻譯／摘要模型清單')
    await expect(runtime.getByRole('checkbox', { name: '顯示訂閱 CLI 模型' })).toBeVisible()
    await expect(runtime.locator('.settings-toggle')).toContainText('勾選後按「儲存模型/上限」')
  } finally {
    fixture.cleanup()
  }
})
