import { useEffect, useState } from 'react'
import { Coins, Database, FolderOpen, KeyRound, ShieldCheck } from 'lucide-react'
import { deriveVaultPaths, toWslPath } from '../../paths'
import { apiFetch } from '../../app/api'
import { PROVIDER_ORDER, providerLabelForModel } from '../../components/model/ModelSelect'
import { SETTINGS_KEY, defaultRadarTuning } from '../../app/settings'
import ProviderSettings from './ProviderSettings'
import RadarSettings from './RadarSettings'
import RuntimeSettings from './RuntimeSettings'
import StorageSettings from './StorageSettings'
import ThemeSettings from './ThemeSettings'
import UpdateSettings from './UpdateSettings'

export default function SettingsView({ settings, setSettings, onOpenSetup }) {
  const [draft, setDraft] = useState(settings)
  const [health, setHealth] = useState('checking')
  const [saved, setSaved] = useState(false)
  const [pickMsg, setPickMsg] = useState('')
  // 原生資料夾選擇器（沿用既有 pickAudio 的 dialog plugin，directory:true）；桌面版可用、
  // 瀏覽器 dev 無原生對話框則提示手貼。回傳的 Windows 路徑由儲存時的 toWslPath 轉換。
  const pickVaultRoot = async () => {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const dir = await open({ directory: true, multiple: false, title: '選擇筆記庫根目錄' })
      if (typeof dir === 'string' && dir) { setDraft({ ...draft, vaultRoot: dir }); setSaved(false); setPickMsg('') }
    } catch {
      setPickMsg('資料夾選擇器只在桌面版可用；瀏覽器請直接貼上路徑。')
    }
  }
  const tuning = { ...defaultRadarTuning(), ...(draft.radarTuning || {}) }
  const setTuning = (key) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setDraft({ ...draft, radarTuning: { ...tuning, [key]: value } }); setSaved(false)
  }

  const [keyStatus, setKeyStatus] = useState(null)
  const [keyProvider, setKeyProvider] = useState('openai')
  const [keyInput, setKeyInput] = useState('')
  const [keyBusy, setKeyBusy] = useState('')
  const [keyMsg, setKeyMsg] = useState(null)
  const [cost, setCost] = useState(null)
  const [rt, setRt] = useState(null)
  const [rtSaved, setRtSaved] = useState(false)
  const [modelOpts, setModelOpts] = useState(null)
  const setRtField = (k) => (e) => { setRt({ ...rt, [k]: e.target.value }); setRtSaved(false) }

  async function refreshCost() { try { setCost(await (await apiFetch(`/app/cost-summary`)).json()) } catch { setCost(null) } }
  async function refreshRt() { try { setRt(await (await apiFetch(`/app/settings`)).json()) } catch { setRt(null) } }
  async function saveRt() {
    try {
      const body = {
        translate_model: rt.translate_model,
        summary_model: rt.summary_model,
        per_job_cap_usd: Number(rt.per_job_cap_usd),
        daily_cap_usd: Number(rt.daily_cap_usd),
        meeting_template: rt.meeting_template || 'general',
        meeting_glossary: Array.isArray(rt.meeting_glossary) ? rt.meeting_glossary : [],
        cli_providers_enabled: Boolean(rt.cli_providers_enabled),
      }
      const d = await (await apiFetch(`/app/settings`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json()
      setRt(d); setRtSaved(true); refreshCost()
      // 開/關 CLI 訂閱模型會改變可選模型清單（providers.py：關著一律空），存檔後重抓
      apiFetch(`/app/model-options`).then((r) => r.json()).then(setModelOpts).catch(() => {})
    } catch { /* ignore */ }
  }

  async function checkHealth() {
    setHealth('checking')
    try {
      const r = await apiFetch(`/app/health`)
      setHealth(r.ok ? 'ok' : 'down')
    } catch { setHealth('down') }
  }
  async function refreshKey() {
    try { setKeyStatus(await (await apiFetch(`/app/secrets-status`)).json()) } catch { setKeyStatus(null) }
  }
  useEffect(() => {
    checkHealth(); refreshKey(); refreshCost(); refreshRt()
    apiFetch(`/app/model-options`).then((r) => r.json()).then(setModelOpts).catch(() => {})
  }, [])

  // Packaged sidecar boots slower than the webview: poll health until it
  // answers, then backfill any panel whose first fetch raced the boot.
  useEffect(() => {
    if (health === 'ok') {
      if (!rt) refreshRt()
      if (!modelOpts) apiFetch(`/app/model-options`).then((r) => r.json()).then(setModelOpts).catch(() => {})
      if (!keyStatus) refreshKey()
      if (!cost) refreshCost()
      return undefined
    }
    const timer = setTimeout(checkHealth, 1500)
    return () => clearTimeout(timer)
  }, [health]) // eslint-disable-line react-hooks/exhaustive-deps

  async function saveKey() {
    if (!keyInput.trim()) return setKeyMsg({ type: 'error', message: '請輸入金鑰' })
    setKeyBusy('save')
    try {
      const r = await apiFetch(`/app/api-key`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: keyInput, provider: keyProvider }) })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || '設定失敗')
      setKeyStatus(d); setKeyInput(''); setKeyMsg({ type: 'ok', message: '金鑰已儲存（家目錄，未進 repo）' })
    } catch (e) { setKeyMsg({ type: 'error', message: e.message }) } finally { setKeyBusy('') }
  }
  async function testKey() {
    setKeyBusy('test'); setKeyMsg({ type: 'info', message: '測試金鑰中...' })
    try {
      const d = await (await apiFetch(`/app/api-key-test`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: keyProvider }) })).json()
      setKeyMsg({ type: d.ok ? 'ok' : 'error', message: d.message })
    } catch (e) { setKeyMsg({ type: 'error', message: e.message }) } finally { setKeyBusy('') }
  }
  async function clearKey() {
    setKeyBusy('clear')
    try { setKeyStatus(await (await apiFetch(`/app/api-key-clear`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: keyProvider }) })).json()); setKeyMsg({ type: 'ok', message: '金鑰已清除' }) }
    catch (e) { setKeyMsg({ type: 'error', message: e.message }) } finally { setKeyBusy('') }
  }


  function save() {
    const folders = (draft.libraryFolders || []).map(toWslPath).filter(Boolean)
    const normalized = { ...draft, vaultRoot: toWslPath(draft.vaultRoot), libraryFolders: folders }
    setDraft(normalized)
    setSettings(normalized)
    try { window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(normalized)) } catch { /* ignore */ }
    setSaved(true)
  }
  // 金鑰歸屬可見化：呼叫哪家 provider 由所選模型決定，這裡反查給使用者看
  const modelProvider = (id) => providerLabelForModel(id, [...(modelOpts?.translate || []), ...(modelOpts?.summary || [])])
  const healthText = { checking: '檢查中…', ok: '已連線', down: '後端未連線，請稍候或重新開啟 App' }
  const healthTone = health === 'ok' ? 'ok' : health === 'down' ? 'error' : 'info'
  const configuredProviderCount = PROVIDER_ORDER.filter((p) => keyStatus?.providers?.[p]?.key_set).length
  const derived = deriveVaultPaths(draft.vaultRoot || settings.vaultRoot)
  const noteTarget = derived.youtube || '後端預設'
  const [rootCheck, setRootCheck] = useState(null) // null=未驗 | ok | empty
  useEffect(() => {
    if (!derived.root || health !== 'ok') { setRootCheck(null); return undefined }
    let cancelled = false
    const timer = setTimeout(async () => {
      try {
        const r = await apiFetch(`/app/vault-folders?${new URLSearchParams({ vault_root: derived.root })}`)
        const d = await r.json()
        if (!cancelled) setRootCheck((d.folders || []).length > 0 ? 'ok' : 'empty')
      } catch { if (!cancelled) setRootCheck(null) }
    }, 600)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [derived.root, health]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="workbench settings-workbench">
      <section className="command-bar settings-command" aria-label="settings status">
        <div className="command-main">
          <div className="command-kicker">設定</div>
          <div className="command-title">本機設定、金鑰與成本上限</div>
          <div className="command-meta">
            <span className={`state-chip ${healthTone}`}><Database size={13} /> 後端：{healthText[health]}</span>
            <span className="state-chip neutral"><KeyRound size={13} /> 金鑰 {configuredProviderCount}/{PROVIDER_ORDER.length} 已設定</span>
            <span className={cost?.over_daily_cap ? 'state-chip error' : 'state-chip ok'}><Coins size={13} /> {cost?.over_daily_cap ? '成本已擋' : '成本額度內'}</span>
          </div>
        </div>
        <div className="command-actions">
          <button className="ghost" onClick={checkHealth}>重新檢查連線</button>
        </div>
      </section>

      <div className="settings-frame">
        <StorageSettings
          derived={derived} draft={draft} onOpenSetup={onOpenSetup}
          onPickVaultRoot={pickVaultRoot} pickMessage={pickMsg} rootCheck={rootCheck}
          saved={saved} save={save} setDraft={setDraft} setSaved={setSaved}
        />

        <div className="settings-cols">
        <ProviderSettings
          busy={keyBusy} clearKey={clearKey} input={keyInput} keyStatus={keyStatus}
          message={keyMsg} provider={keyProvider} saveKey={saveKey}
          setInput={setKeyInput} setMessage={setKeyMsg} setProvider={setKeyProvider}
          testKey={testKey}
        />

        <RuntimeSettings
          cost={cost} modelOptions={modelOpts} modelProvider={modelProvider}
          refreshCost={refreshCost} refreshRuntime={refreshRt} runtime={rt}
          runtimeSaved={rtSaved} saveRuntime={saveRt} setRuntime={setRt}
          setRuntimeField={setRtField} setRuntimeSaved={setRtSaved}
        />

        <RadarSettings
          draft={draft} save={save} saved={saved} setDraft={setDraft}
          setSaved={setSaved} setTuning={setTuning} tuning={tuning}
        />

        <ThemeSettings settings={settings} setSettings={setSettings} setDraft={setDraft} />
        <UpdateSettings />
        </div>
      </div>

      <footer className="status-strip">
        <span><Database size={13} /> 後端：{healthText[health]}</span>
        <span><FolderOpen size={13} /> 筆記目標：{noteTarget}</span>
        <span><ShieldCheck size={13} /> 金鑰：本機遮罩</span>
      </footer>
    </div>
  )
}

