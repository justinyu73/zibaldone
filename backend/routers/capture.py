"""Legacy YouTube capture pipeline routes: fetch, translate, estimate, summarize, save, index."""
from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

import app_config
from model_policy import model_for_task
from obsidian import get_existing, load_index, save_learning_note
from runtime_usage import append_runtime_usage_event, usage_from_estimate
from schemas import EstimateReq, FetchReq, SaveReq, SummarizeReq, TranslateReq, VideoAudioAsrReq
from services.library import _estimate, _normalize_summary, _settings, _to_traditional_text
from services.settings import _check_daily_cap
from transcript import (
    extract_video_id,
    fetch_duration_seconds,
    fetch_meta,
    fetch_transcript,
    segments_to_plain_text,
    segments_to_timestamped,
)
from translator import TranslateError, translate_to_zh

logger = logging.getLogger(__name__)
# 同 main 的 logger 佈線：模組 logger 預設繼承 root 的 WARNING → logger.info 全被濾掉。
# 掛自有 INFO handler 讓翻譯進度 log 真的輸出；propagate=False 免重複經 root。
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(_h)
    logger.propagate = False

router = APIRouter()


def _estimate_translate(text: str) -> dict[str, Any]:
    # English videos translate the full transcript before summarizing; output is
    # ~1:1 in length. Lets the preview show the real total, not summary-only.
    input_tokens = max(1, math.ceil(len(text) / 4))
    output_tokens = input_tokens
    model = model_for_task("translate", "gpt-5-mini")
    input_price, output_price = app_config.price_for_model(model)
    cost = (input_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price)
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_tokens": input_tokens + output_tokens,
        "estimated_usd": round(cost, 6),
    }


def _transcript_failure(
    transcript: dict[str, Any],
    en_segments: list[dict],
    zh_segments: list[dict],
) -> dict[str, str]:
    error = str(transcript.get("error") or "").strip()
    fallback_lang = str(transcript.get("fallback_lang") or "").strip()
    has_transcript = bool(en_segments or zh_segments)

    if has_transcript and fallback_lang and not fallback_lang.lower().startswith("en"):
        return {
            "key": "language_fallback",
            "label": "使用其他語言字幕",
            "detail": f"沒有取得指定 EN/ZH 字幕，已使用 {fallback_lang} 字幕作為 fallback。",
            "next_action": "檢查語言來源與內容，再翻譯、摘要或寫入。",
            "severity": "warning",
        }
    if has_transcript:
        return {
            "key": "transcript_available",
            "label": "字幕可用",
            "detail": "已取得字幕內容。",
            "next_action": "檢查逐字稿、翻譯、摘要或 dry-run 寫入。",
            "severity": "ok",
        }
    if not error:
        return {
            "key": "no_transcript",
            "label": "沒有可用字幕",
            "detail": "影片資訊可讀，但沒有取得字幕內容。",
            "next_action": "貼上人工 evidence，或標記無字幕。",
            "severity": "warning",
        }

    lowered = error.lower()
    if re.search(r"停用字幕|transcriptsdisabled|disabled captions|subtitles are disabled|字幕已停用", lowered):
        return {
            "key": "disabled_captions",
            "label": "字幕已停用",
            "detail": error,
            "next_action": "補人工 evidence 或標記無字幕；不要把它歸為暫時性錯誤。",
            "severity": "warning",
        }
    if re.search(r"too many requests|429|403|forbidden|blocked|\bip\b|rate.?limit|request blocked|youtube is blocking|上游.*拒|存取.*受限", lowered):
        return {
            "key": "rate_limited",
            "label": "YouTube 暫時阻擋",
            "detail": error,
            "next_action": "稍後重試或補人工 evidence；不做登入、繞權限或大量重試。",
            "severity": "warning",
        }
    if re.search(r"videounavailable|unavailable|private|不存在|無法使用|無法觀看|video unavailable", lowered):
        return {
            "key": "video_unavailable",
            "label": "影片不可用",
            "detail": error,
            "next_action": "確認 URL、影片權限或改由人工來源補 evidence。",
            "severity": "warning",
        }
    if re.search(r"parser|parse|json3|vtt|srv3|ttml|解析|無法下載字幕內容|找到字幕軌但無法下載|fallback|yt-dlp|抓取字幕失敗", lowered):
        return {
            "key": "parser_failure",
            "label": "字幕 fallback 失敗",
            "detail": error,
            "next_action": "保留錯誤，走人工 evidence fallback；後續用 fixture 修 parser。",
            "severity": "warning",
        }
    if re.search(r"notranscriptfound|no transcript|找不到.*字幕|沒有字幕|找不到可用字幕|無字幕", lowered):
        return {
            "key": "no_transcript",
            "label": "沒有可用字幕",
            "detail": error,
            "next_action": "貼上人工 evidence，或標記無字幕等待 ASR/OCR lane。",
            "severity": "warning",
        }
    return {
        "key": "unknown_failure",
        "label": "未分類字幕錯誤",
        "detail": error,
        "next_action": "保留原始錯誤，先走人工 evidence；若重複出現再補分類規則。",
        "severity": "warning",
    }


@router.post("/api/fetch")
def fetch(req: FetchReq):
    video_id = extract_video_id(req.url)
    if not video_id:
        raise HTTPException(400, "請輸入有效的 YouTube URL 或 video id")

    meta = fetch_meta(video_id)
    transcript = fetch_transcript(video_id)

    en_segments = transcript.get("en") or []
    zh_segments = transcript.get("zh") or []

    # Check existence in the SAME folder /save writes to, so the UI's overwrite
    # prompt is accurate (user-chosen folder first, else env default).
    if req.vault_path.strip():
        vault, subfolder = req.vault_path.strip(), (req.subfolder or "")
    else:
        vault, subfolder = _settings()
    existing = get_existing(vault, subfolder, video_id) if vault else None
    languages = transcript.get("available_langs", [])
    failure = _transcript_failure(transcript, en_segments, zh_segments)

    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "original_url": req.url,
        "is_short": "/shorts/" in req.url,
        "existing": existing,
        "meta": {
            "title": meta.title,
            "channel": meta.channel,
            "published": meta.published,
            "duration": meta.duration,
            "thumbnail": meta.thumbnail,
        },
        "transcript": {
            "en_segments": en_segments,
            "zh_segments": zh_segments,
            "en_text": segments_to_plain_text(en_segments),
            "zh_text": _to_traditional_text(segments_to_plain_text(zh_segments)),
            "en_timestamped": segments_to_timestamped(en_segments),
            "available_langs": transcript.get("available_langs", []),
            "fallback_lang": transcript.get("fallback_lang"),
            "zh_lang": transcript.get("zh_lang"),
        },
        "estimate": _estimate(segments_to_plain_text(en_segments) or segments_to_plain_text(zh_segments), "quick"),
        "languages": languages,
        "error": transcript.get("error"),
        "failure": failure,
        "failure_class": failure["key"],
        "failure_label": failure["label"],
        "next_action": failure["next_action"],
    }


# Long translations run chunked; the UI polls per-request progress by id.
_TRANSLATE_PROGRESS: Dict[str, Dict[str, int]] = {}


@router.post("/api/translate")
def translate(req: TranslateReq):
    if not req.text.strip():
        return {"translated": ""}

    _check_daily_cap()
    progress_id = (req.progress_id or "").strip()[:64]

    def _log_progress(done: int, total: int) -> None:
        logger.info("translate progress: chunk %d/%d", done, total)
        if progress_id:
            _TRANSLATE_PROGRESS[progress_id] = {"done": done, "total": total}

    try:
        translated = translate_to_zh(req.text, target=req.target, progress_callback=_log_progress)
    except TranslateError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        if progress_id:
            _TRANSLATE_PROGRESS.pop(progress_id, None)
    return {"translated": _to_traditional_text(translated)}


@router.get("/api/translate-progress")
def translate_progress(progress_id: str):
    return _TRANSLATE_PROGRESS.get(progress_id) or {"done": 0, "total": 0}


@router.post("/api/estimate-source")
def estimate_source(req: FetchReq):
    """Fast cost preflight. Estimates from the video DURATION (one page fetch, no
    transcript) when available — ~150 wpm * ~6 chars/word. Falls back to counting
    transcript chars only when duration is unavailable. Returns quick+deep cost."""
    video_id = extract_video_id(req.url)
    if not video_id:
        raise HTTPException(400, "請輸入有效的 YouTube URL 或 video id")
    seconds = fetch_duration_seconds(video_id)
    if seconds > 0:
        chars = seconds * 15  # ~150 words/min * ~6 chars/word
        sized_text = "x" * chars
        return {
            "ok": True,
            "video_id": video_id,
            "source": "duration",
            "duration_seconds": seconds,
            "chars": chars,
            "estimate_quick": _estimate(sized_text, "quick"),
            "estimate_deep": _estimate(sized_text, "deep"),
            "estimate_translate": _estimate_translate(sized_text),
        }
    # Duration unavailable (YouTube throttled / missing). Fail FAST — do NOT fetch
    # the full transcript here (that is the slow path). The precise cost is shown
    # at the 抓取字幕 step from the real transcript.
    return {
        "ok": True,
        "video_id": video_id,
        "source": "unavailable",
        "estimate_quick": None,
        "estimate_deep": None,
    }


@router.post("/api/estimate")
def estimate(req: EstimateReq):
    result = _estimate(req.text, req.mode)
    append_runtime_usage_event(
        task="summary_estimate",
        provider="openai",
        model=result["model"],
        mode=req.mode,
        endpoint="/api/estimate",
        usage=usage_from_estimate(result),
        provider_call_count=0,
        raw_evidence_ref="runtime:estimate:no_provider_call",
        decision_scope="estimated usage only; not provider billing",
    )
    return result


@router.post("/api/summarize")
def summarize(req: SummarizeReq):
    import providers

    summary_model = model_for_task("summary", "gpt-5.2")
    provider = providers.detect_provider(summary_model)
    if provider not in ("cli", "llamacpp") and not app_config.get_provider_key(provider):
        raise HTTPException(400, f"{provider} API 金鑰未設定；AI 摘要已停用")
    _check_daily_cap()

    # 本地小模型不可靠地把英文「邊摘要邊翻譯」成繁中 → 餵已翻譯的中文（中文進中文出，較完整）；
    # 雲端維持讀英文原文（保真、不繞翻譯層），行為不變。
    if provider == "llamacpp":
        source = req.transcript_zh.strip() or req.transcript_en.strip()
    else:
        source = req.transcript_en.strip() or req.transcript_zh.strip()
    if not source:
        raise HTTPException(400, "No transcript text to summarize")

    mode_note = "concise" if req.mode == "quick" else "detailed and high quality"
    source_label = "文章內文" if req.kind == "article" else "YouTube 逐字稿"
    prompt = f"""
請把以下{source_label}整理成繁體中文 Obsidian 學習筆記摘要。
模式：{mode_note}
標題：{req.title}

請回傳 JSON，欄位固定為：
explicit_topic, key_points, terms, content_value, source_platform, content_category

欄位規則：
- explicit_topic：合併原本章節摘要與金句摘錄的作用，用一段話寫出影片明確主題，放最上方。
- key_points：最多 3 條重點。
- terms：專有名詞、人物、工具。
- content_value：提煉逐字稿對使用者專案的核心價值，說明可對應哪個專案區塊、如何應用、是否建議加入雙向連結。
- source_platform：內容來源，例如 YT、Reels、Threads、IG、X。
- content_category：分類，例如 AI LLM、應用、學習參考、財經、哲學思維、領域知識。

重要格式要求：
- 全部內容必須使用繁體中文。
- explicit_topic 只能輸出 1 句濃縮主題，不可列點，不可貼多段摘要。
- key_points 最多 3 條。
- content_value、source_platform、content_category 不可空白；不要把這三欄放進其他欄位。

不要輸出 action checklist 或 backlinks 建議；這些由 APP 自帶核對功能處理，不寫入筆記正文。

內容：
{source[:24000]}
"""
    schema = {
        "type": "object",
        "properties": {
            "explicit_topic": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "terms": {"type": "array", "items": {"type": "string"}},
            "content_value": {"type": "string"},
            "source_platform": {"type": "string"},
            "content_category": {"type": "string"},
        },
        "required": ["explicit_topic", "key_points", "terms", "content_value", "source_platform", "content_category"],
    }
    summary = None
    for attempt in range(2):  # 小模型偶發壞 JSON → retry 一次接變異（B 的 schema 已大幅降低機率）
        try:
            result = providers.chat_complete(model=summary_model, prompt=prompt, json_mode=True, json_schema=schema)
        except providers.ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"{provider} 摘要失敗：{exc}") from exc
        append_runtime_usage_event(
            task="summary", provider=provider, model=summary_model, mode=req.mode,
            endpoint="/api/summarize", usage=result["usage"], provider_call_count=1,
            raw_evidence_ref="runtime:summarize:response_usage",
            decision_scope="summary provider usage accounting only; no prompt or transcript text stored",
        )
        try:
            summary = providers.extract_json(result["text"] or "{}")
            break
        except Exception:
            if attempt == 0:
                continue
            hint = "（本地小模型對長逐字稿較弱，可切回雲端摘要）" if provider == "llamacpp" else ""
            raise HTTPException(502, f"{provider} 回傳的 JSON 無法解析{hint}")
    return {"summary": _normalize_summary(summary, req.source_url), "estimate": _estimate(source, req.mode)}


@router.post("/api/save")
def save(req: SaveReq):
    # User-chosen folder takes priority (local-first: store wherever the user
    # points — an Obsidian vault, a repo, any local markdown folder); else env.
    if req.vault_path.strip():
        vault, subfolder = req.vault_path.strip(), (req.subfolder or "")
    else:
        vault, subfolder = _settings()
    if not vault:
        raise HTTPException(400, "未設定筆記資料夾（OBSIDIAN_VAULT_PATH 或前端設定）")
    if req.dry_run:
        existing = get_existing(vault, subfolder, req.video_id)
        if existing and req.save_mode == "create":
            raise HTTPException(409, {"message": "This video already exists in the YouTube index", "existing": existing})
        return {
            "dry_run": True,
            "would_create_new": not bool(existing) or req.save_mode == "new_copy",
            "would_update_ai": bool(existing) and req.save_mode == "update_ai",
            "target_folder": f"{subfolder}/{'shorts' if req.is_short else 'videos'}",
            "index_key": req.video_id,
        }
    try:
        result = save_learning_note(
            vault_path=vault,
            subfolder=subfolder,
            video_id=req.video_id,
            url=req.url,
            title=req.title,
            channel=req.channel,
            published=req.published,
            duration=req.duration,
            thumbnail=req.thumbnail,
            transcript_en=req.transcript_en,
            transcript_zh=req.transcript_zh,
            ai_summary=_normalize_summary(req.ai_summary),
            ai_mode=req.ai_mode,
            manual_summary=req.manual_summary,
            languages=req.languages,
            failure_class=req.failure_class,
            extraction_sources=req.extraction_sources,
            coverage_summary=req.coverage_summary,
            save_mode=req.save_mode,
            is_short=req.is_short,
        )
    except FileExistsError as exc:
        existing = get_existing(vault, subfolder, req.video_id)
        raise HTTPException(409, {"message": str(exc), "existing": existing}) from exc
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"寫入筆記失敗：{exc}") from exc

    return {
        "saved_path": result["path"],
        "relative_path": result["relative_path"],
        "created_new": result["created_new"],
        "index_entry": result["entry"],
    }


@router.get("/api/index")
def index():
    vault, subfolder = _settings()
    if not vault:
        raise HTTPException(400, "OBSIDIAN_VAULT_PATH is not configured")
    return load_index(vault, subfolder)


@router.post("/api/app/video-audio-asr")
def app_video_audio_asr(req: VideoAudioAsrReq):
    # ASR rung (CC → ASR → OCR): captionless video → download audio → local whisper.
    # Operator-gated: only called by an explicit user action in the video lane.
    import video_audio_asr

    try:
        return video_audio_asr.transcribe_youtube_audio(req.url, asr_model=req.asr_model or "small")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
