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
    await expect(runtime.locator('.settings-toggle')).toContainText('勾選後一定要按「儲存模型/上限」')

    await runtime.getByRole('checkbox', { name: '顯示訂閱 CLI 模型' }).check()
    await expect(runtime.locator('.cli-model-notice')).toContainText('設定尚未儲存：CLI 尚未生效')
    await expect(runtime.locator('.cli-model-notice')).toContainText('請按下方「儲存模型/上限」')
    await expect(runtime.locator('.settings-toggle')).toContainText('已變更但尚未生效')
    await expect(runtime.getByRole('button', { name: '儲存模型/上限' })).toBeVisible()
  } finally {
    fixture.cleanup()
  }
})

test('settings keeps a fixed three-provider CLI inventory with states', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-cli-inventory')
  await page.route('**/api/app/model-options', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        translate: [{ id: 'cli:claude', label: 'Claude CLI', provider: 'cli' }],
        summary: [{ id: 'cli:claude', label: 'Claude CLI', provider: 'cli' }],
        providers: ['llamacpp', 'openai', 'anthropic', 'google', 'cli'],
        cli_inventory: [
          { id: 'claude', label: 'Claude CLI', state: 'available', state_label: '可用', selectable: true, recovery: '可直接使用' },
          { id: 'codex', label: 'Codex CLI', state: 'not_installed', state_label: '未安裝', selectable: false, recovery: '請先安裝 Codex CLI' },
          { id: 'gemini', label: 'Gemini CLI', state: 'call_failed', state_label: '未登入／呼叫失敗', selectable: false, recovery: '請確認登入狀態或重試' },
        ],
      }),
    })
  })
  try {
    await openApp(page, fixture)
    await page.getByRole('button', { name: '設定' }).click()
    const inventory = page.getByTestId('cli-inventory')
    await expect(inventory).toBeVisible()
    await expect(inventory).toContainText('Claude CLI')
    await expect(inventory).toContainText('Codex CLI')
    await expect(inventory).toContainText('Gemini CLI')
    await expect(inventory).toContainText('可用')
    await expect(inventory).toContainText('未安裝')
    await expect(inventory).toContainText('未登入／呼叫失敗')
  } finally {
    fixture.cleanup()
  }
})

test('settings shows cost status unknown when the backend summary is unavailable', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-cost-summary-down')
  await page.route('**/api/app/cost-summary', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'backend unavailable' }),
    })
  })
  try {
    await openApp(page, fixture)
    await page.getByRole('button', { name: '設定' }).click()
    await expect(page.locator('.settings-command')).toContainText('成本狀態未知')
    await expect(page.locator('.cost-panel')).toContainText('狀態未知')
    await expect(page.locator('.cost-panel')).toContainText('無法確認')
  } finally {
    fixture.cleanup()
  }
})

test('one CLI model registry reaches video, article, and meeting selectors', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-cli-lanes')
  await page.route('**/api/app/model-options', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        translate: [{ id: 'cli:claude', label: 'Claude（訂閱）', provider: 'cli' }],
        summary: [{ id: 'cli:claude', label: 'Claude（訂閱）', provider: 'cli' }],
        providers: ['openai', 'anthropic', 'google', 'cli'],
        cli_inventory: [{ id: 'cli:claude', label: 'Claude（訂閱）', state: 'available', state_label: '可用', selectable: true, recovery: '可直接選用' }],
      }),
    })
  })
  try {
    await openApp(page, fixture)
    const assertPicker = async (section) => {
      const picker = page.locator(section).locator('.summary-model-pick')
      await picker.locator('.model-select-toggle').click()
      await expect(picker.locator('[role="listbox"]')).toContainText('cli:claude')
      await page.keyboard.press('Escape')
    }
    await assertPicker('.capture-workbench:visible')
    await page.locator('.ingest-lanes').getByRole('button', { name: '文章網址' }).click()
    await assertPicker('.article-workbench:visible')
    await page.locator('.ingest-lanes').getByRole('button', { name: '會議筆記音檔' }).click()
    await assertPicker('.voice-workbench:visible')
  } finally {
    fixture.cleanup()
  }
})
