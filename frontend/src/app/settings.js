import { vaultRootFromNotesFolder } from '../paths'

export const SETTINGS_KEY = 'yt_product_settings_v3'
export const LEGACY_SETTINGS_KEY = 'yt_product_settings_v2'
export const FIRST_RUN_KEY = 'yt_first_run_setup_v1'
export const FIRST_RUN_ROUTE_KEY = 'yt_first_run_route_v1'

export const THEME_OPTIONS = [
  ['system', '系統預設'],
  ['light', '淺色'],
  ['dark', '深色'],
  ['walnut', '深胡桃'],
  ['gallery', '暖陽美術館'],
  ['atelier', '灰綠畫室'],
]

export const DEFAULT_THEME = 'walnut'

export function defaultRadarTuning() {
  return { totalCap: 50, perSourceCap: 20, hnMinPoints: 80, ghMinStars: 150, keywords: [], enableHn: true, enableGithub: true, enableRss: true }
}

export function defaultSettings() {
  return { vaultRoot: '', libraryFolders: [], radarFeeds: [], radarTuning: defaultRadarTuning(), theme: DEFAULT_THEME }
}

export function loadSettings(storage = window.localStorage) {
  try {
    const raw = storage.getItem(SETTINGS_KEY)
    if (raw) return { ...defaultSettings(), ...JSON.parse(raw) }
    const legacy = storage.getItem(LEGACY_SETTINGS_KEY)
    if (legacy) {
      const previous = JSON.parse(legacy)
      return {
        ...defaultSettings(),
        vaultRoot: vaultRootFromNotesFolder(previous.notesFolder || ''),
        libraryFolders: previous.libraryFolders || [],
      }
    }
  } catch {
    /* ignore malformed or unavailable local storage */
  }
  return defaultSettings()
}
