import { describe, expect, it } from 'vitest'
import { costFmt, costUsd } from './CostView'

describe('cost formatting', () => {
  it('formats zero and paid amounts consistently', () => {
    expect(costUsd()).toBe('$0.0000')
    expect(costUsd(1.23456)).toBe('$1.2346')
    expect(costFmt()).toBe('0')
  })
})
