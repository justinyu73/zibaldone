import { describe, expect, it } from 'vitest'
import {
  DEFAULT_THEME,
  LEGACY_SETTINGS_KEY,
  SETTINGS_KEY,
  defaultSettings,
  loadSettings,
} from './settings'

function storage(values = {}) {
  return { getItem: (key) => values[key] ?? null }
}

describe('settings', () => {
  it('returns isolated defaults', () => {
    const first = defaultSettings()
    const second = defaultSettings()
    first.radarTuning.keywords.push('changed')
    expect(second.theme).toBe(DEFAULT_THEME)
    expect(second.radarTuning.keywords).toEqual([])
  })

  it('merges current persisted settings over defaults', () => {
    const result = loadSettings(storage({
      [SETTINGS_KEY]: JSON.stringify({ vaultRoot: '/vault', theme: 'light' }),
    }))
    expect(result.vaultRoot).toBe('/vault')
    expect(result.theme).toBe('light')
    expect(result.libraryFolders).toEqual([])
  })

  it('migrates the supported legacy notes folder', () => {
    const result = loadSettings(storage({
      [LEGACY_SETTINGS_KEY]: JSON.stringify({
        notesFolder: '/vault/02_Sources/youtube',
        libraryFolders: ['/extra'],
      }),
    }))
    expect(result.vaultRoot).toBe('/vault')
    expect(result.libraryFolders).toEqual(['/extra'])
  })

  it('falls back to defaults for malformed storage', () => {
    expect(loadSettings(storage({ [SETTINGS_KEY]: '{bad json' }))).toEqual(defaultSettings())
  })
})
