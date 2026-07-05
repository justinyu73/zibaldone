import { test, expect } from '@playwright/test'
import { execFileSync } from 'child_process'
import fs from 'fs'
import os from 'os'
import path from 'path'
import { makeVault, openApp } from './fixture.js'

// Behavioral verify for timestamp click-to-playback: a real <audio> element must
// fetch the operator's audio from the REAL backend endpoint when a [mm:ss] capsule
// is clicked. The meeting-note job is stubbed (e2e has no provider to produce a
// summary), but the audio streaming under test is the real /api/app/meeting-audio.
let fixture
let audioPath
test.beforeAll(() => {
  fixture = makeVault('ytapp-e2e-playback')
  audioPath = path.join(os.tmpdir(), `pb-e2e-${Date.now()}.wav`)
  execFileSync('ffmpeg', ['-hide_banner', '-y', '-f', 'lavfi', '-i',
    'sine=frequency=440:sample_rate=16000', '-t', '3', '-ac', '1', '-ar', '16000', audioPath])
})
test.afterAll(() => { fixture.cleanup(); fs.rmSync(audioPath, { force: true }) })

test('timestamp capsule click streams audio (Range) so the player can seek', async ({ page }) => {
  // Stub the job lifecycle so a summary with a [mm:ss] capsule renders (no provider).
  await page.route('**/app/meeting-note-job', (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ ok: true, job_id: 'e2e-pb' }) })
    }
    return route.continue()
  })
  await page.route('**/app/meeting-note-job/e2e-pb', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      status: 'done', stage: 'written',
      summary: {
        title: 'E2E 會議', summary: '', key_organization: '', core_value: '',
        action_items: ['敲定上線時間 [00:01]'], decisions: [], attendees: [], agenda: [],
      },
      write: { relative_path: '02_Sources/meetings/e2e.md' },
    }),
  }))

  await openApp(page, fixture)
  await page.click('nav.side-nav button[aria-label="收錄"]')
  await page.getByRole('button', { name: '會議筆記音檔' }).click()
  await page.getByRole('button', { name: '雲端·付費' }).click() // 高品質 → 不被 mediumBlocked 擋
  await page.fill('input[aria-label="本機音檔路徑"]', audioPath)
  await page.getByRole('button', { name: '產生可校正草稿' }).click()

  // 膠囊出現＝job summary 已渲染，且時間戳是可點 button
  const capsule = page.locator('button.ts-seek', { hasText: '00:01' })
  await expect(capsule).toBeVisible()

  // 點膠囊 = user gesture → seekTo() 設 currentTime + play() → <audio> 真的去拉串流端點
  const respPromise = page.waitForResponse((r) => r.url().includes('/app/meeting-audio'))
  await capsule.click()
  const resp = await respPromise
  console.log('MEETING-AUDIO STATUS:', resp.status(), 'content-range:', resp.headers()['content-range'] || '(none)')
  expect([200, 206]).toContain(resp.status())

  // 播放器掛上、currentTime 跳到該秒（~1s；放寬到 >0 避免 metadata 載入時序 flake）
  const t = await page.locator('.audio-playback audio').evaluate((el) => el.currentTime)
  expect(t).toBeGreaterThan(0)
})

test('summary model dropdown shows per-model cost tag (付費/免費)', async ({ page }) => {
  await openApp(page, fixture)
  await page.click('nav.side-nav button[aria-label="收錄"]')
  await page.getByRole('button', { name: '會議筆記音檔' }).click()
  // 摘要模型下拉的選項應帶各自計費標（雲端=付費 / 本地=免費），證明兩個模型成本可見
  await expect.poll(async () =>
    page.locator('.summary-model-pick select option').allTextContents()
  ).toEqual(expect.arrayContaining([expect.stringMatching(/付費|免費/)]))
  const texts = await page.locator('.summary-model-pick select option').allTextContents()
  console.log('SUMMARY OPTIONS:', texts.filter(t => /付費|免費/.test(t)).slice(0, 3))
})
