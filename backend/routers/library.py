"""Library/intake routes: app config, note detail/assets/thoughts, media playback,
inbox/radar/capture intake, article lane, search and library read models."""
from __future__ import annotations

import hmac
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

import app_config
from app_config import normalize_host_path
from app_state import (
    AppStateError,
    AppStateRuntime,
    bounded_relative_child_path,
    list_source_subfolders,
)
from meeting_note import meeting_note_metadata, replace_meeting_audio_provenance
from note_rollback import write_note_with_backup
from obsidian import get_existing, parse_note_fields
from runtime_usage import append_runtime_usage_event
from schemas import AppRouteReq, MeetingAudioRepairReq, ValueSignalsReq, VaultPath
from services.library import (
    _AUDIO_MIME_BY_EXT,
    _estimate,
    _normalize_summary,
    _settings,
    _to_traditional_text,
)
from services.security import configured_session_token
from services.readiness import _app_state
from services.settings import _check_daily_cap
from value_signals import build_value_signals
from vault_write import vault_write_with_rollback

router = APIRouter()


@router.get("/api/app/config")
def app_state_config():
    """Expose the backend's configured vault so the library reads where capture writes."""
    from obsidian import INDEX_NAME
    vault, subfolder = _settings()
    notes_folder = str(Path(vault) / subfolder) if vault and subfolder else (vault or "")
    return {
        "vault_path": vault,
        "subfolder": subfolder,
        "index_relpath": f"{subfolder}/{INDEX_NAME}" if subfolder else INDEX_NAME,
        "notes_folder": notes_folder,
        "index_name": INDEX_NAME,
    }


class VaultNoteEditReq(BaseModel):
    vault_path: VaultPath
    subfolder: str = ""
    video_id: str
    title: str = ""
    ai_summary: Dict[str, Any] = {}
    ai_mode: str = "quick"
    manual_summary: str = ""


@router.post("/api/app/vault-note-edit")
def app_state_vault_note_edit(req: VaultNoteEditReq):
    """Edit an existing note's AI fields with a rollback backup (read→edit→AC→writeback)."""
    if not req.vault_path.strip():
        raise HTTPException(400, "未提供筆記庫路徑（vault_path）")
    existing = get_existing(req.vault_path, req.subfolder, req.video_id)
    if not existing:
        raise HTTPException(404, f"索引中找不到這篇筆記：{req.video_id}")
    save_kwargs = {
        "url": existing.get("original_url") or f"https://www.youtube.com/watch?v={req.video_id}",
        "title": req.title or existing.get("title", ""),
        "channel": existing.get("channel", ""),
        "published": None, "duration": None, "thumbnail": None,
        "transcript_en": "", "transcript_zh": "",
        "ai_summary": req.ai_summary, "ai_mode": req.ai_mode, "manual_summary": req.manual_summary,
        "languages": existing.get("transcript_languages") or [],
        "save_mode": "update_ai", "is_short": existing.get("source_type") == "short",
    }
    try:
        result = vault_write_with_rollback(
            vault_path=req.vault_path, subfolder=req.subfolder, video_id=req.video_id, save_kwargs=save_kwargs,
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "relative_path": result["relative_path"],
        "rollback_available": result["rollback_available"],
        "backup": result.get("backup"),
    }


@router.get("/api/app/note-detail")
def app_state_note_detail(vault_path: VaultPath, note_relpath: str):
    """Read an existing note: parsed editable fields (media-library edit) plus the
    raw markdown (reading view renders it client-side; storage stays .md)."""
    try:
        target = bounded_relative_child_path(vault_path, note_relpath)
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not target.is_file():
        raise HTTPException(404, f"找不到筆記檔：{note_relpath}")
    content = target.read_text(encoding="utf-8")
    return {
        "ok": True,
        "fields": parse_note_fields(content),
        "meeting": meeting_note_metadata(content),
        "content": content,
    }


@router.post("/api/app/meeting-audio-repair")
def app_state_meeting_audio_repair(req: MeetingAudioRepairReq):
    """Repair a moved meeting recording without rewriting the rest of the note."""
    try:
        target = bounded_relative_child_path(req.vault_path, req.note_relpath)
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not target.is_file():
        raise HTTPException(404, f"找不到筆記檔：{req.note_relpath}")
    try:
        updated = replace_meeting_audio_provenance(
            target.read_text(encoding="utf-8"),
            normalize_host_path(req.audio_path),
        )
        result = write_note_with_backup(target, updated)
    except (OSError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "audio_path": normalize_host_path(req.audio_path),
        "rollback_available": result["rollback_available"],
        "previous_hash": result["previous_hash"],
        "current_hash": result["current_hash"],
    }


_IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".bmp": "image/bmp", ".avif": "image/avif",
}


class NoteThoughtReq(BaseModel):
    vault_path: VaultPath
    note_relpath: str
    text: str
    distill: bool = False


@router.post("/api/app/note-thought")
def app_state_note_thought(req: NoteThoughtReq):
    """事後補心得：追加帶日期的人工心得到個人心得段（前一版自動備份）。"""
    if not req.text.strip():
        raise HTTPException(400, "心得內容是空的")
    try:
        target = bounded_relative_child_path(req.vault_path, req.note_relpath)
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not target.is_file():
        raise HTTPException(404, f"找不到筆記檔：{req.note_relpath}")
    from note_thoughts import append_thought

    return append_thought(target, req.text, distill=req.distill)


@router.get("/api/app/note-asset")
def app_state_note_asset(vault_path: VaultPath, note_relpath: str, src: str):
    """Serve an image referenced by a note for the reading view. Read-only,
    image extensions only, bounded inside vault_path (no traversal); resolves
    relative to the note's folder first, then the vault root."""
    mime = _IMAGE_MIME.get(Path(src).suffix.lower())
    if not mime:
        raise HTTPException(400, f"不支援的附件類型：{src}")
    note_dir = Path(note_relpath).parent.as_posix()
    candidates = [f"{note_dir}/{src}"] if note_dir not in ("", ".") else []
    candidates.append(src)
    # Obsidian convention: bare filenames usually live in the vault-level
    # attachments folder (notes-vault keeps it at <vault_root>/_attachments).
    candidates.append(f"_attachments/{Path(src).name}")
    for rel in candidates:
        try:
            target = bounded_relative_child_path(vault_path, rel)
        except AppStateError:
            continue
        if target.is_file():
            return FileResponse(target, media_type=mime)
    raise HTTPException(404, f"找不到附件：{src}")


def _parse_byte_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single `bytes=start-end` range → inclusive (start, end), clamped.
    Returns None when unsatisfiable (caller should answer 416)."""
    if not range_header.startswith("bytes="):
        return None
    start_s, _, end_s = range_header[len("bytes="):].split(",")[0].strip().partition("-")
    try:
        if start_s == "":  # suffix range: last N bytes
            length = int(end_s)
            if length <= 0:
                return None
            start, end = max(0, file_size - length), file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return None
    if start > end or start >= file_size:
        return None
    return start, min(end, file_size - 1)


class MeetingAudioTicketReq(BaseModel):
    audio_path: str


_MEETING_AUDIO_TICKETS: dict[str, tuple[str, float]] = {}
_MEETING_AUDIO_TICKET_TTL = 10 * 60


def _validated_meeting_audio_path(audio_path: str) -> tuple[Path, str]:
    p = Path(normalize_host_path(audio_path)).expanduser()
    mime = _AUDIO_MIME_BY_EXT.get(p.suffix.lower())
    if not mime:
        raise HTTPException(400, f"不支援的音檔類型：{audio_path}")
    if not p.is_file():
        raise HTTPException(404, f"找不到音檔：{audio_path}")
    return p, mime


@router.post("/api/app/meeting-audio-ticket")
def app_state_meeting_audio_ticket(req: MeetingAudioTicketReq):
    p, _ = _validated_meeting_audio_path(req.audio_path)
    now = time.time()
    for key, (_, expires) in list(_MEETING_AUDIO_TICKETS.items()):
        if expires <= now:
            _MEETING_AUDIO_TICKETS.pop(key, None)
    ticket = uuid.uuid4().hex
    _MEETING_AUDIO_TICKETS[ticket] = (str(p.resolve()), now + _MEETING_AUDIO_TICKET_TTL)
    return {"ticket": ticket, "expires_in": _MEETING_AUDIO_TICKET_TTL}


@router.get("/api/app/meeting-audio")
def app_state_meeting_audio(audio_path: str, request: Request):
    """Stream an operator-supplied meeting audio file for timestamp click-to-playback
    in the draft review (the `[mm:ss]` capsules). Read-only, audio extensions only.
    Implements HTTP Range manually (starlette 0.38 FileResponse ignores Range →
    returns 200 full, which breaks <audio> seek on large meetings) so the player
    can seek without downloading the whole file. Packaged builds use a short-lived,
    path-bound ticket because native media requests cannot attach the session header."""
    p, mime = _validated_meeting_audio_path(audio_path)
    if configured_session_token():
        ticket = request.query_params.get("ticket", "")
        grant = _MEETING_AUDIO_TICKETS.get(ticket)
        resolved = str(p.resolve())
        if not grant or grant[1] <= time.time() or not hmac.compare_digest(grant[0], resolved):
            raise HTTPException(401, "invalid or expired media ticket")
    size = p.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(p, media_type=mime, headers={"Accept-Ranges": "bytes"})
    rng = _parse_byte_range(range_header, size)
    if rng is None:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    start, end = rng

    def _iter():
        with open(p, "rb") as fh:
            fh.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = fh.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    return StreamingResponse(
        _iter(), status_code=206, media_type=mime,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
        },
    )


@router.get("/api/app/local-library/read-model")
def app_state_local_library_read_model(
    workspace_root: str,
    index_path: str,
    query: str = "",
    limit: int = 50,
    category: str = "",
    source_type: str = "",
):
    try:
        return AppStateRuntime.local_library_read_model_for_workspace(
            workspace_root,
            index_path=index_path,
            query=query,
            limit=limit,
            category=category,
            source_type=source_type,
        )
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc


class InboxActionReq(BaseModel):
    vault_root: VaultPath
    note_relpath: str
    confirm: bool = False


@router.get("/api/app/inbox")
def app_state_inbox(vault_root: VaultPath):
    """List undigested notes (status: inbox, or 01_Inbox notes without status)."""
    from inbox import scan_inbox
    return scan_inbox(vault_root)


@router.post("/api/app/inbox-review")
def app_state_inbox_review(req: InboxActionReq):
    """Mark a note digested: status inbox→reviewed, frontmatter lines only."""
    from inbox import mark_reviewed
    try:
        return mark_reviewed(req.vault_root, req.note_relpath)
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/app/inbox-trash")
def app_state_inbox_trash(req: InboxActionReq):
    """Move a note to <vault_root>/_trash. Requires explicit confirm=true."""
    if not req.confirm:
        raise HTTPException(400, "移到垃圾桶需要逐筆明確確認（confirm=true）")
    from inbox import trash_note
    try:
        return trash_note(req.vault_root, req.note_relpath)
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/api/app/retirement-candidates")
def app_state_retirement_candidates(vault_root: VaultPath, stale_days: int = 90):
    """退場候選：Type1 過時參考(age>stale_days)且未被 Type2 引用。只列候選；
    刪除走既有 inbox-trash(移到 _trash，分類器已排除 _trash → 刪了即從候選消失)。"""
    from retirement import retirement_candidates
    return retirement_candidates(vault_root, stale_days=stale_days)


class RadarScanReq(BaseModel):
    feeds: List[str] = []
    tuning: Dict[str, Any] = {}  # 篇數/閾值/主題詞/來源開關；radar._normalize_tuning 收斂


class RadarDismissReq(BaseModel):
    ids: List[str]


class FreeTranslateReq(BaseModel):
    text: str


@router.post("/api/app/free-translate")
def app_state_free_translate(req: FreeTranslateReq):
    """判讀翻譯：先走 Google gtx 免費端點（零成本）；被限流/擋下時自動 fallback
    到使用者設定的翻譯模型（便宜 LLM，判讀一篇成本約 $0.0001），不寫入任何筆記。"""
    from free_translate import FreeTranslateError, free_translate_to_zh
    if not req.text.strip():
        return {"translated": ""}
    try:
        return {"translated": free_translate_to_zh(req.text), "provider": "google-gtx-free"}
    except FreeTranslateError as gtx_exc:
        import providers

        model = app_config.get_settings()["translate_model"]
        provider = providers.detect_provider(model)
        if provider not in ("cli", "llamacpp") and not app_config.get_provider_key(provider):
            raise HTTPException(502, f"免費翻譯端點暫時被擋，且 fallback 需要 {provider} 金鑰（翻譯模型 {model}）——可先讀原文，或到設定填金鑰") from gtx_exc
        _check_daily_cap()
        prompt = f"把以下內容翻成繁體中文，只回譯文、不要前後說明：\n\n{req.text[:24000]}"
        try:
            result = providers.chat_complete(model=model, prompt=prompt)
        except providers.ProviderError as exc:
            raise HTTPException(502, f"翻譯 fallback 失敗：{exc}") from exc
        append_runtime_usage_event(
            task="free_translate_fallback",
            provider=provider,
            model=model,
            mode="judging",
            endpoint="/api/app/free-translate",
            usage=result["usage"],
            provider_call_count=1,
            raw_evidence_ref="runtime:free_translate_fallback:response_usage",
            decision_scope="radar judging translation fallback; no note written, no source text stored",
        )
        return {"translated": _to_traditional_text(result["text"] or ""), "provider": f"llm-fallback:{model}"}


@router.get("/api/app/capture-inbox")
def app_state_capture_inbox(vault_root: VaultPath):
    """手機收錄通道：掃 01_Inbox/ 抽網址當待收候選（檔案不動，指紋去重）。"""
    if not vault_root.strip():
        raise HTTPException(400, "未設定筆記庫根目錄（vault root）")
    from capture_inbox import scan_capture_inbox

    return scan_capture_inbox(vault_root)


@router.post("/api/app/capture-inbox-dismiss")
def app_state_capture_inbox_dismiss(req: RadarDismissReq):
    """忽略或帶入後永久記指紋（重掃不再出現）。"""
    from capture_inbox import dismiss

    return dismiss(req.ids)


class CapturePdfConvertReq(BaseModel):
    vault_root: VaultPath
    file: str


@router.post("/api/app/capture-pdf-convert")
def app_state_capture_pdf_convert(req: CapturePdfConvertReq):
    """01_Inbox 的 PDF → md 筆記（markitdown v1）：原檔移入 _attachments 並連結。"""
    if not req.vault_root.strip():
        raise HTTPException(400, "未設定筆記庫根目錄（vault root）")
    from capture_inbox import convert_pdf_capture

    result = convert_pdf_capture(req.vault_root, req.file)
    if not result.get("ok"):
        raise HTTPException(422, result.get("message", "PDF 轉換失敗"))
    return result


@router.get("/api/app/radar")
def app_state_radar_list():
    """雷達候選清單（app 資料區，不進 vault）。"""
    from radar import list_candidates
    return list_candidates()


@router.post("/api/app/radar-scan")
def app_state_radar_scan(req: RadarScanReq):
    """手動掃描 HN/GitHub/RSS（無排程；指紋去重＋單次上限）。"""
    from radar import scan
    return scan(req.feeds, tuning=req.tuning)


@router.post("/api/app/radar-dismiss")
def app_state_radar_dismiss(req: RadarDismissReq):
    """忽略或採用後移出候選並永久記指紋。"""
    from radar import dismiss
    return dismiss(req.ids)


class ArticleFetchReq(BaseModel):
    url: str
    vault_path: VaultPath = ""


class ArticleSaveReq(BaseModel):
    url: str
    title: str
    content: str = ""
    ai_summary: Dict[str, Any] = {}
    ai_mode: str = "quick"
    manual_summary: str = ""
    author: str = ""
    published: str = ""
    vault_path: VaultPath = ""
    note_status: str = "inbox"  # inbox=進收件匣 | reviewed=就地讀完直接歸檔
    dry_run: bool = False


class EstimateTextReq(BaseModel):
    text: str


@router.post("/api/app/estimate-text")
def app_state_estimate_text(req: EstimateTextReq):
    """Cost preview for pasted/fetched text (article lane). Pure math — no
    provider call, no usage-log event."""
    return {"quick": _estimate(req.text, "quick"), "deep": _estimate(req.text, "deep")}


@router.post("/api/app/article-fetch")
def app_state_article_fetch(req: ArticleFetchReq):
    """Fetch + extract an article body for human review (M1 文章 lane)."""
    from article_note import ARTICLES_SUBFOLDER, fetch_article
    from news_source_to_note import source_hash as article_hash
    from news_vault_write import load_news_index

    result = fetch_article(req.url)
    existing = None
    if req.vault_path.strip():
        try:
            existing = load_news_index(req.vault_path, ARTICLES_SUBFOLDER).get("items", {}).get(article_hash(req.url))
        except (FileNotFoundError, NotADirectoryError):
            existing = None
    return {**result, "existing": existing}


@router.post("/api/app/article-save")
def app_state_article_save(req: ArticleSaveReq):
    """Render + persist an article note (status: inbox; source_hash dedupe with
    backup on overwrite). Same closed loop as video notes."""
    from article_note import ARTICLES_SUBFOLDER, build_article_note
    from news_source_to_note import source_hash as article_hash
    from news_vault_write import write_news_note

    vault = req.vault_path.strip() or _settings()[0]
    if not vault:
        raise HTTPException(400, "未設定筆記庫根目錄（vault root）")
    if not req.url.strip() or not req.title.strip():
        raise HTTPException(400, "url 與 title 為必填")
    if req.note_status not in ("inbox", "reviewed"):
        raise HTTPException(400, "note_status 必須是 inbox 或 reviewed")
    note = build_article_note(
        url=req.url, title=req.title, content=req.content,
        ai_summary=_normalize_summary(req.ai_summary, req.url), ai_mode=req.ai_mode,
        manual_summary=req.manual_summary, author=req.author, published=req.published,
        status=req.note_status,
    )
    if req.dry_run:
        return {"dry_run": True, "target_folder": ARTICLES_SUBFOLDER, "source_hash": article_hash(req.url)}
    try:
        result = write_news_note(
            vault_path=vault, subfolder=ARTICLES_SUBFOLDER,
            source_hash=article_hash(req.url), url=req.url, title=req.title, note_markdown=note,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"寫入筆記失敗：{exc}") from exc
    return {"ok": True, **result}


@router.get("/api/app/search")
def app_state_search(vault_root: VaultPath, query: str = "", limit: int = 50):
    """Full-text search over the vault (FTS5 trigram; CJK substring capable).
    Read-only for the vault; the index lives under the app config dir."""
    from search_index import search_notes
    return search_notes(vault_root, query, limit)


class NoteLinksReq(BaseModel):
    vault_root: VaultPath
    note_relpath: str
    paths: List[str]


@router.get("/api/app/related-notes")
def app_state_related_notes(vault_root: VaultPath, note_relpath: str):
    """相關筆記候選（FTS5 用本篇標題＋專有名詞聚合命中）；只讀不寫。"""
    try:
        target = bounded_relative_child_path(vault_root, note_relpath)
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not target.is_file():
        raise HTTPException(404, f"找不到筆記檔：{note_relpath}")
    from related_notes import related_candidates

    return related_candidates(vault_root, note_relpath)


@router.post("/api/app/note-links")
def app_state_note_links(req: NoteLinksReq):
    """把人工勾選的關聯寫入「## 相關筆記」段（wikilink，前一版自動備份）。"""
    if not req.paths:
        raise HTTPException(400, "沒有勾選任何關聯")
    try:
        target = bounded_relative_child_path(req.vault_root, req.note_relpath)
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not target.is_file():
        raise HTTPException(404, f"找不到筆記檔：{req.note_relpath}")
    from related_notes import write_links

    return write_links(req.vault_root, req.note_relpath, req.paths)


@router.get("/api/app/vault-folders")
def app_state_vault_folders(vault_root: VaultPath):
    """List 02_Sources/* under the vault root — the value library's default
    aggregation set. Read-only."""
    return {"ok": True, "folders": list_source_subfolders(vault_root)}


@router.get("/api/app/value-library")
def app_state_value_library(folders: str = "", query: str = "", sort: str = "recency", limit: int = 300):
    """Cross-source value library: aggregate notes across an allowlist of folders
    (pipe-separated), grouped by source. sort=recency (default) or relevance
    (stdlib keyword/tag overlap ranking when a query is given). Read-only."""
    from app_state import aggregate_value_notes
    folder_list = [f.strip() for f in folders.split("|") if f.strip()]
    if not folder_list:
        return {"records": [], "sources": {}, "total": 0}
    return aggregate_value_notes(folder_list, query=query, sort=sort, limit=limit)


@router.post("/api/app/route")
def app_state_route_source(req: AppRouteReq):
    try:
        job = _app_state(req.workspace_root).route_source(
            source_id=req.source_id,
            route_state=req.route_state,
            stage=req.stage,
        )
        return {"job": job}
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/app/metrics")
def app_state_metrics(workspace_root: str):
    try:
        return _app_state(workspace_root).metrics()
    except AppStateError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/app/value-signals")
def app_state_value_signals(req: ValueSignalsReq):
    return {"ok": True, "read_only": True, "value_signals": build_value_signals(req.summary)}
