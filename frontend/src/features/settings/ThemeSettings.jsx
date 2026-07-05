import { Settings } from 'lucide-react'
import { SETTINGS_KEY, THEME_OPTIONS } from '../../app/settings'

export default function ThemeSettings({ settings, setSettings, setDraft }) {
  return (
    <section className="panel settings-panel">
      <div className="panel-head">
        <div>
          <Settings size={16} />
          <h3>外觀主題</h3>
        </div>
        <span className="state-chip neutral">即時生效</span>
      </div>
      <div className="tabs-mini" role="group" aria-label="外觀主題">
        {THEME_OPTIONS.map(([value, label]) => (
          <button key={value} className={(settings.theme || 'system') === value ? 'active' : ''}
            aria-pressed={(settings.theme || 'system') === value}
            onClick={() => {
              const next = { ...settings, theme: value }
              setSettings(next)
              setDraft((draft) => ({ ...draft, theme: value }))
              try { window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(next)) } catch { /* ignore */ }
            }}>{label}</button>
        ))}
      </div>
    </section>
  )
}
