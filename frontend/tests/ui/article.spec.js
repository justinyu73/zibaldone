import os from 'os'
import path from 'path'
import { test, expect } from '@playwright/test'
import { makeVault, openApp } from './fixture.js'

let fixture
test.beforeAll(() => { fixture = makeVault('ytapp-e2e-article') })
test.afterAll(() => fixture.cleanup())

test('article paste-mode closed loop: save → articles folder → inbox pickup', async ({ page }) => {
  await openApp(page, fixture)
  await page.click('nav.side-nav button[aria-label="收錄"]')
  await page.click('.ingest-lanes button:has-text("文章網址")')

  const tab = page.locator('.article-workbench')
  await expect(tab.locator('.note-fields-workspace')).toBeVisible()
  await expect(tab.locator('.processing-cost-route')).toContainText('來源：正文取得・免費')
  await expect(tab.locator('.processing-cost-route')).toContainText(/摘要：.+・(本機・免費|雲端・付費)/)
  await tab.locator('input[aria-label="文章網址"]').fill('https://example.invalid/fable-5-post')
  // paste fallback: no fetch, body goes straight into the review box
  await tab.locator('textarea[aria-label="文章正文審查區"]').fill('Fable 5 發布重點內文，貼上模式。')
  await tab.getByLabel('標題', { exact: true }).fill('Fable 5 發布筆記')
  await tab.locator('button:has-text("存入筆記")').click()
  await expect(tab.locator('.workbench-alert')).toContainText('已存入')
  await expect(tab.locator('.workbench-alert')).toContainText('02_Sources/articles')

  // note exists on disk, inside the standard inbox loop
  const files = fixture.list('02_Sources/articles').filter((f) => f.endsWith('.md'))
  expect(files.length).toBe(1)
  const content = fixture.read(`02_Sources/articles/${files[0]}`)
  expect(content).toContain('status: inbox')
  expect(content).toContain('貼上模式')

  // Cross-source library exposes source categories, and category + keyword
  // filtering work together instead of being separate browsing modes.
  await page.click('nav.side-nav button[aria-label="筆記庫"]')
  const library = page.locator('.library-workbench')
  await expect(library.getByLabel('價值庫來源分類')).toContainText('articles')
  await library.getByLabel('價值庫來源分類').selectOption('articles')
  await expect(library.locator('.list-item', { hasText: 'Fable 5 發布筆記' })).toBeVisible()
  await library.getByLabel('筆記庫搜尋關鍵字').fill('貼上模式')
  await library.getByRole('button', { name: '搜尋', exact: true }).click()
  await expect(library.locator('.list-item', { hasText: 'Fable 5 發布筆記' })).toBeVisible()
  await page.screenshot({ path: path.join(os.tmpdir(), 'ytapp-library-source-filter.png'), fullPage: true })

  // inbox picks it up after rescan
  await page.click('nav.side-nav button[aria-label="收件匣"]')
  await page.locator('.inbox-workbench button:has-text("重新掃描")').click()
  await expect(page.locator('.inbox-workbench .list-item', { hasText: 'Fable 5 發布筆記' })).toBeVisible()
})

test('video and article lanes share the focused note-review template', async ({ page }) => {
  await page.setViewportSize({ width: 980, height: 800 })
  await openApp(page, fixture)
  await page.click('nav.side-nav button[aria-label="收錄"]')

  const video = page.locator('.capture-workbench')
  await expect(video.locator('.note-fields-workspace')).toBeVisible()
  await expect(video.locator('.processing-cost-route')).toContainText('來源：字幕取得・免費')
  await video.locator('.note-field-nav').getByRole('tab', { name: /主題摘要/ }).click()
  await expect(video.locator('.note-active-field textarea')).toHaveCount(1)

  await page.locator('.ingest-lanes').getByRole('button', { name: '文章網址' }).click()
  const article = page.locator('.article-workbench')
  await expect(article.locator('.note-fields-workspace')).toBeVisible()
  await article.locator('.note-field-nav').getByRole('tab', { name: /重點條列/ }).click()
  await expect(article.locator('.note-active-field textarea')).toHaveCount(1)
  const workspaceGap = await article.locator('.note-fields-workspace').evaluate((element) => {
    const nav = element.querySelector('.note-field-nav').getBoundingClientRect()
    const editor = element.querySelector('.note-active-field').getBoundingClientRect()
    return editor.left - nav.right
  })
  expect(workspaceGap).toBeGreaterThanOrEqual(8)
  const widths = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
  expect(widths.scroll).toBeLessThanOrEqual(widths.client)
  await page.screenshot({ path: path.join(os.tmpdir(), 'ytapp-intake-parity-980.png'), fullPage: true })
})
