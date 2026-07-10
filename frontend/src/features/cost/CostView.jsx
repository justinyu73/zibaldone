import { useEffect, useMemo, useState } from 'react'
import {
  ArrowDownToLine, ArrowUpFromLine, BarChart3, ChevronDown, Coins,
  LayoutGrid, LineChart, Table as TableIcon,
} from 'lucide-react'
import { apiFetch } from '../../app/api'

const COST_RANGES = [['today', '今日'], ['week', '本週'], ['month', '本月']]

// 國際幣別：rate 為示意常數（非即時匯率），USD 為資料真值來源。
export const CURRENCIES = {
  USD: { symbol: '$', flag: '🇺🇸', rate: 1, dp: 2, name: '美元' },
  TWD: { symbol: 'NT$', flag: '🇹🇼', rate: 32.5, dp: 0, name: '新台幣' },
  JPY: { symbol: '¥', flag: '🇯🇵', rate: 157, dp: 0, name: '日圓' },
  CNY: { symbol: '¥', flag: '🇨🇳', rate: 7.2, dp: 2, name: '人民幣' },
  EUR: { symbol: '€', flag: '🇪🇺', rate: 0.92, dp: 2, name: '歐元' },
  GBP: { symbol: '£', flag: '🇬🇧', rate: 0.79, dp: 2, name: '英鎊' },
  KRW: { symbol: '₩', flag: '🇰🇷', rate: 1380, dp: 0, name: '韓元' },
}

export const costFmt = (value) => (value || 0).toLocaleString()
export const costUsd = (value) => `$${(value || 0).toFixed(4)}`

export const costMoney = (usd, currency = 'USD') => {
  const c = CURRENCIES[currency] || CURRENCIES.USD
  const value = (usd || 0) * c.rate
  return c.symbol + value.toLocaleString('en-US', { minimumFractionDigits: c.dp, maximumFractionDigits: c.dp })
}

// 品牌名 → 圖示語意類別（供上色與 glyph）；未知品牌退回通用。
export function brandKey(brand) {
  const b = String(brand || '').toLowerCase()
  if (b.includes('claude') || b.includes('anthropic')) return 'claude'
  if (b.includes('openai') || b.includes('gpt')) return 'openai'
  if (b.includes('gemini') || b.includes('google')) return 'gemini'
  if (b.includes('ollama') || b.includes('llama') || b.includes('qwen')) return 'ollama'
  return 'generic'
}

function BrandGlyph({ brand }) {
  const key = brandKey(brand)
  const paths = {
    claude: <path d="M12 2c.5 3.4 2 5.4 4.5 6.2C14 9 12.5 11 12 14c-.5-3-2-5-4.5-5.8C10 7.4 11.5 5.4 12 2z" />,
    gemini: <path d="M12 2c.6 5.2 4.2 8.8 10 9.4C16.2 12 12.6 15.6 12 22c-.6-6.4-4.2-10-10-10.6C7.8 10.8 11.4 7.2 12 2z" />,
  }
  return (
    <span className={`cost-glyph cg-${key}`} aria-hidden="true">
      {key === 'claude' || key === 'gemini' ? (
        <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">{paths[key]}</svg>
      ) : key === 'openai' ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><circle cx="12" cy="12" r="5" /></svg>
      ) : key === 'ollama' ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13"><rect x="5" y="9" width="14" height="10" rx="2" /></svg>
      ) : (
        <Coins size={13} />
      )}
    </span>
  )
}

function CurrencyPicker({ currency, onChange }) {
  const [open, setOpen] = useState(false)
  const c = CURRENCIES[currency]
  useEffect(() => {
    if (!open) return undefined
    const close = () => setOpen(false)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [open])
  return (
    <div className="cost-cur" onClick={(e) => e.stopPropagation()}>
      <button className="cost-cur-toggle" aria-haspopup="true" aria-expanded={open} aria-label="幣別" onClick={() => setOpen((v) => !v)}>
        <span className="cost-cur-flag">{c.flag}</span>
        <span className="cost-cur-sym">{c.symbol}</span>
        <ChevronDown size={13} className={open ? 'flip' : ''} />
      </button>
      {open && (
        <div className="cost-cur-menu" role="menu">
          {Object.entries(CURRENCIES).map(([code, info]) => (
            <button key={code} role="menuitemradio" aria-checked={code === currency}
              className={code === currency ? 'active' : ''}
              onClick={() => { onChange(code); setOpen(false) }}>
              <span className="mflag">{info.flag}</span><span className="msym">{info.symbol}</span>{code}
              <span className="mname">{info.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function totalsFromData(data) {
  let input = 0
  let output = 0
  for (const group of data?.brands || []) {
    for (const model of group.models) { input += model.input_tokens || 0; output += model.output_tokens || 0 }
  }
  return { input, output }
}

function KpiStrip({ data, currency }) {
  const { input, output } = totalsFromData(data)
  const total = data?.total_tokens || 0
  const cloudUsd = (data?.brands || []).filter((b) => b.kind !== 'local').reduce((s, b) => s + (b.usd || 0), 0)
  const pct = (part) => (total ? `${((part / total) * 100).toFixed(1)}%` : '—')
  return (
    <div className="cost-kpis" role="group" aria-label="區間總覽">
      <div className="cost-kpi">
        <div className="cost-kpi-h"><span className="cost-kpi-ic"><BarChart3 size={15} /></span>總 Token</div>
        <div className="cost-kpi-v">{costFmt(total)}</div>
        <div className="cost-kpi-f">{data?.brands?.length || 0} 品牌</div>
      </div>
      <div className="cost-kpi">
        <div className="cost-kpi-h"><span className="cost-kpi-ic"><ArrowDownToLine size={15} /></span>輸入 Token</div>
        <div className="cost-kpi-v">{costFmt(input)}</div>
        <div className="cost-kpi-f">佔 {pct(input)}</div>
      </div>
      <div className="cost-kpi">
        <div className="cost-kpi-h"><span className="cost-kpi-ic"><ArrowUpFromLine size={15} /></span>輸出 Token</div>
        <div className="cost-kpi-v">{costFmt(output)}</div>
        <div className="cost-kpi-f">佔 {pct(output)}</div>
      </div>
      <div className="cost-kpi cost-kpi-cost">
        <div className="cost-kpi-h"><span className="cost-kpi-ic"><Coins size={15} /></span>估算花費</div>
        <div className="cost-kpi-v">{costMoney(data?.total_usd, currency)}</div>
        <div className="cost-kpi-f">雲端 {costMoney(cloudUsd, currency)} · 本機 {costMoney(0, currency)}</div>
      </div>
    </div>
  )
}

function ChartView({ data, currency }) {
  const brands = data?.brands || []
  const maxUsd = Math.max(1e-9, ...brands.map((b) => b.usd || 0))
  const { input, output } = totalsFromData(data)
  const outPct = input + output ? (output / (input + output)) * 100 : 0
  return (
    <div className="cost-chart-grid">
      <section className="panel cost-chartcard">
        <div className="cost-chart-title"><BarChart3 size={15} />各品牌花費占比</div>
        <div className="cost-bars">
          {brands.map((b) => {
            const local = b.kind === 'local'
            const w = local ? 0 : ((b.usd || 0) / maxUsd) * 100
            return (
              <div className="cost-bar-row" key={b.brand}>
                <span className="cost-bar-name"><BrandGlyph brand={b.brand} />{b.brand}</span>
                <span className="cost-track"><span className={`cost-fill cf-${brandKey(b.brand)}`} style={{ width: `${local ? 40 : w}%`, opacity: local ? 0.5 : 1 }} /></span>
                <span className="cost-bar-amt">{local ? `${costMoney(0, currency)} · ${costFmt(b.total_tokens)}` : costMoney(b.usd, currency)}</span>
              </div>
            )
          })}
        </div>
      </section>
      <section className="panel cost-chartcard cost-donut-wrap">
        <div className="cost-chart-title"><LineChart size={15} />輸入 / 輸出 占比</div>
        <div className="cost-donut" style={{ background: `conic-gradient(var(--brand) 0 ${outPct}%, color-mix(in srgb, var(--brand) 22%, var(--inset)) ${outPct}% 100%)` }}>
          <div className="cost-donut-hole"><span>輸出</span><b>{outPct.toFixed(1)}%</b></div>
        </div>
        <div className="cost-legend">
          <span><i style={{ background: 'var(--brand)' }} />輸出 {costFmt(output)}</span>
          <span><i style={{ background: 'color-mix(in srgb, var(--brand) 22%, var(--inset))' }} />輸入 {costFmt(input)}</span>
        </div>
      </section>
    </div>
  )
}

function CardsView({ data, currency }) {
  return (
    <div className="cost-cards">
      {(data?.brands || []).map((b) => (
        <section className="panel cost-bcard" key={b.brand}>
          <div className="cost-bcard-top">
            <BrandGlyph brand={b.brand} />
            <span className="cost-bcard-nm">{b.brand}</span>
            <span className={`cost-kind ${b.kind === 'local' ? 'local' : 'cloud'}`}>{b.kind === 'local' ? '本機' : '雲'} · {b.models.length} 模型</span>
          </div>
          <div className="cost-metrics">
            <div className="cost-metric"><span>回合</span><b>{costFmt(b.models.reduce((s, m) => s + (m.calls || 0), 0))}</b></div>
            <div className="cost-metric"><span>總 Token</span><b>{costFmt(b.total_tokens)}</b></div>
            <div className="cost-metric"><span>花費</span><b className={b.kind === 'local' ? 'free' : 'usd'}>{costMoney(b.kind === 'local' ? 0 : b.usd, currency)}</b></div>
          </div>
        </section>
      ))}
    </div>
  )
}

function TableView({ data, currency }) {
  return (
    <div className="cost-range-block">
      {(data?.brands || []).length === 0 && <div className="cost-empty">此區間尚無用量紀錄。</div>}
      {(data?.brands || []).map((group) => (
        <section className="panel cost-brand" key={group.brand}>
          <div className="panel-head">
            <span className={`cost-kind ${group.kind === 'local' ? 'local' : 'cloud'}`}>{group.kind === 'local' ? '本機' : '雲'}</span>
            <strong>{group.brand}</strong>
            <span className="cost-brand-meta">{group.models.length} 模型 · {costFmt(group.total_tokens)} tokens · {costMoney(group.kind === 'local' ? 0 : group.usd, currency)}</span>
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
                  <td>{costMoney(group.kind === 'local' ? 0 : model.usd, currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  )
}

const VIEWS = [['chart', '圖表', LineChart], ['cards', '卡片', LayoutGrid], ['table', '表格', TableIcon]]

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
  const [currency, setCurrency] = useState('USD')
  const [view, setView] = useState('chart')
  const [hidden, setHidden] = useState(() => new Set())

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

  const rawData = activeRange === 'custom' ? customData : byRange[activeRange]
  const activeLabel = activeRange === 'custom'
    ? (customData?.range_label || '選擇起訖日期後查詢')
    : rawData?.range_label || COST_RANGES.find(([key]) => key === activeRange)?.[1]

  const filteredData = useMemo(() => {
    if (!rawData) return rawData
    return { ...rawData, brands: (rawData.brands || []).filter((b) => !hidden.has(b.brand)) }
  }, [rawData, hidden])

  function toggleBrand(brand) {
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(brand)) next.delete(brand); else next.add(brand)
      return next
    })
  }

  return (
    <section className="cost-monitor" aria-label="cost monitor">
      <div className="cost-monitor-head">
        <div>
          <div className="command-kicker">成本監控</div>
          <h2 className="cost-title">模型火力與花費</h2>
          <p className="cost-desc">依品牌與模型列出 token 用量和花費；本機 Ollama 零成本。</p>
        </div>
        <div className="cost-head-tools">
          <div className="tabs-mini cost-range-tabs" role="group" aria-label="成本區間">
            {COST_RANGES.map(([key, label]) => (
              <button key={key} className={activeRange === key ? 'active' : ''} aria-pressed={activeRange === key} onClick={() => setActiveRange(key)}>{label}</button>
            ))}
            <button className={activeRange === 'custom' ? 'active' : ''} aria-pressed={activeRange === 'custom'} onClick={() => setActiveRange('custom')}>自訂</button>
          </div>
          <CurrencyPicker currency={currency} onChange={setCurrency} />
        </div>
      </div>

      {loading && <div className="cost-empty">載入中…</div>}
      {error && <div className="cost-empty">讀取失敗：{error}</div>}

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

      {!loading && !error && rawData && (
        <>
          <KpiStrip data={rawData} currency={currency} />

          {(rawData.brands || []).length > 0 && (
            <div className="cost-chips" role="group" aria-label="依品牌篩選">
              <span className="cost-chips-lbl">品牌</span>
              {(rawData.brands || []).map((b) => {
                const on = !hidden.has(b.brand)
                return (
                  <button key={b.brand} className={`cost-chip ${on ? '' : 'off'}`} aria-pressed={on} onClick={() => toggleBrand(b.brand)}>
                    <BrandGlyph brand={b.brand} />{b.brand}
                    <span className="cost-chip-amt">{b.kind === 'local' ? `本機 ${costMoney(0, currency)}` : costMoney(b.usd, currency)}</span>
                  </button>
                )
              })}
            </div>
          )}

          <div className="cost-viewbar">
            <h3>{activeLabel} 用量明細</h3>
            <div className="tabs-mini cost-viewswitch" role="group" aria-label="檢視方式">
              {VIEWS.map(([key, label, Icon]) => (
                <button key={key} className={view === key ? 'active' : ''} aria-pressed={view === key} onClick={() => setView(key)}><Icon size={14} />{label}</button>
              ))}
            </div>
          </div>

          {view === 'chart' && <ChartView data={filteredData} currency={currency} />}
          {view === 'cards' && <CardsView data={filteredData} currency={currency} />}
          {view === 'table' && <TableView data={filteredData} currency={currency} />}
          <p className="cost-fx-note">花費以 USD 記錄；其他幣別為示意匯率換算（非即時）。品牌與模型依花費高到低排列。</p>
        </>
      )}

      {!loading && !error && activeRange === 'custom' && !customData && !customError && (
        <div className="cost-empty">選擇起訖日期後查詢該區間用量。</div>
      )}
    </section>
  )
}
