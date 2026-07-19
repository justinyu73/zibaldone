import { useEffect, useRef, useState } from 'react'
import {
  BookOpen, FileAudio, FileText, FolderOpen, Library, Pencil, Save, Search, Settings,
  ShieldCheck, X,
} from 'lucide-react'
import { deriveVaultPaths } from '../../paths'
import SourceGlyph, { sourceTypeFromPath } from '../../components/SourceGlyph'
import NoteReader from '../../NoteReader'
import { API, apiFetch, postJson } from '../../app/api'
import StatusMessage from '../../components/status/StatusMessage'
import NoteFields from '../../components/note/NoteFields'
import ThoughtBox from '../../components/note/ThoughtBox'
import RelatedBox from '../../components/note/RelatedBox'
import ReadView from '../../components/note/ReadView'
import useMeetingAudioSource from '../meetings/useMeetingAudioSource'
import { tsToSeconds } from '../meetings/timestamp'
import { draftToAiSummary, emptyDraft } from '../../app/noteDraft'

const INDEX_NAME = '_youtube_index.json'

// obsidian:// deep link — assumes the Obsidian vault is opened at the configured
// vault root, so vault name = root folder basename (JY setup: notes-vault).
function obsidianUri(vaultPath, relpath) {
  if (!vaultPath || !relpath) return ''
  const name = String(vaultPath).replace(/[\\/]+$/, '').split(/[\\/]/).pop()
  return `obsidian://open?vault=${encodeURIComponent(name)}&file=${encodeURIComponent(relpath)}`
}

async function openInObsidian(vaultPath, relpath) {
  const uri = obsidianUri(vaultPath, relpath)
  if (!uri) return
  try {
    const { open } = await import('@tauri-apps/plugin-shell')
    await open(uri)
  } catch {
    window.open(uri)
  }
}

export default function LibraryView({ settings, onGo, ready = true }) {
  const paths = deriveVaultPaths(settings.vaultRoot)
  const extras = settings.libraryFolders || []
  const [query, setQuery] = useState('')
  const [records, setRecords] = useState([])
  const [status, setStatus] = useState(null)
  const [selected, setSelected] = useState(null)
  const [draft, setDraft] = useState(emptyDraft())
  const [busy, setBusy] = useState('')
  const [mode, setMode] = useState('read') // read → editConfirm → edit → saveConfirm
  const [sort, setSort] = useState('recency') // value-library: recency | relevance
  const [noteContent, setNoteContent] = useState('') // raw md for the reading view
  const [view, setView] = useState('reader') // read mode: reader (HTML) | fields
  const [libMode, setLibMode] = useState('value') // value=全庫唯讀 | youtube=單庫可編輯
  const [sourceFilter, setSourceFilter] = useState('all') // value-library source category
  const [detailVideoId, setDetailVideoId] = useState('') // from note frontmatter（全庫模式編輯入口）
  const [vaultFolders, setVaultFolders] = useState([]) // derived 02_Sources/* aggregation set
  const [meetingMeta, setMeetingMeta] = useState(null)
  const libraryAudioRef = useRef(null)
  const libraryAudioSrc = useMeetingAudioSource(meetingMeta?.audio_exists ? meetingMeta.audio_path : '')

  const valueMode = libMode === 'value'
  const valueFolders = [...new Set([...vaultFolders.map((f) => f.path), ...extras])]

  async function search(sortArg, foldersArg) {
    const folders = foldersArg || valueFolders
    if (valueMode && folders.length === 0) return setStatus({ type: 'error', message: '請先在「設定」指定筆記庫根目錄（或額外價值庫資料夾）' })
    if (!valueMode && !paths.youtube) return setStatus({ type: 'error', message: '請先在「設定」指定筆記庫根目錄' })
    const sortMode = sortArg || sort
    setBusy('search'); setStatus({ type: 'info', message: '搜尋中...' })
    try {
      if (valueMode && query.trim() && paths.root) {
        // Full-text search (FTS5, CJK substring) over the vault root; extra
        // folders outside the root still rely on the aggregation filter below.
        const params = new URLSearchParams({ vault_root: paths.root, query, limit: '100' })
        const response = await apiFetch(`/app/search?${params.toString()}`)
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail?.message || data.detail || '搜尋失敗')
        setRecords((data.records || []).map((r) => ({ ...r, vault_path: paths.root })))
        setStatus({ type: 'ok', message: `全文搜尋 ${data.total || 0} 筆（含內文比對）` })
      } else if (valueMode) {
        const params = new URLSearchParams({ folders: folders.join('|'), query, sort: sortMode, limit: '300' })
        const response = await apiFetch(`/app/value-library?${params.toString()}`)
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail?.message || data.detail || '搜尋失敗')
        setRecords(data.records || [])
        setStatus({ type: 'ok', message: `價值庫 ${data.total || 0} 筆` })
      } else {
        const params = new URLSearchParams({ workspace_root: paths.youtube, index_path: INDEX_NAME, query, limit: '100' })
        const response = await apiFetch(`/app/local-library/read-model?${params.toString()}`)
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail?.message || data.detail || '搜尋失敗')
        setRecords(data.read_model?.records || [])
        setStatus({ type: 'ok', message: `${data.read_model?.record_count || 0} 筆，符合 ${data.read_model?.matched_count || 0} 筆` })
      }
    } catch (error) {
      if (/does not exist/i.test(error.message)) {
        setRecords([])
        setStatus({ type: 'info', message: '筆記資料夾尚未建立（第一次存入時會自動建立）。若路徑看起來不對，請到「設定」檢查筆記庫根目錄。' })
      } else {
        setStatus({ type: 'error', message: `搜尋失敗：${error.message}（可按「搜尋」重試）` })
      }
    } finally { setBusy('') }
  }

  // Load the derived 02_Sources/* aggregation set, then run the first search.
  useEffect(() => {
    let cancelled = false
    async function init() {
      let folders = []
      if (paths.root) {
        try {
          const r = await apiFetch(`/app/vault-folders?${new URLSearchParams({ vault_root: paths.root })}`)
          const d = await r.json()
          folders = r.ok ? d.folders || [] : []
        } catch { folders = [] }
      }
      if (cancelled) return
      setVaultFolders(folders)
      const merged = [...new Set([...folders.map((f) => f.path), ...extras])]
      if (valueMode ? merged.length : paths.youtube) search(undefined, valueMode ? merged : undefined)
    }
    if (ready) init()
    return () => { cancelled = true }
  }, [paths.root, extras.join('|'), libMode, ready]) // eslint-disable-line react-hooks/exhaustive-deps

  // Bind note-detail / note-asset to the vault ROOT when possible so the reading
  // view can resolve vault-level _attachments images.
  function notePathParams(rec) {
    const base = rec.vault_path || paths.youtube
    if (paths.root && base && base.startsWith(paths.root)) {
      const prefix = base.slice(paths.root.length).replace(/^\//, '')
      return { vault_path: paths.root, note_relpath: prefix ? `${prefix}/${rec.path}` : rec.path }
    }
    return { vault_path: base, note_relpath: rec.path }
  }

  async function openRecord(rec) {
    setSelected(rec); setMode('read'); setNoteContent(''); setDetailVideoId(''); setMeetingMeta(null)
    setDraft({ ...emptyDraft(), title: rec.title || '', content_category: rec.category || 'AI LLM' })
    setBusy('load')
    try {
      const params = new URLSearchParams(notePathParams(rec))
      const response = await apiFetch(`/app/note-detail?${params.toString()}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '讀取筆記失敗')
      setNoteContent(data.content || '')
      setMeetingMeta(data.meeting?.is_meeting ? data.meeting : null)
      const f = data.fields || {}
      setDetailVideoId(f.video_id || '')
      setDraft((d) => ({
        ...d,
        title: f.title || d.title,
        explicit_topic: f.explicit_topic || '', key_points: f.key_points || '', terms: f.terms || '',
        content_value: f.content_value || '', source_platform: f.source_platform || 'YT',
        content_category: f.content_category || d.content_category,
      }))
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  function seekLibraryAudio(ts) {
    const seconds = tsToSeconds(ts)
    if (seconds == null || !libraryAudioRef.current) return
    libraryAudioRef.current.currentTime = seconds
    libraryAudioRef.current.play().catch(() => {})
  }

  async function repairMeetingAudio() {
    if (!selected) return
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const file = await open({
        multiple: false,
        title: '重新指定會議音檔',
        filters: [{ name: '音檔', extensions: ['mp3', 'm4a', 'wav', 'webm', 'ogg', 'mp4'] }],
      })
      if (typeof file !== 'string' || !file) return
      setBusy('repair')
      await postJson('/app/meeting-audio-repair', { ...notePathParams(selected), audio_path: file })
      setStatus({ type: 'ok', message: '音檔來源已修復（前一版已備份）' })
      await openRecord(selected)
    } catch (error) {
      setStatus({ type: 'error', message: error.message || '音檔選擇器只在桌面版可用' })
    } finally { setBusy('') }
  }

  // Editable when in the dedicated YouTube mode, or when an opened 全庫 note is
  // a YouTube note (frontmatter video_id) living in the youtube library folder.
  const selectedInYoutube = !!selected && (selected.vault_path || paths.youtube) === paths.youtube
  const canEditSelected = !valueMode || (!!detailVideoId && selectedInYoutube)

  async function saveThought(text, distill) {
    setBusy('thought')
    try {
      await postJson('/app/note-thought', { ...notePathParams(selected), text, distill })
      setStatus({ type: 'ok', message: distill ? '已補心得並標記可提取（前一版已備份）' : '已補心得（前一版已備份）' })
      await openRecord(selected)
      return true
    } catch (e) { setStatus({ type: 'error', message: e.message }); return false } finally { setBusy('') }
  }

  async function saveEdit() {
    if (!selected) return
    const videoId = detailVideoId || selected.canonical_id || selected.source_id
    setBusy('save'); setStatus({ type: 'info', message: '寫回筆記（前一版備份中）...' })
    try {
      const data = await postJson('/app/vault-note-edit', {
        vault_path: paths.youtube, subfolder: '', video_id: videoId,
        title: draft.title, ai_summary: draftToAiSummary(draft), ai_mode: 'quick',
        manual_summary: draft.manual_summary,
      })
      setStatus({ type: 'ok', message: `已寫回：${data.relative_path}${data.rollback_available ? '（前一版已備份，可還原）' : ''}` })
      setMode('read'); search()
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  const sourceCounts = records.reduce((acc, record) => {
    const source = record.source || '其他'
    acc[source] = (acc[source] || 0) + 1
    return acc
  }, {})
  const sourceOptions = [...new Set([
    ...vaultFolders.map((folder) => folder.name),
    ...extras.map((folder) => String(folder).replace(/[\\/]+$/, '').split(/[\\/]/).pop()),
    ...Object.keys(sourceCounts),
  ].filter(Boolean))].sort((a, b) => a.localeCompare(b))
  const sourceLinks = sourceOptions.filter((source) => sourceCounts[source] > 0)
  const visibleRecords = valueMode && sourceFilter !== 'all'
    ? records.filter((record) => (record.source || '其他') === sourceFilter)
    : records
  const grouped = visibleRecords.reduce((acc, r) => {
    const k = valueMode ? (r.source || '其他') : (r.category || '未分類'); (acc[k] = acc[k] || []).push(r); return acc
  }, {})
  const groupCount = Object.keys(grouped).length
  const selectedTitle = selected?.title || selected?.canonical_id || '尚未選取筆記'
  const libraryModeLabel = valueMode ? '跨來源價值庫' : 'YouTube 筆記庫'
  const emptyMessage = !paths.root && valueFolders.length === 0
    ? '尚未設定筆記庫根目錄，請到「設定」指定後再查閱。'
    : valueMode
      ? sourceFilter !== 'all'
        ? `「${sourceFilter}」分類目前沒有符合的筆記或關鍵字。`
        : '價值庫沒有可顯示的筆記，確認筆記庫根目錄下的 02_Sources 內容。'
      : query
        ? '查無符合的筆記，換個關鍵字試試。'
      : '這個資料夾還沒有影片筆記，先到「收錄」收一篇。'

  function selectSource(source) {
    setSourceFilter(source)
    setSelected(null)
  }

  return (
    <div className="workbench library-workbench">
      <section className="command-bar library-command" aria-label="library search">
        <div className="command-main">
          <div className="command-kicker">筆記庫</div>
          <div className="command-title" title={selectedTitle}>{selectedTitle}</div>
          <div className="command-meta">
            <span className="state-chip info"><Library size={13} /> {libraryModeLabel}</span>
            <span className="state-chip neutral">{sourceFilter === 'all' || !valueMode ? records.length : `${visibleRecords.length} / ${records.length}`} 筆</span>
            <span className="state-chip neutral">{groupCount} 組</span>
            {busy && <span className="state-chip info">{busy === 'search' ? '搜尋中' : busy === 'load' ? '載入中' : '寫回中'}</span>}
          </div>
        </div>
        <div className="command-input library-search">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="關鍵字（標題 / 關鍵詞 / 路徑）"
            aria-label="筆記庫搜尋關鍵字"
            onKeyDown={(e) => e.key === 'Enter' && search()} />
          <button className="primary" onClick={() => search()} disabled={busy === 'search'}><Search size={16} />{busy === 'search' ? '搜尋中' : '搜尋'}</button>
          <button className="ghost icon-button" onClick={() => { setQuery(''); setRecords([]); setSelected(null); setStatus(null) }} title="清除" aria-label="清除搜尋與選取"><X size={16} /><span>清除</span></button>
        </div>
      </section>

      <StatusMessage status={status} className="workbench-alert" />

      <div className="library-frame">
        <section className="panel library-list-panel">
          <div className="panel-head">
            <div>
              <BookOpen size={16} />
              <h3>{valueMode ? '價值筆記' : '文章列表'}</h3>
            </div>
            <span className="state-chip neutral">{valueMode ? (sourceFilter === 'all' ? '依來源分組' : `來源：${sourceFilter}`) : '依分類分組'}</span>
          </div>
        <div className="library-toolbar">
          <div className="tabs-mini" role="group" aria-label="筆記庫模式">
            <button className={valueMode ? 'active' : ''} aria-pressed={valueMode} onClick={() => { setLibMode('value'); setSelected(null) }}>全庫</button>
            <button className={!valueMode ? 'active' : ''} aria-pressed={!valueMode} onClick={() => { setLibMode('youtube'); setSelected(null) }}>YouTube（可編輯）</button>
          </div>
          {valueMode ? (
            <>
              <nav className="library-source-links" aria-label="價值庫來源捷徑">
                <span className="library-source-links-label">來源分類</span>
                <button
                  type="button"
                  className={`library-source-link ${sourceFilter === 'all' ? 'active' : ''}`}
                  aria-pressed={sourceFilter === 'all'}
                  onClick={() => selectSource('all')}
                >
                  全部 <span className="source-count">{records.length}</span>
                </button>
                {sourceLinks.map((source) => (
                  <button
                    type="button"
                    key={source}
                    className={`library-source-link ${sourceFilter === source ? 'active' : ''}`}
                    aria-pressed={sourceFilter === source}
                    onClick={() => selectSource(source)}
                  >
                    {source} <span className="source-count">{sourceCounts[source]}</span>
                  </button>
                ))}
                <span className="library-source-links-hint">點選分類直接篩選</span>
              </nav>
              <label className="library-source-filter">完整分類清單
                <select aria-label="價值庫來源分類" value={sourceFilter} onChange={(event) => selectSource(event.target.value)}>
                  <option value="all">全部來源（{records.length}）</option>
                  {sourceOptions.map((source) => <option key={source} value={source}>{source}（{sourceCounts[source] || 0}）</option>)}
                </select>
              </label>
              <span className="muted">排序</span>
              <div className="tabs-mini" role="group" aria-label="價值庫排序">
                <button className={sort === 'recency' ? 'active' : ''} aria-pressed={sort === 'recency'} onClick={() => { setSort('recency'); search('recency') }}>最近</button>
                <button className={sort === 'relevance' ? 'active' : ''} aria-pressed={sort === 'relevance'} onClick={() => { setSort('relevance'); search('relevance') }}>相關度</button>
              </div>
              {sort === 'relevance' ? <span className="muted">依關鍵字 / 標籤重疊排序（需輸入關鍵字）</span> : null}
            </>
          ) : <span className="muted">單一 YouTube 筆記庫，可人工確認後修改</span>}
        </div>
          {groupCount === 0 ? (
            <div className="empty-surface library-empty">
              <Library size={22} />
              <span>{emptyMessage}</span>
              {!paths.root && valueFolders.length === 0 && (
                <button className="primary" onClick={() => onGo?.('settings')}><Settings size={15} />前往設定</button>
              )}
            </div>
          ) : (
            <div className="library-list-scroll" aria-label="筆記列表">
              {Object.entries(grouped).map(([group, items]) => (
                <div key={group} className="cat-group">
                  <div className="cat-label">{group}（{items.length}）</div>
                  {items.map((r, i) => {
                    const active = selected === r || selected?.path === r.path
                    return (
                      <button
                        key={`${r.source_id || r.path || r.title}-${i}`}
                        className={`list-item ${active ? 'active' : ''}`}
                        onClick={() => openRecord(r)}
                        aria-pressed={active}
                      >
                        <SourceGlyph type={sourceTypeFromPath(r.path || r.source_type)} />
                        <span className="li-main">
                          <span className="li-title">{r.title || r.canonical_id}</span>
                          {r.snippet && <span className="li-snippet">{r.snippet}</span>}
                        </span>
                        <span className="li-type">{valueMode ? (r.recency || '全文') : r.source_type}</span>
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel library-detail-panel">
          <div className="panel-head">
            <div>
              <FileText size={16} />
              <h3>筆記詳情</h3>
            </div>
            <span className={`state-chip ${selected ? 'ok' : 'neutral'}`}>{selected ? ({ read: '閱讀', editConfirm: '待確認', edit: '編輯中', saveConfirm: '確認寫回' }[mode] || mode) : '未選取'}</span>
          </div>
          {selected ? (
            <div className="note-detail library-detail">
              <div className="detail-path">{selected.path}{busy === 'load' ? '｜載入中...' : ''}</div>

              {mode === 'read' && (
                <>
                  <div className="reader-toolbar">
                    <div className="tabs-mini" role="group" aria-label="筆記檢視模式">
                      <button className={view === 'reader' ? 'active' : ''} aria-pressed={view === 'reader'} onClick={() => setView('reader')}>閱讀</button>
                      <button className={view === 'fields' ? 'active' : ''} aria-pressed={view === 'fields'} onClick={() => setView('fields')}>欄位</button>
                    </div>
                    <span className="muted">閱讀＝筆記原文渲染；欄位＝AI 摘要結構</span>
                    <button
                      className="ghost obsidian-open"
                      title="在 Obsidian 開啟此筆記（需以 vault 根目錄開啟 Obsidian）"
                      onClick={() => { const p = notePathParams(selected); openInObsidian(p.vault_path, p.note_relpath) }}
                    >
                      在 Obsidian 開啟
                    </button>
                  </div>
                  {view === 'reader' && noteContent ? (
                    <>
                      {meetingMeta && (
                        <div className={`meeting-evidence-bar ${meetingMeta.audio_exists ? 'ready' : 'missing'}`}>
                          <div>
                            <strong><FileAudio size={15} /> 原音證據</strong>
                            <span title={meetingMeta.audio_path}>{meetingMeta.audio_exists ? meetingMeta.audio_path : '原音檔已搬移或不存在'}</span>
                          </div>
                          <button type="button" className="ghost" onClick={repairMeetingAudio} disabled={busy === 'repair'}>
                            <FolderOpen size={15} />{meetingMeta.audio_exists ? '重新指定' : '修復路徑'}
                          </button>
                          {meetingMeta.audio_exists && (
                            <audio
                              ref={libraryAudioRef}
                              src={libraryAudioSrc}
                              controls
                              preload="none"
                            />
                          )}
                        </div>
                      )}
                      <NoteReader
                        content={noteContent}
                        assetUrl={(src) => `${API}/app/note-asset?${new URLSearchParams({ ...notePathParams(selected), src })}`}
                        onTimestamp={meetingMeta?.audio_exists ? seekLibraryAudio : undefined}
                      />
                    </>
                  ) : (
                    <ReadView draft={draft} sourceUrl={selected.source_url || (selected.canonical_id ? `https://www.youtube.com/watch?v=${selected.canonical_id}` : '')} />
                  )}
                  <ThoughtBox key={selected.path} onSave={saveThought} busy={busy === 'thought'} />
                  {notePathParams(selected).vault_path === paths.root && (
                    <RelatedBox key={`rel-${selected.path}`} params={notePathParams(selected)} onStatus={setStatus} onWritten={() => openRecord(selected)} />
                  )}
                  <div className="row end">
                    <button className="ghost" onClick={() => setSelected(null)}>關閉</button>
                    {canEditSelected && <button className="primary" onClick={() => setMode('editConfirm')} disabled={busy === 'load'}><Pencil size={16} />修改</button>}
                  </div>
                </>
              )}

              {mode === 'editConfirm' && (
                <div className="ac-gate">
                  <span>要編輯這篇筆記嗎？儲存時會再確認並自動備份前一版。</span>
                  <div className="row end">
                    <button className="ghost" onClick={() => setMode('read')}>取消</button>
                    <button className="primary" onClick={() => setMode('edit')}>確認編輯</button>
                  </div>
                </div>
              )}

              {mode === 'edit' && (
                <>
                  {/* disabled: update_ai writeback only replaces the AI block; a
                      manual-summary edit here would be silently dropped. */}
                  <NoteFields draft={draft} setDraft={setDraft} disabled />
                  <div className="row end">
                    <button className="ghost" onClick={() => setMode('read')}>取消</button>
                    <button className="primary" onClick={() => setMode('saveConfirm')}><Save size={16} />保存</button>
                  </div>
                </>
              )}

              {mode === 'saveConfirm' && (
                <div className="ac-gate ac-warn">
                  <span>將覆寫《{draft.title}》的 AI 內容，前一版會自動備份（可還原）。確認寫回？</span>
                  <div className="row end">
                    <button className="ghost" onClick={() => setMode('edit')}>返回編輯</button>
                    <button className="primary" onClick={saveEdit} disabled={busy === 'save'}>{busy === 'save' ? '寫回中...' : '確認寫回'}</button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="empty-surface library-empty">
              <FileText size={22} />
              <span>從左側列表選一篇查閱；YouTube 模式可進入人工確認後修改。</span>
            </div>
          )}
        </section>
      </div>
      <footer className="status-strip">
        <span><FolderOpen size={13} /> {valueMode ? `${valueFolders.length} 個價值庫資料夾` : paths.youtube || '尚未設定筆記庫根目錄'}</span>
        <span><Search size={13} /> {query || '未輸入關鍵字'} · {valueMode ? (sourceFilter === 'all' ? '全部來源' : sourceFilter) : 'YouTube'}</span>
        <span><ShieldCheck size={13} /> {valueMode ? '唯讀瀏覽' : '編輯需確認與備份'}</span>
      </footer>
    </div>
  )
}
