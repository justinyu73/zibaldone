# macOS Apple Silicon 安裝

目前公開安裝檔支援 Apple Silicon（`aarch64`）。Intel Mac 目前沒有公開 DMG。

## 下載與安裝

1. 開啟 [GitHub Releases](https://github.com/justinyu73/zibaldone/releases) 的目標版本。
2. 下載 `Zibaldone_<版本>_aarch64.dmg`，不要下載 `.sig` 或 `latest.json` 當安裝程式。
3. （建議）先用 Release 內的 `SHA256SUMS-macos-latest.txt` 核對 DMG。
4. 開啟 DMG，把 **Zibaldone.app** 拖到 **Applications**。
5. 第一次開啟前，先閱讀下方 Gatekeeper 說明，再完成首次設定。

## Gatekeeper 風險說明

本專案目前沒有 Apple Developer ID signing 或 notarization。即使 DMG 沒有被
竄改，macOS 仍可能顯示「Zibaldone 已損毀，無法打開」；這是未 notarize app 的
常見 Gatekeeper 措辭，不代表一定是檔案損壞。

只有在你已確認來源與 SHA-256 都正確後，對**這個 App 的固定路徑**移除隔離標記：

```bash
xattr -r -d com.apple.quarantine "/Applications/Zibaldone.app"
```

接著從 Applications 開啟。不要執行 `xattr -r -d com.apple.quarantine /`、對整個
Downloads／Applications 解除隔離，或為了安裝而停用 Gatekeeper。若指令顯示檔案
不存在，請先確認 App 名稱與 Applications 路徑；不要改用廣泛的刪除指令。

Updater 的下載檔有專案簽章驗證，但這不會取代 Apple notarization；永久消除首次
提示需要 Apple Developer Program 與 release secrets。

## 第一次使用

- 不需要 WSL、Python 或 Node。
- 第 4 步的下載項目是內建本機 AI（llama.cpp + Gemma），不是 Ollama，也不是 CLI；
  可選「跳過，本次不下載」，之後再到設定頁下載。
- 若要使用已登入的 Claude／Codex／Gemini CLI，勾選後一定要按「儲存模型/上限」。
- YouTube 無字幕時，ASR/OCR 會在你明確點選後從 YouTube 下載必要的暫存媒體；
  預設本機 OCR 不會把影片上傳雲端。選用雲端 provider 時，請先確認內容可外傳。
- 生成草稿後先人工檢查，再按「存入筆記」；沒有設定筆記庫根目錄時不會寫入。

## 升級與解除安裝

可在「設定 → 版本與更新」使用簽章 updater，或關閉 App 後從新 DMG 替換
Applications 內的舊版。解除安裝時把 Zibaldone.app 移到垃圾桶；外部筆記庫、
音檔與附件不應被刪除。家目錄中的設定、金鑰與模型快取可能保留，需清除時再
依隱私文件手動處理。
