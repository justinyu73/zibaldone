import { useEffect, useState } from 'react'
import { apiFetch } from '../../app/api'

const COST_RANGES = [['today', '當天'], ['week', '當週'], ['month', '當月']]

export const costFmt = (value) => (value || 0).toLocaleString()
export const costUsd = (value) => `$${(value || 0).toFixed(4)}`

function CostRangeBlock({ data, showSummary = true }) {
  if (!data) return null
  return (
    <div className="cost-range-block">
      {showSummary && <div className="cost-summary-line">
        {data.range_label} · 花費 <strong>{costUsd(data.total_usd)}</strong> / tokens {costFmt(data.total_tokens)}
      </div>}
      {data.brands.length === 0 && <div className="cost-empty">此區間尚無用量紀錄。</div>}
      {data.brands.map((group) => (
        <section className="panel cost-brand" key={group.brand}>
          <div className="panel-head">
            <span className={`cost-kind ${group.kind}`}>{group.kind === 'local' ? '本機' : '雲'}</span>
            <strong>{group.brand}</strong>
            <span className="cost-brand-meta">{group.models.length} 模型 · {costFmt(group.total_tokens)} tokens · {costUsd(group.usd)}</span>
          </div>
          <table className="cost-table">
            <thead><tr><th>模型</th><th>回合</th><th>輸入</th><th>輸出</th><th>總 Token</th><th>花費</th></tr></thead>
            <tbody>
              {group.models.map((model) => (
                <tr key={model.model}>
                  <td className="cost-model">{model.model}</td>
                  <td>{costFmt(model.calls)}</td>
                  <td>{costFmt(model.input_tokens)}</td>
                  <td>{costFmt(model.output_tokens)}</td>
                  <td>{costFmt(model.total_tokens)}</td>
                  <td>{costUsd(model.usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  )
}

export default function CostView({ active }) {
  const [byRange, setByRange] = useState({})
  const [activeRange, setActiveRange] = useState('month')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [customData, setCustomData] = useState(null)
  const [customBusy, setCustomBusy] = useState(false)
  const [customError, setCustomError] = useState('')

  useEffect(() => {
    if (!active) return
    let cancelled = false
    setLoading(true); setError('')
    Promise.all(COST_RANGES.map(([key]) =>
      apiFetch(`/app/cost-breakdown?range=${key}`)
        .then((response) => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json() })
        .then((data) => [key, data])
    ))
      .then((pairs) => { if (!cancelled) setByRange(Object.fromEntries(pairs)) })
      .catch((caught) => { if (!cancelled) setError(String(caught.message || caught)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [active])

  async function queryCustom() {
    if (!customStart && !customEnd) { setCustomError('請至少選一個日期'); return }
    if (customStart && customEnd && customStart > customEnd) { setCustomError('起始日不可晚於結束日'); return }
    setCustomBusy(true); setCustomError('')
    try {
      const query = new URLSearchParams()
      if (customStart) query.set('start', customStart)
      if (customEnd) query.set('end', customEnd)
      const response = await apiFetch(`/app/cost-breakdown?${query.toString()}`)
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setCustomData(await response.json()); setActiveRange('custom')
    } catch (caught) {
      setCustomError(String(caught.message || caught)); setCustomData(null)
    } finally { setCustomBusy(false) }
  }

  const activeData = activeRange === 'custom' ? customData : byRange[activeRange]
  const activeLabel = activeRange === 'custom'
    ? (customData?.range_label || '選擇起訖日期後查詢')
    : activeData?.range_label || COST_RANGES.find(([key]) => key === activeRange)?.[1]

  return (
    <section className="cost-monitor" aria-label="cost monitor">
      <div className="cost-monitor-head">
        <div>
          <div className="command-kicker">成本監控</div>
          <h2 className="cost-title">模型火力與花費</h2>
          <p className="cost-desc">依品牌與模型列出 token 用量和花費；本機 Ollama 零成本。</p>
        </div>
        <div className="tabs-mini cost-range-tabs" role="group" aria-label="成本區間">
          {COST_RANGES.map(([key, label]) => (
            <button key={key} className={activeRange === key ? 'active' : ''} aria-pressed={activeRange === key} onClick={() => setActiveRange(key)}>{label}</button>
          ))}
          <button className={activeRange === 'custom' ? 'active' : ''} aria-pressed={activeRange === 'custom'} onClick={() => setActiveRange('custom')}>自訂</button>
        </div>
      </div>
      {loading && <div className="cost-empty">載入中…</div>}
      {error && <div className="cost-empty">讀取失敗：{error}</div>}

      {!loading && !error && (
        <div className="cost-active-overview" role="group" aria-label="目前區間總覽">
          <div><span>區間</span><strong>{activeLabel}</strong></div>
          <div><span>花費</span><strong className="cost-overview-usd">{costUsd(activeData?.total_usd)}</strong></div>
          <div><span>Token</span><strong>{costFmt(activeData?.total_tokens)}</strong></div>
        </div>
      )}

      {!loading && !error && activeRange === 'custom' && (
        <div className="cost-custom">
          <div className="cost-custom-bar">
            <span className="cost-custom-lbl">日期區間</span>
            <input type="date" value={customStart} onChange={(event) => setCustomStart(event.target.value)} aria-label="起始日" />
            <span>至</span>
            <input type="date" value={customEnd} onChange={(event) => setCustomEnd(event.target.value)} aria-label="結束日" />
            <button className="primary" onClick={queryCustom} disabled={customBusy}>{customBusy ? '查詢中…' : '查詢'}</button>
          </div>
          {customError && <div className="cost-empty">{customError}</div>}
        </div>
      )}

      {!loading && !error && activeData && (
        <>
          <div className="cost-sort-note"><strong>排序</strong><span>品牌與模型依花費高到低，同額再依 Token 用量排列。</span></div>
          <CostRangeBlock data={activeData} showSummary={false} />
        </>
      )}
      {!loading && !error && activeRange === 'custom' && !customData && !customError && (
        <div className="cost-empty">選擇起訖日期後查詢該區間用量。</div>
      )}
    </section>
  )
}
