import { Coins, FileText, KeyRound, Settings } from 'lucide-react'
import ModelSelect, { PROVIDER_META } from '../../components/model/ModelSelect'

export default function RuntimeSettings({
  cost, modelOptions, modelProvider, refreshCost, refreshRuntime, runtime,
  runtimeSaved, saveRuntime, setRuntime, setRuntimeField, setRuntimeSaved,
}) {
  return (
    <section className="panel settings-panel cost-panel">
      <div className="panel-head">
        <div><Coins size={16} /><h3>用量與成本</h3></div>
        <div className="row">
          <button className="ghost" onClick={() => { refreshCost(); refreshRuntime() }}>重新整理用量</button>
          <span className={cost?.over_daily_cap ? 'state-chip error' : 'state-chip ok'}>{cost?.over_daily_cap ? '付費已擋' : '額度內'}</span>
        </div>
      </div>
      <div className="cost-grid">
        <div className="cost-stat"><div className="cost-stat-label">今日花費</div><div className="cost-stat-value">${cost?.today_usd ?? '—'}</div><div className="muted">{cost?.today_calls ?? 0} 次呼叫</div></div>
        <div className="cost-stat"><div className="cost-stat-label">累計花費</div><div className="cost-stat-value">${cost?.total_usd ?? '—'}</div><div className="muted">{cost?.total_calls ?? 0} 次呼叫</div></div>
        <div className="cost-stat"><div className="cost-stat-label">每日上限</div><div className="cost-stat-value">${cost?.daily_cap_usd ?? '—'}</div><div className={cost?.over_daily_cap ? 'state-chip error' : 'state-chip neutral'}>{cost?.over_daily_cap ? '已達上限' : '可執行'}</div></div>
      </div>
      {cost?.by_provider && Object.keys(cost.by_provider).length > 0 && (
        <div className="provider-breakdown">
          <span className="muted">累計分項：</span>
          {Object.entries(cost.by_provider).map(([provider, value]) => (
            <span key={provider} className="provider-chip">{PROVIDER_META[provider]?.label || provider} ${value.usd} · {value.calls} 次</span>
          ))}
        </div>
      )}
      {runtime ? (
        <div className="settings-form">
          <div className="note-fields-row">
            <label>翻譯模型<ModelSelect value={runtime.translate_model} onChange={setRuntimeField('translate_model')} options={modelOptions?.translate} /></label>
            <label>摘要模型<ModelSelect value={runtime.summary_model} onChange={setRuntimeField('summary_model')} options={modelOptions?.summary} /></label>
          </div>
          <div className="settings-note">
            <KeyRound size={14} />
            <span>模型呼叫的 provider：翻譯 {modelProvider(runtime.translate_model)}、摘要 {modelProvider(runtime.summary_model)}。雲端用對應金鑰；本地 Ollama 免金鑰、零雲端成本。</span>
          </div>
          <label className="settings-toggle">
            <input type="checkbox" checked={Boolean(runtime.cli_providers_enabled)}
              onChange={(event) => { setRuntime({ ...runtime, cli_providers_enabled: event.target.checked }); setRuntimeSaved(false) }} />
            <span>啟用訂閱 CLI 模型（進階）——偵測本機已登入的 claude / codex / gemini CLI 當翻譯/摘要模型，用你的訂閱額度、app 端零 API 成本。注意：以程式呼叫訂閱 CLI 可能落在各家服務條款的灰色地帶，請自行確認後再開啟。</span>
          </label>
          <div className="note-fields-row">
            <label>每筆成本上限 (USD)<input type="number" step="0.01" value={runtime.per_job_cap_usd} onChange={setRuntimeField('per_job_cap_usd')} /></label>
            <label>每日成本上限 (USD，硬性擋)<input type="number" step="0.05" value={runtime.daily_cap_usd} onChange={setRuntimeField('daily_cap_usd')} /></label>
          </div>
          <div className="note-fields-row">
            <label>會議摘要模板
              <select value={runtime.meeting_template || 'general'} onChange={setRuntimeField('meeting_template')}>
                <option value="general">一般會議</option><option value="decision">決策會議</option>
                <option value="interview">訪談／研究</option><option value="learning">課程／分享</option>
              </select>
            </label>
            <label>個人詞彙表（一行一詞）
              <textarea rows={4} value={(runtime.meeting_glossary || []).join('\n')}
                onChange={(event) => {
                  setRuntime({ ...runtime, meeting_glossary: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean) })
                  setRuntimeSaved(false)
                }} placeholder={'YT Note App\nWhisperX\n專案名稱'} />
            </label>
          </div>
          <div className="settings-note"><FileText size={14} /><span>模板只調整摘要重點，欄位契約不變；詞彙表只在逐字稿確實提到時協助拼寫。</span></div>
          <div className="row end">
            {runtimeSaved && <span className="state-chip ok">已儲存</span>}
            <button className="primary" onClick={saveRuntime}>儲存模型/上限</button>
          </div>
        </div>
      ) : <div className="settings-state info"><Settings size={15} /><span>讀取模型與成本上限中…</span></div>}
    </section>
  )
}
