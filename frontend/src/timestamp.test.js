import { describe, it, expect } from 'vitest'
import { splitTimestamp, tsToSeconds } from './features/meetings/timestamp'

describe('tsToSeconds', () => {
  it('parses m:ss and mm:ss to seconds', () => {
    expect(tsToSeconds('1:05')).toBe(65)
    expect(tsToSeconds('0:00')).toBe(0)
    expect(tsToSeconds('12:34')).toBe(754)
  })
  it('returns null for malformed input (not seekable)', () => {
    expect(tsToSeconds('')).toBeNull()
    expect(tsToSeconds(null)).toBeNull()
    expect(tsToSeconds('90')).toBeNull()
    expect(tsToSeconds('1:5')).toBeNull()
  })
})

describe('splitTimestamp', () => {
  it('normalizes square and fullwidth timestamp capsules', () => {
    expect(splitTimestamp('決議 [00:11]')).toEqual({ text: '決議', ts: '00:11' })
    expect(splitTimestamp('【00:23】預設 medium')).toEqual({ text: '預設 medium', ts: '00:23' })
  })
})
