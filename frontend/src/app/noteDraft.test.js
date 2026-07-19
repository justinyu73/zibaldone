import { describe, expect, it } from 'vitest'
import { draftFromSource, draftFromSummary, draftToAiSummary, emptyDraft, extractVideoId, str } from './noteDraft'

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

  it('creates an editable evidence draft without pretending it is AI output', () => {
    expect(draftFromSource('第一句\n第二句。第三句', 'OCR 影片', 'YT')).toMatchObject({
      title: 'OCR 影片',
      explicit_topic: '待人工整理：第一句 第二句。第三句',
      key_points: '- 第一句\n- 第二句。\n- 第三句',
      content_value: '來源文字已取得；尚未使用 AI 摘要，請人工確認主題、重點與可應用價值。',
      content_category: '待分類',
    })
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
