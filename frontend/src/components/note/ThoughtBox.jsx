import { useState } from 'react'
import { Pencil } from 'lucide-react'

// 事後補心得（消化的本義）：追加帶日期心得到「個人心得筆記」段，不動原有內容；
// 可標「可提取」（frontmatter distill: candidate）攢給日後蒸餾輪，app 不做自動提取。
export default function ThoughtBox({ onSave, busy }) {
  const [text, setText] = useState('')
  const [distill, setDistill] = useState(false)
  async function save() {
    if (!text.trim()) return
    const ok = await onSave(text.trim(), distill)
    if (ok) { setText(''); setDistill(false) }
  }
  return (
    <div className="thought-box">
      <label>補心得（追加到「個人心得筆記」，原內容不動、前一版自動備份）
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)}
          placeholder="讀完的想法、可複用的點…" />
      </label>
      <div className="row thought-actions">
        <label className="thought-distill">
          <input type="checkbox" checked={distill} onChange={(e) => setDistill(e.target.checked)} />
          含可提取的 prompt／方法／判斷
        </label>
        <button className="primary" onClick={save} disabled={busy || !text.trim()}>
          <Pencil size={15} />{busy ? '寫入中…' : '寫入心得'}
        </button>
      </div>
    </div>
  )
}
