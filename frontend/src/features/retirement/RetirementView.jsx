import { useEffect, useState } from 'react'
import { CheckSquare, Search, Trash2 } from 'lucide-react'
import { apiFetch, postJson } from '../../app/api'
import StatusMessage from '../../components/status/StatusMessage'
import SourceGlyph, { sourceTypeFromPath } from '../../components/SourceGlyph'
import { deriveVaultPaths } from '../../paths'

export default function RetirementView({ settings, active = true, ready = true }) {
  const paths = deriveVaultPaths(settings.vaultRoot)
  const [staleDays, setStaleDays] = useState(90)
  const [items, setItems] = useState([])
  const [scanned, setScanned] = useState(0)
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState('')
  const [checked, setChecked] = useState([])
  const [confirmAsk, setConfirmAsk] = useState(false)

  async function load(silent = false) {
    if (!paths.root) return setStatus({ type: 'error', message: '請先在「設定」指定筆記庫根目錄' })
    setBusy('load'); if (!silent) setStatus({ type: 'info', message: '掃描退場候選中…' })
    try {
      const params = new URLSearchParams({ vault_root: paths.root, stale_days: String(staleDays) })
      const r = await apiFetch(`/app/retirement-candidates?${params.toString()}`)
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail?.message || d.detail || '掃描失敗')
      setItems(d.candidates || [])
      setScanned(d.scanned || 0)
      setChecked([])
      if (!silent) setStatus({ type: 'ok', message: `掃描 ${d.scanned} 篇，退場候選 ${d.total} 筆（窗 ${staleDays} 天）` })
    } catch (e) { setStatus({ type: 'error', message: e.message }) } finally { setBusy('') }
  }

  useEffect(() => { if (ready && active) load(true) }, [ready, active]) // eslint-disable-line react-hooks/exhaustive-deps

  function toggleChecked(path) {
    setChecked((arr) => (arr.includes(path) ? arr.filter((p) => p !== path) : [...arr, path]))
  }

  async function doDelete() {
    const targets = items.filter((x) => checked.includes(x.path))
    setBusy('delete')
    let done = 0
    try {
      for (const item of targets) {
        await postJson('/app/inbox-trash', { vault_root: paths.root, note_relpath: item.path, confirm: true })
        done += 1
      }
      setStatus({ type: 'ok', message: `已移到垃圾桶 ${done} 筆（可從 _trash 救回）` })
    } catch (e) {
      setStatus({ type: 'error', message: `刪除中斷（已完成 ${done} 筆）：${e.message}` })
    } finally {
      setBusy(''); setConfirmAsk(false); load(true)
    }
  }

  const allChecked = items.length > 0 && checked.length === items.length
  return (
    <div className="retire-tab">
      <p className="retire-note">
        退場候選＝外部參考筆記過時超過設定天數、且沒有被任何系統自述筆記引用。
        系統自述（架構／原子卡／歷史節點）永不出現在這。這裡只列候選；刪除是移到
        <code> _trash</code>（可救回），需逐批二次確認，不自動刪。
      </p>

      <div className="panel retire-control">
        <label htmlFor="stale-days">過時窗（天）</label>
        <input
          id="stale-days" type="number" min="1" value={staleDays}
          onChange={(e) => setStaleDays(Math.max(1, Number(e.target.value) || 1))}
          className="retire-days"
        />
        <button className="btn primary" onClick={() => load(false)} disabled={busy === 'load'}>
          <Search size={15} /> 重新掃描
        </button>
        <span className="retire-scanned">掃描 {scanned} 篇 · 候選 {items.length} 筆</span>
      </div>

      <StatusMessage status={status} className="workbench-alert" />

      {confirmAsk && (
        <div className="retire-confirm">
          <p>確認把勾選的 <b>{checked.length}</b> 筆移到 _trash？（可從該資料夾救回）</p>
          <div className="retire-confirm-actions">
            <button className="btn danger" onClick={doDelete} disabled={busy === 'delete'}>確認刪除</button>
            <button className="btn" onClick={() => setConfirmAsk(false)} disabled={busy === 'delete'}>取消</button>
          </div>
        </div>
      )}

      {items.length > 0 && (
        <section className="panel">
          <div className="retire-batchbar">
            <button className="btn" onClick={() => setChecked(allChecked ? [] : items.map((x) => x.path))}>
              <CheckSquare size={15} /> {allChecked ? '取消全選' : '全選'}
            </button>
            <span className="retire-sel">已勾 {checked.length}</span>
            <button className="btn danger" style={{ marginLeft: 'auto' }} onClick={() => setConfirmAsk(true)} disabled={checked.length === 0 || busy === 'delete'}>
              <Trash2 size={15} /> 刪除勾選（{checked.length}）
            </button>
          </div>
          <div className="retire-rows">
            {items.map((it) => (
              <label key={it.path} className="retire-row" title={it.path}>
                <input type="checkbox" checked={checked.includes(it.path)} onChange={() => toggleChecked(it.path)} />
                <SourceGlyph type={sourceTypeFromPath(it.path)} />
                <span className="retire-row-title">{it.title}</span>
                <span className="retire-age">停留 {it.age_days} 天</span>
              </label>
            ))}
          </div>
        </section>
      )}

      {ready && items.length === 0 && status?.type !== 'info' && (
        <div className="cost-empty">目前沒有退場候選（窗 {staleDays} 天）。筆記庫還年輕時這是正常的；調小窗可預覽機制。</div>
      )}
    </div>
  )
}
