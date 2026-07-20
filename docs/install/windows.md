# Windows x64 安裝

## 下載與安裝

1. 開啟 [GitHub Releases](https://github.com/justinyu73/zibaldone/releases) 的目標版本。
2. 下載 `Zibaldone_<版本>_x64-setup.exe`，不要下載 `.sig` 或 `latest.json` 當安裝程式。
3. （建議）先用 Release 內的 `SHA256SUMS-windows-latest.txt` 核對下載檔案。
4. 執行安裝程式，預設的目前使用者安裝即可；不需要 WSL、Python 或 Node。
5. 安裝後開啟 **Zibaldone**，依首次設定選擇筆記庫根目錄。

## SmartScreen 風險說明

本專案目前沒有購買 Microsoft Authenticode 憑證，因此 SmartScreen 可能顯示
「Windows 已保護您的電腦」或未知發行者。只有在你已確認：

- 來源是 `github.com/justinyu73/zibaldone/releases`；
- Release tag 與檔名正確；
- SHA-256 與 Release 內 checksum 相符；

才在視窗中選 **更多資訊 → 仍要執行**。不要因此關閉 SmartScreen、整台電腦的
防毒或執行網路上其他人提供的解除封鎖工具。

Windows 版已修正啟動時跳出額外終端機視窗的問題；若仍出現，請先確認不是用
WSL／開發指令啟動，而是執行 Release 的安裝版。

## 第一次使用

- 第 4 步說明的是**內建本機 AI（llama.cpp + Gemma）**，不是 Ollama，也不是 CLI。
- 可選「跳過，本次不下載」並完成設定；模型可稍後到設定頁下載。
- 若要用 Claude／Codex／Gemini 訂閱 CLI，必須在設定勾選後再按「儲存模型/上限」；畫面會直接提示未儲存狀態。
- YouTube 無字幕時，ASR/OCR 會依使用者明確操作下載音訊或低解析度影片；本機 OCR 預設使用 RapidOCR，暫存媒體完成後不作為筆記庫內容保存。
- 生成草稿不等於已寫入；請確認草稿、筆記庫根目錄與儲存結果。

## 升級

可在「設定 → 版本與更新」檢查 Release。更新檔使用專案 updater 簽章驗證，
但這不是 Windows 系統的 Authenticode 簽章。若一鍵更新失敗，直接從 GitHub
Release 下載較新的 setup.exe，關閉 App 後覆蓋安裝即可。

不要刪除外部筆記庫；升級與解除安裝都不應刪除你的 Markdown、音檔或附件。

## 解除安裝

到「Windows 設定 → 應用程式 → 已安裝的應用程式 → Zibaldone → 解除安裝」。
解除安裝程式本身不應刪除外部筆記庫。家目錄中的設定與模型快取可能保留，只有
在你明確要清除金鑰、偏好與本機模型時才手動處理。
