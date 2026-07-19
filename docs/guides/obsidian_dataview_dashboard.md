# Obsidian Dataview 建置流程（搭配本 app 的筆記）

目的：用 Dataview 把本 app 寫進筆記 frontmatter 的欄位（`distill`、`status`、
`source`…）即時查成儀表板。**你之前想要的「蒸餾候選檢視」不必寫進 app——
一條 Dataview 查詢就有了。** Dataview 只讀不寫，不會改到你的筆記。

> 本文查詢全部對準 app 實際寫入的 frontmatter（已核對程式碼）。直接複製可用。

---

## 一、安裝（3 步，0 代碼）

1. Obsidian → 設定 → 社群外掛 → 關閉「限制模式」
2. 瀏覽 → 搜尋 **Dataview**（作者 blacksmithgu）→ 安裝 → 啟用
3. 在任一筆記貼上下面的查詢區塊即可（見第三節）

> 查詢寫在一個 ```` ```dataview ```` 程式碼區塊裡，Obsidian 切到「閱讀模式」
> 就會即時渲染成表格。

建議：在 vault 根目錄建一篇 `00_Dashboard.md` 當你的「首頁主控台」，
把第三節的查詢都放進去，釘選或設成起始頁。

---

## 二、app 寫入的 frontmatter 欄位（Dataview 可查的）

核對自 `backend/obsidian.py`、`article_note.py`、`capture_inbox.py`：

| 欄位 | 值 | 說明 |
|------|-----|------|
| `type` | `source` | 所有來源筆記 |
| `source` | `youtube` / `article` / `pdf` | 來源型態 |
| `status` | `inbox` / `reviewed` | inbox=收了沒讀；reviewed=已消化 |
| `next_action` | `review` / `none` | |
| `distill` | `candidate` | **補心得時勾「可提取」才有**（蒸餾候選） |
| `created` / `updated` | 日期 | |
| `tags` | `[type/source, source/<x>, status/<x>]` | |
| `author` / `site` / `url` | | |

**⚠ 限制：「分類」（content_category）不在 frontmatter**——app 把它寫進筆記內文
的 AI 區塊（`### 分類`），所以 Dataview **無法直接依分類做儀表板**。三個解法見
第四節。

---

## 三、可直接複製的查詢

### 1. 蒸餾候選清單（最對口你的複利需求）

把所有標了「可提取」的筆記列出來，標一篇就多一筆：

````
```dataview
TABLE source AS "來源", file.mtime AS "最近更新"
FROM "02_Sources"
WHERE distill = "candidate"
SORT file.mtime DESC
```
````

### 2. 待消化收件匣

````
```dataview
TABLE source AS "來源", file.ctime AS "收錄時間"
FROM "02_Sources"
WHERE status = "inbox"
SORT file.ctime DESC
```
````

### 3. 來源分佈（各來源幾篇）

````
```dataview
TABLE length(rows) AS "篇數"
FROM "02_Sources"
WHERE type = "source"
GROUP BY source
```
````

### 4. 最近消化的（已 reviewed）

````
```dataview
TABLE source AS "來源", updated AS "消化日"
FROM "02_Sources"
WHERE status = "reviewed"
SORT updated DESC
LIMIT 20
```
````

### 5. 本週收錄

````
```dataview
TABLE source AS "來源", status AS "狀態"
FROM "02_Sources"
WHERE file.ctime >= date(today) - dur(7 days)
SORT file.ctime DESC
```
````

---

## 四、想依「分類」做儀表板的三個解法

因為分類不在 frontmatter（見第二節限制）：

- **(a) 手動加 inline 欄位**：在想分類的筆記內文任一行寫 `category:: AI LLM`，
  Dataview 就能用 `category` 查（`WHERE category = "AI LLM"`）。適合少量筆記。
- **(b) 改用 tags**：在 app 的「個人心得」或筆記裡手動加 `#cat/ai-llm` 類標籤，
  用 `FROM #cat/ai-llm` 查。
- **(c) app 端補一刀（要我做）**：讓 app 把 `content_category` 也寫進 frontmatter，
  之後 Dataview 就能 `GROUP BY content_category` 直接出分類儀表板。這是個小改動，
  你要的話我加。

---

## 五、首頁主控台範例

`00_Dashboard.md` 一頁集合（仿你看到的那種「Home Console」）：

````
# 知識筆記主控台

## 📥 待消化
```dataview
TABLE source AS "來源", file.ctime AS "收錄"
FROM "02_Sources"
WHERE status = "inbox"
SORT file.ctime DESC
```

## ⭐ 蒸餾候選（可提取）
```dataview
LIST
FROM "02_Sources"
WHERE distill = "candidate"
SORT file.mtime DESC
```

## 📊 來源分佈
```dataview
TABLE length(rows) AS "篇數"
FROM "02_Sources"
WHERE type = "source"
GROUP BY source
```
````

---

## 六、注意

- **Dataview 只讀**：不改你的筆記，安全；先裝這一個試水溫，順了再加
  Smart Connections（語意關聯）、Copilot（vault 內問答）。
- **查詢回空大多是欄位名打錯或資料夾路徑不對**——先確認 `FROM "02_Sources"`
  對應你的實際資料夾結構。
- Dataview 是社群外掛，版本/維護狀態以 Obsidian 市集顯示為準。
