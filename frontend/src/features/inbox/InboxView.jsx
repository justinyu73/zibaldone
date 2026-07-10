import { useEffect, useState } from 'react'
import {
  AlertTriangle, CheckCheck, Eye, FileText, FolderOpen, Globe, Inbox, PlayCircle, Radar,
  Save, Settings, ShieldCheck, Trash2,
} from 'lucide-react'
import { deriveVaultPaths } from '../../paths'
import SourceGlyph, { sourceTypeFromPath } from '../../components/SourceGlyph'
import NoteReader from '../../NoteReader'
import { API, apiFetch, postJson } from '../../app/api'
import StatusMessage from '../../components/status/StatusMessage'
import ThoughtBox from '../../components/note/ThoughtBox'
import { defaultRadarTuning } from '../../app/settings'

const TRASH_HINT = '_trash/'

export default function InboxView({ settings, active = true, onCount, onGo, ready = true, onAdopt }) {
  const paths = deriveVaultPaths(settings.vaultRoot)
  const [items, setItems] = useState([])
  const [status, setStatus] = useState(null)
  const [selected, setSelected] = useState(null)
  const [noteContent, setNoteContent] = useState('')
  const [busy, setBusy] = useState('')
  const [trashAsk, setTrashAsk] = useState(false)
  const [checked, setChecked] = useState([]) // batch selection (paths)
  const [batchTrashAsk, setBatchTrashAsk] = useState(false)
  const [inboxView, setInboxView] = useState('notes') // notes | radar | capture
  const [radarItems, setRadarItems] = useState([])
  const [radarBusy, setRadarBusy] = useState('')
  const [radarMsg, setRadarMsg] = useState(null)
  const [captureItems, setCaptureItems] = useState([])
  const [captureMsg, setCaptureMsg] = useState(null)
  const canReview = selected && selected.status === 'inbox'

  // 手機收錄通道：手機丟進 vault 01_Inbox/ 的網址，掃出來一鍵帶入收錄。
  async function refreshCapture(silent = false) {
    if (!paths.root) return
    try {
      const r = await apiFetch(`/app/capture-inbox?${new URLSearchParams({ vault_root: paths.root })}`)
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || '掃描 01_Inbox 失敗')
      setCaptureItems(d.items || [])
      if (!silent) setCaptureMsg({ type: 'ok', message: `01_Inbox 找到 ${d.total} 條待收網址` })
    } catch (e) { setCaptureMsg({ type: 'error', message: e.message }) }
  }
  useEffect(() => { if (ready) refreshCapture(true) }, [ready, paths.root]) // eslint-disable-line react-hooks/exhaustive-deps

  async function captureDismiss(ids) {
    try {
      await postJson('/app/capture-inbox-dismiss', { ids })
      setCaptureItems((arr) => arr.filter((c) => !ids.includes(c.id)))
    } catch (e) { setCaptureMsg({ type: 'error', message: e.message }) }
  }

  function adoptCapture(item) {
    onAdopt?.(item.url, item.kind)
    captureDismiss([item.id])
  }

  const [captureBusy, setCaptureBusy] = useState('')
  async function convertPdfCapture(item) {
    setCaptureBusy(item.id)
    try {
      const d = await postJson('/app/capture-pdf-convert', { vault_root: paths.root, file: item.file })
      setCaptureItems((arr) => arr.filter((c) => c.id !== item.id))
      setCaptureMsg({ type: 'ok', message: `已轉為筆記：${d.title}（原檔移至 ${d.attachment}）` })
    } catch (e) { setCaptureMsg({ type: 'error', message: e.message }) }
    finally { setCaptureBusy('') }
  }

  async function refreshRadar(silent = false) {
    try {
      const r = await apiFetch(`/app/radar`)
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || '讀取雷達候選失敗')
      setRadarItems(d.candidates || [])
      if (!silent) setRadarMsg({ type: 'ok', message: `候選 ${d.total} 筆` })
    } catch (e) { setRadarMsg({ type: 'error', message: e.message }) }
  }
  useEffect(() => { if (ready) refreshRadar(true) }, [ready]) // eslint-disable-line react-hooks/exhaustive-deps

  async function scanRadar() {
    setRadarBusy('scan'); setRadarMsg({ type: 'info', message: '掃描新聞來源中…' })
    try {
      const t = { ...defaultRadarTuning(), ...(settings.radarTuning || {}) }
      const data = await postJson('/app/radar-scan', {
        feeds: settings.radarFeeds || [],
        tuning: {
          total_cap: t.totalCap, per_source_cap: t.perSourceCap,
          hn_min_points: t.hnMinPoints, gh_min_stars: t.ghMinStars,
          keywords: t.keywords, enable_hn: t.enableHn,
          enable_github: t.enableGithub, enable_rss: t.enableRss,
        },
      })
      const errorNote = (data.errors || []).length ? `；來源異常：${data.errors.join('、')}` : ''
      setRadarMsg({ type: 'ok', message: `本次新增 ${data.added} 筆（候選共 ${data.total}）${errorNote}` })
      await refreshRadar(true)
    } catch (e) { setRadarMsg({ type: 'error', message: e.message }) } finally { setRadarBusy('') }
  }

  async function radarDismiss(ids) {
    try {
      await postJson('/app/radar-dismiss', { ids })
      setRadarItems((arr) => arr.filter((c) => !ids.includes(c.id)))
      setRadarSelected((cur) => (cur && ids.includes(cur.id) ? null : cur))
    } catch (e) { setRadarMsg({ type: 'error', message: e.message }) }
  }

  function adoptCandidate(candidate) {
    onAdopt?.(candidate.url, 'article')
    radarDismiss([candidate.id])
  }

  // 新聞台模式：點候選→右側即讀，讀完就地收藏（reviewed，不再過收件匣）
  const [radarSelected, setRadarSelected] = useState(null)
  const [radarPreview, setRadarPreview] = useState(null) // {state, title, text, site, author, date, existing, message}
  const [radarEst, setRadarEst] = useState(null)

  const [radarLang, setRadarLang] = useState('orig') // orig | zh
  const [radarZh, setRadarZh] = useState('')
  const [radarTransBusy, setRadarTransBusy] = useState(false)

  async function showRadarZh() {
    if (radarZh) { setRadarLang('zh'); return }
    if (radarPreview?.state !== 'ok') return
    setRadarTransBusy(true)
    try {
      const data = await postJson('/app/free-translate', { text: radarPreview.text })
      setRadarZh(data.translated || '')
      setRadarLang('zh')
    } catch (e) {
      setRadarMsg({ type: 'error', message: e.message })
    } finally { setRadarTransBusy(false) }
  }

  async function selectCandidate(candidate) {
    setRadarSelected(candidate)
    setRadarPreview({ state: 'loading' })
    setRadarEst(null)
    setRadarLang('orig'); setRadarZh('')
    try {
      const data = await postJson('/app/article-fetch', { url: candidate.url, vault_path: paths.root })
      if (!data.ok) {
        setRadarPreview({ state: 'fail', message: data.message || '抓不到正文', existing: data.existing })
        return
      }
      setRadarPreview({ state: 'ok', ...data })
      try { setRadarEst((await postJson('/app/estimate-text', { text: data.text || '' })).quick) } catch { setRadarEst(null) }
    } catch (e) {
      setRadarPreview({ state: 'fail', message: e.message })
    }
  }

  async function quickSave() {
    if (!radarSelected || radarPreview?.state !== 'ok') return
    setRadarBusy('save'); setRadarMsg({ type: 'info', message: 'AI 摘要＋收藏入庫中…' })
    try {
      const title = radarPreview.title || radarSelected.title
      const summarized = await postJson('/summarize', {
        title, transcript_en: radarPreview.text, mode: 'quick', source_url: radarSelected.url, kind: 'article',
      })
      const summary = summarized.summary || {}
      const saved = await postJson('/app/article-save', {
        url: radarSelected.url, title, content: radarPreview.text,
        ai_summary: summary, ai_mode: 'quick', manual_summary: '',
        author: radarPreview.author || '', published: radarPreview.date || '',
        vault_path: paths.root, note_status: 'reviewed',
      })
      setRadarMsg({ type: 'ok', message: `已收藏入庫（已標已消化）：${saved.relative_path}——可在筆記庫閱讀/搜尋` })
      radarDismiss([radarSelected.id])
    } catch (e) {
      setRadarMsg({ type: 'error', message: `收藏失敗：${e.message}` })
    } finally { setRadarBusy('') }
  }

  function setCount(list) { setItems(list); onCount?.(list.length) }

  // silent: refresh the list without clobbering an action's result message.
  async function refresh(silent = false) {
    if (!paths.root) return
    setBusy('scan')
    try {
      const r = await apiFetch(`/app/inbox?${new URLSearchParams({ vault_root: paths.root })}`)
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || '讀取收件匣失敗')
      setCount(d.items || [])
      if (!silent) setStatus({ type: 'ok', message: `待消化 ${d.total} 筆` })
    } catch (e) { setStatus({ type: 'error', message: e.message }) } finally { setBusy('') }
  }
  useEffect(() => { if (ready) refresh() }, [paths.root, ready]) // eslint-disable-line react-hooks/exhaustive-deps

  // Keyboard digestion flow: j/k navigate, e mark reviewed, d open trash gate.
  // Only while this tab is shown and focus is not in a form field.
  useEffect(() => {
    if (!active || inboxView !== 'notes') return undefined
    function onKey(event) {
      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (!['j', 'k', 'e', 'd'].includes(event.key) || event.ctrlKey || event.metaKey || event.altKey) return
      event.preventDefault()
      const index = selected ? items.findIndex((x) => x.path === selected.path) : -1
      if (event.key === 'j') { const next = items[Math.min(index + 1, items.length - 1)]; if (next && next !== selected) open(next) }
      if (event.key === 'k') { const prev = items[Math.max(index - 1, 0)]; if (prev && prev !== selected) open(prev) }
      if (event.key === 'e' && selected && selected.status === 'inbox') act('review')
      if (event.key === 'd' && selected) setTrashAsk(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }) // re-bind each render so handlers see current items/selected

  async function open(item) {
    setSelected(item); setNoteContent(''); setTrashAsk(false); setBusy('load')
    try {
      const params = new URLSearchParams({ vault_path: paths.root, note_relpath: item.path })
      const r = await apiFetch(`/app/note-detail?${params.toString()}`)
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || '讀取筆記失敗')
      setNoteContent(d.content || '')
    } catch (e) { setStatus({ type: 'error', message: e.message }) } finally { setBusy('') }
  }

  async function saveThought(text, distill) {
    setBusy('thought')
    try {
      await postJson('/app/note-thought', { vault_path: paths.root, note_relpath: selected.path, text, distill })
      setStatus({ type: 'ok', message: distill ? '已補心得並標記可提取（前一版已備份）' : '已補心得（前一版已備份）' })
      await open(selected)
      return true
    } catch (e) { setStatus({ type: 'error', message: e.message }); return false } finally { setBusy('') }
  }

  async function act(kind) {
    if (!selected) return
    setBusy(kind)
    try {
      const data = await postJson(kind === 'review' ? '/app/inbox-review' : '/app/inbox-trash', {
        vault_root: paths.root, note_relpath: selected.path, confirm: kind === 'trash',
      })
      setStatus({ type: 'ok', message: kind === 'review' ? `已標記消化：${selected.title}` : `已移到垃圾桶：${data.trashed_to}（可從該資料夾救回）` })
      setCount(items.filter((x) => x.path !== selected.path))
      setChecked((arr) => arr.filter((p) => p !== selected.path))
      setSelected(null); setNoteContent(''); setTrashAsk(false)
    } catch (e) { setStatus({ type: 'error', message: e.message }) } finally { setBusy('') }
  }

  async function batchAct(kind) {
    const targets = items.filter((x) => checked.includes(x.path) && (kind === 'trash' || x.status === 'inbox'))
    const skipped = checked.length - targets.length
    setBusy(kind)
    let done = 0
    try {
      for (const item of targets) {
        await postJson(kind === 'review' ? '/app/inbox-review' : '/app/inbox-trash', {
          vault_root: paths.root, note_relpath: item.path, confirm: kind === 'trash',
        })
        done += 1
      }
      setStatus({
        type: 'ok',
        message: `${kind === 'review' ? '批次標記已消化' : '批次移到垃圾桶'} ${done} 筆${skipped > 0 ? `（略過 ${skipped} 筆無 status 欄）` : ''}`,
      })
    } catch (e) {
      setStatus({ type: 'error', message: `批次處理中斷（已完成 ${done} 筆）：${e.message}` })
    } finally {
      setBusy(''); setChecked([]); setBatchTrashAsk(false); setSelected(null); setNoteContent('')
      refresh(true)
    }
  }

  function toggleChecked(path) {
    setChecked((arr) => (arr.includes(path) ? arr.filter((p) => p !== path) : [...arr, path]))
  }

  const grouped = items.reduce((acc, r) => { (acc[r.source] = acc[r.source] || []).push(r); return acc }, {})
  const allChecked = items.length > 0 && checked.length === items.length

  return (
    <div className="workbench inbox-workbench">
      <section className="command-bar library-command" aria-label="inbox status">
        <div className="command-main">
          <div className="command-kicker">待消化</div>
          <div className="command-title">{selected?.title || '待消化筆記'}</div>
          <div className="command-meta">
            <span className="state-chip info"><Inbox size={13} /> {items.length} 筆待消化</span>
            <span className="state-chip neutral">只動 frontmatter，不碰內文</span>
            {busy && <span className="state-chip info">{busy === 'scan' ? '掃描中' : busy === 'load' ? '載入中' : '處理中'}</span>}
          </div>
        </div>
        <div className="command-actions">
          <button className="ghost" onClick={refresh} disabled={busy === 'scan' || !paths.root}>重新掃描筆記</button>
        </div>
      </section>

      <div className="library-toolbar">
        <div className="tabs-mini" role="group" aria-label="收件匣檢視">
          <button className={inboxView === 'notes' ? 'active' : ''} aria-pressed={inboxView === 'notes'} onClick={() => setInboxView('notes')}><FileText size={14} />待消化筆記<span className="cnt">{items.length}</span></button>
          <button className={inboxView === 'capture' ? 'active' : ''} aria-pressed={inboxView === 'capture'} onClick={() => setInboxView('capture')}><Inbox size={14} />手機收錄<span className="cnt">{captureItems.length}</span></button>
          <button className={inboxView === 'radar' ? 'active' : ''} aria-pressed={inboxView === 'radar'} onClick={() => setInboxView('radar')}><Radar size={14} />新聞雷達<span className="cnt">{radarItems.length}</span></button>
        </div>
        {inboxView === 'radar' && (
          <>
            <button className="primary" onClick={scanRadar} disabled={radarBusy === 'scan'}>{radarBusy === 'scan' ? '掃描中…' : '掃描新聞來源'}</button>
            {radarItems.length > 0 && (
              <button className="ghost danger-ghost" onClick={() => radarDismiss(radarItems.map((c) => c.id))}>全部忽略</button>
            )}
          </>
        )}
        {inboxView === 'capture' && (
          <>
            <button className="primary" onClick={() => refreshCapture()} disabled={!paths.root}>重新掃描 01_Inbox</button>
            {captureItems.length > 0 && (
              <button className="ghost danger-ghost" onClick={() => captureDismiss(captureItems.map((c) => c.id))}>全部忽略</button>
            )}
          </>
        )}
      </div>

      <StatusMessage status={inboxView === 'notes' ? status : inboxView === 'radar' ? radarMsg : captureMsg} className="workbench-alert" />

      {inboxView === 'radar' ? (
      <div className="library-frame">
        <section className="panel library-list-panel">
          <div className="panel-head">
            <div>
              <Radar size={16} />
              <h3>候選（{radarItems.length}）</h3>
            </div>
            <span className="state-chip neutral">點選候選即讀</span>
          </div>
          {radarItems.length === 0 ? (
            <div className="empty-surface library-empty">
              <Radar size={22} />
              <span>還沒有候選。按「掃描新聞來源」抓一輪——HN 熱門、GitHub 90 天內新專案、官方部落格 RSS。</span>
            </div>
          ) : (
            <div className="library-list-scroll" aria-label="雷達候選清單">
              {radarItems.map((c) => (
                <button key={c.id} className={`list-item radar-item ${radarSelected?.id === c.id ? 'active' : ''}`}
                  onClick={() => selectCandidate(c)} aria-pressed={radarSelected?.id === c.id}>
                  <SourceGlyph type="article" />
                  <span className="li-main">
                    <span className="li-title">{c.important && <span className="state-chip warn">重要</span>}{c.title}</span>
                    <span className="li-snippet">{c.source}{c.heat ? `・${c.heat}` : ''}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="panel library-detail-panel">
          <div className="panel-head">
            <div>
              <FileText size={16} />
              <h3>即讀與裁決</h3>
            </div>
            <span className={`state-chip ${radarSelected ? 'ok' : 'neutral'}`}>{radarSelected ? radarSelected.source : '未選'}</span>
          </div>
          {!radarSelected ? (
            <div className="empty-surface library-empty">
              <FileText size={22} />
              <span>左側選一則 → 這裡直接讀正文 → 讀完就地「收藏入庫」或「忽略」。收藏的會直接標已消化，不再經過收件匣。</span>
            </div>
          ) : (
            <div className="note-detail library-detail">
              <div className="read-view">
                <h4 className="read-title">{radarPreview?.title || radarSelected.title}</h4>
                <div className="read-meta">
                  <span className="li-type">{radarSelected.source}</span>
                  {radarSelected.heat && <span className="li-type">{radarSelected.heat}</span>}
                  {radarPreview?.existing && <span className="state-chip info">已存過，收藏＝更新</span>}
                </div>
                <a className="read-source" href={radarSelected.url} target="_blank" rel="noreferrer">
                  <Globe size={14} /><span>{radarSelected.url}</span><PlayCircle size={14} />
                </a>
              </div>
              {radarPreview?.state === 'loading' && (
                <div className="settings-state info"><Eye size={15} /><span>抓取正文中…</span></div>
              )}
              {radarPreview?.state === 'fail' && (
                <div className="settings-state info"><AlertTriangle size={15} /><span>{radarPreview.message}——可「細修收錄」改用貼上備援，或開原文閱讀。</span></div>
              )}
              {radarPreview?.state === 'ok' && (
                <>
                  <div className="reader-toolbar">
                    <div className="tabs-mini" role="group" aria-label="預覽語言">
                      <button className={radarLang === 'orig' ? 'active' : ''} aria-pressed={radarLang === 'orig'} onClick={() => setRadarLang('orig')}>原文</button>
                      <button className={radarLang === 'zh' ? 'active' : ''} aria-pressed={radarLang === 'zh'} onClick={showRadarZh} disabled={radarTransBusy}>
                        {radarTransBusy ? '翻譯中…' : '中文（免費翻譯）'}
                      </button>
                    </div>
                    <span className="muted">免費翻譯供判讀；收藏存原文，AI 摘要為繁中</span>
                  </div>
                  <div className="radar-read">{radarLang === 'zh' && radarZh ? radarZh : radarPreview.text}</div>
                </>
              )}
              <div className="row end">
                <button className="ghost danger-ghost" onClick={() => radarDismiss([radarSelected.id])}><Trash2 size={15} />忽略</button>
                <button className="ghost" onClick={() => adoptCandidate(radarSelected)} title="帶入「收錄→文章網址」細修欄位">細修收錄</button>
                <button className="primary gated-action" onClick={quickSave}
                  disabled={radarBusy === 'save' || radarPreview?.state !== 'ok'}
                  title="AI 摘要後存入筆記庫，標記已消化">
                  <Save size={16} />{radarBusy === 'save' ? '收藏中…' : `一鍵收藏入庫${radarEst ? `（≈$${radarEst.estimated_usd}）` : ''}`}
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
      ) : inboxView === 'capture' ? (
      <div className="library-frame capture-frame">
        <section className="panel">
          <div className="panel-head">
            <div>
              <Inbox size={16} />
              <h3>待收網址（{captureItems.length}）</h3>
            </div>
            <span className="state-chip neutral">你的檔案不動；帶入或忽略後不再出現</span>
          </div>
          {captureItems.length === 0 ? (
            <div className="empty-surface library-empty">
              <Inbox size={22} />
              <span>沒有待收網址。手機端用 Obsidian／備忘錄把連結存進 vault 的 01_Inbox/，這裡掃出來一鍵帶入收錄。</span>
            </div>
          ) : (
            <div className="library-list-scroll" aria-label="待收網址清單">
              {captureItems.map((c) => (
                <div key={c.id} className="capture-row">
                  <span className="li-type">{c.kind === 'video' ? '影片' : c.kind === 'pdf' ? 'PDF' : '文章'}</span>
                  <span className="li-main">
                    <span className="li-title">{c.kind === 'pdf' ? c.hint : c.url}</span>
                    <span className="li-snippet">{c.file}{c.hint && c.hint !== c.url && c.kind !== 'pdf' ? `｜${c.hint}` : ''}</span>
                  </span>
                  {c.kind === 'pdf' ? (
                    <button className="primary" disabled={captureBusy === c.id} onClick={() => convertPdfCapture(c)}>
                      {captureBusy === c.id ? '轉換中…' : '轉為筆記'}
                    </button>
                  ) : (
                    <button className="primary" onClick={() => adoptCapture(c)}>帶入收錄</button>
                  )}
                  <button className="ghost danger-ghost" onClick={() => captureDismiss([c.id])}>忽略</button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
      ) : (
      <div className="library-frame">
        <section className="panel library-list-panel">
          <div className="panel-head">
            <div>
              <Inbox size={16} />
              <h3>待消化（{items.length}）</h3>
            </div>
            {items.length > 0 && (
              <button className="ghost" onClick={() => setChecked(allChecked ? [] : items.map((x) => x.path))}>
                {allChecked ? '清除勾選' : '全選'}
              </button>
            )}
          </div>
          {checked.length > 0 && (
            batchTrashAsk ? (
              <div className="ac-gate ac-warn">
                <span>確定把勾選的 {checked.length} 筆全部移到垃圾桶（{TRASH_HINT}）？可手動救回。</span>
                <div className="row end">
                  <button className="ghost" onClick={() => setBatchTrashAsk(false)}>取消</button>
                  <button className="primary" onClick={() => batchAct('trash')} disabled={!!busy}>確認批次移動</button>
                </div>
              </div>
            ) : (
              <div className="batch-bar">
                <span className="state-chip info">已勾選 {checked.length} 筆</span>
                <button className="primary" onClick={() => batchAct('review')} disabled={!!busy}><CheckCheck size={15} />批次標記已消化</button>
                <button className="ghost danger-ghost" onClick={() => setBatchTrashAsk(true)} disabled={!!busy}><Trash2 size={15} />批次刪除</button>
              </div>
            )
          )}
          {!paths.root ? (
            <div className="empty-surface library-empty">
              <Inbox size={22} />
              <span>尚未設定筆記庫根目錄，指定後即可消化收件匣。</span>
              <button className="primary" onClick={() => onGo?.('settings')}><Settings size={15} />前往設定</button>
            </div>
          ) : items.length === 0 ? (
            <div className="empty-surface library-empty">
              <CheckCheck size={22} />
              <span>收件匣已清空，沒有待消化的筆記。</span>
            </div>
          ) : (
            <div className="library-list-scroll" aria-label="待消化清單">
              {Object.entries(grouped).map(([group, groupItems]) => (
                <div key={group} className="cat-group">
                  <div className="cat-label">{group}（{groupItems.length}）</div>
                  {groupItems.map((item) => (
                    <div key={item.path} className="inbox-row">
                      <input
                        type="checkbox"
                        aria-label={`勾選 ${item.title}`}
                        checked={checked.includes(item.path)}
                        onChange={() => toggleChecked(item.path)}
                      />
                      <SourceGlyph type={sourceTypeFromPath(item.path)} />
                      <button className={`list-item ${selected?.path === item.path ? 'active' : ''}`}
                        onClick={() => open(item)} aria-pressed={selected?.path === item.path}>
                        <span className="li-title">{item.title}</span>
                        <span className="li-type">{item.date ? item.date.slice(0, 10) : item.status}</span>
                      </button>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel library-detail-panel">
          <div className="panel-head">
            <div>
              <FileText size={16} />
              <h3>筆記內容</h3>
            </div>
            <span className={`state-chip ${selected ? 'ok' : 'neutral'}`}>{selected ? (selected.status === 'no_status' ? '無狀態欄' : selected.status) : '未選取'}</span>
          </div>
          {selected ? (
            <div className="note-detail library-detail">
              <div className="detail-path">{selected.path}{busy === 'load' ? '｜載入中...' : ''}</div>
              {noteContent && (
                <NoteReader content={noteContent}
                  assetUrl={(src) => `${API}/app/note-asset?${new URLSearchParams({ vault_path: paths.root, note_relpath: selected.path, src })}`} />
              )}
              <ThoughtBox key={selected.path} onSave={saveThought} busy={busy === 'thought'} />
              {trashAsk ? (
                <div className="ac-gate ac-warn">
                  <span>確定把《{selected.title}》移到垃圾桶（{TRASH_HINT}）？檔案不會被刪除，可手動救回。</span>
                  <div className="row end">
                    <button className="ghost" onClick={() => setTrashAsk(false)}>取消</button>
                    <button className="primary" onClick={() => act('trash')} disabled={busy === 'trash'}>{busy === 'trash' ? '移動中...' : '確認移到垃圾桶'}</button>
                  </div>
                </div>
              ) : (
                <div className="row end">
                  <button className="ghost danger-ghost" onClick={() => setTrashAsk(true)}><Trash2 size={15} />刪除</button>
                  <button className="primary" onClick={() => act('review')} disabled={!canReview || busy === 'review'}
                    title={canReview ? '寫回 status: reviewed' : '此筆記沒有 status: inbox 欄位，請直接整理原檔或刪除'}>
                    <CheckCheck size={16} />{busy === 'review' ? '寫回中...' : '標記已消化'}
                  </button>
                </div>
              )}
            </div>
          ) : (
            <div className="empty-surface library-empty">
              <FileText size={22} />
              <span>從左側選一篇閱讀，確認後標記已消化或刪除。</span>
            </div>
          )}
        </section>
      </div>
      )}
      <footer className="status-strip">
        <span><FolderOpen size={13} /> {paths.root || '尚未設定筆記庫根目錄'}</span>
        <span><Inbox size={13} /> 待消化 {items.length} 筆</span>
        <span>鍵盤：j/k 上下｜e 消化｜d 刪除</span>
        <span><ShieldCheck size={13} /> 消化＝改 frontmatter；刪除＝移到 {TRASH_HINT}</span>
      </footer>
    </div>
  )
}
