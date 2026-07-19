export const SOURCE_OPTIONS = ['YT', 'Reels', 'Threads', 'IG', 'X']
export const CATEGORY_OPTIONS = ['AI LLM', '應用', '學習參考', '財經', '哲學思維', '領域知識']
export const SOURCE_LIST_KEY = 'yt_source_options_v1'
export const CATEGORY_LIST_KEY = 'yt_category_options_v1'

const LEGACY_CUSTOM_KEYS = {
  [SOURCE_LIST_KEY]: 'yt_custom_sources',
  [CATEGORY_LIST_KEY]: 'yt_custom_categories',
}

export function loadOptionList(storageKey, presets, storage = window.localStorage) {
  try {
    const raw = storage.getItem(storageKey)
    if (raw) return JSON.parse(raw).filter(Boolean)
    const legacy = JSON.parse(storage.getItem(LEGACY_CUSTOM_KEYS[storageKey]) || '[]').filter(Boolean)
    const seeded = [...new Set([...presets, ...legacy])]
    storage.setItem(storageKey, JSON.stringify(seeded))
    return seeded
  } catch { return [...presets] }
}

export function saveOptionList(storageKey, list, storage = window.localStorage) {
  try { storage.setItem(storageKey, JSON.stringify(list)) } catch { /* ignore */ }
}

export function withCurrent(options, current) {
  return current && !options.includes(current) ? [current, ...options] : options
}
