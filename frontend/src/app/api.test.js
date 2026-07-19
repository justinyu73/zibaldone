import { describe, expect, it } from 'vitest'
import { loopbackApiOverride } from './api'

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
