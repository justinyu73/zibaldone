const API_SESSION_HEADER = 'X-YT-Note-Token'
let apiSessionTokenPromise = null

export function loopbackApiOverride(value) {
  try {
    const parsed = new URL(String(value || '').trim())
    const host = parsed.hostname
    if (parsed.protocol !== 'http:') return ''
    if (!['127.0.0.1', 'localhost', '[::1]', '::1'].includes(host)) return ''
    return parsed.origin
  } catch { return '' }
}

function apiBase() {
  if (!import.meta.env.PROD) return '/api'
  try {
    const override = loopbackApiOverride(window.localStorage.getItem('yt_api_base'))
    if (override) return `${override}/api`
  } catch { /* ignore */ }
  return 'http://127.0.0.1:8766/api'
}

export const API = apiBase()

async function apiSessionToken() {
  if (!import.meta.env.PROD) return ''
  if (!apiSessionTokenPromise) {
    apiSessionTokenPromise = import('@tauri-apps/api/core')
      .then((module) => module.invoke('sidecar_session_token'))
      .catch(() => '')
  }
  return apiSessionTokenPromise
}

// Sidecar being unreachable used to hang fetch() until the connection layer
// itself gave up (or never — see win-asr-ocr-hardsub-recovery root cause).
// Default covers the slowest normal call (OCR's enforced 240s server-side
// ceiling) with margin; callers with a legitimately longer single request
// (e.g. video ASR transcription of a long video) pass a bigger timeoutMs.
// 0/null opts out entirely.
const DEFAULT_TIMEOUT_MS = 300000

export async function apiFetch(url, options = {}) {
  const token = await apiSessionToken()
  const { timeoutMs = DEFAULT_TIMEOUT_MS, headers: rawHeaders, ...rest } = options
  const headers = new Headers(rawHeaders || {})
  if (token) headers.set(API_SESSION_HEADER, token)
  const target = typeof url === 'string' && url.startsWith('/') ? `${API}${url}` : url
  if (!timeoutMs) return fetch(target, { ...rest, headers })
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(target, { ...rest, headers, signal: controller.signal })
  } catch (error) {
    if (error.name === 'AbortError') throw new Error(`請求逾時（超過 ${Math.round(timeoutMs / 1000)} 秒），請確認應用程式仍在執行`)
    throw error
  } finally {
    clearTimeout(timer)
  }
}

export async function postJson(path, body, options = {}) {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    ...options,
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = payload.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `${path} 失敗`)
  }
  return payload
}
