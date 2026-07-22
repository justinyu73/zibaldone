import { useEffect, useState } from 'react'
import { apiFetch, postJson } from '../../app/api'
import ModelSelect, { PROVIDER_META, providerForModel } from './ModelSelect'

// 草稿面板就地切換摘要模型（讀/寫後端摘要設定）——本地模型摘要較弱時可切雲端/大模型重生，
// 翻譯模型獨立不受影響。沿用既有 /app/model-options + /app/settings，不另造 per-request 覆寫。
export default function SummaryModelPicker({ transcriptionRoute = 'local', evidenceLabel = '' }) {
  const [opts, setOpts] = useState(null)
  const [model, setModel] = useState('')
  useEffect(() => {
    // 收錄是開機預設分頁，會在 sidecar 就緒前就掛載 → 首次 fetch 可能失敗。
    // 重試直到拿到 options，否則永遠卡「載入中」（設定頁是之後才點、剛好沒撞到）。
    let cancelled = false
    let retryTimer
    const load = () => {
      apiFetch('/app/model-options').then((r) => r.json())
        .then((d) => { if (!cancelled) setOpts(d) })
        .catch(() => { if (!cancelled) retryTimer = setTimeout(load, 1500) })
      apiFetch('/app/settings').then((r) => r.json())
        .then((s) => { if (!cancelled) setModel(s.summary_model || '') })
        .catch(() => {})
    }
    const refresh = () => load()
    load()
    window.addEventListener('zibaldone:model-options-changed', refresh)
    return () => {
      cancelled = true
      clearTimeout(retryTimer)
      window.removeEventListener('zibaldone:model-options-changed', refresh)
    }
  }, [])
  const change = async (e) => {
    const v = e.target.value
    setModel(v)
    try { await postJson('/app/settings', { summary_model: v }) } catch { /* 設定頁仍可改 */ }
  }
  const provider = providerForModel(model, opts?.summary || [])
  // 摘要成本分類：內建本機＝免費、訂閱 CLI＝零成本、其餘雲端＝付費。
  const summaryFree = provider === 'llamacpp' || provider === 'cli'
  const summaryCost = provider === 'llamacpp' ? '本機・免費' : provider === 'cli' ? '訂閱・零成本' : '雲端・付費'
  const transcriptLabel = evidenceLabel || (transcriptionRoute === 'provided'
    ? '轉錄：已提供・免費'
    : transcriptionRoute === 'cloud' ? '轉錄：雲端・付費' : '轉錄：本機・免費')
  const summaryLabel = `摘要：${PROVIDER_META[provider]?.label || provider}・${summaryCost}`
  return (
    <div className="summary-model-pick" title="轉錄與摘要是兩個獨立步驟，可能分別免費或付費。">
      <label><span>摘要模型</span><ModelSelect value={model} onChange={change} options={opts?.summary} compact /></label>
      <div className="processing-cost-route" aria-label="本次處理成本路線">
        <span className={`state-chip ${transcriptionRoute === 'cloud' ? 'cost-paid' : 'cost-free'}`}>{transcriptLabel}</span>
        <span aria-hidden="true">→</span>
        <span className={`state-chip ${summaryFree ? 'cost-free' : 'cost-paid'}`}>{summaryLabel}</span>
      </div>
    </div>
  )
}
