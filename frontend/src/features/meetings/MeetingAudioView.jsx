import { useEffect, useRef, useState } from 'react'
import {
  Database, Download, Eye, FileText, FolderOpen, LockKeyhole, Mic, Route, Save, ShieldCheck,
} from 'lucide-react'
import { deriveVaultPaths } from '../../paths'
import { apiFetch, postJson } from '../../app/api'
import StatusMessage from '../../components/status/StatusMessage'
import SummaryModelPicker from '../../components/model/SummaryModelPicker'
import MeetingQueue from './MeetingQueue'
import MeetingReviewEditor from './MeetingReviewEditor'
import MeetingField from './MeetingField'
import useMeetingNoteJob from './useMeetingNoteJob'
import useMeetingAudioSource from './useMeetingAudioSource'
import { tsToSeconds } from './timestamp'

const MEETING_QUEUE_KEY = 'yt_meeting_queue_v1'

export default function MeetingAudioView({ settings }) {
  const paths = deriveVaultPaths(settings.vaultRoot)
  const { busy, setBusy, status, setStatus, result, setResult, jobId, jobStage, setJobStage, inFlight, settle, startJob, cancelJob } = useMeetingNoteJob({ vaultPath: paths.root })
  const [audioPath, setAudioPath] = useState('')
  const [tier, setTier] = useState('中')  // 品質階梯 快=small/中=medium(預設)/高品質=cloud；標籤帶情境、非技術名
  const [precise, setPrecise] = useState(false)  // 精準/長音檔=whisperx（VAD切片+字級對齊）；正交於 tier，只作用本地 tier
  const [modelStatus, setModelStatus] = useState(null)  // { base, medium } from backend
  const [dragOver, setDragOver] = useState(false)
  const [sourceMode, setSourceMode] = useState('audio')  // audio | transcript（GLUE：匯入既有逐字稿，跳 ASR）
  const [transcriptText, setTranscriptText] = useState('')
  const [transcriptName, setTranscriptName] = useState('')
  const [templateId, setTemplateId] = useState('general')
  const [glossaryText, setGlossaryText] = useState('')
  const [draftSummary, setDraftSummary] = useState(null)
  const [draftTranscript, setDraftTranscript] = useState('')
  const [queue, setQueue] = useState(() => {
    try {
      return JSON.parse(window.localStorage.getItem(MEETING_QUEUE_KEY) || '[]')
        .map((item) => item.status === 'running' ? { ...item, status: 'interrupted' } : item)
    }
    catch { return [] }
  })
  const [queueRunning, setQueueRunning] = useState(false)
  const [activeDraftJobId, setActiveDraftJobId] = useState('')
  const hasAudio = !!audioPath.trim()
  const hasTranscript = !!transcriptText.trim()
  const mediumInfo = modelStatus?.medium
  const glossary = glossaryText.split('\n').map((item) => item.trim()).filter(Boolean)

  useEffect(() => {
    apiFetch('/app/settings').then((r) => r.json()).then((data) => {
      setTemplateId(data.meeting_template || 'general')
      setGlossaryText((data.meeting_glossary || []).join('\n'))
    }).catch(() => {})
  }, [])

  useEffect(() => {
    try { window.localStorage.setItem(MEETING_QUEUE_KEY, JSON.stringify(queue)) } catch { /* ignore */ }
  }, [queue])

  useEffect(() => {
    setDraftSummary(result?.summary ? { ...result.summary } : null)
    setDraftTranscript(result?.transcript || '')
  }, [result])

  function addQueuePaths(pathsToAdd) {
    const clean = pathsToAdd.map((path) => String(path || '').trim()).filter(Boolean)
    if (!clean.length) return
    setQueue((current) => {
      const known = new Set(current.map((item) => item.audio_path))
      const added = clean.filter((path) => !known.has(path)).map((path, index) => ({
        id: `${Date.now()}-${index}`,
        audio_path: path,
        tier,
        precise,
        status: 'queued',
        job_id: '',
        error: '',
      }))
      return [...current, ...added]
    })
    setAudioPath(clean[0])
  }

  async function runQueue() {
    if (queueRunning || busy) return
    setQueueRunning(true)
    const pending = queue.filter((item) => ['queued', 'error', 'interrupted'].includes(item.status))
    for (const item of pending) {
      setAudioPath(item.audio_path)
      setQueue((current) => current.map((entry) => entry.id === item.id ? { ...entry, status: 'running', error: '' } : entry))
      const job = await startJob({
        audioPath: item.audio_path,
        tier: item.tier,
        precise: item.precise,
        templateId,
        glossary,
        onStarted: (id) => setQueue((current) => current.map((entry) => entry.id === item.id ? { ...entry, job_id: id } : entry)),
      })
      if (!job || job.status === 'error' || job.status === 'cancelled') {
        setQueue((current) => current.map((entry) => entry.id === item.id ? { ...entry, status: job?.status || 'error', error: job?.error || '處理失敗' } : entry))
        break
      }
      setQueue((current) => current.map((entry) => entry.id === item.id ? { ...entry, status: job.stage === 'written' ? 'written' : 'review_ready', job_id: job.job_id } : entry))
    }
    setQueueRunning(false)
  }

  async function openQueueDraft(item) {
    if (!item.job_id) { setAudioPath(item.audio_path); return }
    try {
      const response = await apiFetch(`/app/meeting-note-job/${item.job_id}`)
      const job = await response.json()
      if (!response.ok) throw new Error(job.detail || '讀取草稿失敗')
      setAudioPath(job.audio_path || item.audio_path)
      setActiveDraftJobId(item.job_id)
      setResult({ ok: true, stage: job.stage, summary: job.summary, transcript: job.transcript, audio_path: job.audio_path, write: job.write })
      setStatus({ type: 'ok', message: job.stage === 'written' ? `已寫入：${job.write?.relative_path}` : '已載入可校正草稿' })
    } catch (error) { setStatus({ type: 'error', message: error.message }) }
  }

  // 時間戳點擊回放：點摘要 [mm:ss] 膠囊 → 共用 player 跳到該秒並播，把音檔當證據核對。
  // 音檔走後端串流端點（FileResponse 帶 Range，原生 seek）；逐字稿匯入無音檔則不掛 player。
  const audioRef = useRef(null)
  const canPlay = hasAudio && sourceMode === 'audio'
  const audioSrc = useMeetingAudioSource(canPlay ? audioPath : '')
  function seekTo(ts) {
    const sec = tsToSeconds(ts)
    const el = audioRef.current
    if (sec == null || !el) return
    el.currentTime = sec
    el.play().catch(() => { /* autoplay 受阻時使用者可手動播 */ })
  }
  const mediumDownloading = mediumInfo?.download?.status === 'downloading'
  const mediumPct = mediumInfo?.download?.total
    ? Math.floor((mediumInfo.download.downloaded / mediumInfo.download.total) * 100)
    : 0
  const mediumBlocked = tier === '中' && !precise && mediumInfo && !mediumInfo.installed  // ggml-medium 閘只對 中+非精準(whisper.cpp)；精準(whisperx) 自抓 faster-whisper 模型
  // 進度由後端真實 stage 驅動（非只看 busy）——故 retry 跳過 ASR 時「轉錄音訊」會立刻顯示完成。
  const STAGE_IDX = { intake: 0, asr: 1, summarize: 2, review_ready: 3, written: 4 }
  const sIdx = busy === 'run' && jobStage ? (STAGE_IDX[jobStage] ?? 0) : -1
  const runStep = (idx) => sIdx < 0 ? null : sIdx > idx ? 'done' : sIdx === idx ? 'active' : 'pending'
  const voiceState = busy === 'preview'
    ? '檢查中'
    : busy === 'run'
      ? (jobStage === 'asr' ? '轉錄中' : jobStage === 'summarize' ? '整理中' : jobStage === 'written' ? '寫入中' : '處理中')
      : result?.summary
        ? (result?.write ? '已寫入' : '待人工校正')
        : sourceMode === 'transcript' ? (hasTranscript ? '待整理' : '等待逐字稿') : (hasAudio ? '待檢查' : '等待音檔')
  const resultTone = status?.type || (result?.summary ? 'ok' : 'neutral')
  const targetPath = result?.would_write_to || result?.write?.relative_path || paths.meetings || '尚未設定'
  // 匯入逐字稿無 ASR：進度收成 整理筆記/寫入目標 兩步（誠實，不顯示不存在的轉錄步）。
  const voiceProgress = sourceMode === 'transcript'
    ? [
        { key: 'note', label: '整理筆記', state: busy === 'run' ? 'active' : result?.summary ? 'done' : 'idle' },
        { key: 'review', label: '人工校正', state: result?.summary && !result?.write ? 'active' : result?.write ? 'done' : 'idle' },
        { key: 'write', label: '寫入目標', state: result?.write ? 'done' : 'idle' },
      ]
    : [
        { key: 'file', label: '檢查檔案', state: runStep(0) ?? (busy === 'preview' ? 'active' : hasAudio ? 'done' : 'idle') },
        { key: 'transcribe', label: '轉錄音訊', state: runStep(1) ?? (result?.summary && !result?.dry_run ? 'done' : 'idle') },
        { key: 'note', label: '整理筆記', state: runStep(2) ?? (result?.summary ? 'done' : 'idle') },
        { key: 'review', label: '人工校正', state: runStep(3) ?? (result?.summary && !result?.write ? 'active' : result?.write ? 'done' : 'idle') },
        { key: 'write', label: '寫入目標', state: runStep(4) ?? (result?.write ? 'done' : result?.dry_run ? 'preview' : 'idle') },
      ]

  async function refreshModelStatus() {
    try {
      const r = await apiFetch('/app/local-asr-model/status')
      if (r.ok) setModelStatus(await r.json())
    } catch { /* offline backend: leave status unknown, run() surfaces errors */ }
  }

  // Fetch model status when the local lane is shown; poll while medium downloads.
  useEffect(() => {
    if (tier !== '中' || precise) return undefined  // 只有 中+非精準 需要 ggml-medium
    refreshModelStatus()
    if (!mediumDownloading) return undefined
    const id = setInterval(refreshModelStatus, 1500)
    return () => clearInterval(id)
  }, [tier, precise, mediumDownloading])

  async function downloadMedium() {
    try {
      await postJson('/app/local-asr-model/download', { model: 'medium' })
      setStatus({ type: 'info', message: '開始下載 ggml-medium（約 1.5GB，視網速數分鐘）…' })
      refreshModelStatus()
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    }
  }

  // Desktop drag-drop gives real filesystem paths (browser cannot expose them).
  useEffect(() => {
    let unlisten
    import('@tauri-apps/api/webview')
      .then(({ getCurrentWebview }) => getCurrentWebview().onDragDropEvent((event) => {
        if (event.payload.type === 'drop' && event.payload.paths?.length) {
          addQueuePaths(event.payload.paths)
          setStatus(null)
        }
      }))
      .then((fn) => { unlisten = fn })
      .catch(() => { /* plain browser: HTML5 drop handler shows a hint instead */ })
    return () => { if (unlisten) unlisten() }
  }, [tier, precise])

  function onBrowserDrop(event) {
    event.preventDefault()
    setDragOver(false)
    const files = [...(event.dataTransfer?.files || [])]
    if (files.length && files.every((file) => file.path)) { addQueuePaths(files.map((file) => file.path)); setStatus(null) }  // Tauri webview exposes .path
    else if (files.length) setStatus({ type: 'info', message: '瀏覽器無法取得檔案真實路徑；請用桌面版拖拉，或貼上路徑 / 用「選擇檔案」。' })
  }

  // Native file picker (packaged desktop). Dev runs in a plain browser where the
  // Tauri IPC is absent — fall back to a hint instead of breaking.
  async function pickAudio() {
    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const file = await open({
        multiple: true,
        title: '選擇一個或多個本機音檔',
        filters: [{ name: '音檔', extensions: ['mp3', 'm4a', 'wav', 'webm', 'ogg', 'mp4'] }],
      })
      const paths = Array.isArray(file) ? file : (typeof file === 'string' && file ? [file] : [])
      if (paths.length) { addQueuePaths(paths); setStatus(null) }
    } catch {
      setStatus({ type: 'info', message: '檔案選擇器只在桌面版可用；瀏覽器請直接貼上音檔路徑。' })
    }
  }

  // 預檢維持同步（輕、即時、不花費）。run(false) 走 hook 背景 job；run(true) 預覽不花費。
  async function run(dryRun) {
    if (!audioPath.trim()) return setStatus({ type: 'error', message: '請輸入本機音檔路徑' })
    if (!dryRun) { setActiveDraftJobId(''); return startJob({ audioPath, tier, precise, templateId, glossary }) }  // 長 ASR → 背景 job + 輪詢，非阻塞
    if (inFlight.current) return  // 擋雙擊
    inFlight.current = true
    setBusy('preview')
    setStatus({ type: 'info', message: '檢查音檔（不花費）...' })
    try {
      const data = await postJson('/app/meeting-note', { audio_path: audioPath, vault_path: paths.root, dry_run: true, tier, precise })
      setResult(data)
      if (!data.ok) setStatus({ type: 'error', message: data.reason || '無法處理' })
      else setStatus(
        data.preflight
          ? { type: data.preflight.usable ? 'ok' : 'error', message: `音檔檢查：${data.preflight.reason}` }
          : { type: 'ok', message: `音檔就緒 ${data.bytes} bytes → 將寫入 ${data.would_write_to}` }
      )
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { settle() }
  }

  // GLUE：匯入既有逐字稿 → 跳 ASR → 同步整理+寫入（無背景 job）。dryRun=檢查段數/時間戳、不寫。
  async function importTranscript(dryRun) {
    if (!hasTranscript) return setStatus({ type: 'error', message: '請貼上或選擇逐字稿' })
    if (inFlight.current) return  // 擋雙擊
    inFlight.current = true
    setBusy(dryRun ? 'preview' : 'run')
    if (!dryRun) { setResult(null); setJobStage(''); setActiveDraftJobId('') }
    setStatus({ type: 'info', message: dryRun ? '檢查逐字稿（不花費）...' : '整理筆記 + 寫入...' })
    try {
      const data = await postJson('/app/import-transcript', {
        text: transcriptText,
        filename: transcriptName,
        vault_path: paths.root,
        dry_run: dryRun,
        review_only: !dryRun,
        template_id: templateId,
        glossary,
      })
      if (!data.ok) { setStatus({ type: 'error', message: data.reason === 'transcript_empty' ? '逐字稿是空的' : (data.reason || '無法處理') }); return }
      if (dryRun) {
        setStatus({ type: 'ok', message: `逐字稿就緒：${data.segment_count} 段${data.has_timestamps ? '（含時間戳，會附 [mm:ss]）' : '（無時間戳，不附 [mm:ss]）'} → 將寫入 ${data.would_write_to}` })
      } else {
        setResult(data)
        setStatus({ type: 'ok', message: '草稿已完成；請校正逐字稿與摘要，再確認寫入' })
      }
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { settle() }
  }

  async function saveReviewedDraft() {
    if (!draftSummary || !draftTranscript.trim()) return
    setBusy('save')
    setStatus({ type: 'info', message: '確認寫入中（會保留 rollback）...' })
    try {
      const data = await postJson('/app/meeting-note-save', {
        vault_path: paths.root,
        audio_path: sourceMode === 'audio' ? audioPath : (transcriptName || 'imported-transcript.txt'),
        transcript: draftTranscript,
        summary: draftSummary,
        job_id: sourceMode === 'audio' ? (activeDraftJobId || jobId) : '',
      })
      setResult(data)
      const savedJobId = activeDraftJobId || jobId
      if (savedJobId) setQueue((current) => current.map((item) => item.job_id === savedJobId ? { ...item, status: 'written' } : item))
      setStatus({ type: 'ok', message: `已寫入：${data.write?.relative_path}` })
    } catch (error) {
      setStatus({ type: 'error', message: error.message })
    } finally { setBusy('') }
  }

  function onTranscriptFile(event) {
    const file = event.target.files?.[0]
    if (!file) return
    setTranscriptName(file.name)
    const reader = new FileReader()
    reader.onload = () => setTranscriptText(String(reader.result || ''))
    reader.readAsText(file)
  }

  return (
    <div className="workbench voice-workbench">
      <section className="command-bar voice-command" aria-label="voice note command">
        <div className="command-main">
          <div className="command-kicker">語音收錄</div>
          <div className="command-title">{sourceMode === 'transcript' ? (transcriptName || (hasTranscript ? '已貼上逐字稿' : '尚未匯入逐字稿')) : (hasAudio ? audioPath : '尚未選擇本機音檔')}</div>
          <div className="command-meta">
            <span className={`state-chip ${(sourceMode === 'transcript' ? hasTranscript : hasAudio) ? 'ok' : 'neutral'}`}><Mic size={13} /> {voiceState}</span>
            <div className="tabs-mini" role="group" aria-label="來源方式">
              <button className={sourceMode === 'audio' ? 'active' : ''} aria-pressed={sourceMode === 'audio'} onClick={() => setSourceMode('audio')}>本機音檔</button>
              <button className={sourceMode === 'transcript' ? 'active' : ''} aria-pressed={sourceMode === 'transcript'} onClick={() => setSourceMode('transcript')} title="已有 SRT/VTT/TXT/JSON 逐字稿：跳過轉錄，直接整理筆記">我已有逐字稿</button>
            </div>
            {sourceMode === 'transcript' && <span className="state-chip info">匯入逐字稿 · 無 ASR</span>}
            {sourceMode === 'audio' && <>
            <span className="state-chip info">僅本機音檔</span>
            <div className="tabs-mini asr-engine-tabs" role="group" aria-label="轉錄品質">
              <button className={tier === '快' ? 'active' : ''} aria-pressed={tier === '快'} onClick={() => setTier('快')} title="本地 small、免費、最快；一般筆記夠用"><span className="seg-main">快</span><span className="seg-sub">（免費·最快）</span></button>
              <button className={tier === '中' ? 'active' : ''} aria-pressed={tier === '中'} onClick={() => setTier('中')} title="本地 medium、免費、較準；日常預設"><span className="seg-main">中</span><span className="seg-sub">（免費·較準·預設）</span></button>
              <button className={tier === '高品質' ? 'active' : ''} aria-pressed={tier === '高品質'} onClick={() => setTier('高品質')} title="雲端 ASR、最準、付費"><span className="seg-main">高品質</span><span className="seg-sub">（雲端·付費）</span></button>
            </div>
            <p className="muted" style={{ margin: '4px 0 0' }}>轉錄<strong>品質</strong>：一般選<strong>中</strong>（免費較準）；要最準選<strong>高品質</strong>（付費雲端）。</p>
            {/* 固定高度容器：精準開關/下載列出現消失不讓版面跳動 */}
            <div className="engine-extra">
              {tier !== '高品質' && (
                <button className={`ghost asr-precise${precise ? ' active' : ''}`} aria-pressed={precise} onClick={() => setPrecise(!precise)} title="開＝whisperx：VAD 切片吃長音檔 + 字級對齊（決議/引用回放更準），會較慢">{precise ? '✓ ' : ''}精準／長音檔</button>
              )}
              {tier === '中' && !precise && mediumInfo && (
                mediumInfo.installed
                  ? <span className="state-chip ok"><Download size={13} /> medium 已安裝</span>
                  : mediumDownloading
                    ? <span className="state-chip info"><Download size={13} /> 下載中 {mediumPct}%</span>
                    : <button className="ghost" onClick={downloadMedium} title="下載 ggml-medium（約 1.5GB）"><Download size={14} /> 下載 medium 模型</button>
              )}
            </div>
            </>}
          </div>
        </div>
        {sourceMode === 'audio' ? (
        <div
          className={`command-input voice-input${dragOver ? ' drag-over' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onBrowserDrop}
          title="可把音檔拖到這裡（桌面版）"
        >
          <input value={audioPath} onChange={(e) => setAudioPath(e.target.value)} aria-label="本機音檔路徑" placeholder="拖入音檔，或貼上路徑 /Users/you/.../meeting.m4a" />
          <button onClick={pickAudio} title="選擇本機音檔"><FolderOpen size={16} />選擇檔案</button>
          <button onClick={() => addQueuePaths([audioPath])} disabled={!hasAudio} title="把目前路徑加入批次佇列">加入佇列</button>
          <button onClick={() => run(true)} disabled={!!busy || !hasAudio}><Eye size={16} />{busy === 'preview' ? '檢查中...' : '預覽'}</button>
          <div className="panel-actions">
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} aria-label="會議摘要模板" title="摘要模板">
              <option value="general">一般會議</option>
              <option value="decision">決策會議</option>
              <option value="interview">訪談／研究</option>
              <option value="learning">課程／分享</option>
            </select>
            <SummaryModelPicker transcriptionRoute={tier === '高品質' ? 'cloud' : 'local'} />
            <button className="primary gated-action" onClick={() => run(false)} disabled={!!busy || !hasAudio || mediumBlocked} title={mediumBlocked ? '請先下載 medium 模型，或改用 base' : ''}><FileText size={16} />{busy === 'run' ? '處理中...' : '產生可校正草稿'}</button>
            {busy === 'run' && <button className="ghost" onClick={cancelJob} title="取消目前轉錄（逐字稿已保留，可重試從該處續跑）">取消</button>}
          </div>
          {jobId && busy !== 'run' && status?.type === 'error' && (
            <button onClick={() => startJob({ audioPath, tier, precise, templateId, glossary, isRetry: true })} title="從已轉錄的逐字稿續跑，不重轉錄">重試（不重轉錄）</button>
          )}
        </div>
        ) : (
        <div className="command-input voice-input transcript-input">
          <textarea value={transcriptText} onChange={(e) => setTranscriptText(e.target.value)} aria-label="逐字稿內容"
            placeholder="貼上逐字稿（SRT / VTT / 純文字 / JSON）。SRT/VTT 帶時碼會附 [mm:ss] 回放錨；純文字則無。" />
          <label className="ghost file-pick" title="選擇逐字稿檔（.srt/.vtt/.txt/.json）"><FolderOpen size={16} />選擇檔案
            <input type="file" accept=".srt,.vtt,.txt,.json,text/plain" onChange={onTranscriptFile} hidden />
          </label>
          <button onClick={() => importTranscript(true)} disabled={!!busy || !hasTranscript}><Eye size={16} />{busy === 'preview' ? '檢查中...' : '預覽'}</button>
          <div className="panel-actions">
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} aria-label="會議摘要模板" title="摘要模板">
              <option value="general">一般會議</option>
              <option value="decision">決策會議</option>
              <option value="interview">訪談／研究</option>
              <option value="learning">課程／分享</option>
            </select>
            <SummaryModelPicker transcriptionRoute="provided" />
            <button className="primary gated-action" onClick={() => importTranscript(false)} disabled={!!busy || !hasTranscript}><FileText size={16} />{busy === 'run' ? '處理中...' : '產生可校正草稿'}</button>
          </div>
        </div>
        )}
      </section>

      <StatusMessage status={status} className="workbench-alert" />

      <div className="voice-frame">
        <div className="voice-main">
          <section className="panel voice-action-panel">
            <div className="panel-head">
              <div>
                {sourceMode === 'transcript' ? <FileText size={16} /> : <Mic size={16} />}
                <h3>{sourceMode === 'transcript' ? '逐字稿整理' : '本機音檔處理'}</h3>
              </div>
              <span className={`state-chip ${resultTone}`}>{voiceState}</span>
            </div>
            <div className="progress-steps" aria-label="語音處理進度" aria-live="polite">
              {voiceProgress.map((step) => (
                <div key={step.key} className={`progress-step ${step.state}`}>
                  <span>{step.label}</span>
                  <strong>{step.state === 'active' ? '進行中' : step.state === 'done' ? '完成' : step.state === 'preview' ? '預檢' : step.state === 'pending' ? '等待' : '未開始'}</strong>
                </div>
              ))}
            </div>
            {(sourceMode === 'transcript' ? !hasTranscript : !hasAudio) && (
              <div className="empty-surface voice-empty">
                {sourceMode === 'transcript' ? <FileText size={22} /> : <Mic size={22} />}
                <span>{sourceMode === 'transcript' ? '貼上或選擇逐字稿後，按「預覽」確認段數與寫入目標。' : '貼上本機音檔路徑後，先按「預覽」確認檔案與寫入目標。'}</span>
              </div>
            )}
          </section>

          {sourceMode === 'audio' && (
            <MeetingQueue
              busy={!!busy} onOpen={openQueueDraft}
              onRemove={(id) => setQueue((current) => current.filter((entry) => entry.id !== id))}
              onRun={runQueue} queue={queue} running={queueRunning}
            />
          )}

          <section className="panel voice-result-panel">
            <div className="panel-head">
              <div>
                <FileText size={16} />
                <h3>結果預覽</h3>
              </div>
              <span className={`state-chip ${result?.summary ? 'ok' : 'neutral'}`}>{result?.summary ? '已有摘要' : '尚無結果'}</span>
            </div>
            {result?.summary ? (
              <div className={`note-detail voice-result${result.write ? '' : ' review-mode'}`}>
                {result.write ? <>
                  <strong>{result.summary.title}</strong>
                  {result.summary.summary && <p>{result.summary.summary}</p>}
                  <MeetingField label="重要整理" value={result.summary.key_organization} onSeek={canPlay ? seekTo : undefined} />
                  <MeetingField label="核心價值" value={result.summary.core_value} onSeek={canPlay ? seekTo : undefined} />
                  <MeetingField label="行動項目" value={result.summary.action_items} list onSeek={canPlay ? seekTo : undefined} />
                  <MeetingField label="決議" value={result.summary.decisions} list onSeek={canPlay ? seekTo : undefined} />
                  <MeetingField label="出席者" value={result.summary.attendees} list />
                  <MeetingField label="議程" value={result.summary.agenda} list onSeek={canPlay ? seekTo : undefined} />
                </> : <MeetingReviewEditor
                  summary={draftSummary || result.summary}
                  transcript={draftTranscript}
                  onSummary={setDraftSummary}
                  onTranscript={setDraftTranscript}
                />}
                {canPlay && (
                  <div className="audio-playback">
                    <span className="audio-playback-label"><Mic size={13} /> 點上方 [mm:ss] 跳回音檔核對</span>
                    <audio ref={audioRef} src={audioSrc} controls preload="none" />
                  </div>
                )}
                {!result.write && (
                  <div className="review-save-gate">
                    <span><ShieldCheck size={15} /> 校正不會重新呼叫模型；確認後才寫入筆記。</span>
                    <button className="primary gated-action" onClick={saveReviewedDraft} disabled={busy === 'save'}>
                      <Save size={16} />{busy === 'save' ? '寫入中...' : '確認寫入校正版'}
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="empty-surface voice-empty">
                <FileText size={22} />
                <span>轉錄結果會顯示在這裡。</span>
              </div>
            )}
          </section>
        </div>

        <aside className="inspector voice-inspector" aria-label="voice route inspector">
          <section className="inspector-section">
            <h3><Route size={15} /> 路線</h3>
            <div className="state-list">
              <div><span>來源</span><strong>{sourceMode === 'transcript' ? '匯入逐字稿' : (hasAudio ? '本機音檔' : '未選')}</strong></div>
              {sourceMode === 'transcript' && <div><span>轉錄</span><strong>跳過（已有逐字稿）</strong></div>}
              <div><span>模式</span><strong>{result?.write ? '已寫入' : result?.summary ? '人工校正' : result?.dry_run ? '已預檢' : busy === 'run' ? '產生草稿中' : '先預覽'}</strong></div>
              <div><span>目標</span><strong>{targetPath}</strong></div>
            </div>
          </section>
          <section className="inspector-section">
            <h3><ShieldCheck size={15} /> 門檻</h3>
            {sourceMode === 'transcript' ? <>
              <div className={hasTranscript ? 'gate-row ok' : 'gate-row muted-gate'}><FileText size={14} /> 逐字稿已提供</div>
              <div className="gate-row ok"><Eye size={14} /> 無 ASR、不呼叫轉錄服務</div>
              <div className="gate-row warn"><LockKeyhole size={14} /> 產生草稿會呼叫摘要模型；確認後才寫入</div>
            </> : <>
              <div className={hasAudio ? 'gate-row ok' : 'gate-row muted-gate'}><Mic size={14} /> 本機路徑已提供</div>
              <div className="gate-row ok"><Eye size={14} /> 預覽不寫入筆記</div>
              <div className="gate-row warn"><LockKeyhole size={14} /> 產生草稿會執行 ASR／摘要；確認後才寫入</div>
            </>}
          </section>
          <section className="inspector-section">
            <h3><Database size={15} /> 本機狀態</h3>
            <div className="state-list">
              <div><span>會議筆記目標</span><strong>{paths.meetings || '後端預設'}</strong></div>
              <div><span>結果</span><strong>{result?.ok ? '完成' : result ? '受阻' : '尚無'}</strong></div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  )
}
