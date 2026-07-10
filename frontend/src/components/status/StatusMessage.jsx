export function recoveryHint(status) {
  if (!status || status.type !== 'error') return ''
  const message = String(status.message || '').toLowerCase()
  if (message.includes('daily') || message.includes('cap') || message.includes('額度') || message.includes('上限')) {
    return '保護：付費或 provider 操作已停止。下一步：到「設定」檢查每日上限與模型用量。'
  }
  if (message.includes('caption') || message.includes('字幕')) {
    return '保護：不會自動下載媒體或呼叫雲端。字幕優先；缺字幕時可用下方 ASR（本機轉錄）或 OCR（讀畫面），皆需你明確觸發。'
  }
  if (message.includes('not found')) {
    return '保護：未執行任何寫入。可能原因：更新後舊版背景服務仍佔用連線。下一步：完全結束 App 再重新開啟（必要時重開機）。'
  }
  if (message.includes('network') || message.includes('failed to fetch') || message.includes('後端') || message.includes('連線')) {
    return '保護：未寫入本機筆記。下一步：確認後端 sidecar 已啟動，再重試目前操作。'
  }
  return '保護：未執行後續寫入。下一步：修正輸入或狀態後重試。'
}

export default function StatusMessage({ status, className = '' }) {
  if (!status) return null
  const hint = recoveryHint(status)
  return (
    <div
      className={`status ${status.type} ${className}`}
      role={status.type === 'error' ? 'alert' : 'status'}
      aria-live={status.type === 'error' ? 'assertive' : 'polite'}
    >
      <span>{status.message}</span>
      {hint && <small>{hint}</small>}
    </div>
  )
}
