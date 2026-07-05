import { useEffect, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { apiFetch } from '../../app/api'
import { newerVersion } from '../../app/version'

const UPDATE_TOKEN_KEY = 'yt_update_token'
const REPO_API = 'https://api.github.com/repos/justinyu73/zibaldone'

export function normalizeTag(tag) {
  return String(tag || '').replace(/^[Vv]/, '')
}

export default function UpdateSettings() {
  const [appVersion, setAppVersion] = useState('')
  const [updateToken, setUpdateToken] = useState('')
  const [update, setUpdate] = useState({ state: 'idle', message: '', latest: '', endpoint: '' })
  const [diagnostic, setDiagnostic] = useState('')

  useEffect(() => {
    import('@tauri-apps/api/app').then((module) => module.getVersion()).then(setAppVersion).catch(() => {})
    apiFetch('/app/update-token').then((response) => response.json()).then((data) => {
      if (data.token) setUpdateToken(data.token)
    }).catch(() => {})
    try { window.localStorage.removeItem(UPDATE_TOKEN_KEY) } catch { /* clean legacy token */ }
  }, [])

  async function checkUpdate() {
    // token 選填（S2 公開化）：私有 repo 需 token；公開 repo 匿名即可查 release
    const token = updateToken.trim()
    setUpdate({ state: 'checking', message: '檢查最新版本中…', latest: '', endpoint: '' })
    try {
      const headers = { Accept: 'application/vnd.github+json' }
      if (token) headers.Authorization = `Bearer ${token}`
      const response = await fetch(`${REPO_API}/releases/latest`, { headers })
      if (response.status === 401 || response.status === 403) throw new Error(token ? 'token 無效或權限不足（需要此 repo 的 Contents 唯讀權限）' : '此 repo 需要 GitHub 唯讀 token 才能檢查更新')
      if (token) {
        apiFetch('/app/update-token', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        }).catch(() => {})
      }
      if (response.status === 404) throw new Error('尚無發佈版本（repo 還沒有 Release）')
      if (!response.ok) throw new Error(`GitHub API ${response.status}`)
      const release = await response.json()
      const latest = normalizeTag(release.tag_name)
      const asset = (release.assets || []).find((item) => item.name === 'latest.json')
      if (latest && appVersion && newerVersion(latest, appVersion) && asset) {
        setUpdate({ state: 'available', message: `有新版本 v${latest}（目前 v${appVersion}）`, latest, endpoint: asset.url })
      } else {
        setUpdate({ state: 'none', message: `已是最新（v${appVersion || latest || '—'}）`, latest: '', endpoint: '' })
      }
    } catch (error) {
      setUpdate({ state: 'error', message: error.message, latest: '', endpoint: '' })
    }
  }

  async function installUpdate() {
    setUpdate((current) => ({ ...current, state: 'installing', message: '下載並驗證更新中，完成後會自動重啟…' }))
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      await invoke('install_app_update', { endpoint: update.endpoint, token: updateToken.trim() })
    } catch (error) {
      setUpdate((current) => ({
        ...current,
        state: 'error',
        message: `更新失敗：${typeof error === 'string' ? error : error.message || '僅桌面版支援一鍵更新'}`,
      }))
    }
  }

  async function openLogDir() {
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      await invoke('open_log_dir')
      setDiagnostic('已開啟 log 資料夾——出問題時把 app.log 拖進對話即可診斷。')
    } catch (error) {
      setDiagnostic(`無法開啟 log 資料夾（僅桌面版支援）：${typeof error === 'string' ? error : error.message || ''}`)
    }
  }

  return (
    <section className="panel settings-panel update-panel">
      <div className="panel-head">
        <div>
          <ShieldCheck size={16} />
          <h3>版本與更新</h3>
        </div>
        <span className="state-chip neutral">目前 v{appVersion || '—（桌面版顯示）'}</span>
      </div>
      <label>更新用 GitHub Token（fine-grained，僅此 repo Contents 唯讀；驗證成功後保存於本機設定，同 AI 金鑰，免再貼）
        <input type="password" value={updateToken} onChange={(event) => setUpdateToken(event.target.value)}
          placeholder="github_pat_...（貼一次，檢查更新成功後記住）" autoComplete="off" />
      </label>
      <div className="row">
        <button onClick={checkUpdate} disabled={update.state === 'checking' || update.state === 'installing'}>
          {update.state === 'checking' ? '檢查中…' : '檢查更新'}
        </button>
        {update.state === 'available' && (
          <button className="primary gated-action" onClick={installUpdate}>下載並安裝（自動重啟）</button>
        )}
      </div>
      {update.message && (
        <div className={`settings-state ${update.state === 'error' ? 'info' : update.state === 'available' ? 'ok' : 'neutral'}`}>
          <ShieldCheck size={15} />
          <span>{update.message}</span>
        </div>
      )}
      <div className="settings-note">
        <span>更新檔以簽章驗證後安裝（防掉包）；一鍵更新不經瀏覽器下載，不會再被 macOS 隔離標記。</span>
      </div>
      <div className="row">
        <button onClick={openLogDir}>打開 log 資料夾（診斷用）</button>
      </div>
      {diagnostic && (
        <div className="settings-state neutral">
          <ShieldCheck size={15} />
          <span>{diagnostic}</span>
        </div>
      )}
    </section>
  )
}
