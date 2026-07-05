import { FileAudio, PlayCircle, X } from 'lucide-react'

const STATUS_LABELS = {
  queued: '等待',
  running: '處理中',
  review_ready: '待校正',
  written: '已寫入',
  error: '失敗',
  cancelled: '已取消',
  interrupted: '可續跑',
}

function statusTone(status) {
  if (status === 'written') return 'ok'
  if (status === 'error') return 'error'
  if (status === 'review_ready') return 'info'
  return 'neutral'
}

export default function MeetingQueue({ busy, onOpen, onRemove, onRun, queue, running }) {
  if (!queue.length) return null
  return (
    <section className="panel meeting-queue-panel">
      <div className="panel-head">
        <div><FileAudio size={16} /><h3>批次佇列</h3></div>
        <div className="row">
          <span className="state-chip neutral">{queue.length} 項</span>
          <button className="primary" onClick={onRun} disabled={running || busy}>
            <PlayCircle size={15} />{running ? '順序處理中' : '開始／續跑'}
          </button>
        </div>
      </div>
      <div className="meeting-queue-list">
        {queue.map((item) => (
          <div key={item.id} className={`meeting-queue-item ${item.status}`}>
            <button type="button" className="queue-main" onClick={() => onOpen(item)} title={item.audio_path}>
              <span>{item.audio_path.split(/[\\/]/).pop()}</span>
              <small>{item.tier}{item.precise ? ' · 精準' : ''}</small>
            </button>
            <span className={`state-chip ${statusTone(item.status)}`}>
              {STATUS_LABELS[item.status] || item.status}
            </span>
            {item.status !== 'running' && (
              <button type="button" className="ghost danger-ghost icon-button queue-remove"
                aria-label="移除佇列項目" title="只移除佇列，不刪除音檔或草稿"
                onClick={() => onRemove(item.id)}>
                <X size={14} /><span>移除</span>
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
