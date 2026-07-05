import { test, expect } from '@playwright/test'
import { execFileSync } from 'child_process'
import fs from 'fs'
import os from 'os'
import path from 'path'
import { makeVault, openApp } from './fixture.js'

let fixture
let audioPath
let audioPath2

test.beforeAll(() => {
  fixture = makeVault('ytapp-e2e-personal-expansion')
  audioPath = path.join(os.tmpdir(), `personal-expansion-${Date.now()}.wav`)
  audioPath2 = path.join(os.tmpdir(), `personal-expansion-2-${Date.now()}.wav`)
  execFileSync('ffmpeg', ['-hide_banner', '-y', '-f', 'lavfi', '-i',
    'sine=frequency=440:sample_rate=16000', '-t', '4', '-ac', '1', '-ar', '16000', audioPath])
  fs.copyFileSync(audioPath, audioPath2)
  const meetings = path.join(fixture.vault, '02_Sources/meetings')
  fs.mkdirSync(meetings, { recursive: true })
  fs.writeFileSync(path.join(meetings, 'e2e_meeting.md'), `---
type: source
source: meeting
title: E2E 可回放會議
created: 2026-07-01
audio_source: ${path.basename(audioPath)}
audio_path: ${audioPath}
tags: [type/source, source/meeting]
---

# E2E 可回放會議

## 音檔來源
[${path.basename(audioPath)}](file://${audioPath})
位置：${path.dirname(audioPath)}/

## 摘要
驗證舊筆記回放。

## 決議
- 採用人工校正草稿 [00:01]

## 逐字稿
[00:01] 採用人工校正草稿
`)
})

test.afterAll(() => {
  fixture.cleanup()
  fs.rmSync(audioPath, { force: true })
  fs.rmSync(audioPath2, { force: true })
})

async function assertNoPageOverflow(page) {
  const size = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }))
  expect(size.scroll).toBeLessThanOrEqual(size.client)
}

test('review-ready draft is editable and stable at desktop and narrow widths', async ({ page }) => {
  await page.route('**/app/meeting-note-job', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true, job_id: 'e2e-review' }),
  }))
  await page.route('**/app/meeting-note-job/e2e-review', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      job_id: 'e2e-review', status: 'review_ready', stage: 'review_ready', audio_path: audioPath,
      transcript: Array.from({ length: 900 }, (_, index) => `[${String(Math.floor(index / 2)).padStart(2, '0')}:${index % 2 ? '30' : '00'}] 長會議逐字稿第 ${index + 1} 段`).join('\n'), write: null,
      summary: {
        title: 'E2E 校正草稿', summary: '待人工確認',
        key_organization: '保留證據鏈 [00:01]', core_value: '避免錯誤入庫 [00:01]',
        action_items: ['完成視覺驗收 [00:01]'], decisions: ['採用人工校正 [00:01]'],
        attendees: ['JY'], agenda: ['驗收 [00:01]'],
      },
    }),
  }))

  await page.setViewportSize({ width: 1440, height: 1000 })
  await openApp(page, fixture)
  await page.click('nav.side-nav button[aria-label="收錄"]')
  await page.getByRole('button', { name: '會議筆記音檔' }).click()
  const costRoute = page.locator('.voice-workbench .processing-cost-route')
  await expect(costRoute).toContainText('轉錄：本機・免費')
  await expect(costRoute).toContainText(/摘要：.+・雲端・付費/)
  const modelOptions = await page.locator('.voice-workbench .summary-model-pick select option').allTextContents()
  expect(modelOptions[0]).toMatch(/^gpt-5\.2（推薦） · 付費$/)
  await page.getByRole('button', { name: '雲端·付費' }).click()
  await expect(costRoute).toContainText('轉錄：雲端・付費')
  await page.fill('input[aria-label="本機音檔路徑"]', audioPath)
  await page.getByRole('button', { name: '產生可校正草稿' }).click()
  await expect(page.locator('.meeting-review-editor')).toBeVisible()
  await expect(page.locator('.progress-step')).toHaveCount(5)
  await expect(page.locator('.meeting-review-editor textarea:visible')).toHaveCount(1)
  const reviewOverflow = await page.locator('.voice-result.review-mode').evaluate((element) => getComputedStyle(element).overflowY)
  expect(reviewOverflow).toBe('visible')
  await page.getByRole('button', { name: '逐字稿', exact: true }).click()
  await expect(page.locator('.meeting-review-editor textarea:visible')).toHaveCount(1)
  await expect(page.locator('.meeting-transcript-editor textarea')).toHaveValue(/長會議逐字稿第 900 段/)
  await page.getByRole('button', { name: '摘要欄位' }).click()
  await assertNoPageOverflow(page)
  await page.screenshot({ path: path.join(os.tmpdir(), 'ytapp-review-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 980, height: 900 })
  await expect(page.locator('.meeting-review-editor')).toBeVisible()
  await assertNoPageOverflow(page)
  const narrowLayout = await page.evaluate(() => {
    const frame = document.querySelector('.voice-frame').getBoundingClientRect()
    const inspector = document.querySelector('.voice-inspector').getBoundingClientRect()
    return { frameWidth: frame.width, inspectorWidth: inspector.width, inspectorLeft: inspector.left, frameLeft: frame.left }
  })
  expect(narrowLayout.inspectorWidth).toBeGreaterThan(narrowLayout.frameWidth * 0.9)
  expect(Math.abs(narrowLayout.inspectorLeft - narrowLayout.frameLeft)).toBeLessThan(2)
  await page.screenshot({ path: path.join(os.tmpdir(), 'ytapp-review-narrow.png'), fullPage: true })

  await page.locator('.meeting-review-editor').getByRole('textbox', { name: '標題' }).fill('E2E 人工校正版')
  await page.getByRole('button', { name: '確認寫入校正版' }).click()
  await expect(page.locator('.voice-workbench > .workbench-alert')).toContainText('已寫入')
  const written = fixture.list('02_Sources/meetings').find((name) => name.includes('e2e-人工校正版'))
  expect(written).toBeTruthy()
  expect(fixture.read(`02_Sources/meetings/${written}`)).toContain('# E2E 人工校正版')
})

test('two-file queue runs sequentially and survives reload', async ({ page }) => {
  let counter = 0
  const jobs = new Map()
  await page.route('**/app/meeting-note-job', async (route) => {
    const body = route.request().postDataJSON()
    const id = `e2e-queue-${++counter}`
    jobs.set(id, body.audio_path)
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, job_id: id }) })
  })
  await page.route('**/app/meeting-note-job/e2e-queue-*', async (route) => {
    const id = route.request().url().split('/').pop()
    const source = jobs.get(id)
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        job_id: id, status: 'review_ready', stage: 'review_ready', audio_path: source,
        transcript: '[00:01] 佇列草稿', write: null,
        summary: { title: path.basename(source), summary: '佇列完成', key_organization: '', core_value: '', action_items: [], decisions: [], attendees: [], agenda: [] },
      }),
    })
  })

  await openApp(page, fixture)
  await page.click('nav.side-nav button[aria-label="收錄"]')
  await page.getByRole('button', { name: '會議筆記音檔' }).click()
  await page.fill('input[aria-label="本機音檔路徑"]', audioPath)
  await page.getByRole('button', { name: '加入佇列' }).click()
  await page.fill('input[aria-label="本機音檔路徑"]', audioPath2)
  await page.getByRole('button', { name: '加入佇列' }).click()
  await expect(page.locator('.meeting-queue-item')).toHaveCount(2)
  const removeButton = page.getByRole('button', { name: '移除佇列項目' }).first()
  await expect(removeButton).toHaveClass(/danger-ghost/)
  await expect(removeButton).toContainText('移除')
  const dangerStyle = await removeButton.evaluate((element) => {
    const style = getComputedStyle(element)
    return { color: style.color, border: style.borderTopColor }
  })
  expect(dangerStyle.color).not.toBe('rgba(0, 0, 0, 0)')
  expect(dangerStyle.border).not.toBe('rgba(0, 0, 0, 0)')
  const themeResults = await page.evaluate(async () => {
    const themes = ['system', 'light', 'dark', 'walnut', 'gallery', 'atelier']
    const normalizeColor = (value) => {
      const channels = String(value).match(/[\d.]+/g)?.map(Number) || []
      if (channels.length === 3) channels.push(1)
      return channels.join(',')
    }
    const resolveToken = (name) => {
      const probe = document.createElement('span')
      probe.style.color = `var(${name})`
      document.body.appendChild(probe)
      const value = getComputedStyle(probe).color
      probe.remove()
      return normalizeColor(value)
    }
    const results = []
    const danger = document.querySelector('.queue-remove')
    danger.style.transition = 'none'
    for (const theme of themes) {
      if (theme === 'system') delete document.documentElement.dataset.theme
      else document.documentElement.dataset.theme = theme
      await new Promise((resolve) => setTimeout(resolve, 180))
      const paid = document.querySelector('.processing-cost-route .cost-paid')
      const dangerStyle = getComputedStyle(danger)
      const paidStyle = getComputedStyle(paid)
      results.push({
        theme,
        dangerColor: normalizeColor(dangerStyle.color),
        expectedDanger: resolveToken('--err-ink'),
        dangerBorder: normalizeColor(dangerStyle.borderTopColor),
        expectedBorder: resolveToken('--err-line'),
        paidColor: normalizeColor(paidStyle.color),
        expectedPaid: resolveToken('--warn-ink'),
      })
    }
    document.documentElement.dataset.theme = 'walnut'
    return results
  })
  for (const result of themeResults) {
    expect(result.dangerColor, `${result.theme} danger color`).toBe(result.expectedDanger)
    expect(result.dangerBorder, `${result.theme} danger border`).toBe(result.expectedBorder)
    expect(result.paidColor, `${result.theme} paid color`).toBe(result.expectedPaid)
  }
  await page.getByRole('button', { name: '開始／續跑' }).click()
  await expect(page.locator('.meeting-queue-item.review_ready')).toHaveCount(2)
  expect(counter).toBe(2)

  await page.reload({ waitUntil: 'networkidle' })
  await page.click('nav.side-nav button[aria-label="收錄"]')
  await page.getByRole('button', { name: '會議筆記音檔' }).click()
  await expect(page.locator('.meeting-queue-item.review_ready')).toHaveCount(2)
})

test('library meeting note exposes evidence playback without layout overflow', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await openApp(page, fixture)
  await page.click('nav.side-nav button[aria-label="筆記庫"]')
  const item = page.locator('.list-item', { hasText: 'E2E 可回放會議' })
  await expect(item).toBeVisible()
  await item.click()
  await expect(page.locator('.meeting-evidence-bar.ready')).toBeVisible()
  await expect(page.locator('.note-reader button.ts-seek', { hasText: '00:01' }).first()).toBeVisible()
  await assertNoPageOverflow(page)
  await page.screenshot({ path: path.join(os.tmpdir(), 'ytapp-library-playback-desktop.png'), fullPage: true })

  await page.setViewportSize({ width: 980, height: 900 })
  await expect(page.locator('.meeting-evidence-bar.ready')).toBeVisible()
  await assertNoPageOverflow(page)
  await page.screenshot({ path: path.join(os.tmpdir(), 'ytapp-library-playback-narrow.png'), fullPage: true })
})
