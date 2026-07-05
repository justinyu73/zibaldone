import { useRef, useState } from 'react'
import { apiFetch, postJson } from '../../app/api'

// 長 ASR 走背景 job + 輪詢；階段標籤對映後端 stage（intake/asr/summarize/written）。
const MEETING_STAGE_LABEL = { intake: '檢查檔案', asr: '轉錄音訊', summarize: '整理筆記', review_ready: '等待人工校正', written: '完成' }

// 會議筆記 meeting-note-job 生命週期（POST→輪詢 stage→result）。批次音檔 lane 與
// 即時逐字稿 handoff 共用同一條 whisper.cpp lane，避免兩份平行 poller。
export default function useMeetingNoteJob({ vaultPath }) {
  const [busy, setBusy] = useState('')  // '' | 'preview' | 'run'
  const [status, setStatus] = useState(null)
  const [result, setResult] = useState(null)
  const [jobId, setJobId] = useState('')  // 失敗時保留以便 retry（從 checkpoint 續跑、不重轉錄）
  const [jobStage, setJobStage] = useState('')  // 後端真實 stage（intake/asr/summarize/written），驅動誠實進度
  // 同步再入鎖：busy 是非同步 state，快速雙擊時兩個 click 都在 disabled 生效前觸發；ref 同步擋第二擊。
  const inFlight = useRef(false)
  const settle = () => { setBusy(''); inFlight.current = false }

  async function pollJob(id) {
    try {
      const r = await apiFetch(`/app/meeting-note-job/${id}`)
      if (!r.ok) throw new Error(`輪詢失敗（${r.status}）`)
      const job = await r.json()
      const stageLabel = MEETING_STAGE_LABEL[job.stage] || job.stage
      setJobStage(job.stage)  // 誠實進度：retry 跳 ASR 時 stage 直接是 summarize，畫面立刻顯示轉錄已完成
      if (job.status === 'running') {
        setStatus({ type: 'info', message: `處理中…（${stageLabel}）` })
        await new Promise((resolve) => setTimeout(resolve, 1500))
        return pollJob(id)
      }
      settle()
      if (job.status === 'error') {
        setStatus({ type: 'error', message: `失敗於「${stageLabel}」：${job.error}（可重試，逐字稿不會重轉錄）` })
      } else if (job.status === 'cancelled') {
        setStatus({ type: 'info', message: '已取消（逐字稿已保留，可重試從該處續跑）' })
      } else if (job.status === 'review_ready' || job.stage === 'review_ready') {
        setResult({ ok: true, dry_run: false, stage: 'review_ready', summary: job.summary, transcript: job.transcript, audio_path: job.audio_path, write: null })
        setStatus({ type: 'ok', message: '草稿已完成；請校正逐字稿與摘要，再確認寫入' })
      } else {
        setResult({ ok: true, dry_run: false, stage: job.stage, summary: job.summary, transcript: job.transcript, audio_path: job.audio_path, write: job.write })
        setStatus({ type: 'ok', message: `已寫入：${job.write?.relative_path}` })
      }
      return job
    } catch (error) {
      settle(); setStatus({ type: 'error', message: error.message }); return null
    }
  }

  async function cancelJob() {
    if (!jobId) return
    try {
      await postJson(`/app/meeting-note-job/${jobId}/cancel`, {})
      setStatus({ type: 'info', message: '已送出取消，等目前階段結束…' })
    } catch (error) { setStatus({ type: 'error', message: error.message }) }
  }

  // 起背景 job（首次或 retry），立即返回 job_id 後輪詢——長 ASR 不阻塞 UI、不 timeout。
  async function startJob({ audioPath, tier = '中', precise = false, templateId = 'general', glossary = [], isRetry = false, onStarted }) {
    if (!audioPath.trim()) return setStatus({ type: 'error', message: '請輸入本機音檔路徑' })
    if (inFlight.current) return  // 擋雙擊
    inFlight.current = true
    setBusy('run'); setResult(null); setJobStage('intake')
    setStatus({ type: 'info', message: isRetry ? '重試（從逐字稿續跑，不重轉錄）…' : '轉錄 + 整理會議筆記…' })
    try {
      const body = { audio_path: audioPath, vault_path: vaultPath, dry_run: false, tier, precise, review_only: true, template_id: templateId, glossary }
      const data = await postJson(isRetry ? `/app/meeting-note-job/${jobId}/retry` : '/app/meeting-note-job', body)
      if (!data.ok || !data.job_id) { settle(); return setStatus({ type: 'error', message: data.reason || '無法起始轉錄' }) }
      setJobId(data.job_id)
      onStarted?.(data.job_id)
      return await pollJob(data.job_id)
    } catch (error) {
      settle(); setStatus({ type: 'error', message: error.message }); return null
    }
  }

  return { busy, setBusy, status, setStatus, result, setResult, jobId, jobStage, setJobStage, inFlight, settle, startJob, cancelJob }
}
