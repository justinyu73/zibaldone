import { useEffect, useState } from 'react'
import {
  Captions, Coins, Database, Eye, Globe, LockKeyhole, Route, Save, ShieldCheck, Sparkles, Trash2,
} from 'lucide-react'
import { deriveVaultPaths } from '../../paths'
import { postJson } from '../../app/api'
import StatusMessage from '../../components/status/StatusMessage'
import SummaryModelPicker from '../../components/model/SummaryModelPicker'
import NoteFields from '../../components/note/NoteFields'
import { draftFromSummary, draftToAiSummary, emptyDraft } from '../../app/noteDraft'

// 文章 lane（M1）：URL → 抓正文 → 人審/可改 → AI 提取 → 存 02_Sources/articles。
// 抓取失敗（付費牆/JS 頁）就直接把內文貼進正文框，同一條流程走完。
export default function ArticleCapture({ settings, adoptUrl = '' }) {
  const paths = deriveVaultPaths(settings.vaultRoot)
  const [url, setUrl] = useState('')
  useEffect(() => {
    if (!adoptUrl) return
    setUrl(adoptUrl)
    setStatus({ type: 'info', message: '已帶入雷達候選網址，按「抓取正文」開始。' })
  }, [adoptUrl]) // eslint-disable-line react-hooks/exhaustive-deps
  const [busy, setBusy] = useState('')
  const [status, setStatus] = useState(null)
  const [article, setArticle] = useState(null)
  const [text, setText] = useState('')
  const [draft, setDraft] = useState(emptyDraft())
  const [updateAsk, setUpdateAsk] = useState(false)
  const [aiMode, setAiMode] = useState('quick')
  const [costs, setCosts] = useState(null) // { quick, deep }
  const hasUrl = !!url.trim()
  const sourceLabel = article?.title || draft.title || (hasUrl ? url : '尚未載入文章')
  const estimate = costs ? (aiMode === 'quick' ? costs.quick : costs.deep) : null

  // 免費估價：正文一就緒（抓取或貼上）就算，純本機數學不打 provider
  useEffect(() => {
    if (!text.trim()) { setCosts(null); return undefined }
    const timer = setTimeout(async () => {
      try { setCosts(await postJson('/app/estimate-text', { text })) } catch { setCosts(null) }
    }, 700)
    return () => clearTimeout(timer)
  }, [text])

  function clearAll() {
    setUrl(''); setArticle(null); setText(''); setDraft(emptyDraft()); setStatus(null); setUpdateAsk(false)
  }

  async function fetchArticle() {
    if (!hasUrl) return setStatus({ type: 'error', message: '請先貼上文章網址' })
    setBusy('fetch'); setStatus({ type: 'info', message: '抓取文章正文中…' })
    try {
      const data = await postJson('/app/article-fetch', { url, vault_path: paths.root })
      if (!data.ok) {
        setArticle({ existing: data.existing })
        setStatus({ type: 'error', message: data.message || '抓取失敗，請把內文直接貼進下方正文框。' })
        return
      }
      setArticle(data)
      setText(data.text || '')
      setDraft((d) => ({ ...d, title: data.title || d.title, source_platform: data.site || d.source_platform }))
      setStatus({
        type: data.existing ? 'info' : 'ok',
        message: data.existing ? '正文已取得；此網址已存過，存入時會更新原筆記（有備份）。' : '正文已取得，請審查後生成草稿。',
      })
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  async function generateDraft() {
    if (!text.trim()) return setStatus({ type: 'error', message: '正文是空的——先「抓取正文」或直接貼上內文' })
    setBusy('draft'); setStatus({ type: 'info', message: 'AI 摘要生成中…' })
    try {
      const data = await postJson('/summarize', {
        title: draft.title || article?.title || '', transcript_en: text, mode: aiMode, source_url: url, kind: 'article',
      })
      const site = article?.site || draft.source_platform
      setDraft({ ...draftFromSummary(data.summary || {}, draft.title || article?.title || ''), source_platform: site || 'articles' })
      setStatus({ type: 'ok', message: '草稿已生成，可編輯後存入。' })
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  function save() {
    if (busy) return setStatus({ type: 'info', message: '草稿或正文仍在處理中，完成後才能存入筆記。' })
    if (!hasUrl) return setStatus({ type: 'error', message: '文章網址必填（作為去重依據）' })
    if (!draft.title.trim()) return setStatus({ type: 'error', message: '標題必填' })
    if (article?.existing && !updateAsk) { setUpdateAsk(true); return }
    doSave()
  }

  async function doSave() {
    setUpdateAsk(false)
    setBusy('save'); setStatus({ type: 'info', message: '存入筆記…' })
    try {
      const data = await postJson('/app/article-save', {
        url, title: draft.title, content: text,
        ai_summary: draftToAiSummary(draft), ai_mode: aiMode, manual_summary: draft.manual_summary,
        author: article?.author || '', published: article?.date || '', vault_path: paths.root,
      })
      setStatus({ type: 'ok', message: `已存入：${data.relative_path}（status: inbox，可到收件匣消化）` })
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  return (
    <div className="workbench article-workbench">
      <section className="command-bar" aria-label="article command">
        <div className="command-main">
          <div className="command-kicker">文章收錄</div>
          <div className="command-title">{sourceLabel}</div>
          <div className="command-meta">
            <span className="state-chip info"><Globe size={13} /> 正文抓取＋貼上備援</span>
            <span className={`state-chip ${text ? 'ok' : 'neutral'}`}>{text ? '正文可審查' : '等待正文'}</span>
            {article?.existing && <span className="state-chip info">已存過，存入＝更新</span>}
          </div>
        </div>
        <div className="command-input">
          <input value={url} onChange={(e) => setUrl(e.target.value)} aria-label="文章網址"
            onKeyDown={(e) => e.key === 'Enter' && fetchArticle()} placeholder="貼上文章網址（去重依據，必填）" />
          <button className="primary" onClick={fetchArticle} disabled={busy === 'fetch'}><Eye size={16} />{busy === 'fetch' ? '抓取中…' : '抓取正文'}</button>
          <button className="ghost icon-button" onClick={clearAll} title="清空" aria-label="清空文章與草稿"><Trash2 size={16} /><span>清空</span></button>
        </div>
      </section>

      <StatusMessage status={status} className="workbench-alert" />

      <div className="workflow-frame">
        <div className="workflow-main">
          <section className="panel">
            <div className="panel-head">
              <div>
                <span className="panel-step">1</span>
                <h3>正文審查</h3>
              </div>
              <span className="state-chip neutral">{text ? `${text.length} 字` : '抓取失敗可直接貼上'}</span>
            </div>
            <textarea className="transcript transcript-scroll" rows={10} value={text}
              aria-label="文章正文審查區" onChange={(e) => setText(e.target.value)}
              placeholder="抓取後的正文會出現在這裡（可校正）；抓不到就把內文直接貼上。" />
            {costs && (
              <div className="metric-card compact">
                <div className="metric-icon"><Coins size={18} /></div>
                <div className="metric-body">
                  <div className="metric-label">預估成本 · {aiMode === 'quick' ? '快速模式' : '高品質模式'}</div>
                  <div className="metric-value">{estimate ? `$${estimate.estimated_usd}` : '—'}</div>
                  <div className="metric-sub">{estimate ? `約 ${estimate.estimated_tokens} tokens · 免費估算，不呼叫 AI` : ''}</div>
                </div>
                <div className="tabs-mini" role="group" aria-label="摘要成本模式">
                  <button className={aiMode === 'quick' ? 'active' : ''} aria-pressed={aiMode === 'quick'} onClick={() => setAiMode('quick')}>快速</button>
                  <button className={aiMode === 'deep' ? 'active' : ''} aria-pressed={aiMode === 'deep'} onClick={() => setAiMode('deep')}>高品質</button>
                </div>
              </div>
            )}
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <span className="panel-step">2</span>
                <h3>筆記欄位</h3>
              </div>
              <div className="panel-actions">
                <SummaryModelPicker evidenceLabel="來源：正文取得・免費" />
                <button className="primary" onClick={generateDraft} disabled={busy === 'draft' || !text.trim()}><Sparkles size={16} />{busy === 'draft' ? '生成中…' : '生成草稿'}</button>
              </div>
            </div>
            <NoteFields draft={draft} setDraft={setDraft} workspace />
            {updateAsk && (
              <div className="ac-gate ac-warn">
                <span>此網址已存過筆記，存入會以目前內容更新原筆記（前一版自動備份）。確認更新？</span>
                <div className="row end">
                  <button className="ghost" onClick={() => setUpdateAsk(false)}>取消</button>
                  <button className="primary" onClick={doSave} disabled={busy === 'save'}>確認更新</button>
                </div>
              </div>
            )}
            <div className="row end">
              <button className="ghost" onClick={() => setDraft(emptyDraft())}>保留正文，清空草稿</button>
              <button className="primary gated-action" onClick={save} disabled={busy !== ''}><Save size={16} />{busy === 'save' ? '存入中…' : '存入筆記'}</button>
            </div>
          </section>
        </div>

        <aside className="inspector" aria-label="article route inspector">
          <section className="inspector-section">
            <h3><Route size={15} /> 路線</h3>
            <div className="state-list">
              <div><span>來源</span><strong>{article?.site || (hasUrl ? '網址待抓取' : '未選')}</strong></div>
              <div><span>正文</span><strong>{text ? '已就緒' : '等待'}</strong></div>
              <div><span>去重</span><strong>{article?.existing ? '已存過' : '網址指紋'}</strong></div>
            </div>
          </section>
          <section className="inspector-section">
            <h3><ShieldCheck size={15} /> 門檻</h3>
            <div className="gate-row ok"><Eye size={14} /> 抓取與審查：不呼叫 AI</div>
            <div className={text ? 'gate-row ok' : 'gate-row muted-gate'}><Captions size={14} /> 正文審查後才摘要</div>
            <div className="gate-row warn"><LockKeyhole size={14} /> 存入＝寫入本機筆記（可備份還原）</div>
          </section>
        </aside>
      </div>

      <footer className="status-strip">
        <span><Database size={13} /> 筆記目標：{paths.articles || '後端預設'}</span>
        <span><Globe size={13} /> {article?.site || '尚無來源'}</span>
        <span><LockKeyhole size={13} /> AI 呼叫與寫入：人工把關</span>
      </footer>
    </div>
  )
}
