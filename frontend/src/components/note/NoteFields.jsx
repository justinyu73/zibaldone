import { useState } from 'react'
import {
  CATEGORY_LIST_KEY, CATEGORY_OPTIONS, SOURCE_LIST_KEY, SOURCE_OPTIONS,
  loadOptionList, saveOptionList, withCurrent,
} from '../../app/optionLists'

// Select with a fully user-managed option list (seeded from presets plus any
// pre-v1 custom entries on first run): ＋ adds an entry, － removes the
// currently selected one; the last remaining entry cannot be removed.
// Used by 內容來源 and 分類.
function CustomSelect({ value, onChange, presets, storageKey, ariaLabel }) {
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [list, setList] = useState(() => loadOptionList(storageKey, presets))
  const options = withCurrent(list, value)
  function confirm() {
    const trimmed = name.trim()
    if (!trimmed) return
    const next = [...new Set([...list, trimmed])]
    saveOptionList(storageKey, next); setList(next)
    onChange(trimmed)
    setAdding(false); setName('')
  }
  function removeCurrent() {
    const next = list.filter((n) => n !== value)
    saveOptionList(storageKey, next); setList(next)
    onChange(next[0])
  }
  if (adding) {
    return (
      <div className="cat-row">
        <input value={name} autoFocus placeholder="新增選項（Enter 加入）"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && confirm()} />
        <button className="primary" type="button" onClick={confirm}>加入</button>
        <button className="ghost" type="button" onClick={() => setAdding(false)}>取消</button>
      </div>
    )
  }
  return (
    <div className="cat-row">
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={ariaLabel}>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
      <button className="ghost" type="button" onClick={() => setAdding(true)} title="新增自訂選項">＋</button>
      {list.includes(value) && list.length > 1 && (
        <button className="ghost danger-ghost" type="button" title="移除此選項"
          onClick={removeCurrent}>－</button>
      )}
    </div>
  )
}

const NOTE_EDIT_FIELDS = [
  ['title', '標題', 'input'],
  ['explicit_topic', '主題摘要', 'textarea'],
  ['key_points', '重點條列', 'textarea'],
  ['terms', '專有名詞 / 人物 / 工具', 'textarea'],
  ['content_value', '核心內容價值', 'textarea'],
  ['manual_summary', '個人心得', 'textarea'],
  ['source_meta', '來源與分類', 'meta'],
  ['filename', '檔名', 'input'],
]

// Shared editable note-fields block (區塊3 / 媒體庫筆記詳情).
// Intake lanes use the focused workspace so long drafts do not stack many textareas.
export default function NoteFields({ draft, setDraft, disabled, workspace = false }) {
  const [activeField, setActiveField] = useState('title')
  const set = (key) => (event) => setDraft({ ...draft, [key]: event.target.value })
  if (workspace) {
    const active = NOTE_EDIT_FIELDS.find(([key]) => key === activeField) || NOTE_EDIT_FIELDS[0]
    const [key, label, control] = active
    const value = key === 'source_meta'
      ? `${draft.source_platform || ''}${draft.content_category || ''}`
      : draft[key] || ''
    return (
      <div className="note-fields-workspace">
        <div className="summary-field-nav note-field-nav" role="tablist" aria-label="筆記欄位">
          {NOTE_EDIT_FIELDS.map(([itemKey, itemLabel]) => {
            const itemValue = itemKey === 'source_meta'
              ? `${draft.source_platform || ''}${draft.content_category || ''}`
              : draft[itemKey] || ''
            return <button key={itemKey} type="button" role="tab" aria-selected={activeField === itemKey}
              className={activeField === itemKey ? 'active' : ''} onClick={() => setActiveField(itemKey)}>
              <span>{itemLabel}</span><small>{itemValue.length}</small>
            </button>
          })}
        </div>
        <div className="note-active-field">
          <div className="active-field-head"><strong>{label}</strong><span className="muted">{value.length} 字</span></div>
          {control === 'meta' ? (
            <div className="note-fields-row">
              <label>內容來源
                <CustomSelect value={draft.source_platform} onChange={(v) => setDraft({ ...draft, source_platform: v })}
                  presets={SOURCE_OPTIONS} storageKey={SOURCE_LIST_KEY} ariaLabel="內容來源" />
              </label>
              <label>分類
                <CustomSelect value={draft.content_category} onChange={(v) => setDraft({ ...draft, content_category: v })}
                  presets={CATEGORY_OPTIONS} storageKey={CATEGORY_LIST_KEY} ariaLabel="分類" />
              </label>
            </div>
          ) : control === 'input' ? (
            <input aria-label={label} value={value} onChange={set(key)} placeholder={key === 'filename' ? '留空則以標題自動建立' : ''} />
          ) : (
            <textarea aria-label={label} rows={14} value={value} onChange={set(key)}
              placeholder={key === 'manual_summary' ? (disabled ? '編輯模式不寫回個人心得' : '人為補充的心得 / 對應專案') : ''}
              disabled={disabled && key === 'manual_summary'} />
          )}
        </div>
      </div>
    )
  }
  return (
    <div className="note-fields">
      <label>檔名（留空＝自動）<input value={draft.filename} onChange={set('filename')} placeholder="自動以標題建立" /></label>
      <label>標題<input value={draft.title} onChange={set('title')} /></label>
      <label>主題摘要<textarea rows={2} value={draft.explicit_topic} onChange={set('explicit_topic')} /></label>
      <label>重點條列<textarea rows={4} value={draft.key_points} onChange={set('key_points')} /></label>
      <label>專有名詞 / 人物 / 工具<textarea rows={3} value={draft.terms} onChange={set('terms')} /></label>
      <label>核心內容價值提取<textarea rows={3} value={draft.content_value} onChange={set('content_value')} /></label>
      <div className="note-fields-row">
        <label>內容來源
          <CustomSelect value={draft.source_platform} onChange={(v) => setDraft({ ...draft, source_platform: v })}
            presets={SOURCE_OPTIONS} storageKey={SOURCE_LIST_KEY} ariaLabel="內容來源" />
        </label>
        <label>分類
          <CustomSelect value={draft.content_category} onChange={(v) => setDraft({ ...draft, content_category: v })}
            presets={CATEGORY_OPTIONS} storageKey={CATEGORY_LIST_KEY} ariaLabel="分類" />
        </label>
      </div>
      <label>個人心得筆記<textarea rows={3} value={draft.manual_summary} onChange={set('manual_summary')}
        placeholder={disabled ? '編輯模式不寫回個人心得（保護筆記中的人工內容，請直接在筆記檔編輯）' : '人為補充的心得 / 對應專案'} disabled={disabled} /></label>
    </div>
  )
}
