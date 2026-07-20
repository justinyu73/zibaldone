# Zibaldone 安裝與使用指南

Zibaldone 是本機優先的 Markdown 筆記收錄工具。公開安裝檔放在
[GitHub Releases](https://github.com/justinyu73/zibaldone/releases)，一般使用者不需要安裝 WSL、Python 或 Node。

## 下載哪一個檔案

| 平台 | 下載檔 | 目前限制 |
|---|---|---|
| Windows 10/11 x64 | `Zibaldone_<版本>_x64-setup.exe` | 需要處理 SmartScreen 未簽章提示 |
| macOS Apple Silicon | `Zibaldone_<版本>_aarch64.dmg` | 需要處理未 notarize 的 Gatekeeper 提示 |
| macOS Intel | 目前沒有公開檔 | 請自行從原始碼建置，或等待 Intel runner 版本 |
| Linux | 目前沒有公開檔 | 請看開發安裝文件 |

下載後可先用 Release 內的 `SHA256SUMS-*.txt` 核對檔案；`.sig` 是 updater 簽章，不是安裝程式。

## 安全提醒

這些安裝檔是開源專案的公開 binary，但沒有 Windows Authenticode 或 Apple
Developer ID notarization。請遵守這個順序：

1. 只從 `github.com/justinyu73/zibaldone/releases` 下載。
2. 確認 Release tag、檔名與 SHA-256。
3. 只對這個已核對的檔案依平台指南放行。
4. 不要停用整台電腦的防毒或系統安全功能，也不要下載第三方「破解」版本。

App 的網路、金鑰、筆記與模型邊界見[隱私與網路行為](../privacy-and-network.md)。

## 第一次使用的最短路徑

1. 安裝並開啟 Zibaldone。
2. 在首次設定選擇筆記庫根目錄，完成後確認設定頁顯示後端已連線。
3. 第 4 步選擇是否下載**內建本機 AI（llama.cpp + Gemma）**；不想現在下載就選「跳過，本次不下載」，之後仍可在設定頁處理。
4. 從「收錄」選擇 YouTube、文章或會議音檔；先預覽，再抓字幕／ASR／OCR，最後生成可編輯草稿。
5. 確認筆記庫根目錄已設定後，再按「存入筆記」。

### 訂閱 CLI 模型

Claude／Codex／Gemini CLI 預設不顯示。若電腦已安裝並登入對應 CLI：

1. 開啟「設定」。
2. 勾選「顯示訂閱 CLI 模型」。
3. 按「儲存模型/上限」；勾選本身不會立即套用。

畫面會在未儲存時顯示「設定尚未儲存：CLI 尚未生效」。CLI 是否可用仍取決於
各家 CLI 的本機安裝、登入狀態與服務條款；App 不替你購買或驗證訂閱。

## 平台指南

- [Windows x64](windows.md)
- [macOS Apple Silicon](macos.md)
- [開發環境與 Linux/WSL](development.md)
- [疑難排解](../troubleshooting.md)
