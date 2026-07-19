import { test, expect } from '@playwright/test'
import { makeVault, openApp } from './fixture.js'

test('video draft generation locks note write until the draft is ready', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-draft-gate')
  try {
    await page.route('**/estimate-source', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        estimate_quick: { estimated_usd: 0.001 },
        estimate_deep: { estimated_usd: 0.002 },
        estimate_translate: { estimated_usd: 0 },
      }),
    }))
    await page.route('**/fetch', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        url: 'https://www.youtube.com/watch?v=e2e-gate-01',
        video_id: 'e2e-gate-01',
        meta: { title: 'E2E 草稿閘門', channel: 'E2E' },
        transcript: { en_text: 'source transcript', zh_text: '來源字幕', available_langs: ['en', 'zh-TW'] },
        existing: false,
      }),
    }))

    let releaseSummary
    const summaryPending = new Promise((resolve) => { releaseSummary = resolve })
    await page.route('**/summarize', async (route) => {
      await summaryPending
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ summary: { title: 'E2E 草稿閘門', summary: '完成' } }),
      })
    })

    await openApp(page, fixture)
    await page.click('nav.side-nav button[aria-label="收錄"]')
    const video = page.locator('.capture-workbench')
    await video.getByLabel('YouTube 網址或影片 ID').fill('https://www.youtube.com/watch?v=e2e-gate-01')
    await video.getByRole('button', { name: '預覽' }).click()
    await video.getByRole('button', { name: '抓取字幕' }).click()
    await expect(video.getByRole('button', { name: '生成草稿' })).toBeEnabled()

    const save = video.getByRole('button', { name: '存入筆記' })
    await video.getByRole('button', { name: '生成草稿' }).click()
    await expect(video.getByRole('button', { name: '生成中...' })).toBeVisible()
    await expect(save).toBeDisabled()

    releaseSummary()
    await expect(video.getByRole('button', { name: '存入筆記' })).toBeEnabled()
  } finally {
    fixture.cleanup()
  }
})
