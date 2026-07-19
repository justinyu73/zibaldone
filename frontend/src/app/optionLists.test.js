import { describe, expect, it, vi } from 'vitest'
import { SOURCE_LIST_KEY, loadOptionList, saveOptionList, withCurrent } from './optionLists'

function storage(values = {}) {
  return {
    getItem: (key) => values[key] ?? null,
    setItem: vi.fn(),
  }
}

describe('option lists', () => {
  it('seeds presets with deduplicated legacy additions', () => {
    const target = storage({ yt_custom_sources: JSON.stringify(['YT', 'Podcast']) })
    expect(loadOptionList(SOURCE_LIST_KEY, ['YT'], target)).toEqual(['YT', 'Podcast'])
    expect(target.setItem).toHaveBeenCalledWith(SOURCE_LIST_KEY, JSON.stringify(['YT', 'Podcast']))
  })

  it('keeps a loaded non-standard value selectable', () => {
    expect(withCurrent(['YT'], 'Podcast')).toEqual(['Podcast', 'YT'])
    expect(withCurrent(['YT'], 'YT')).toEqual(['YT'])
  })

  it('persists managed options', () => {
    const target = storage()
    saveOptionList(SOURCE_LIST_KEY, ['YT', 'Podcast'], target)
    expect(target.setItem).toHaveBeenCalledWith(SOURCE_LIST_KEY, '["YT","Podcast"]')
  })
})
