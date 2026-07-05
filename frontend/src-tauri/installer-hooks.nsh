; Windows 更新老毛病根治：安裝前先終止仍在跑的 FastAPI sidecar，否則 NSIS 覆寫
; video-intake-fastapi-sidecar.exe 時檔案被鎖（"Error opening file for writing"），
; 安裝中斷/半裝壞掉。主程式關閉由 Tauri NSIS 既有流程處理，這裡只補殺 sidecar。
!macro NSIS_HOOK_PREINSTALL
  nsExec::Exec 'taskkill /F /IM "video-intake-fastapi-sidecar.exe" /T'
  Sleep 500
!macroend
