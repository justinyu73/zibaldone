import { describe, expect, it } from 'vitest'
import { newerVersion } from './version'

describe('newerVersion', () => {
  it('compares three-part versions numerically', () => {
    expect(newerVersion('0.6.0', '0.5.9')).toBe(true)
    expect(newerVersion('0.5.10', '0.5.9')).toBe(true)
    expect(newerVersion('0.5.0', '0.5.0')).toBe(false)
    expect(newerVersion('0.4.9', '0.5.0')).toBe(false)
  })

  it('returns false for non-numeric semver parts', () => {
    expect(newerVersion('1.x.0', '1.0.0')).toBe(false)
    expect(newerVersion('1.0.0-beta', '0.9.0')).toBe(false)
    expect(newerVersion('0.6.0alpha', '0.5.0')).toBe(false)
    expect(newerVersion('1.0.0', '1.x.0')).toBe(false)
  })

  it('returns false for null or undefined inputs', () => {
    expect(newerVersion(null, '1.0.0')).toBe(false)
    expect(newerVersion(undefined, '1.0.0')).toBe(false)
    expect(newerVersion('1.0.0', null)).toBe(false)
    expect(newerVersion('1.0.0', undefined)).toBe(false)
  })

  it('returns false for empty string input', () => {
    expect(newerVersion('', '1.0.0')).toBe(false)
    expect(newerVersion('1.0.0', '')).toBe(false)
  })

  it('returns false for negative version parts', () => {
    expect(newerVersion('-1.0.0', '1.0.0')).toBe(false)
    expect(newerVersion('1.0.0', '-1.0.0')).toBe(false)
  })

  it('handles 1- and 2-part versions by padding with zeros', () => {
    expect(newerVersion('1.1', '1.0.0')).toBe(true)
    expect(newerVersion('2', '1.9.9')).toBe(true)
    expect(newerVersion('1.0', '1.0.0')).toBe(false)
  })

  it('ignores parts beyond the third when all are valid digits', () => {
    expect(newerVersion('1.0.0.9', '1.0.0')).toBe(false)
    expect(newerVersion('1.0.1.9', '1.0.0')).toBe(true)
  })

  it('strips leading v or V prefix before comparing', () => {
    expect(newerVersion('v0.6.0', '0.5.9')).toBe(true)
    expect(newerVersion('V0.6.0', '0.5.9')).toBe(true)
    expect(newerVersion('v0.5.0', 'v0.5.0')).toBe(false)
    expect(newerVersion('v0.4.9', 'v0.5.0')).toBe(false)
    expect(newerVersion('v1.0.0', 'V0.9.9')).toBe(true)
    expect(newerVersion('0.6.0', 'v0.5.9')).toBe(true)
    expect(newerVersion('v0.6.0alpha', '0.5.0')).toBe(false)
  })
})
