import { describe, expect, it } from 'vitest'
import { normalizeTag } from './UpdateSettings'

describe('normalizeTag', () => {
  it('strips lowercase v prefix', () => {
    expect(normalizeTag('v1.2.3')).toBe('1.2.3')
    expect(normalizeTag('v0.6.0')).toBe('0.6.0')
  })

  it('strips uppercase V prefix', () => {
    expect(normalizeTag('V1.2.3')).toBe('1.2.3')
    expect(normalizeTag('V0.6.0')).toBe('0.6.0')
  })

  it('passes through bare semver unchanged', () => {
    expect(normalizeTag('1.2.3')).toBe('1.2.3')
    expect(normalizeTag('0.6.0')).toBe('0.6.0')
  })

  it('returns empty string for null, undefined, or empty input', () => {
    expect(normalizeTag(null)).toBe('')
    expect(normalizeTag(undefined)).toBe('')
    expect(normalizeTag('')).toBe('')
  })

  it('does not strip v mid-string', () => {
    expect(normalizeTag('1.0.0-v2')).toBe('1.0.0-v2')
  })
})
