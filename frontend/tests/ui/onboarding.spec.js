import { test, expect } from '@playwright/test'
import { makeVault } from './fixture.js'

let fixture

test.beforeAll(() => {
  fixture = makeVault('ytapp-e2e-onboarding')
})

test.afterAll(() => {
  fixture.cleanup()
})

test('first-run setup is optional, read-only, persistent, and reopenable', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' })

  const dialog = page.getByRole('dialog', { name: '資料與連線' })
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: '下一步' }).click()

  const vaultDialog = page.getByRole('dialog', { name: '筆記庫位置' })
  await expect(vaultDialog).toBeVisible()
  await vaultDialog.getByLabel('筆記庫根目錄').fill(fixture.vault)
  await vaultDialog.getByRole('button', { name: '下一步' }).click()

  const routeDialog = page.getByRole('dialog', { name: '處理路線' })
  await expect(routeDialog).toBeVisible()
  await expect(routeDialog.getByRole('button', { name: /先用免費路線/ })).toHaveAttribute('aria-pressed', 'true')
  await routeDialog.getByRole('button', { name: '下一步' }).click()

  // 本機 AI 步驟：內建 llama.cpp 各狀態（選配未裝 / 下載中 / 就緒）都可直接略過
  const llmDialog = page.getByRole('dialog', { name: '本機 AI' })
  await expect(llmDialog).toBeVisible()
  await expect(llmDialog.getByText(/非 Ollama/)).toBeVisible()
  await expect(llmDialog.getByText(/訂閱 CLI 不下載/)).toBeVisible()
  await expect(llmDialog.getByText(/本機 AI（非 Ollama）|內建本機 AI 就緒|下載.*中/)).toBeVisible()
  await llmDialog.getByRole('button', { name: '下一步' }).click()

  const checkDialog = page.getByRole('dialog', { name: '環境確認' })
  await expect(checkDialog).toBeVisible()
  await expect(checkDialog.getByText('可讀寫')).toBeVisible()
  await expect(checkDialog.getByText('環境檢查為唯讀')).toBeVisible()
  await checkDialog.getByRole('button', { name: /完成設定/ }).click()
  await expect(checkDialog).toBeHidden()

  const stored = await page.evaluate(() => ({
    marker: localStorage.getItem('yt_first_run_setup_v1'),
    route: localStorage.getItem('yt_first_run_route_v1'),
    settings: JSON.parse(localStorage.getItem('yt_product_settings_v3')),
  }))
  expect(stored.marker).toBe('complete')
  expect(stored.route).toBe('local')
  expect(stored.settings.vaultRoot).toBe(fixture.vault)

  await page.getByRole('button', { name: '設定' }).click()
  await page.getByRole('button', { name: '重新開啟首次設定' }).click()
  await expect(page.getByRole('dialog', { name: '資料與連線' })).toBeVisible()
  await page.getByRole('button', { name: '稍後設定' }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
})

test('first-run setup can be skipped without a provider key', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  const dialog = page.getByRole('dialog', { name: '資料與連線' })
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect.poll(() => page.evaluate(() => localStorage.getItem('yt_first_run_setup_v1'))).toBe('skipped')
})

test('built-in local AI download can be skipped for this setup', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' })
  const dialog = page.getByRole('dialog', { name: '資料與連線' })
  await dialog.getByRole('button', { name: '下一步' }).click()
  const vaultDialog = page.getByRole('dialog', { name: '筆記庫位置' })
  await vaultDialog.getByLabel('筆記庫根目錄').fill(fixture.vault)
  await vaultDialog.getByRole('button', { name: '下一步' }).click()
  await page.getByRole('dialog', { name: '處理路線' }).getByRole('button', { name: '下一步' }).click()

  const llmDialog = page.getByRole('dialog', { name: '本機 AI' })
  await expect(llmDialog.getByRole('button', { name: /跳過，本次不下載/ })).toBeVisible()
  await llmDialog.getByRole('button', { name: /跳過，本次不下載/ }).click()

  const checkDialog = page.getByRole('dialog', { name: '環境確認' })
  await expect(checkDialog).toBeVisible()
  await expect(checkDialog.getByRole('button', { name: /完成設定/ })).toBeEnabled()
  await checkDialog.getByRole('button', { name: /完成設定/ }).click()
  await expect(checkDialog).toBeHidden()
})
