import { useEffect, useRef, useState } from 'react'
import {
  ArrowLeft, ArrowRight, Check, Cloud, Database, Download, FolderOpen, KeyRound,
  Laptop, LoaderCircle, RefreshCw, ShieldCheck, X,
} from 'lucide-react'
import { toWslPath } from './paths'

const PROVIDERS = [
  ['openai', 'OpenAI'],
  ['anthropic', 'Claude'],
  ['google', 'Gemini'],
]

function statusTone(ok) {
  return ok ? 'ok' : 'info'
}

function pullProgressText(pull) {
  if (!pull?.total) return ''
  const mb = (n) => Math.round(n / 1048576)
  return `（${Math.round((pull.downloaded / pull.total) * 100)}%，${mb(pull.downloaded)} / ${mb(pull.total)} MB）`
}

export default function FirstRunWizard({
  settings,
  backendReady,
  request,
  onSaveSettings,
  onFinish,
  onSkip,
}) {
  const dialogRef = useRef(null)
  const onSkipRef = useRef(onSkip)
  onSkipRef.current = onSkip
  const [step, setStep] = useState(0)
  const [vaultRoot, setVaultRoot] = useState(settings.vaultRoot || '')
  const [route, setRoute] = useState('local')
  const [provider, setProvider] = useState('openai')
  const [keyInput, setKeyInput] = useState('')
  const [keyState, setKeyState] = useState('idle')
  const [keyMessage, setKeyMessage] = useState('')
  const [readiness, setReadiness] = useState(null)
  const [readinessState, setReadinessState] = useState('idle')
  const [pickMessage, setPickMessage] = useState('')
  const [llm, setLlm] = useState(null)
  const [llmState, setLlmState] = useState('idle')

  async function pickVault() {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({ directory: true, multiple: false, title: '選擇筆記庫根目錄' })
      if (typeof selected === 'string' && selected) {
        setVaultRoot(selected)
        setPickMessage('')
      }
    } catch {
      setPickMessage('瀏覽器模式請直接貼上路徑；桌面版可使用資料夾選擇器。')
    }
  }

  async function saveProviderKey() {
    if (!keyInput.trim()) {
      setKeyMessage('未輸入金鑰；可以略過並稍後在設定中新增。')
      return
    }
    setKeyState('saving')
    setKeyMessage('')
    try {
      const response = await request('/app/api-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, api_key: keyInput.trim() }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || '金鑰儲存失敗')
      setKeyInput('')
      setKeyState('saved')
      setKeyMessage('已保存於本機使用者設定。未執行付費測試。')
    } catch (error) {
      setKeyState('error')
      setKeyMessage(error.message || '金鑰儲存失敗')
    }
  }

  async function refreshReadiness() {
    setReadinessState('loading')
    try {
      const params = new URLSearchParams({ vault_root: toWslPath(vaultRoot) })
      const response = await request(`/app/setup-readiness?${params}`)
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || '環境檢查失敗')
      setReadiness(body)
      setReadinessState('ready')
    } catch (error) {
      setReadiness({ error: error.message || '環境檢查失敗' })
      setReadinessState('error')
    }
  }

  async function refreshLlm() {
    setLlmState('loading')
    try {
      const response = await request('/app/local-llm/status')
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || '本機 AI 偵測失敗')
      setLlm(body)
      setLlmState('ready')
    } catch (error) {
      setLlm({ error: error.message || '本機 AI 偵測失敗' })
      setLlmState('error')
    }
  }

  async function startPull() {
    try {
      const response = await request('/app/local-llm/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || '模型下載啟動失敗')
    } catch (error) {
      setLlm((current) => ({ ...current, pull: { status: 'error', error: error.message } }))
      return
    }
    refreshLlm()
  }

  async function startBuiltinInstall() {
    try {
      const response = await request('/app/local-llm/builtin/install', { method: 'POST' })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || '內建本機 AI 下載啟動失敗')
    } catch (error) {
      setLlm((current) => ({
        ...current,
        builtin: { ...current?.builtin, download: { status: 'error', error: error.message } },
      }))
      return
    }
    refreshLlm()
  }

  useEffect(() => {
    if (step === 3 && backendReady) refreshLlm()
    if (step === 4 && backendReady) refreshReadiness()
  }, [step, backendReady]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const downloading = llm?.pull?.status === 'downloading'
      || llm?.builtin?.download?.status === 'downloading'
    if (step !== 3 || !downloading) return
    const timer = setTimeout(refreshLlm, 1200)
    return () => clearTimeout(timer)
  }, [step, llm]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialogRef.current?.focus()
    function keepFocusInside(event) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onSkipRef.current()
        return
      }
      if (event.key !== 'Tab' || !dialogRef.current) return
      const controls = [...dialogRef.current.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')]
      if (!controls.length) return
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', keepFocusInside)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', keepFocusInside)
    }
  }, [])

  useEffect(() => {
    dialogRef.current?.focus()
  }, [step])

  function goNext() {
    if (step === 1) {
      const normalized = toWslPath(vaultRoot)
      onSaveSettings({ ...settings, vaultRoot: normalized })
      setVaultRoot(normalized)
    }
    setStep((current) => Math.min(4, current + 1))
  }

  const vaultReady = Boolean(readiness?.vault?.exists && readiness?.vault?.is_directory && readiness?.vault?.readable && readiness?.vault?.writable)
  const providerReady = Object.values(readiness?.providers || {}).some((item) => item.key_set)
  const asrReady = Boolean(readiness?.local_asr?.ok || readiness?.local_asr?.runtime_ready)

  return (
    <div className="setup-overlay" role="dialog" aria-modal="true" aria-labelledby="setup-title">
      <section className="setup-dialog" ref={dialogRef} tabIndex={-1}>
        <header className="setup-head">
          <div>
            <span className="command-kicker">首次設定</span>
            <h2 id="setup-title">{['資料與連線', '筆記庫位置', '處理路線', '本機 AI', '環境確認'][step]}</h2>
          </div>
          <button className="icon-button ghost" onClick={onSkip} title="略過首次設定" aria-label="略過首次設定"><X size={18} /></button>
        </header>

        <div className="setup-progress" aria-label={`設定進度 ${step + 1} / 5`}>
          {[0, 1, 2, 3, 4].map((index) => <span key={index} className={index <= step ? 'active' : ''} />)}
        </div>

        <div className="setup-body">
          {step === 0 && (
            <div className="setup-disclosures">
              <div><Database size={19} /><span><strong>筆記保存在你選擇的資料夾</strong><small>升級或移除 APP 不會刪除外部筆記庫。</small></span></div>
              <div><ShieldCheck size={19} /><span><strong>沒有遙測</strong><small>診斷紀錄保存在本機，可由設定頁開啟。</small></span></div>
              <div><Cloud size={19} /><span><strong>雲端處理必須由你選擇</strong><small>字幕、文章或逐字稿只有在執行對應操作時才送往所選服務。</small></span></div>
            </div>
          )}

          {step === 1 && (
            <div className="setup-form">
              <label htmlFor="setup-vault">筆記庫根目錄</label>
              <div className="setup-path-row">
                <input id="setup-vault" value={vaultRoot} onChange={(event) => setVaultRoot(event.target.value)} placeholder="選擇 Obsidian vault 或專用筆記資料夾" autoFocus />
                <button onClick={pickVault}><FolderOpen size={16} />選擇</button>
              </div>
              {pickMessage && <div className="settings-state info">{pickMessage}</div>}
              <div className="settings-note">此步驟只保存路徑；環境確認不會建立或寫入筆記。</div>
            </div>
          )}

          {step === 2 && (
            <div className="setup-form">
              <div className="setup-route" role="group" aria-label="預設處理路線">
                <button className={route === 'local' ? 'active' : ''} aria-pressed={route === 'local'} onClick={() => setRoute('local')}>
                  <Laptop size={18} /><span><strong>先用免費路線</strong><small>字幕抓取、本機筆記、Ollama 本地模型均可用；翻譯與 AI 摘要才需金鑰</small></span>
                </button>
                <button className={route === 'cloud' ? 'active' : ''} aria-pressed={route === 'cloud'} onClick={() => setRoute('cloud')}>
                  <Cloud size={18} /><span><strong>啟用雲端模型</strong><small>可能依供應商計費</small></span>
                </button>
              </div>
              {route === 'cloud' && (
                <div className="setup-key-block">
                  <label htmlFor="setup-provider">供應商</label>
                  <select id="setup-provider" value={provider} onChange={(event) => setProvider(event.target.value)}>
                    {PROVIDERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                  <label htmlFor="setup-key">API key（選填）</label>
                  <input id="setup-key" type="password" value={keyInput} onChange={(event) => setKeyInput(event.target.value)} autoComplete="off" placeholder="只保存於本機使用者設定" />
                  <button onClick={saveProviderKey} disabled={keyState === 'saving'}><KeyRound size={16} />{keyState === 'saving' ? '儲存中…' : '儲存金鑰'}</button>
                  {keyMessage && <div className={`settings-state ${keyState === 'error' ? 'error' : keyState === 'saved' ? 'ok' : 'info'}`}>{keyMessage}</div>}
                </div>
              )}
            </div>
          )}

          {step === 3 && (
            <div className="setup-form">
              {!backendReady || (llmState === 'loading' && !llm) ? (
                <div className="setup-loading"><LoaderCircle size={20} className="spin" />偵測本機 AI…</div>
              ) : llm?.error ? (
                <>
                  <div className="settings-state error">{llm.error}</div>
                  <button onClick={refreshLlm}><RefreshCw size={16} />重新偵測</button>
                </>
              ) : !llm?.running ? (
                llm?.builtin?.ready ? (
                  <div className="settings-state ok">內建本機 AI 就緒——{llm.builtin.model_label} 可離線用於翻譯與 AI 摘要，無需金鑰。</div>
                ) : llm?.builtin?.download?.status === 'downloading' ? (
                  <>
                    <div className="setup-loading"><LoaderCircle size={20} className="spin" />下載內建本機 AI（{llm.builtin.download.stage === 'model' ? '模型' : '執行引擎'}）中…{pullProgressText(llm.builtin.download)}</div>
                    <div className="settings-note">可直接按「下一步」，下載會在背景繼續完成。</div>
                  </>
                ) : (
                  <>
                    {llm?.builtin?.download?.status === 'error' && <div className="settings-state error">下載失敗：{llm.builtin.download.error}</div>}
                    <div className="settings-state info">本機 AI 為選配：啟用後，翻譯與 AI 摘要可離線、免金鑰使用。</div>
                    {llm?.builtin?.supported && (
                      <button className="primary" onClick={startBuiltinInstall}><Download size={16} />{llm?.builtin?.download?.status === 'error' ? '重試下載' : '下載內建本機 AI'}（引擎約 15MB＋模型約 2.4GB，一次性）</button>
                    )}
                    <div className="settings-note">已有 <a href="https://ollama.com" target="_blank" rel="noreferrer">Ollama</a> 的話，啟動它後按「重新偵測」即可沿用；都不需要的話按「下一步」略過。</div>
                    <button onClick={refreshLlm}><RefreshCw size={16} />重新偵測</button>
                  </>
                )
              ) : llm.recommended_installed ? (
                <div className="settings-state ok">本機 AI 就緒——模型 {llm.recommended} 已可用於翻譯與 AI 摘要，無需金鑰。</div>
              ) : llm.pull?.status === 'downloading' ? (
                <>
                  <div className="setup-loading"><LoaderCircle size={20} className="spin" />下載 {llm.recommended} 中…{pullProgressText(llm.pull)}</div>
                  <div className="settings-note">可直接按「下一步」，下載會在背景繼續完成。</div>
                </>
              ) : (
                <>
                  {llm.pull?.status === 'error' && <div className="settings-state error">下載失敗：{llm.pull.error}</div>}
                  <div className="settings-state info">Ollama 已啟動，尚未安裝推薦模型。</div>
                  <button className="primary" onClick={startPull}><Download size={16} />{llm.pull?.status === 'error' ? '重試下載' : '下載推薦模型'} {llm.recommended}（約 3GB，一次性）</button>
                  <div className="settings-note">下載後翻譯與 AI 摘要即可離線使用；不影響雲端模型選項。</div>
                </>
              )}
            </div>
          )}

          {step === 4 && (
            <div className="setup-checks">
              {!backendReady || readinessState === 'loading' ? (
                <div className="setup-loading"><LoaderCircle size={20} className="spin" />檢查本機環境…</div>
              ) : readiness?.error ? (
                <div className="settings-state error">{readiness.error}</div>
              ) : (
                <>
                  <div className={`setup-check ${statusTone(backendReady)}`}><Check size={17} /><span>本機後端</span><strong>{backendReady ? '已連線' : '未連線'}</strong></div>
                  <div className={`setup-check ${statusTone(vaultReady)}`}><FolderOpen size={17} /><span>筆記庫</span><strong>{vaultReady ? '可讀寫' : '請確認路徑與權限'}</strong></div>
                  <div className={`setup-check ${statusTone(asrReady)}`}><Laptop size={17} /><span>本機語音</span><strong>{asrReady ? '可用' : '選配元件未就緒'}</strong></div>
                  <div className={`setup-check ${statusTone(providerReady)}`}><KeyRound size={17} /><span>雲端金鑰</span><strong>{providerReady ? '已有設定' : '未設定（可略過）'}</strong></div>
                  <div className="settings-note">環境檢查為唯讀，不會建立筆記或呼叫付費模型。</div>
                </>
              )}
            </div>
          )}
        </div>

        <footer className="setup-actions">
          <button className="ghost" onClick={onSkip}>稍後設定</button>
          <div>
            {step > 0 && <button onClick={() => setStep((current) => current - 1)}><ArrowLeft size={16} />上一步</button>}
            {step < 4 ? (
              <button className="primary" onClick={goNext} disabled={step === 1 && !vaultRoot.trim()}>下一步<ArrowRight size={16} /></button>
            ) : (
              <button className="primary" onClick={() => onFinish({ route, readiness })} disabled={!vaultReady}>完成設定<Check size={16} /></button>
            )}
          </div>
        </footer>
      </section>
    </div>
  )
}
