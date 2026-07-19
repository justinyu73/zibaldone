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
