import { KeyRound, LockKeyhole, ShieldCheck } from 'lucide-react'
import { PROVIDER_META, PROVIDER_ORDER } from '../../components/model/ModelSelect'
import BrandGlyph from '../../components/BrandGlyph'
import StatusMessage from '../../components/status/StatusMessage'

export default function ProviderSettings({
  busy, clearKey, input, keyStatus, message, provider, saveKey, setInput,
  setMessage, setProvider, testKey,
}) {
  const selected = keyStatus?.providers?.[provider]
  return (
    <section className="panel settings-panel provider-panel">
      <div className="panel-head">
        <div><KeyRound size={16} /><h3>Provider 金鑰</h3></div>
        <span className={`state-chip ${selected?.key_set ? 'ok' : 'info'}`}>{selected?.key_set ? '已設定' : '未設定'}</span>
      </div>
      <div className="provider-tabs">
        {PROVIDER_ORDER.map((item) => {
          const status = keyStatus?.providers?.[item]
          return (
            <button key={item} className={provider === item ? 'active' : ''} aria-pressed={provider === item}
              onClick={() => { setProvider(item); setMessage(null) }}>
              <BrandGlyph provider={item} />{PROVIDER_META[item].label}<span className={`provider-dot ${status?.key_set ? 'ok' : ''}`} />
            </button>
          )
        })}
      </div>
      <div className={`settings-state ${selected?.key_set ? 'ok' : 'info'}`}>
        <ShieldCheck size={15} />
        <span>{keyStatus
          ? (selected?.key_set
            ? `已設定 …${selected.key_hint}（來源：${selected.source === 'config' ? '本機設定檔' : selected.source === 'env' ? '.env（建議改存本機）' : '—'}）`
            : '未設定金鑰；字幕抓取、本機筆記與 Ollama 本地模型不受影響，翻譯與 AI 摘要才需要金鑰。')
          : '讀取 provider 狀態中…'}</span>
      </div>
      <label>輸入 / 更換 {PROVIDER_META[provider].label} 金鑰
        <input type="password" value={input} onChange={(event) => { setInput(event.target.value); setMessage(null) }}
          placeholder={PROVIDER_META[provider].placeholder} autoComplete="off" />
      </label>
      <div className="settings-note">
        <LockKeyhole size={14} />
        <span>金鑰存在 <code>~/.config/yt-note-app/config.json</code>，UI 只顯示遮罩末 4 碼，不回傳明文、不寫入日誌。</span>
      </div>
      <div className="row">
        <button className="primary gated-action" onClick={saveKey} disabled={busy === 'save'}>{busy === 'save' ? '儲存中...' : '儲存金鑰'}</button>
        <button className="gated-action" onClick={testKey} disabled={busy === 'test' || !selected?.key_set}><ShieldCheck size={15} />{busy === 'test' ? '測試中...' : '測試金鑰'}</button>
        <button className="ghost danger-ghost" onClick={clearKey} disabled={busy === 'clear' || !selected?.key_set} title="清除目前 provider 金鑰">清除</button>
      </div>
      <StatusMessage status={message} className="settings-message" />
    </section>
  )
}
