import { useEffect, useState } from 'react'
import { Check, ChevronDown } from 'lucide-react'
import BrandGlyph from '../BrandGlyph'

export const PROVIDER_META = {
  openai: { label: 'OpenAI', cost: '雲端·付費', placeholder: 'sk-...（只存本機家目錄，不進 repo、不顯示明文）' },
  anthropic: { label: 'Claude', cost: '雲端·付費', placeholder: 'sk-ant-...（只存本機家目錄，不進 repo、不顯示明文）' },
  google: { label: 'Gemini', cost: '雲端·付費', placeholder: 'AIza...（只存本機家目錄，不進 repo、不顯示明文）' },
  llamacpp: { label: '內建本機 AI', cost: '免費' },
  cli: { label: '訂閱 CLI', cost: '訂閱額度·app 零成本' },
}

export const PROVIDER_ORDER = ['openai', 'anthropic', 'google']

export function providerForModel(id, options = []) {
  return options.find((option) => option.id === id)?.provider
    || (String(id || '').startsWith('llamacpp:')
      ? 'llamacpp'
      : String(id || '').startsWith('cli:')
        ? 'cli'
      : String(id || '').startsWith('claude')
        ? 'anthropic'
        : String(id || '').startsWith('gemini')
          ? 'google'
          : 'openai')
}

export function providerLabelForModel(id, options = []) {
  const provider = providerForModel(id, options)
  return PROVIDER_META[provider]?.label || provider
}

// 精簡：LOGO 代表 provider，短標籤只留「模型名 + 單一費用字」，不重複 provider/雲端。
export function costTag(provider) {
  if (provider === 'llamacpp') return '免費'
  if (provider === 'cli') return '零成本'
  return '付費'
}

function ModelRow({ option, compact, toggle = false }) {
  const provider = option.provider || providerForModel(option.id)
  const name = compact ? option.id : (option.label || option.id)
  return (
    <span className="ms-row">
      <BrandGlyph provider={provider} />
      <span className="ms-name">{name}</span>
      {/* 收合鈕在窄欄位省略「推薦」小標，優先讓模型名可讀，避免版位超出 */}
      {!toggle && option.recommended && <span className="ms-rec">推薦</span>}
      <span className={`ms-tag ${provider === 'llamacpp' || provider === 'cli' ? 'free' : 'paid'}`}>{costTag(provider)}</span>
    </span>
  )
}

export default function ModelSelect({ value, onChange, options, compact = false }) {
  const [open, setOpen] = useState(false)
  const available = options || []
  const ids = available.map((option) => option.id)
  const list = value && !ids.includes(value) ? [{ id: value, label: value }, ...available] : available
  const current = list.find((o) => o.id === value) || (value ? { id: value, label: value } : null)

  useEffect(() => {
    if (!open) return undefined
    const close = () => setOpen(false)
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('click', close)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('click', close); window.removeEventListener('keydown', onKey) }
  }, [open])

  function pick(id) { onChange?.({ target: { value: id } }); setOpen(false) }

  return (
    <div className={`model-select ${compact ? 'compact' : ''}${open ? ' open' : ''}`} onClick={(e) => e.stopPropagation()}>
      <button type="button" className="model-select-toggle" aria-haspopup="listbox" aria-expanded={open}
        disabled={list.length === 0} onClick={() => setOpen((v) => !v)}>
        {current ? <ModelRow option={current} compact={compact} toggle /> : <span className="ms-placeholder">{list.length ? '選擇模型' : '載入中…'}</span>}
        <ChevronDown size={15} className="ms-caret" />
      </button>
      {open && (
        <div className="model-select-menu" role="listbox">
          {list.map((option) => (
            <button key={option.id} type="button" role="option" aria-selected={option.id === value}
              className={option.id === value ? 'active' : ''} onClick={() => pick(option.id)}>
              <ModelRow option={option} compact={compact} />
              {option.id === value && <Check size={15} className="ms-check" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
