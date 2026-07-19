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

export async function apiFetch(url, options = {}) {
  const token = await apiSessionToken()
  const headers = new Headers(options.headers || {})
  if (token) headers.set(API_SESSION_HEADER, token)
  const target = typeof url === 'string' && url.startsWith('/') ? `${API}${url}` : url
  return fetch(target, { ...options, headers })
}

export async function postJson(path, body) {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = payload.detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `${path} 失敗`)
  }
  return payload
}
