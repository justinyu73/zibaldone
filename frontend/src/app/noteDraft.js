export function str(value) {
  if (Array.isArray(value)) return value.join('\n')
  return value == null ? '' : String(value)
}

export function emptyDraft() {
  return {
    filename: '',
    title: '',
    explicit_topic: '',
    key_points: '',
    terms: '',
    content_value: '',
    source_platform: 'YT',
    content_category: 'AI LLM',
    manual_summary: '',
  }
}

export function draftFromSummary(summary, title) {
  return {
    filename: '',
    title: title || '',
    explicit_topic: str(summary.explicit_topic),
    key_points: str(summary.key_points),
    terms: str(summary.terms),
    content_value: str(summary.content_value),
    source_platform: summary.source_platform || 'YT',
    content_category: summary.content_category || 'AI LLM',
    manual_summary: '',
  }
}

// No-AI fallback: keep the capture lane usable when the user intentionally
// skipped the optional local model download and has not configured a cloud key.
// This is an editable evidence draft, not an AI-generated summary.
export function draftFromSource(text, title, sourcePlatform = 'YT') {
  const compact = str(text).replace(/\s+/g, ' ').trim()
  const fragments = str(text)
    .split(/\n+|(?<=[。！？.!?])/u)
    .map((part) => part.replace(/^[-*•\s]+/, '').trim())
    .filter(Boolean)
    .slice(0, 3)
  const preview = compact.length > 160 ? `${compact.slice(0, 160)}…` : compact
  const points = fragments.length
    ? fragments.map((part) => `- ${part}`).join('\n')
    : '待人工整理（原文已保留於上方審查區）'
  return {
    ...emptyDraft(),
    title: title || '',
    explicit_topic: preview ? `待人工整理：${preview}` : '待人工整理',
    key_points: points,
    content_value: '來源文字已取得；尚未使用 AI 摘要，請人工確認主題、重點與可應用價值。',
    source_platform: sourcePlatform,
    content_category: '待分類',
  }
}

export function extractVideoId(url) {
  const value = String(url || '').trim()
  if (/^[A-Za-z0-9_-]{11}$/.test(value)) return value
  const match = value.match(/(?:youtube\.com\/(?:watch\?v=|live\/|embed\/|shorts\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/)
  return match ? match[1] : ''
}

export function draftToAiSummary(draft) {
  return {
    explicit_topic: draft.explicit_topic,
    key_points: draft.key_points,
    terms: draft.terms,
    content_value: draft.content_value,
    source_platform: draft.source_platform,
    content_category: draft.content_category,
  }
}
