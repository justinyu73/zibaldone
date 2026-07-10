import { describe, expect, it } from 'vitest'
import { brandKey, costFmt, costMoney, costUsd } from './CostView'

describe('cost formatting', () => {
  it('formats zero and paid amounts consistently', () => {
    expect(costUsd()).toBe('$0.0000')
    expect(costUsd(1.23456)).toBe('$1.2346')
    expect(costFmt()).toBe('0')
  })

  it('converts money into international currencies with correct symbol and precision', () => {
    expect(costMoney(2.14, 'USD')).toBe('$2.14')
    expect(costMoney(2.14, 'TWD')).toBe('NT$70') // 2.14 * 32.5 = 69.55 -> 70, 0 dp
    expect(costMoney(1, 'JPY')).toBe('¥157')
    expect(costMoney(0, 'EUR')).toBe('€0.00')
    expect(costMoney(2.14)).toBe('$2.14') // defaults to USD
    expect(costMoney(1, 'BOGUS')).toBe('$1.00') // unknown falls back to USD
  })

  it('maps brand names to icon keys, falling back to generic', () => {
    expect(brandKey('Claude')).toBe('claude')
    expect(brandKey('Anthropic')).toBe('claude')
    expect(brandKey('OpenAI GPT-4')).toBe('openai')
    expect(brandKey('Google Gemini')).toBe('gemini')
    expect(brandKey('本機')).toBe('local')
    expect(brandKey('SomethingElse')).toBe('generic')
  })
})
