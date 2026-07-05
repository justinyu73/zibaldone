import fs from 'fs'
import os from 'os'
import path from 'path'

const YT_NOTE = `---
type: source
title: "E2E 測試影片筆記"
status: inbox
next_action: review
updated: 2026-06-01
created: 2026-06-10
---

# E2E 測試影片筆記

> [!info] 來源資訊
> - 連結：[YouTube](https://example.invalid/watch?v=e2e)

## 重點表格

| 欄 | 值 |
|---|---|
| A | 1 |

\`\`\`python
print("hello")
\`\`\`

<details><summary>英文逐字稿</summary>

transcript body

</details>
`

const INBOX_NOTE = `---
type: source
title: "E2E 待消化速記"
status: inbox
next_action: review
updated: 2026-06-02
created: 2026-06-09
---

# E2E 待消化速記

> [!tip] 重點
> - 待消化

內文不可被動作改動。
`

// Throwaway vault under /tmp: 01_Inbox + 02_Sources/youtube, one note each.
export function makeVault(prefix) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), `${prefix}-`))
  const vault = path.join(root, 'note_study')
  fs.mkdirSync(path.join(vault, '01_Inbox/manual-intake'), { recursive: true })
  fs.mkdirSync(path.join(vault, '02_Sources/youtube'), { recursive: true })
  fs.writeFileSync(path.join(vault, '02_Sources/youtube/e2e_video.md'), YT_NOTE)
  fs.writeFileSync(path.join(vault, '01_Inbox/manual-intake/e2e_quick.md'), INBOX_NOTE)
  return {
    vault,
    settings: JSON.stringify({ vaultRoot: vault, libraryFolders: [] }),
    read: (rel) => fs.readFileSync(path.join(vault, rel), 'utf8'),
    exists: (rel) => fs.existsSync(path.join(vault, rel)),
    list: (rel) => fs.readdirSync(path.join(vault, rel)),
    cleanup: () => fs.rmSync(root, { recursive: true, force: true }),
  }
}

export async function openApp(page, fixture) {
  await page.addInitScript((s) => localStorage.setItem('yt_product_settings_v3', s), fixture.settings)
  await page.goto('/', { waitUntil: 'networkidle' })
}
