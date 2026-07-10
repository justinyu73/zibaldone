import { useEffect, useState } from 'react'
import {
  AlertTriangle, Captions, Clapperboard, Coins, Database, Eye, FileText, Globe, Languages,
  LockKeyhole, PlayCircle, Route, Save, ShieldCheck, Sparkles, Trash2,
} from 'lucide-react'
import { deriveVaultPaths } from '../../paths'
import { apiFetch, postJson } from '../../app/api'
import StatusMessage from '../../components/status/StatusMessage'
import SummaryModelPicker from '../../components/model/SummaryModelPicker'
import NoteFields from '../../components/note/NoteFields'
import { draftFromSummary, draftToAiSummary, emptyDraft, extractVideoId } from '../../app/noteDraft'

export default function VideoCapture({ settings, adoptUrl = '' }) {
  const paths = deriveVaultPaths(settings.vaultRoot)
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState('')
  const [status, setStatus] = useState(null)
  useEffect(() => {
    if (!adoptUrl) return
    setUrl(adoptUrl)
    setStatus({ type: 'info', message: '已帶入待收網址，按「預覽」開始。' })
  }, [adoptUrl]) // eslint-disable-line react-hooks/exhaustive-deps
  const [videoId, setVideoId] = useState('')
  const [fetched, setFetched] = useState(null)
  const [lang, setLang] = useState('en')
  const [enText, setEnText] = useState('')
  const [zhText, setZhText] = useState('')
  const [draft, setDraft] = useState(emptyDraft())
  const [mode, setMode] = useState('quick')
  const [costs, setCosts] = useState(null) // { quick, deep } estimates
  const [overwriteAsk, setOverwriteAsk] = useState(false)
  const estimate = costs ? (mode === 'quick' ? costs.quick : costs.deep) : null
  const sourceLabel = fetched?.meta?.title || (videoId ? `YouTube ${videoId}` : '尚未載入來源')
  const evidenceState = fetched
    ? (enText || zhText ? '字幕可審查' : '無可用字幕')
    : videoId ? '待抓取字幕' : '等待來源'
  const evidenceTone = fetched
    ? (enText || zhText ? 'ok' : 'error')
    : videoId ? 'info' : 'neutral'
  const languageState = zhText ? '繁中可用' : enText ? '需翻譯' : '尚無字幕'
  const writeState = fetched ? (overwriteAsk ? '覆寫確認中' : '預覽後可存入') : '尚未存入'
  const nextAction = !(videoId)
    ? '預覽來源'
    : !(enText || zhText)
      ? '抓取字幕'
      : !draft.title && !draft.explicit_topic && !draft.key_points
        ? '生成草稿'
        : '審查後存入'

  function chooseMode(nextMode) { setMode(nextMode) }

  function clearAll() {
    setUrl(''); setVideoId(''); setFetched(null); setEnText(''); setZhText(''); setDraft(emptyDraft()); setStatus(null); setCosts(null); setOverwriteAsk(false)
  }

  // ① 預覽 — 播放器秒開（client-side）+ lean 免費估價（只抓字幕算字數，跳過繁簡轉換等重活）。
  async function preview() {
    const vid = extractVideoId(url)
    if (!vid) return setStatus({ type: 'error', message: '無法辨識 YouTube 網址或影片 ID' })
    setVideoId(vid); setFetched(null); setEnText(''); setZhText(''); setCosts(null); setStatus(null)
    setBusy('estimate')
    try {
      const data = await postJson('/estimate-source', { url })
      setCosts({ quick: data.estimate_quick, deep: data.estimate_deep, translate: data.estimate_translate })
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  // ② 抓取字幕 — 完整 /api/fetch（含繁簡轉換，供編輯與摘要）。
  async function fetchCaptions() {
    if (!extractVideoId(url)) return setStatus({ type: 'error', message: '請先輸入有效 URL' })
    setBusy('fetch'); setStatus({ type: 'info', message: '抓取字幕中（長影片較久）...' })
    try {
      const data = await postJson('/fetch', { url, vault_path: paths.youtube, subfolder: '' })
      const en = data.transcript?.en_text || ''
      const zh = data.transcript?.zh_text || ''
      setFetched(data); setEnText(en); setZhText(zh)
      setDraft((d) => ({ ...d, title: data.meta?.title || '' }))
      setStatus({ type: en || zh ? 'ok' : 'error', message: en || zh ? '字幕已取得，可校正後生成草稿。' : '此來源沒有可用字幕。可用下方「下載音檔並轉錄（ASR）」直接本機轉錄。' })
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  // 無字幕 fallback（收斂在影片筆記流程內，非獨立分頁）：使用者明確觸發。
  // ASR：下載音檔→本機 whisper 轉錄；轉錄稿當原文字幕，續走既有 translate→summarize。
  async function runVideoAsr() {
    if (!extractVideoId(url)) return setStatus({ type: 'error', message: '請先輸入有效 URL' })
    setBusy('asr'); setStatus({ type: 'info', message: '下載音檔並本機轉錄中（長影片較久，離線免金鑰）...' })
    try {
      const data = await postJson('/app/video-audio-asr', { url })
      const t = (data.transcript || '').trim()
      if (!t) throw new Error('轉錄結果為空（此來源可能無可辨識語音）')
      setEnText(t); setLang('en')
      setStatus({ type: 'ok', message: '已用本機語音轉錄產生逐字稿，可校正後生成草稿。' })
    } catch (error) {
      setStatus({ type: 'error', message: `語音轉錄失敗：${error.message}` })
    } finally { setBusy('') }
  }

  // OCR（rung 3）：無字幕且畫面有硬字幕時，讀 6 幀畫面文字。需雲端 provider。
  async function runVideoOcr() {
    if (!extractVideoId(url)) return setStatus({ type: 'error', message: '請先輸入有效 URL' })
    setBusy('ocr'); setStatus({ type: 'info', message: '讀取影片畫面硬字幕（OCR，需雲端 provider）...' })
    try {
      const data = await postJson('/production-extractor', {
        url, mode: 'real', user_authorized_media: true, allow_provider_ocr: true, confirm_report_only: true,
      })
      const text = (data.ocr_text || '').trim()
      if (!text) throw new Error('OCR 未取得可用文字（此來源畫面可能無硬字幕）')
      setEnText(text); setLang('en')
      setStatus({ type: 'ok', message: '已用畫面 OCR 產生文字，可校正後生成草稿。' })
    } catch (error) {
      setStatus({ type: 'error', message: `OCR 失敗：${error.message}` })
    } finally { setBusy('') }
  }

  // ③ 生成草稿 — 需要時先翻譯字幕為中文（貼入中文區塊），再付費 AI 摘要。
  async function generateDraft() {
    if (!(enText || zhText)) return setStatus({ type: 'error', message: '請先「抓取字幕」' })
    setBusy('draft')
    try {
      // 判斷是否需轉中：有原文、中文區塊還空 → 翻譯後貼入中文區塊供校閱。
      let zh = zhText
      const didTranslate = !zh.trim() && !!enText.trim()
      if (didTranslate) {
        // chunked on the backend; poll per-request progress so long videos
        // show 3/12 段 instead of an opaque spinner
        const progressId = `t-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        setStatus({ type: 'info', message: '翻譯字幕為中文...' })
        const poll = setInterval(async () => {
          try {
            const r = await apiFetch(`/translate-progress?progress_id=${progressId}`)
            const d = await r.json()
            if (d.total > 0) setStatus({ type: 'info', message: `翻譯字幕為中文...（${d.done}/${d.total} 段）` })
          } catch { /* ignore */ }
        }, 900)
        try {
          const t = await postJson('/translate', { text: enText, target: 'zh-TW', progress_id: progressId })
          zh = t.translated || ''
        } finally { clearInterval(poll) }
        setZhText(zh); setLang('zh')
      }
      setStatus({ type: 'info', message: 'AI 摘要生成中...' })
      const data = await postJson('/summarize', {
        title: fetched?.meta?.title || '', transcript_en: enText, transcript_zh: zh, mode, source_url: fetched?.url || url,
      })
      setDraft(draftFromSummary(data.summary || {}, fetched?.meta?.title || ''))
      setStatus({ type: 'ok', message: didTranslate ? '已翻譯中文字幕並生成草稿，可編輯後存入。' : '草稿已生成，可編輯後存入。' })
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  // 存入前的安全閘：已存在 → 先問是否覆寫，不直接蓋掉。
  function save() {
    if (!fetched) return setStatus({ type: 'error', message: '請先抓取字幕' })
    if (fetched.existing) { setOverwriteAsk(true); return }
    doSave('create')
  }

  async function doSave(saveMode) {
    setOverwriteAsk(false)
    setBusy('save'); setStatus({ type: 'info', message: saveMode === 'update_ai' ? '覆寫更新筆記...' : '存入筆記...' })
    try {
      const data = await postJson('/save', {
        url: fetched.url, video_id: fetched.video_id, title: draft.title || fetched.meta?.title || fetched.video_id,
        channel: fetched.meta?.channel || '', published: fetched.meta?.published, duration: fetched.meta?.duration,
        thumbnail: fetched.meta?.thumbnail, transcript_en: enText, transcript_zh: zhText,
        manual_summary: draft.manual_summary, ai_summary: draftToAiSummary(draft), ai_mode: mode,
        save_mode: saveMode, languages: fetched.transcript?.available_langs || [],
        is_short: fetched.is_short, filename: draft.filename || null,
        vault_path: paths.youtube, subfolder: '',
      })
      setStatus({ type: 'ok', message: `${saveMode === 'update_ai' ? '已覆寫更新' : '已存入'}：${data.relative_path}（資料夾：${paths.youtube || '後端預設'}）` })
    } catch (error) {
      // Backend race / stale existing flag → fall back to the same overwrite prompt.
      if (/already exists/i.test(error.message) && saveMode === 'create') { setOverwriteAsk(true); return }
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  return (
    <div className="workbench capture-workbench">
      <section className="command-bar" aria-label="source command">
        <div className="command-main">
          <div className="command-kicker">來源收錄</div>
          <div className="command-title">{sourceLabel}</div>
          <div className="command-meta">
            <span className="state-chip info"><Route size={13} /> 字幕優先路線</span>
            <span className={`state-chip ${evidenceTone}`}>{evidenceState}</span>
            <span className="state-chip neutral">{writeState}</span>
          </div>
        </div>
        <div className="command-input">
          <input value={url} onChange={(e) => setUrl(e.target.value)}
            aria-label="YouTube 網址或影片 ID"
            onKeyDown={(e) => e.key === 'Enter' && preview()} placeholder="貼上 YouTube 網址或影片 ID" />
          <button className="primary" onClick={preview} title="預覽來源"><Eye size={16} />預覽</button>
          <button className="ghost icon-button" onClick={clearAll} title="清空" aria-label="清空來源與草稿"><Trash2 size={16} /><span>清空</span></button>
        </div>
      </section>

      <StatusMessage status={status} className="workbench-alert" />

      <div className="workflow-frame">
        <div className="workflow-main">
          <section className="panel source-panel">
            <div className="panel-head">
              <div>
                <span className="panel-step">1</span>
                <h3>來源與估價</h3>
              </div>
              <span className="state-chip neutral">下一步：{nextAction}</span>
            </div>
            {videoId ? (
              // YouTube 內嵌會被 tauri:// origin 擋(錯誤153)，改用縮圖卡 + 點擊外開瀏覽器。
              <a className="yt-thumb" href={`https://www.youtube.com/watch?v=${videoId}`} target="_blank" rel="noreferrer" title="在瀏覽器開啟 YouTube">
                <img src={`https://img.youtube.com/vi/${videoId}/hqdefault.jpg`} alt="影片縮圖" loading="lazy" />
                <span className="yt-thumb-play"><PlayCircle size={52} /></span>
                <span className="yt-thumb-hint"><Globe size={13} /> 在瀏覽器開啟 YouTube</span>
              </a>
            ) : (
              <div className="empty-surface">
                <Clapperboard size={22} />
                <span>貼上來源後，先預覽與免費估價；不會呼叫 AI 或寫入筆記。</span>
              </div>
            )}
            {(busy === 'estimate' || costs) && (
              <div className="metric-card compact">
                <div className="metric-icon"><Coins size={18} /></div>
                <div className="metric-body">
                  <div className="metric-label">預估成本 · {mode === 'quick' ? '快速模式' : '高品質模式'}</div>
                  <div className="metric-value">{busy === 'estimate' ? '估算中…' : estimate ? `$${(estimate.estimated_usd + (costs?.translate?.estimated_usd || 0)).toFixed(6)}` : '抓字幕後得知'}</div>
                  <div className="metric-sub">{estimate ? `摘要 $${estimate.estimated_usd}${costs?.translate ? ` · 翻譯 $${costs.translate.estimated_usd}` : ''}` : '免費估算，不呼叫 AI'}</div>
                </div>
                <div className="tabs-mini" role="group" aria-label="摘要成本模式">
                  <button className={mode === 'quick' ? 'active' : ''} aria-pressed={mode === 'quick'} onClick={() => chooseMode('quick')}>快速</button>
                  <button className={mode === 'deep' ? 'active' : ''} aria-pressed={mode === 'deep'} onClick={() => chooseMode('deep')}>高品質</button>
                </div>
              </div>
            )}
          </section>

          <section className="panel transcript-panel">
            <div className="panel-head">
              <div>
                <span className="panel-step">2</span>
                <h3>字幕審查</h3>
              </div>
              <div className="panel-actions">
                <button className="primary" onClick={fetchCaptions} disabled={busy === 'fetch' || !videoId} title={videoId ? '抓取字幕' : '請先預覽有效來源'}><Captions size={16} />{busy === 'fetch' ? '抓取中...' : '抓取字幕'}</button>
                <div className="tabs-mini" role="group" aria-label="字幕語言">
                  <button className={lang === 'en' ? 'active' : ''} aria-pressed={lang === 'en'} onClick={() => setLang('en')}>原文</button>
                  <button className={lang === 'zh' ? 'active' : ''} aria-pressed={lang === 'zh'} onClick={() => setLang('zh')}>中文</button>
                </div>
              </div>
            </div>
            <textarea className="transcript transcript-scroll" rows={10} value={lang === 'en' ? enText : zhText}
              aria-label={lang === 'en' ? '原文字幕審查區' : '中文字幕審查區'}
              onChange={(e) => (lang === 'en' ? setEnText(e.target.value) : setZhText(e.target.value))}
              placeholder="字幕內容（抓取後可校正）。這裡是 AI 摘要前的人為審查區。" />
            {fetched && !enText && !zhText && (
              <div className="caption-fallback">
                <div className="settings-note">字幕優先；此來源無可用字幕。可用進階本機能力（免金鑰、離線；收斂在影片筆記流程內）：</div>
                <div className="panel-actions">
                  <button onClick={runVideoAsr} disabled={busy === 'asr'}><Captions size={16} />{busy === 'asr' ? '轉錄中...' : '下載音檔並轉錄（ASR）'}</button>
                  <button onClick={runVideoOcr} disabled={busy === 'ocr'}><FileText size={16} />{busy === 'ocr' ? '讀取中...' : '讀畫面硬字幕（OCR）'}</button>
                </div>
              </div>
            )}
          </section>

          <section className="panel note-panel">
            <div className="panel-head">
              <div>
                <span className="panel-step">3</span>
                <h3>筆記預覽與編輯</h3>
              </div>
              <div className="panel-actions">
                <SummaryModelPicker evidenceLabel="來源：字幕取得・免費" />
                <button className="primary" onClick={generateDraft} disabled={busy === 'draft' || !(enText || zhText)}><Sparkles size={16} />{busy === 'draft' ? '生成中...' : '生成草稿'}</button>
              </div>
            </div>
            <NoteFields draft={draft} setDraft={setDraft} workspace />
            {overwriteAsk && (
              <div className="status info overwrite-ask" role="group" aria-label="覆寫確認">
                <span>此影片已存在於筆記庫。覆寫只更新筆記的 AI 摘要區塊；原筆記的逐字稿與個人心得會保留原樣，這裡輸入的心得不會寫入。</span>
                <div className="row">
                  <button className="ghost" onClick={() => setOverwriteAsk(false)}>取消</button>
                  <button className="primary" onClick={() => doSave('update_ai')} disabled={busy === 'save'}>{busy === 'save' ? '覆寫中...' : '確認覆寫'}</button>
                </div>
              </div>
            )}
            <div className="row end">
              <button className="ghost" onClick={() => setDraft(emptyDraft())}>保留來源，清空草稿</button>
              <button className="primary gated-action" onClick={save} disabled={busy === 'save' || !fetched}><Save size={16} />{busy === 'save' ? '存入中...' : '存入筆記'}</button>
            </div>
          </section>
        </div>

        <aside className="inspector" aria-label="route inspector">
          <section className="inspector-section">
            <h3><Route size={15} /> 路線</h3>
            <div className="state-list">
              <div><span>來源</span><strong>{videoId ? 'YouTube' : '未選'}</strong></div>
              <div><span>取得</span><strong>字幕優先</strong></div>
              <div><span>字幕狀態</span><strong>{evidenceState}</strong></div>
              <div><span>語言</span><strong>{languageState}</strong></div>
            </div>
          </section>
          <section className="inspector-section">
            <h3><ShieldCheck size={15} /> 門檻</h3>
            <div className="gate-row ok"><ShieldCheck size={14} /> 預覽與估價：不呼叫 AI、不寫入</div>
            <div className={(enText || zhText) ? 'gate-row ok' : 'gate-row muted-gate'}><Captions size={14} /> 字幕審查後才摘要</div>
            <div className={fetched ? 'gate-row warn' : 'gate-row muted-gate'}><LockKeyhole size={14} /> 存入需先取得來源資料</div>
          </section>
          <section className="inspector-section">
            <h3><Coins size={15} /> 成本</h3>
            {estimate ? (
              <div className="cost-mini">
                <strong>${(estimate.estimated_usd + (costs?.translate?.estimated_usd || 0)).toFixed(6)}</strong>
                <span>{mode === 'quick' ? '快速摘要' : '高品質摘要'} · 翻譯 {costs?.translate ? `$${costs.translate.estimated_usd}` : '—'}</span>
              </div>
            ) : (
              <div className="gate-row muted-gate"><AlertTriangle size={14} /> 尚未估價或無字幕</div>
            )}
          </section>
          {fetched && (
            <section className="inspector-section">
              <h3><FileText size={15} /> 來源資訊</h3>
              <div className="video-info compact">
                <strong>{fetched.meta?.title}</strong>
                <span>{fetched.meta?.channel}{fetched.meta?.duration ? `｜${fetched.meta.duration}` : ''}</span>
                <span>字幕：{(fetched.transcript?.available_langs || []).join(', ') || '—'}</span>
                {fetched.existing && <span className="state-chip info">索引中已存在，存入時更新</span>}
              </div>
            </section>
          )}
        </aside>
      </div>

      <footer className="status-strip">
        <span><Database size={13} /> 筆記目標：{paths.youtube || '後端預設'}</span>
        <span><Languages size={13} /> {languageState}</span>
        <span><LockKeyhole size={13} /> AI 呼叫與寫入：人工把關</span>
      </footer>
    </div>
  )
}
