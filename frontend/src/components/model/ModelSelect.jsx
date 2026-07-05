export const PROVIDER_META = {
  openai: { label: 'OpenAI', cost: '雲端·付費', placeholder: 'sk-...（只存本機家目錄，不進 repo、不顯示明文）' },
  anthropic: { label: 'Claude', cost: '雲端·付費', placeholder: 'sk-ant-...（只存本機家目錄，不進 repo、不顯示明文）' },
  google: { label: 'Gemini', cost: '雲端·付費', placeholder: 'AIza...（只存本機家目錄，不進 repo、不顯示明文）' },
  ollama: { label: '本地 Ollama', cost: '免費' },
  cli: { label: '訂閱 CLI', cost: '訂閱額度·app 零成本' },
}

export const PROVIDER_ORDER = ['openai', 'anthropic', 'google']

export function providerForModel(id, options = []) {
  return options.find((option) => option.id === id)?.provider
    || (String(id || '').startsWith('ollama:')
      ? 'ollama'
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

export default function ModelSelect({ value, onChange, options, compact = false }) {
  const available = options || []
  const ids = available.map((option) => option.id)
  const list = value && !ids.includes(value) ? [{ id: value, label: value }, ...available] : available
  return (
    <select value={value || ''} onChange={onChange}>
      {list.length === 0 && <option value={value || ''}>{value || '載入中…'}</option>}
      {list.map((option) => (
        <option key={option.id} value={option.id}>
          {compact
            ? `${option.id}${option.recommended ? '（推薦）' : ''} · ${option.provider === 'ollama' ? '免費' : '付費'}`
            : `${option.label}${option.recommended ? '（推薦）' : ''}${option.provider ? ` · ${PROVIDER_META[option.provider]?.label || option.provider}${PROVIDER_META[option.provider]?.cost ? '·' + PROVIDER_META[option.provider].cost : ''}` : ''}`}
        </option>
      ))}
    </select>
  )
}
