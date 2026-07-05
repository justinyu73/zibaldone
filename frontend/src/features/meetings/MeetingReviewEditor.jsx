import { useState } from 'react'

const MEETING_EDIT_FIELDS = [
  ['title', '標題', false],
  ['summary', '摘要', false],
  ['key_organization', '重要整理', false],
  ['core_value', '核心價值', false],
  ['action_items', '行動項目', true],
  ['decisions', '決議', true],
  ['attendees', '出席者', true],
  ['agenda', '議程', true],
]

export default function MeetingReviewEditor({ summary, transcript, onSummary, onTranscript }) {
  const [mode, setMode] = useState('summary')
  const [activeField, setActiveField] = useState('title')
  const active = MEETING_EDIT_FIELDS.find(([field]) => field === activeField) || MEETING_EDIT_FIELDS[0]
  const [field, label, list] = active
  const activeValue = list ? (summary?.[field] || []).join('\n') : (summary?.[field] || '')
  const update = (event) => {
    const value = list
      ? event.target.value.split('\n').map((line) => line.trim()).filter(Boolean)
      : event.target.value
    onSummary({ ...summary, [field]: value })
  }
  return (
    <div className="meeting-review-editor">
      <div className="review-editor-head">
        <div>
          <strong>人工校正草稿</strong>
          <span className="muted">{mode === 'summary' ? `${label} · ${activeValue.length} 字` : `逐字稿 · ${transcript.length} 字`}</span>
        </div>
        <span className="state-chip info">尚未寫入</span>
      </div>
      <div className="tabs-mini review-mode-tabs" role="group" aria-label="人工校正內容">
        <button type="button" className={mode === 'summary' ? 'active' : ''} aria-pressed={mode === 'summary'} onClick={() => setMode('summary')}>摘要欄位</button>
        <button type="button" className={mode === 'transcript' ? 'active' : ''} aria-pressed={mode === 'transcript'} onClick={() => setMode('transcript')}>逐字稿</button>
      </div>
      {mode === 'summary' ? (
        <div className="meeting-summary-workspace">
          <div className="summary-field-nav" role="tablist" aria-label="摘要欄位">
            {MEETING_EDIT_FIELDS.map(([itemField, itemLabel, itemList]) => {
              const value = itemList ? (summary?.[itemField] || []).join('\n') : (summary?.[itemField] || '')
              return <button key={itemField} type="button" role="tab" aria-selected={activeField === itemField} className={activeField === itemField ? 'active' : ''} onClick={() => setActiveField(itemField)}>
                <span>{itemLabel}</span><small>{value.length}</small>
              </button>
            })}
          </div>
          <label className="meeting-active-field">{label}
            <textarea rows={list ? 12 : 10} value={activeValue} onChange={update} />
          </label>
        </div>
      ) : (
        <label className="meeting-transcript-editor">逐字稿
          <textarea rows={24} value={transcript} onChange={(event) => onTranscript(event.target.value)} />
        </label>
      )}
    </div>
  )
}
