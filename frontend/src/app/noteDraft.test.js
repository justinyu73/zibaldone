import { describe, expect, it } from 'vitest'
import { draftFromSummary, draftToAiSummary, emptyDraft, extractVideoId, str } from './noteDraft'

describe('note draft helpers', () => {
  it('normalizes values and summary arrays', () => {
    expect(str(['one', 'two'])).toBe('one\ntwo')
    expect(str(null)).toBe('')
    expect(draftFromSummary({ key_points: ['A', 'B'] }, 'Title')).toMatchObject({
      title: 'Title',
      key_points: 'A\nB',
      source_platform: 'YT',
      content_category: 'AI LLM',
    })
  })

  it('extracts supported YouTube video identifiers', () => {
    const id = 'dQw4w9WgXcQ'
    expect(extractVideoId(id)).toBe(id)
    expect(extractVideoId(`https://www.youtube.com/watch?v=${id}&t=1`)).toBe(id)
    expect(extractVideoId(`https://youtu.be/${id}`)).toBe(id)
    expect(extractVideoId('https://example.com/video')).toBe('')
  })

  it('projects only AI summary fields', () => {
    const draft = { ...emptyDraft(), title: 'ignored', explicit_topic: 'topic' }
    expect(draftToAiSummary(draft)).toEqual({
      explicit_topic: 'topic',
      key_points: '',
      terms: '',
      content_value: '',
      source_platform: 'YT',
      content_category: 'AI LLM',
    })
  })
})
