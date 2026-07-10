import { describe, expect, it } from 'vitest'
import { recoveryHint } from './StatusMessage'

describe('recoveryHint', () => {
  it('does not add recovery copy to non-errors', () => {
    expect(recoveryHint({ type: 'ok', message: '完成' })).toBe('')
    expect(recoveryHint(null)).toBe('')
  })

  it('routes known failures to actionable recovery', () => {
    expect(recoveryHint({ type: 'error', message: 'daily cap exceeded' })).toContain('每日上限')
    expect(recoveryHint({ type: 'error', message: '字幕不可用' })).toContain('缺字幕時可用下方 ASR')
    expect(recoveryHint({ type: 'error', message: 'backend network error' })).toContain('sidecar')
  })

  it('keeps a safe generic fallback', () => {
    expect(recoveryHint({ type: 'error', message: 'unknown' })).toContain('未執行後續寫入')
  })
})
