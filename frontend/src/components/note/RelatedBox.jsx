import { useState } from 'react'
import { Route, Save } from 'lucide-react'
import { apiFetch, postJson } from '../../app/api'

// 相關筆記：FTS5 候選（本篇標題＋專有名詞命中）→ 人勾選確認 → 寫入「## 相關筆記」
// 段的 [[wikilink]]。鏈接落在檔案裡：Obsidian 圖譜與之後讀 vault 的 AI 讀同一張關聯網。
export default function RelatedBox({ params, onStatus, onWritten }) {
  const [busy, setBusy] = useState('')
  const [cands, setCands] = useState(null) // null=尚未找
  const [picked, setPicked] = useState([])
  async function find() {
    setBusy('find')
    try {
      const r = await apiFetch(`/app/related-notes?${new URLSearchParams({ vault_root: params.vault_path, note_relpath: params.note_relpath })}`)
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || '找相關筆記失敗')
      setCands(d.candidates || []); setPicked((d.candidates || []).map((c) => c.path))
    } catch (e) { onStatus?.({ type: 'error', message: e.message }) } finally { setBusy('') }
  }
  async function write() {
    setBusy('write')
    try {
      const d = await postJson('/app/note-links', { vault_root: params.vault_path, note_relpath: params.note_relpath, paths: picked })
      onStatus?.({ type: 'ok', message: `已寫入 ${d.added} 條關聯到「相關筆記」段（前一版已備份）` })
      setCands(null); setPicked([])
      onWritten?.()
    } catch (e) { onStatus?.({ type: 'error', message: e.message }) } finally { setBusy('') }
  }
  const toggle = (path) => setPicked((arr) => (arr.includes(path) ? arr.filter((p) => p !== path) : [...arr, path]))
  return (
    <div className="related-box">
      <div className="row related-head">
        <span className="related-title"><Route size={14} /> 相關筆記（寫入後 Obsidian 圖譜可見）</span>
        <button className="ghost" onClick={find} disabled={busy === 'find'}>{busy === 'find' ? '尋找中…' : '找相關'}</button>
      </div>
      {cands && (cands.length === 0 ? (
        <span className="muted">沒有命中的相關筆記（候選來自本篇標題與專有名詞；已鏈接過的不重複出現）。</span>
      ) : (
        <>
          {cands.map((c) => (
            <label key={c.path} className="related-item">
              <input type="checkbox" checked={picked.includes(c.path)} onChange={() => toggle(c.path)} />
              <span className="li-main">
                <span className="li-title">{c.title}</span>
                <span className="li-snippet">命中：{c.matched.join('、')}</span>
              </span>
            </label>
          ))}
          <div className="row end">
            <button className="primary" onClick={write} disabled={busy === 'write' || picked.length === 0}>
              <Save size={15} />{busy === 'write' ? '寫入中…' : `寫入勾選的關聯（${picked.length}）`}
            </button>
          </div>
        </>
      ))}
    </div>
  )
}
