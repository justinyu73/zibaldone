import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFetch, loopbackApiOverride } from './api'

describe('loopbackApiOverride', () => {
  it('accepts HTTP loopback origins', () => {
    expect(loopbackApiOverride('http://127.0.0.1:9000/path')).toBe('http://127.0.0.1:9000')
    expect(loopbackApiOverride('http://localhost:8766')).toBe('http://localhost:8766')
    expect(loopbackApiOverride('http://[::1]:8766/api')).toBe('http://[::1]:8766')
  })

  it('rejects remote, HTTPS, and malformed origins', () => {
    expect(loopbackApiOverride('http://192.168.1.10:8766')).toBe('')
    expect(loopbackApiOverride('https://localhost:8766')).toBe('')
    expect(loopbackApiOverride('not a URL')).toBe('')
  })
})

// win-asr-ocr-hardsub-recovery Fix 2-3: a dead/hung sidecar connection used to
// leave fetch() waiting forever. apiFetch must attach an AbortSignal by
// default and turn its abort into a readable message, while still letting a
// caller opt out (long ASR transcriptions) or override the duration.
describe('apiFetch timeout', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('attaches an AbortSignal by default', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/health')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal)
  })

  it('timeoutMs: 0 opts out of the abort signal entirely', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/app/video-audio-asr', { timeoutMs: 0 })

    expect(fetchMock.mock.calls[0][1].signal).toBeUndefined()
  })

  it('wraps an AbortError into a readable Chinese timeout message', async () => {
    const abortError = new Error('aborted')
    abortError.name = 'AbortError'
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abortError))

    await expect(apiFetch('/slow', { timeoutMs: 5 })).rejects.toThrow(/逾時/)
  })

  it('propagates non-abort errors unchanged', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(apiFetch('/health')).rejects.toThrow('Failed to fetch')
  })
})
