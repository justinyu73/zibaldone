import { Globe, PlayCircle } from 'lucide-react'

// Read-only article view (筆記庫 查閱模式).
export default function ReadView({ draft, sourceUrl }) {
  const Field = ({ label, value }) => (value ? (
    <div className="read-field">
      <div className="read-label">{label}</div>
      <div className="read-value">{value}</div>
    </div>
  ) : null)
  return (
    <div className="read-view">
      <h4 className="read-title">{draft.title || '（無標題）'}</h4>
      <div className="read-meta">
        {draft.source_platform && <span className="li-type">{draft.source_platform}</span>}
        {draft.content_category && <span className="li-type">{draft.content_category}</span>}
      </div>
      {sourceUrl && (
        <a className="read-source" href={sourceUrl} target="_blank" rel="noreferrer">
          <Globe size={14} /><span>{sourceUrl}</span><PlayCircle size={14} />
        </a>
      )}
      <Field label="主題摘要" value={draft.explicit_topic} />
      <Field label="重點條列" value={draft.key_points} />
      <Field label="專有名詞 / 人物 / 工具" value={draft.terms} />
      <Field label="核心內容價值" value={draft.content_value} />
      <Field label="個人心得" value={draft.manual_summary} />
    </div>
  )
}
