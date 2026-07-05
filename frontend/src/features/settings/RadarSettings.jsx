import { Radar } from 'lucide-react'

export default function RadarSettings({ draft, save, saved, setDraft, setSaved, setTuning, tuning }) {
  return (
    <section className="panel settings-panel radar-panel">
      <div className="panel-head">
        <div><Radar size={16} /><h3>新聞雷達</h3></div>
        <span className="state-chip neutral">收件匣的雷達分頁使用這些設定</span>
      </div>
      <label><Radar size={14} /> 雷達 RSS 來源（選填，一行一個；留空用預設：OpenAI／Google AI／HuggingFace／Simon Willison）
        <textarea rows={3} value={(draft.radarFeeds || []).join('\n')}
          onChange={(event) => {
            setDraft({ ...draft, radarFeeds: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean) })
            setSaved(false)
          }} placeholder={'https://example.com/feed.xml'} />
      </label>
      <label><Radar size={14} /> 雷達主題關鍵詞（選填，一行一個；留空＝內建 AI 詞庫。影響 HN 與 GitHub，RSS 為人工精選不過濾）
        <textarea rows={2} value={(tuning.keywords || []).join('\n')}
          onChange={(event) => {
            setDraft({ ...draft, radarTuning: { ...tuning, keywords: event.target.value.split('\n').map((item) => item.trim()).filter(Boolean) } })
            setSaved(false)
          }} placeholder={'rust\nrobotics'} />
      </label>
      <div className="note-fields-row">
        <label>雷達總篇數上限<input type="number" min="1" value={tuning.totalCap} onChange={setTuning('totalCap')} /></label>
        <label>單一來源篇數上限<input type="number" min="1" value={tuning.perSourceCap} onChange={setTuning('perSourceCap')} /></label>
      </div>
      <div className="note-fields-row">
        <label>HN 分數下限<input type="number" min="0" value={tuning.hnMinPoints} onChange={setTuning('hnMinPoints')} /></label>
        <label>GitHub 星數下限<input type="number" min="0" value={tuning.ghMinStars} onChange={setTuning('ghMinStars')} /></label>
      </div>
      <div className="row radar-toggles">
        <span>掃描來源：</span>
        <label><input type="checkbox" checked={tuning.enableHn} onChange={setTuning('enableHn')} /> HN 熱門</label>
        <label><input type="checkbox" checked={tuning.enableGithub} onChange={setTuning('enableGithub')} /> GitHub 新專案</label>
        <label><input type="checkbox" checked={tuning.enableRss} onChange={setTuning('enableRss')} /> RSS</label>
      </div>
      <div className="row end">
        {saved && <span className="state-chip ok">已儲存</span>}
        <button className="primary" onClick={save}>儲存設定</button>
      </div>
    </section>
  )
}
