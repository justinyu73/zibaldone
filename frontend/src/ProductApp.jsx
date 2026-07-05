import { useEffect, useState } from 'react'
import { Clapperboard, Coins, Inbox, Library, Settings, Trash2 } from 'lucide-react'
import { vaultRootFromNotesFolder } from './paths'
import FirstRunWizard from './FirstRunWizard'
import { apiFetch } from './app/api'
import CostView from './features/cost/CostView'
import CaptureWorkspace from './features/capture/CaptureWorkspace'
import InboxView from './features/inbox/InboxView'
import LibraryView from './features/library/LibraryView'
import RetirementView from './features/retirement/RetirementView'
import SettingsView from './features/settings/SettingsView'
import { FIRST_RUN_KEY, FIRST_RUN_ROUTE_KEY, SETTINGS_KEY, loadSettings } from './app/settings'

// 收 → 理 → 用：收錄（網址/音檔兩個 lane）→ 收件匣 → 筆記庫 → 設定
const TABS = [
  { id: 'capture', label: '收錄', icon: Clapperboard },
  { id: 'inbox', label: '收件匣', icon: Inbox },
  { id: 'library', label: '筆記庫', icon: Library },
  { id: 'cost', label: '成本監控', icon: Coins },
  { id: 'retire', label: '退場', icon: Trash2 },
  { id: 'settings', label: '設定', icon: Settings },
]

export default function ProductApp() {
  const [tab, setTab] = useState('capture')
  const [settings, setSettings] = useState(loadSettings)
  const [setupOpen, setSetupOpen] = useState(() => {
    try {
      return !loadSettings().vaultRoot && !window.localStorage.getItem(FIRST_RUN_KEY)
    } catch {
      return !loadSettings().vaultRoot
    }
  })
  const [inboxCount, setInboxCount] = useState(0)
  const [backendReady, setBackendReady] = useState(false)
  const [adopt, setAdopt] = useState({ url: '', kind: 'article' }) // 雷達/手機收錄「帶入」→ 收錄對應 lane
  const activeTab = TABS.find((t) => t.id === tab)

  // 主題：system 跟隨系統（移除 data-theme 屬性），其餘主題強制覆寫
  useEffect(() => {
    const theme = settings.theme || 'system'
    if (theme === 'system') delete document.documentElement.dataset.theme
    else document.documentElement.dataset.theme = theme
  }, [settings.theme])

  // Packaged sidecar boots after the webview; tabs that fetch on mount used to
  // race it and stick on "Load failed" with no retry. Poll until ready.
  useEffect(() => {
    if (backendReady) return undefined
    let cancelled = false
    async function probe() {
      try {
        const r = await apiFetch(`/health`)
        if (!cancelled && r.ok) { setBackendReady(true); return }
      } catch { /* not up yet */ }
      if (!cancelled) timer = setTimeout(probe, 1200)
    }
    let timer = setTimeout(probe, 0)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [backendReady])

  // First run: derive the vault root from the backend's configured vault (env)
  // when the folder follows the 02_Sources/youtube convention.
  useEffect(() => {
    apiFetch(`/app/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => {
        const root = vaultRootFromNotesFolder(c?.notes_folder || '')
        if (root) {
          setSettings((s) => (s.vaultRoot ? s : { ...s, vaultRoot: root }))
          setSetupOpen(false)
          try { window.localStorage.setItem(FIRST_RUN_KEY, 'existing-config') } catch { /* ignore */ }
        }
      })
      .catch(() => {})
  }, [])

  function saveFirstRunSettings(next) {
    setSettings(next)
    try { window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(next)) } catch { /* ignore */ }
  }

  function finishFirstRun({ route }) {
    try {
      window.localStorage.setItem(FIRST_RUN_KEY, 'complete')
      window.localStorage.setItem(FIRST_RUN_ROUTE_KEY, route)
    } catch { /* ignore */ }
    setSetupOpen(false)
    setTab('capture')
  }

  function skipFirstRun() {
    try { window.localStorage.setItem(FIRST_RUN_KEY, 'skipped') } catch { /* ignore */ }
    setSetupOpen(false)
  }
  return (
    <div className="app-shell">
      {setupOpen && (
        <FirstRunWizard
          settings={settings}
          backendReady={backendReady}
          request={apiFetch}
          onSaveSettings={saveFirstRunSettings}
          onFinish={finishFirstRun}
          onSkip={skipFirstRun}
        />
      )}
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">V</div>
          <span>知識筆記</span>
        </div>
        <nav className="side-nav" aria-label="主要功能">
          {TABS.map((t) => {
            const Icon = t.icon
            return (
              <button
                key={t.id}
                className={tab === t.id ? 'active' : ''}
                onClick={() => setTab(t.id)}
                aria-label={t.label}
                aria-current={tab === t.id ? 'page' : undefined}
                title={t.label}
              >
                <Icon size={18} strokeWidth={2} /><span>{t.label}</span>
                {t.id === 'inbox' && inboxCount > 0 && <span className="nav-badge">{inboxCount}</span>}
              </button>
            )
          })}
        </nav>
        <div className="sidebar-foot">知識筆記 · 本機優先</div>
      </aside>
      <div className="app-content">
        <header className="content-head">
          {activeTab && <activeTab.icon size={18} />}
          <h2>{activeTab?.label}</h2>
        </header>
        <main className="app-main">
          {/* 掛載策略（P1 lazy mount）：草稿/狀態型 tab 用 CSS 隱藏保留掛載（capture=收錄草稿、
              inbox=餵 nav badge 計數、settings=表單防丟）；view 型重 tab（library 啟動掃 vault、
              cost/retire）改 active 才掛載，避免大型 vault 啟動同時觸發多組磁碟/API 掃描。 */}
          <div style={{ display: tab === 'capture' ? 'block' : 'none' }}><CaptureWorkspace settings={settings} adopt={adopt} /></div>
          <div style={{ display: tab === 'inbox' ? 'block' : 'none' }}><InboxView settings={settings} active={tab === 'inbox'} onCount={setInboxCount} onGo={setTab} ready={backendReady} onAdopt={(url, kind = 'article') => { setAdopt({ url, kind }); setTab('capture') }} /></div>
          {tab === 'library' && <LibraryView settings={settings} onGo={setTab} ready={backendReady} />}
          {tab === 'cost' && <CostView active />}
          {tab === 'retire' && <RetirementView settings={settings} active ready={backendReady} />}
          <div style={{ display: tab === 'settings' ? 'block' : 'none' }}><SettingsView settings={settings} setSettings={setSettings} onOpenSetup={() => setSetupOpen(true)} /></div>
        </main>
      </div>
    </div>
  )
}
