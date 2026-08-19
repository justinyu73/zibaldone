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

test('video OCR can create an editable draft when AI routes are not configured', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-no-ai-draft')
  try {
    await page.route('**/estimate-source', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ estimate_quick: { estimated_usd: 0 }, estimate_deep: { estimated_usd: 0 }, estimate_translate: { estimated_usd: 0 } }),
    }))
    await page.route('**/fetch', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        ok: true, url: 'https://www.youtube.com/watch?v=e2e-no-ai01', video_id: 'e2e-no-ai01',
        meta: { title: '無 AI OCR 草稿', channel: 'E2E' },
        transcript: { en_text: '', zh_text: '', available_langs: [] }, existing: false,
      }),
    }))
    await page.route('**/app/ffmpeg/status', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ ready: true }),
    }))
    // Pin "no key configured" explicitly — otherwise this test's OCR click
    // would depend on whatever OPENAI_API_KEY happens to be set in the real
    // spawned E2E backend's ambient environment.
    await page.route('**/provider-runtime/status', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ openai_api_key_present: false }),
    }))
    await page.route('**/production-extractor', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ provider: 'local', ocr_text: '硬字幕第一句\n硬字幕第二句' }),
    }))
    let translateCalls = 0
    await page.route('**/translate', (route) => {
      translateCalls += 1
      return route.fulfill({
        status: 502, contentType: 'application/json',
        body: JSON.stringify({ detail: '翻譯不應在中文 OCR 時被呼叫' }),
      })
    })
    await page.route('**/summarize', (route) => route.fulfill({
      status: 400, contentType: 'application/json',
      body: JSON.stringify({ detail: 'openai API 金鑰未設定；AI 摘要已停用' }),
    }))

    await openApp(page, fixture)
    await page.click('nav.side-nav button[aria-label="收錄"]')
    const video = page.locator('.capture-workbench')
    await video.getByLabel('YouTube 網址或影片 ID').fill('https://www.youtube.com/watch?v=e2e-no-ai01')
    await video.getByRole('button', { name: '預覽' }).click()
    await video.getByRole('button', { name: '抓取字幕' }).click()
    await video.getByRole('button', { name: '讀畫面硬字幕（OCR）' }).click()
    await video.getByRole('button', { name: '生成草稿' }).click()

    expect(translateCalls).toBe(0)
    await video.getByRole('tab', { name: /主題摘要/ }).click()
    await expect(video.locator('textarea[aria-label="主題摘要"]')).toHaveValue(/待人工整理：硬字幕第一句 硬字幕第二句/)
    await expect(video.getByText('已建立待人工整理草稿；若要 AI 翻譯與摘要，請到設定下載內建本機 AI，或填入對應 API 金鑰。')).toBeVisible()
    await expect(video.getByRole('button', { name: '存入筆記' })).toBeEnabled()
  } finally {
    fixture.cleanup()
  }
})

test('video OCR asks for upload consent before calling cloud OCR when a key is configured', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-ocr-consent')
  try {
    await page.route('**/estimate-source', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ estimate_quick: { estimated_usd: 0 }, estimate_deep: { estimated_usd: 0 }, estimate_translate: { estimated_usd: 0 } }),
    }))
    await page.route('**/fetch', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        ok: true, url: 'https://www.youtube.com/watch?v=e2e-ocr-consent01', video_id: 'e2e-ocr-consent01',
        meta: { title: '雲端 OCR 同意測試', channel: 'E2E' },
        transcript: { en_text: '', zh_text: '', available_langs: [] }, existing: false,
      }),
    }))
    await page.route('**/app/ffmpeg/status', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ ready: true }),
    }))
    // Simulates OPENAI_API_KEY being configured: production_extractor.py would
    // route this OCR call to cloud vision — the frontend must ask first.
    await page.route('**/provider-runtime/status', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ openai_api_key_present: true }),
    }))
    let extractorCalls = 0
    await page.route('**/production-extractor', (route) => {
      extractorCalls += 1
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ provider: 'openai', ocr_text: '雲端硬字幕文字' }),
      })
    })

    await openApp(page, fixture)
    await page.click('nav.side-nav button[aria-label="收錄"]')
    const video = page.locator('.capture-workbench')
    await video.getByLabel('YouTube 網址或影片 ID').fill('https://www.youtube.com/watch?v=e2e-ocr-consent01')
    await video.getByRole('button', { name: '預覽' }).click()
    await video.getByRole('button', { name: '抓取字幕' }).click()
    await video.getByRole('button', { name: '讀畫面硬字幕（OCR）' }).click()

    // Consent must appear before any upload — production-extractor must not
    // have fired yet.
    const consent = video.locator('.ocr-consent-ask')
    await expect(consent).toBeVisible()
    expect(extractorCalls).toBe(0)

    // Cancel must not send anything either.
    await consent.getByRole('button', { name: '取消' }).click()
    await expect(consent).toBeHidden()
    expect(extractorCalls).toBe(0)

    // Re-open and confirm: only now may the upload fire.
    await video.getByRole('button', { name: '讀畫面硬字幕（OCR）' }).click()
    await video.locator('.ocr-consent-ask').getByRole('button', { name: '確認上傳並讀取' }).click()
    await expect(video.getByText(/已用雲端畫面 OCR/)).toBeVisible()
    expect(extractorCalls).toBe(1)
  } finally {
    fixture.cleanup()
  }
})
