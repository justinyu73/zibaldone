import { test, expect } from '@playwright/test'
import { execFileSync } from 'child_process'
import fs from 'fs'
import os from 'os'
import path from 'path'
import { makeVault, openApp } from './fixture.js'

// Real audio file so the dry-run preflight (ffmpeg) returns a usable verdict.
let fixture
let audioPath
test.beforeAll(() => {
  fixture = makeVault('ytapp-e2e-asr')
  audioPath = path.join(os.tmpdir(), `asr-e2e-${Date.now()}.wav`)
  execFileSync('ffmpeg', ['-hide_banner', '-y', '-f', 'lavfi', '-i',
    'sine=frequency=440:sample_rate=16000', '-t', '2', '-ac', '1', '-ar', '16000', audioPath])
})
test.afterAll(() => { fixture.cleanup(); fs.rmSync(audioPath, { force: true }) })

test('ASR voice lane: tab → mode toggle → preview preflight', async ({ page }) => {
  await openApp(page, fixture)

  // ① 側欄「收錄」→「會議筆記音檔」lane → MeetingAudioTab 顯示
  await page.click('nav.side-nav button[aria-label="收錄"]')
  await page.getByRole('button', { name: '會議筆記音檔' }).click()
  await expect(page.locator('.command-kicker', { hasText: '語音收錄' })).toBeVisible()

  // ② 三層品質 selector：預設「中」active，點「高品質」換手（精準開關隨之隱藏），再切回中預覽
  const midBtn = page.getByRole('button', { name: '較準·預設' })   // 中
  const cloudBtn = page.getByRole('button', { name: '雲端·付費' }) // 高品質
  const preciseBtn = page.getByRole('button', { name: '精準／長音檔' })
  await expect(midBtn).toHaveAttribute('aria-pressed', 'true')
  await expect(preciseBtn).toBeVisible()  // 本地 tier 有精準/長音檔開關
  await cloudBtn.click()
  await expect(cloudBtn).toHaveAttribute('aria-pressed', 'true')
  await expect(midBtn).toHaveAttribute('aria-pressed', 'false')
  await expect(preciseBtn).toBeHidden()   // 高品質(雲端)無精準開關
  await midBtn.click()  // 切回中做預覽

  // ③ 填音檔路徑 → 預覽 → 等 /meeting-note dry_run 回 preflight 判定
  await page.fill('input[aria-label="本機音檔路徑"]', audioPath)
  const respPromise = page.waitForResponse((r) => r.url().includes('/app/meeting-note'))
  await page.getByRole('button', { name: '預覽' }).click()
  const resp = await respPromise
  const body = await resp.json()
  console.log('PREFLIGHT RESPONSE:', JSON.stringify(body.preflight))
  expect(body.dry_run).toBe(true)
  expect(body.preflight.usable).toBe(true)

  // 畫面上的 preflight 判定字串（scope 到 MeetingAudioTab，其他 tab 也用 workbench-alert）
  await expect(page.locator('.voice-workbench > .workbench-alert')).toContainText('音檔檢查')
  await expect(page.locator('.voice-workbench > .workbench-alert')).toContainText('可用')
  await page.screenshot({ path: path.join(os.tmpdir(), 'ytapp-asr-preview.png'), fullPage: true })
})
