import { describe, expect, it } from 'vitest'
import { providerForModel, providerLabelForModel } from './ModelSelect'

describe('model provider resolution', () => {
  it('prefers provider metadata from model options', () => {
    const options = [{ id: 'custom-model', provider: 'google' }]
    expect(providerForModel('custom-model', options)).toBe('google')
    expect(providerLabelForModel('custom-model', options)).toBe('Gemini')
  })

  it('preserves legacy model-name inference', () => {
    expect(providerForModel('llamacpp:gemma-3-4b-it')).toBe('llamacpp')
    expect(providerForModel('claude-sonnet')).toBe('anthropic')
    expect(providerForModel('gemini-flash')).toBe('google')
    expect(providerForModel('gpt-5-mini')).toBe('openai')
  })
})
