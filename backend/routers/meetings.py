"""Meeting note/ASR job and local model (whisper.cpp / built-in llama.cpp) routes."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from meeting_note import (
    MEETINGS_SUBFOLDER,
    normalize_meeting_summary,
    run_meeting_note,
    validate_summary_timestamps,
    write_meeting_note,
)
from provider_runtime import ProviderRuntimeError
from schemas import (
    AsrModelDownloadReq,
    ImportTranscriptReq,
    MeetingDraftSaveReq,
    MeetingNoteReq,
)
from services.library import _settings
from services.meetings import (
    _ASR_DOWNLOAD_LOCK,
    _ASR_MODEL_DOWNLOADS,
    _ASR_MODEL_REGISTRY,
    _MEETING_JOBS,
    _asr_model_installed,
    _download_asr_model,
    _load_job_state,
    _load_meeting_draft,
    _meeting_asr_fn_for,
    _persist_job_state,
    _persist_meeting_draft,
    _spawn_meeting_job,
    _summarize_meeting,
    _timestamped_transcript,
)

router = APIRouter()


def _resolve_meeting_vault(req: MeetingNoteReq) -> str:
    vault_path = req.vault_path or _settings()[0]
    if not vault_path:
        raise HTTPException(400, "vault_path is required (or set OBSIDIAN_VAULT_PATH)")
    return vault_path


@router.post("/api/app/meeting-note")
def app_state_meeting_note(req: MeetingNoteReq):
    from audio_preflight import audio_preflight

    vault_path = _resolve_meeting_vault(req)
    try:
        return run_meeting_note(
            req.audio_path,
            asr_fn=_meeting_asr_fn_for(req),
            summarizer_fn=lambda transcript: _summarize_meeting(
                transcript, req.template_id, req.glossary),
            writer_fn=lambda data: write_meeting_note(
                vault_path, data["summary"], data["transcript"], data["audio_path"]
            ),
            dry_run=req.dry_run,
            preflight_fn=lambda p: audio_preflight(str(p)),
            review_only=req.review_only,
        )
    except (ProviderRuntimeError, ValueError, OSError) as exc:
        raise HTTPException(502, f"meeting-note failed: {exc}") from exc


@router.post("/api/app/import-transcript")
def app_state_import_transcript(req: ImportTranscriptReq):
    """GLUE（make_vs_take）：匯入既有逐字稿 → 跳 ASR → 同步整理筆記 + [mm:ss] distill。
    無音檔、無 ASR、無 pre-flight；摘要那次 LLM 與會議筆記同一條。SRT/VTT 帶時碼 → 膠囊；
    純 TXT 無時碼 → distill 自然略過 [mm:ss]。寫入與會議筆記同 02_Sources/meetings。"""
    from transcript import parse_imported_transcript

    if not req.text.strip():
        return {"ok": False, "stage": "intake", "reason": "transcript_empty"}
    vault_path = _resolve_meeting_vault(req)
    segments = parse_imported_transcript(req.text, req.filename)
    timestamped = _timestamped_transcript(segments, req.text)
    if req.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "stage": "preview",
            "filename": req.filename,
            "segment_count": len(segments),
            "has_timestamps": bool(segments),
            "would_write_to": MEETINGS_SUBFOLDER,
            "provider_call_count": 0,
        }
    try:
        summary = normalize_meeting_summary(
            _summarize_meeting(timestamped, req.template_id, req.glossary))
        summary = validate_summary_timestamps(summary, timestamped)
        if req.review_only:
            return {
                "ok": True,
                "dry_run": False,
                "stage": "review_ready",
                "summary": summary,
                "transcript": timestamped,
                "audio_path": req.filename or "imported-transcript.txt",
                "write": None,
            }
        write = write_meeting_note(vault_path, summary, timestamped, req.filename or "imported-transcript.txt")
    except (ProviderRuntimeError, ValueError, OSError) as exc:
        raise HTTPException(502, f"import-transcript failed: {exc}") from exc
    return {"ok": True, "dry_run": False, "stage": "written", "summary": summary, "write": write}


@router.post("/api/app/meeting-note-save")
def app_state_meeting_note_save(req: MeetingDraftSaveReq):
    """Human gate: persist the edited review draft, never re-run ASR or summary."""
    vault_path = req.vault_path or _settings()[0]
    if not vault_path:
        raise HTTPException(400, "vault_path is required (or set OBSIDIAN_VAULT_PATH)")
    transcript = req.transcript.strip()
    if not transcript:
        raise HTTPException(400, "逐字稿是空的")
    summary = validate_summary_timestamps(normalize_meeting_summary(req.summary), transcript)
    try:
        write = write_meeting_note(vault_path, summary, transcript, req.audio_path or "imported-transcript.txt")
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    if req.job_id:
        state = _MEETING_JOBS.get(req.job_id)
        if state:
            state.update({"stage": "written", "status": "done", "summary": summary, "write": write})
            _persist_job_state(req.job_id, state)
        _persist_meeting_draft(req.job_id, {
            "schema_id": "meeting-review-draft/v1",
            "job_id": req.job_id,
            "status": "written",
            "audio_path": req.audio_path,
            "transcript": transcript,
            "summary": summary,
            "write": write,
        })
    return {"ok": True, "stage": "written", "summary": summary, "write": write}


@router.post("/api/app/meeting-note-job")
def app_meeting_note_job_start(req: MeetingNoteReq):
    return _spawn_meeting_job(req, _resolve_meeting_vault(req), uuid.uuid4().hex)


@router.get("/api/app/meeting-note-job/{job_id}")
def app_meeting_note_job_status(job_id: str):
    state = _MEETING_JOBS.get(job_id)
    if state:
        return {"job_id": job_id, **{k: state.get(k) for k in
                ("status", "stage", "error", "summary", "transcript", "audio_path", "write")}}
    draft = _load_meeting_draft(job_id)
    if draft:
        return {
            "job_id": job_id,
            "status": draft.get("status", "review_ready"),
            "stage": draft.get("status", "review_ready"),
            "error": "",
            "summary": draft.get("summary"),
            "transcript": draft.get("transcript"),
            "audio_path": draft.get("audio_path"),
            "write": draft.get("write"),
        }
    disk = _load_job_state(job_id)  # 記憶體沒（crash/重啟）→讀磁碟持久狀態；running→interrupted
    if disk:
        return {"job_id": job_id, "summary": None,
                **{k: disk.get(k) for k in ("status", "stage", "error", "write")}}
    raise HTTPException(404, "unknown job")


@router.post("/api/app/meeting-note-job/{job_id}/retry")
def app_meeting_note_job_retry(job_id: str, req: MeetingNoteReq):
    # 從磁碟 checkpoint resume（_run_meeting_job 讀回 transcript → 跳 ASR）。
    return _spawn_meeting_job(req, _resolve_meeting_vault(req), job_id)


@router.post("/api/app/meeting-note-job/{job_id}/cancel")
def app_meeting_note_job_cancel(job_id: str):
    # 合作式取消：設旗標，背景執行緒在下個階段邊界（ASR 前/summarize 前）自行中止。
    # ASR 已 checkpoint 故取消不浪費轉錄；之後 retry 可從 transcript resume。
    state = _MEETING_JOBS.get(job_id)
    if not state:
        raise HTTPException(404, "unknown job")
    state["cancel"] = True
    return {"ok": True, "job_id": job_id, "status": state.get("status")}


@router.get("/api/app/local-asr-model/status")
def app_local_asr_model_status():
    out: dict[str, Any] = {}
    for name in ("base", *_ASR_MODEL_REGISTRY):
        info = _asr_model_installed(name)
        info["downloadable"] = name in _ASR_MODEL_REGISTRY
        progress = _ASR_MODEL_DOWNLOADS.get(name)
        if progress:
            info["download"] = {k: progress.get(k) for k in ("status", "downloaded", "total", "error")}
        out[name] = info
    return out


@router.post("/api/app/local-asr-model/download")
def app_local_asr_model_download(req: AsrModelDownloadReq):
    name = req.model
    if name not in _ASR_MODEL_REGISTRY:
        raise HTTPException(400, f"未知或不可下載的模型：{name}")
    if _asr_model_installed(name)["installed"]:
        return {"ok": True, "status": "done", "already_installed": True}
    with _ASR_DOWNLOAD_LOCK:
        current = _ASR_MODEL_DOWNLOADS.get(name)
        if current and current.get("status") == "downloading":
            return {"ok": True, "status": "downloading", **{k: current.get(k) for k in ("downloaded", "total")}}
        _ASR_MODEL_DOWNLOADS[name] = {"status": "downloading", "downloaded": 0, "total": 0, "error": ""}
    threading.Thread(target=_download_asr_model, args=(name,), daemon=True).start()
    return {"ok": True, "status": "downloading"}


@router.get("/api/app/local-llm/status")
def app_local_llm_status():
    # 本機免金鑰 AI = 內建 llama.cpp runtime（spec C）；狀態含就緒與首用下載進度。
    import local_llm_builtin

    return {"builtin": local_llm_builtin.status()}


@router.post("/api/app/local-llm/builtin/install")
def app_local_llm_builtin_install():
    # spec C：llama.cpp runtime＋gguf 首用下載（背景執行緒，UI 輪詢 status().builtin.download）。
    import local_llm_builtin

    try:
        return local_llm_builtin.start_install()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
