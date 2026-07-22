import { useEffect, useState } from 'react'
import { Bot, FileText, RefreshCw } from 'lucide-react'
import { apiFetch, postJson } from '../../app/api'

export default function AgentIndexSettings({ vaultRoot }) {
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)

  async function refresh() {
    if (!vaultRoot) {
      setStatus(null)
      return
    }
    try {
      const response = await apiFetch(`/app/agent-index/status?${new URLSearchParams({ vault_root: vaultRoot })}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '讀取 Agent 索引狀態失敗')
      setStatus(data)
    } catch (error) {
      setStatus(null)
      setMessage({ type: 'info', text: error.message })
    }
  }

  useEffect(() => {
    setMessage(null)
    refresh()
  }, [vaultRoot]) // eslint-disable-line react-hooks/exhaustive-deps

  async function generate() {
    if (!vaultRoot) return
    setBusy(true)
    setMessage({ type: 'info', text: '掃描 vault metadata 並產生索引中…' })
    try {
      const data = await postJson('/app/agent-index', { vault_root: vaultRoot, dry_run: false, confirm: true })
      setMessage({
        type: 'ok',
        text: data.changed
          ? `Agent 索引已更新（${data.note_count} 篇）`
          : `Agent 索引已是最新（${data.note_count} 篇）`,
      })
      await refresh()
    } catch (error) {
      setMessage({ type: 'error', text: error.message })
    } finally {
      setBusy(false)
    }
  }

  const statusLabel = !vaultRoot
    ? '請先指定 vault'
    : status?.managed
      ? `${status.note_count || 0} 篇已建立`
      : status?.exists
        ? '有未管理檔案'
        : '尚未建立'
  const statusTone = status?.managed ? 'ok' : status?.exists ? 'info' : 'neutral'

  return (
    <section className="panel settings-panel agent-index-panel" aria-label="Agent Bridge">
      <div className="panel-head">
        <div><Bot size={16} /><h3>Agent Bridge</h3></div>
        <span className={`state-chip ${statusTone}`}>{statusLabel}</span>
      </div>
      <div className="settings-state neutral">
        <FileText size={15} />
        <span>把 vault 的筆記 metadata 與關係連結產成 agent 可讀索引；原始筆記仍是唯一資料來源，不讀內文送雲端。</span>
      </div>
      <div className="state-list">
        <div><span>輸出 bundle</span><strong><code>_zibaldone/agent-index/</code>（OKF v0.1）</strong></div>
        <div><span>更新方式</span><strong>手動、只在本機</strong></div>
        {status?.generated_at && <div><span>上次更新</span><strong>{status.generated_at}</strong></div>}
      </div>
      <div className="row">
        <button type="button" className="ghost" onClick={refresh} disabled={!vaultRoot || busy}>
          <RefreshCw size={14} />重新整理狀態
        </button>
        <button type="button" className="primary" onClick={generate} disabled={!vaultRoot || busy}>
          <Bot size={14} />{busy ? '產生中…' : '產生／更新 Agent 索引'}
        </button>
      </div>
      {message && <div className={`settings-state ${message.type}`} role="status"><Bot size={15} /><span>{message.text}</span></div>}
      <div className="settings-note"><span>只會寫入 Zibaldone 管理的衍生檔；若目標檔是使用者自行建立，App 會拒絕覆寫。</span></div>
    </section>
  )
}
