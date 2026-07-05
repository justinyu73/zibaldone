import { test, expect } from '@playwright/test'
import { makeVault, openApp } from './fixture.js'

let fixture
test.beforeAll(() => { fixture = makeVault('ytapp-e2e-inbox') })
test.afterAll(() => fixture.cleanup())

test('inbox digestion: mark reviewed touches frontmatter only, trash double-confirms and moves', async ({ page }) => {
  await openApp(page, fixture)
  await page.click('nav.side-nav button[aria-label="收件匣"]')
  const inbox = page.locator('.inbox-workbench')
  await expect(inbox.locator('.list-item')).toHaveCount(2)

  // mark the quick note reviewed → frontmatter changes, body byte-identical
  await inbox.locator('.list-item', { hasText: 'E2E 待消化速記' }).click()
  await expect(inbox.locator('.note-reader')).toBeVisible()
  await inbox.locator('button:has-text("標記已消化")').click()
  await expect(inbox.locator('.workbench-alert')).toContainText('已標記消化')
  await expect(inbox.locator('.list-item')).toHaveCount(1)
  const reviewed = fixture.read('01_Inbox/manual-intake/e2e_quick.md')
  expect(reviewed).toContain('status: reviewed')
  expect(reviewed).toContain('next_action: none')
  expect(reviewed).toContain('內文不可被動作改動。')

  // trash the video note: first click only opens the confirm gate
  await inbox.locator('.list-item', { hasText: 'E2E 測試影片筆記' }).click()
  await inbox.locator('button:has-text("刪除")').click()
  await expect(inbox.locator('.ac-gate')).toBeVisible()
  expect(fixture.exists('02_Sources/youtube/e2e_video.md')).toBe(true)

  await inbox.locator('button:has-text("確認移到垃圾桶")').click()
  await expect(inbox.locator('.workbench-alert')).toContainText('垃圾桶')
  await expect(inbox.locator('.list-item')).toHaveCount(0)
  expect(fixture.exists('02_Sources/youtube/e2e_video.md')).toBe(false)
  expect(fixture.list('_trash').some((f) => f.includes('e2e_video'))).toBe(true)
})

test('inbox batch: select all then mark reviewed clears the list', async ({ page }) => {
  const batchFixture = makeVault('ytapp-e2e-inbox-batch')
  try {
    await openApp(page, batchFixture)
    await page.click('nav.side-nav button[aria-label="收件匣"]')
    const inbox = page.locator('.inbox-workbench')
    await expect(inbox.locator('.list-item')).toHaveCount(2)

    await inbox.locator('button:has-text("全選")').click()
    await expect(inbox.locator('.batch-bar')).toContainText('已勾選 2 筆')
    await inbox.locator('button:has-text("批次標記已消化")').click()
    await expect(inbox.locator('.workbench-alert')).toContainText('批次標記已消化 2 筆')
    await expect(inbox.locator('.list-item')).toHaveCount(0)
    expect(batchFixture.read('01_Inbox/manual-intake/e2e_quick.md')).toContain('status: reviewed')
    expect(batchFixture.read('02_Sources/youtube/e2e_video.md')).toContain('status: reviewed')
  } finally {
    batchFixture.cleanup()
  }
})
