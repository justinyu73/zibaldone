// 三條新閉環：補心得（追加＋distill 標記＋內文不動）、手機收錄（01_Inbox 掃描
// →帶入對應 lane→指紋去重）、相關筆記（候選→人工確認→wikilink 落檔）。
import fs from 'fs'
import path from 'path'
import { test, expect } from '@playwright/test'
import { makeVault, openApp } from './fixture.js'

test('thought box appends dated callout + distill marker, body untouched', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-thought')
  try {
    await openApp(page, fixture)
    await page.click('nav.side-nav button[aria-label="收件匣"]')
    const inbox = page.locator('.inbox-workbench')
    await inbox.locator('.list-item', { hasText: 'E2E 待消化速記' }).click()
    await expect(inbox.locator('.note-reader')).toBeVisible()
    await inbox.locator('.thought-box textarea').fill('e2e 補心得內容')
    await inbox.locator('.thought-distill input').check()
    await inbox.locator('button:has-text("寫入心得")').click()
    await expect(inbox.locator('.workbench-alert')).toContainText('已補心得並標記可提取')
    const text = fixture.read('01_Inbox/manual-intake/e2e_quick.md')
    expect(text).toContain('補心得')
    expect(text).toContain('> e2e 補心得內容')
    expect(text).toContain('distill: candidate')
    expect(text).toContain('內文不可被動作改動。')
  } finally { fixture.cleanup() }
})

test('phone capture: scanned from 01_Inbox, adopted into matching lane, fingerprinted', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-capture')
  try {
    const stamp = Date.now()
    fs.writeFileSync(
      path.join(fixture.vault, '01_Inbox/phone-links.md'),
      `看這篇 https://example.com/e2e-${stamp}\n影片 https://youtu.be/e2e${stamp}\n`,
    )
    await openApp(page, fixture)
    await page.click('nav.side-nav button[aria-label="收件匣"]')
    const inbox = page.locator('.inbox-workbench')
    await inbox.locator('button:has-text("手機收錄")').click()
    await expect(inbox.locator('.capture-row')).toHaveCount(2)

    // article URL → 文章 lane with the URL pre-filled
    await inbox.locator('.capture-row', { hasText: `example.com/e2e-${stamp}` })
      .locator('button:has-text("帶入收錄")').click()
    await expect(page.locator('.content-head h2')).toHaveText('收錄')
    await expect(page.locator('.article-workbench input[aria-label="文章網址"]'))
      .toHaveValue(`https://example.com/e2e-${stamp}`)

    // video URL → 影片 lane with the URL pre-filled
    await page.click('nav.side-nav button[aria-label="收件匣"]')
    await inbox.locator('button:has-text("手機收錄")').click()
    await inbox.locator('.capture-row').locator('button:has-text("帶入收錄")').click()
    await expect(page.locator('.capture-workbench input[aria-label="YouTube 網址或影片 ID"]'))
      .toHaveValue(`https://youtu.be/e2e${stamp}`)

    // both fingerprinted: rescan finds nothing although the file is untouched
    await page.click('nav.side-nav button[aria-label="收件匣"]')
    await inbox.locator('button:has-text("手機收錄")').click()
    await inbox.locator('button:has-text("重新掃描 01_Inbox")').click()
    await expect(inbox.locator('.capture-row')).toHaveCount(0)
    expect(fixture.read('01_Inbox/phone-links.md')).toContain(`https://example.com/e2e-${stamp}`)
  } finally { fixture.cleanup() }
})

// Regression: the global `input { width:100% }` rule once stretched checkboxes
// over their label text (radar toggles, 0.2.6). Every checkbox must stay square.
test('checkboxes render at natural size everywhere', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-checkbox')
  try {
    await openApp(page, fixture)
    await page.click('nav.side-nav button[aria-label="設定"]')
    const toggles = page.locator('.radar-toggles input[type="checkbox"]')
    await expect(toggles).toHaveCount(3)
    for (const box of await toggles.all()) {
      const bb = await box.boundingBox()
      expect(bb.width).toBeLessThanOrEqual(24)
    }
    await page.click('nav.side-nav button[aria-label="收件匣"]')
    const inbox = page.locator('.inbox-workbench')
    await inbox.locator('.list-item', { hasText: 'E2E 待消化速記' }).click()
    const distill = inbox.locator('.thought-distill input[type="checkbox"]')
    await expect(distill).toBeVisible()
    expect((await distill.boundingBox()).width).toBeLessThanOrEqual(24)
  } finally { fixture.cleanup() }
})

const RELATED_MAIN = `---
title: "E2E 關聯主筆記"
---

<!-- vaultwiki:ai:start -->
### 專有名詞 / 人物 / 工具
- QuantumFooBarE2E
<!-- vaultwiki:ai:end -->

## 個人心得筆記

-

## 逐字稿

main body
`

const RELATED_TARGET = `---
title: "E2E 關聯目標筆記"
---

內文提到 QuantumFooBarE2E 的細節。
`

test('related notes: candidates found, human-confirmed wikilink written to file', async ({ page }) => {
  const fixture = makeVault('ytapp-e2e-related')
  try {
    fs.writeFileSync(path.join(fixture.vault, '02_Sources/youtube/related_main.md'), RELATED_MAIN)
    fs.writeFileSync(path.join(fixture.vault, '02_Sources/youtube/related_target.md'), RELATED_TARGET)
    await openApp(page, fixture)
    await page.click('nav.side-nav button[aria-label="筆記庫"]')
    const lib = page.locator('.library-workbench')
    await lib.locator('.list-item', { hasText: 'E2E 關聯主筆記' }).click()
    await expect(lib.locator('.related-box')).toBeVisible()
    await lib.locator('button:has-text("找相關")').click()
    await expect(lib.locator('.related-item', { hasText: 'E2E 關聯目標筆記' })).toBeVisible()
    await lib.locator('button:has-text("寫入勾選的關聯")').click()
    await expect(lib.locator('.workbench-alert')).toContainText('已寫入')
    const text = fixture.read('02_Sources/youtube/related_main.md')
    expect(text).toContain('## 相關筆記')
    expect(text).toContain('- [[related_target]]')
  } finally { fixture.cleanup() }
})
