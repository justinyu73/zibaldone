import { splitTimestamp } from './timestamp'

export default function MeetingField({ label, value, list, onSeek }) {
  const empty = list ? !(value && value.length) : !value
  if (empty) return null
  const items = list
    ? value
    : String(value).split(/\n+/).map((item) => item.replace(/^\s*-\s*/, '')).filter(Boolean)
  const renderItem = (item, i) => {
    const { text, ts } = splitTimestamp(item)
    return <li key={i}><span className="txt">{text}</span>{ts && (onSeek
      ? <button type="button" className="ts ts-seek" onClick={() => onSeek(ts)} title="跳到音檔此處核對">{ts}</button>
      : <span className="ts">{ts}</span>)}</li>
  }
  return (
    <div className="meeting-field">
      <div className="meeting-field-label">{label}</div>
      {(list || items.length > 1)
        ? <ul>{items.map(renderItem)}</ul>
        : (() => {
            const { text, ts } = splitTimestamp(items[0])
            return <p><span className="txt">{text}</span>{ts && (onSeek
              ? <button type="button" className="ts ts-seek" onClick={() => onSeek(ts)} title="跳到音檔此處核對">{ts}</button>
              : <span className="ts">{ts}</span>)}</p>
          })()}
    </div>
  )
}
