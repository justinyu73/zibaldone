"""Meeting ASR/summary/job pipeline and model-download workers shared by routers.meetings."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import threading
import urllib.request
from pathlib import Path
from typing import Any, Dict

from fastapi import HTTPException

import app_config
import providers
from meeting_note import run_meeting_note, write_meeting_note
from model_policy import model_for_task
from provider_runtime import transcribe_audio
from schemas import MeetingNoteReq
from services.library import _AUDIO_MIME_BY_EXT, _to_traditional_text
from services.readiness import _asr_root, _local_asr_runtime_readiness

logger = logging.getLogger(__name__)
# 同 main 的 logger 佈線：模組 logger 預設繼承 root 的 WARNING → logger.info 全被濾掉。
# 掛自有 INFO handler 讓 [asr] 診斷 log 真的輸出；propagate=False 免重複經 root。
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(_h)
    logger.propagate = False


_MEETING_PROMPT = """請把以下會議逐字稿整理成繁體中文會議筆記。回傳 JSON，欄位固定為：
title, summary, key_organization, core_value, action_items, decisions, attendees, agenda
- title：會議標題（一句）
- summary：整體摘要（散文，不需時間戳）
- key_organization：重要整理（重點脈絡）；每條離散重點末附該句逐字稿的 [mm:ss]
- core_value：核心價值（對專案/決策的關鍵價值）；每條離散重點末附 [mm:ss]
- action_items：行動項目陣列；每條末附該行動依據的逐字稿 [mm:ss]
- decisions：決議陣列；每條末附該決議出處的逐字稿 [mm:ss]
- attendees：可辨識的出席者陣列
- agenda：議程/主題分段陣列
時間戳規則（quote+timestamp distill）：逐字稿每行以 [mm:ss] 前綴。引用某句作為依據時，
把那句的 [mm:ss] 附在該條結尾，例：「採 WhisperX CPU 版 [12:30]」。無法歸因到具體某句的
條目，略過時間戳、不要杜撰一個。
全部使用繁體中文。逐字稿：
"""

_MEETING_TEMPLATE_GUIDANCE = {
    "general": "一般會議：平衡整理脈絡、決議與後續行動。",
    "decision": "決策會議：優先整理選項、判斷依據、已定決議、負責人與未決事項。",
    "interview": "訪談／研究：優先保留受訪者觀點、需求、痛點、例證與可驗證引句。",
    "learning": "課程／分享：優先整理概念、方法、例子、可實作步驟與待查證問題。",
}


def _meeting_prompt(template_id: str = "general", glossary: list[str] | None = None) -> str:
    template = template_id if template_id in _MEETING_TEMPLATE_GUIDANCE else "general"
    terms = []
    for raw in glossary or []:
        term = str(raw).strip()
        if term and len(term) <= 80 and term not in terms:
            terms.append(term)
        if len(terms) >= 100:
            break
    glossary_hint = (
        "\n個人詞彙表（只用於逐字稿確實提到時的拼寫，不得硬塞）：" + "、".join(terms)
        if terms else ""
    )
    return _MEETING_PROMPT.replace(
        "全部使用繁體中文。逐字稿：",
        f"模板重點：{_MEETING_TEMPLATE_GUIDANCE[template]}{glossary_hint}\n全部使用繁體中文。逐字稿：",
    )


def _meeting_asr(path: Path) -> str:
    data = Path(path).read_bytes()
    mime = _AUDIO_MIME_BY_EXT.get(Path(path).suffix.lower(), "audio/mpeg")
    result = transcribe_audio(
        filename=Path(path).name,
        media_base64=base64.b64encode(data).decode("ascii"),
        media_mime=mime,
        task="asr",
        mode="real",
    )
    segments = result.get("segments") or []
    # 診斷雲端 ASR 時間戳：單段＝無逐句歸因（高品質 [00:00] bug 的源頭）。
    logger.info("[asr] cloud segments=%d granular=%s", len(segments), _has_granular_timestamps(segments))
    return _timestamped_transcript(segments, result.get("text", ""))


_ASR_MODEL_FILES = {"base": "ggml-base.bin", "small": "ggml-small.bin", "medium": "ggml-medium.bin"}

# Downloadable larger models. base ships via setup_asr_runtime.sh; medium is
# fetched on demand (1.5GB) with the official whisper.cpp sha1 verified.
_ASR_MODEL_REGISTRY = {
    "medium": {
        "filename": "ggml-medium.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
        "sha1": "fd9727b6e1217c2f614f9b698455c4ffd82463b4",  # whisper.cpp models/README.md
    },
}
_ASR_MODEL_DOWNLOADS: dict[str, dict[str, Any]] = {}
_ASR_DOWNLOAD_LOCK = threading.Lock()


def _asr_models_dir() -> Path:
    return _asr_root() / "tools/whisper.cpp/models"


def _asr_model_installed(name: str) -> dict[str, Any]:
    filename = _ASR_MODEL_FILES.get(name) or (_ASR_MODEL_REGISTRY.get(name) or {}).get("filename")
    path = (_asr_models_dir() / filename) if filename else None
    ok = bool(path and path.is_file())
    return {"installed": ok, "bytes": path.stat().st_size if ok else 0}


def _download_asr_model(name: str) -> None:
    """Stream the model to a .part file (so a half-download never looks installed),
    verify the official sha1, then atomically move into place. Progress lives in
    _ASR_MODEL_DOWNLOADS for the UI to poll."""
    spec = _ASR_MODEL_REGISTRY[name]
    dest = _asr_models_dir() / spec["filename"]
    tmp = dest.with_suffix(dest.suffix + ".part")
    state = _ASR_MODEL_DOWNLOADS[name]
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(spec["url"], headers={"User-Agent": "yt-note-app"})
        digest = hashlib.sha1()
        with urllib.request.urlopen(request, timeout=60) as resp:
            state["total"] = int(resp.headers.get("Content-Length") or 0)
            with open(tmp, "wb") as handle:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    state["downloaded"] += len(chunk)
        if digest.hexdigest() != spec["sha1"]:
            tmp.unlink(missing_ok=True)
            raise ValueError("下載檔 sha1 不符（可能損毀），已捨棄")
        tmp.replace(dest)
        state["status"] = "done"
    except Exception as exc:  # noqa: BLE001 — any failure must surface to the UI, not crash the thread
        tmp.unlink(missing_ok=True)
        state["status"] = "error"
        state["error"] = str(exc)


def _resolve_local_asr_model(asr_model: str, readiness: dict[str, Any]) -> str:
    """base = the sha1-verified runtime-lock model; small/medium = larger siblings
    (more accurate, slower; medium emits Simplified — normalized to Traditional after).
    The whisper-cli binary is shared, so only the model file differs."""
    if asr_model in ("small", "medium"):
        filename = _ASR_MODEL_FILES[asr_model]
        candidate = _asr_root() / "tools/whisper.cpp/models" / filename
        if not candidate.is_file():
            raise ValueError(f"ggml-{asr_model} 模型未安裝（缺 models/{filename}）——請先下載或改用 base")
        return candidate.as_posix()
    return str(readiness.get("model", {}).get("path") or "")


def _mmss(seconds: Any) -> str:
    total = int(float(seconds or 0))
    return f"{total // 60:02d}:{total % 60:02d}"


def _has_granular_timestamps(segments: list[dict[str, Any]]) -> bool:
    """逐句時間戳是否可用。退化案＝雲端 ASR 把整段會議回成單一 start=0 segment
    （無逐句歸因）→ 不該把那唯一 [00:00] 前綴上去讓摘要全歸 00:00。判準：
    多段(≥2)＝可用；單段＝只有 start 是真非零時間（如匯入的 SRT 單 cue [00:31]）才算，
    單段 start≈0（雲端整段）＝不可用。多段維持既有行為（真 start 才前綴、None 不杜撰）。"""
    texted = [seg for seg in segments if seg.get("text")]
    if len(texted) >= 2:
        return True
    if len(texted) == 1:
        start = texted[0].get("start")
        return start is not None and int(float(start)) > 0
    return False


def _timestamped_transcript(segments: list[dict[str, Any]], fallback_text: str = "") -> str:
    """quote+timestamp distill（make_vs_take value-add）：每段逐字稿前綴 [mm:ss]，
    讓任一句都能追回音檔時間。文字統一繁體。沒有可用逐句時間戳時退回純文字。"""
    # 機械強制「不杜撰時間戳」：prompt 叫摘要模型別杜撰 00:00 但雲端模型不一定聽；
    # 源頭就不給假時間戳——無逐句時間戳（單段/全 0）時不前綴，摘要層自然無從附 [mm:ss]。
    granular = _has_granular_timestamps(segments)
    lines = []
    for seg in segments:
        text = _to_traditional_text(str(seg.get("text") or "").strip())
        if not text:
            continue
        start = seg.get("start")
        lines.append(f"[{_mmss(start)}] {text}" if (granular and start is not None) else text)
    return "\n".join(lines) if lines else _to_traditional_text(str(fallback_text or "").strip())


def _meeting_asr_local(path: Path, language: str = "auto", asr_model: str = "base") -> str:
    """Local whisper.cpp ASR — free/offline, no upload. Runtime-gated.
    Transcript is normalized to Taiwan Traditional (medium emits Simplified)
    and timestamped per segment (quote+timestamp distill)."""
    from whisper_transcribe import transcribe

    readiness = _local_asr_runtime_readiness()
    if readiness.get("runtime_ready") is not True:
        raise ValueError("本地語音轉錄環境尚未就緒（缺 whisper.cpp，請跑 setup_asr_runtime.sh 或改用雲端 ASR）")
    result = transcribe(
        str(path),
        binary_path=str(readiness.get("binary", {}).get("path") or ""),
        model_path=_resolve_local_asr_model(asr_model, readiness),
        language=language or "auto",
    )
    if not result.get("ok"):
        raise ValueError(f"本地轉錄失敗：{result.get('message') or result.get('error_code')}")
    return _strip_asr_hallucinations(_timestamped_transcript(result.get("segments") or [], result.get("text", "")))


def _meeting_asr_whisperx(path: Path, language: str = "auto", model_size: str = "medium") -> str:
    """WhisperX engine（make_vs_take TAKE）：VAD 切片 + 字級對齊，吃長音檔。
    回傳帶 [mm:ss] 的繁體逐字稿（quote+timestamp distill；段時間用對齊後的精準值）。"""
    from whisperx_transcribe import transcribe

    result = transcribe(str(path), model_size=(model_size or "medium"), language=language or "auto")
    if not result.get("ok"):
        raise ValueError(f"WhisperX 轉錄失敗：{result.get('message') or result.get('error_code')}")
    return _strip_asr_hallucinations(_timestamped_transcript(result.get("segments") or [], result.get("text", "")))


def _traditionalize_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """硬保證摘要輸出一律繁體：逐字稿已轉繁，但小摘要模型（如 gemma3:4b）偶發吐簡體，
    prompt 的「繁體」是軟約束→這裡用 OpenCC 收口。[mm:ss]/英文詞不受影響。"""
    def conv(v):
        if isinstance(v, str):
            return _to_traditional_text(v)
        if isinstance(v, list):
            return [_to_traditional_text(x) if isinstance(x, str) else x for x in v]
        return v
    return {k: conv(v) for k, v in summary.items()}


def _summarize_meeting(
    transcript: str,
    template_id: str = "general",
    glossary: list[str] | None = None,
) -> Dict[str, Any]:
    import providers

    summary_model = model_for_task("summary", "gpt-5.2")
    provider = providers.detect_provider(summary_model)
    if provider != "ollama" and not app_config.get_provider_key(provider):
        raise HTTPException(400, f"{provider} API 金鑰未設定")
    _str = {"type": "string"}
    _strs = {"type": "array", "items": {"type": "string"}}
    schema = {
        "type": "object",
        "properties": {
            "title": _str, "summary": _str, "key_organization": _str, "core_value": _str,
            "action_items": _strs, "decisions": _strs, "attendees": _strs, "agenda": _strs,
        },
        "required": ["title", "summary", "action_items", "decisions"],
    }
    for attempt in range(2):  # 小模型偶發壞 JSON → retry 一次（schema 已大幅降低機率）
        try:
            result = providers.chat_complete(
                model=summary_model,
                prompt=_meeting_prompt(template_id, glossary) + transcript[:24000],
                json_mode=True,
                json_schema=schema,
            )
        except providers.ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            return _traditionalize_summary(providers.extract_json(result["text"] or "{}"))
        except Exception:
            if attempt == 0:
                continue
            hint = "（本地小模型對長逐字稿較弱，可改用較大本地模型或雲端摘要）" if provider == "ollama" else ""
            raise HTTPException(502, f"{provider} 回傳的 JSON 無法解析{hint}")


# 品質分層（JY 2026-06-30）：UI 標籤帶使用情境、非技術名（合「固定預設別飄移」準則）。
# tier→(asr_mode, asr_model)；前端 selector 決定預設=中。後端空 tier=用明傳 asr_mode/asr_model。
_ASR_TIERS = {
    "快": ("local", "small"),    # 本地免費、快（base 前端已退役＝品質不堪，small 為下限）
    "中": ("local", "medium"),   # 本地免費、較準（日常預設，由前端 selector 設）
    "高品質": ("cloud", ""),      # provider ASR、計費（個人需要最準時 opt-in）
}


def _resolve_asr_tier(tier: str, asr_mode: str, asr_model: str, precise: bool = False) -> tuple[str, str]:
    if tier in _ASR_TIERS:
        mode, model = _ASR_TIERS[tier]
        if precise and mode == "local":  # 精準/長音檔=whisperx（VAD 切片+字級對齊）；cloud 不受影響
            mode = "whisperx"
        return mode, (model or asr_model)
    return asr_mode, asr_model


def _meeting_asr_fn_for(req: MeetingNoteReq):
    """ASR 引擎選擇——同步端點與背景 job runner 共用（不平行造）。tier 設定時覆蓋 mode/model。"""
    mode, model = _resolve_asr_tier(req.tier, req.asr_mode, req.asr_model, req.precise)
    if mode == "local":
        return lambda p: _meeting_asr_local(p, req.language, model)
    if mode == "whisperx":
        return lambda p: _meeting_asr_whisperx(p, req.language, model)
    return _meeting_asr


# ── 會議 ASR job lifecycle（spec docs/design/meeting_job_lifecycle_spec.md）──────
# 沿用既有 model-download 的 background+poll+lock 範式（不平行造）：長 ASR 跑背景執行緒、
# UI 輪詢；transcript 成功即落磁碟 checkpoint，故 ASR 後失敗 retry 跳過轉錄、不重跑那 150 分鐘。
_MEETING_JOBS: dict[str, dict[str, Any]] = {}
_MEETING_JOB_LOCK = threading.Lock()


_MEETING_CHECKPOINT_SCHEMA = 2
_ASR_TIMESTAMP_PIPELINE_VERSION = "segment-mmss-v2"


def _meeting_checkpoint_key(
    audio_path: str,
    asr_mode: str,
    asr_model: str,
    *,
    language: str = "auto",
    provider_model: str = "",
) -> str:
    """以**音檔內容 + 引擎**為 key（非 job_id），故同一個檔不管按「轉錄並存入」或「重試」、
    不管 job_id 是什麼，都絕不重轉錄；換引擎或檔案被換掉（size/mtime 變）才重轉。"""
    p = Path(audio_path).expanduser()
    try:
        st = p.stat()
        sig = (
            f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}|{asr_mode}|{asr_model}|"
            f"{language}|{provider_model}|{_ASR_TIMESTAMP_PIPELINE_VERSION}"
        )
    except OSError:
        sig = (
            f"{audio_path}|{asr_mode}|{asr_model}|{language}|{provider_model}|"
            f"{_ASR_TIMESTAMP_PIPELINE_VERSION}"
        )
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()


def _meeting_checkpoint_path(key: str) -> Path:
    # app-data 目錄，**不寫進使用者 vault**（vault 只放筆記、不被 runtime 產物弄髒/同步）。
    d = _asr_root() / "meeting_jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def _read_meeting_checkpoint(key: str) -> str | None:
    # 修復（2026-07-05）：函式體曾被 8e9d88d 插入 draft helpers 切斷成永遠回 None，
    # 導致 retry 從未真正跳過 ASR（重轉錄）。批5 盤點發現、此處歸位。
    p = _meeting_checkpoint_path(key)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("transcript")
    except (OSError, json.JSONDecodeError):
        return None


def _meeting_draft_path(job_id: str) -> Path:
    return _meeting_checkpoint_path(f"draft_{job_id}")


def _persist_meeting_draft(job_id: str, draft: dict[str, Any]) -> None:
    try:
        _meeting_draft_path(job_id).write_text(
            json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_meeting_draft(job_id: str) -> dict[str, Any] | None:
    path = _meeting_draft_path(job_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# Job-state 持久化（P1）：_MEETING_JOBS 是記憶體，crash/更新後 job 進度消失。把小狀態落
# 磁碟（同 meeting_jobs 目錄），讓重啟後仍能查到 job 結果/狀態。
def _persist_job_state(job_id: str, state: dict[str, Any]) -> None:
    try:
        _meeting_checkpoint_path(f"state_{job_id}").write_text(
            json.dumps({k: state.get(k) for k in ("status", "stage", "error", "audio_path", "write")},
                       ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def _load_job_state(job_id: str) -> dict[str, Any] | None:
    p = _meeting_checkpoint_path(f"state_{job_id}")
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # 記憶體沒這 job 卻磁碟記 running → 背景 thread 已隨 crash/重啟消失 → interrupted（可 retry 續跑）。
    if d.get("status") == "running":
        d["status"], d["stage"] = "interrupted", "interrupted"
    return d


class _JobCancelled(Exception):
    """Cooperative cancel: raised at a stage boundary (before ASR / before summarize)
    when the job's cancel flag is set, so the daemon thread aborts cleanly."""


def _raise_if_cancelled(state: dict[str, Any]) -> None:
    if state.get("cancel"):
        raise _JobCancelled()


def _run_meeting_job(job_id: str, req: MeetingNoteReq, vault_path: str) -> None:
    from audio_preflight import audio_preflight
    state = _MEETING_JOBS[job_id]
    try:
        mode, model = _resolve_asr_tier(req.tier, req.asr_mode, req.asr_model, req.precise)
        # Cloud tier 的 UI model 欄位不是實際 ASR model。把 provider model、語言與 timestamp
        # pipeline 版本納入 key，避免 whisper-1 修正後仍重用舊的單段 [00:00] checkpoint。
        provider_model = model_for_task("asr", "whisper-1") if mode == "cloud" else ""
        key = _meeting_checkpoint_key(
            req.audio_path,
            mode,
            model,
            language=req.language or "auto",
            provider_model=provider_model,
        )
        prior = _read_meeting_checkpoint(key)
        state["stage"] = "summarize" if prior else "asr"

        def on_transcript(t: str) -> None:
            _meeting_checkpoint_path(key).write_text(
                json.dumps({
                    "schema_version": _MEETING_CHECKPOINT_SCHEMA,
                    "timestamp_pipeline": _ASR_TIMESTAMP_PIPELINE_VERSION,
                    "transcript": t,
                    "audio_path": req.audio_path,
                    "asr_mode": mode,
                    "asr_model": model,
                    "provider_model": provider_model,
                    "language": req.language or "auto",
                }, ensure_ascii=False),
                encoding="utf-8")
            state["stage"] = "summarize"
            _persist_job_state(job_id, state)

        # cancel 注入在兩個階段邊界（都在昂貴操作前；ASR 後已 checkpoint，取消不浪費轉錄）。
        asr_inner = _meeting_asr_fn_for(req)

        def asr_fn(p):
            _raise_if_cancelled(state)
            return asr_inner(p)

        def summarizer_fn(t):
            _raise_if_cancelled(state)
            return _summarize_meeting(t, req.template_id, req.glossary)

        result = run_meeting_note(
            req.audio_path,
            asr_fn=asr_fn,
            summarizer_fn=summarizer_fn,
            writer_fn=lambda data: write_meeting_note(
                vault_path, data["summary"], data["transcript"], data["audio_path"]),
            dry_run=False,
            preflight_fn=lambda p: audio_preflight(str(p)),
            transcript=prior,
            on_transcript=on_transcript,
            review_only=req.review_only,
        )
        if not result.get("ok"):
            state["status"], state["error"] = "error", result.get("reason", "unknown")
            _persist_job_state(job_id, state)
            return
        state["stage"] = result.get("stage", "written")
        state["summary"] = result.get("summary")
        state["transcript"] = result.get("transcript")
        state["write"] = result.get("write")
        state["status"] = "review_ready" if state["stage"] == "review_ready" else "done"
        if state["stage"] == "review_ready":
            _persist_meeting_draft(job_id, {
                "schema_id": "meeting-review-draft/v1",
                "job_id": job_id,
                "status": "review_ready",
                "audio_path": req.audio_path,
                "transcript": state["transcript"],
                "summary": state["summary"],
                "template_id": req.template_id,
                "glossary": req.glossary,
            })
        _persist_job_state(job_id, state)
    except _JobCancelled:
        state["status"], state["stage"] = "cancelled", "cancelled"
        _persist_job_state(job_id, state)
    except Exception as exc:  # noqa: BLE001 — 任何失敗浮到輪詢，不讓背景執行緒崩
        state["status"], state["error"] = "error", str(exc)
        _persist_job_state(job_id, state)


def _spawn_meeting_job(req: MeetingNoteReq, vault_path: str, job_id: str) -> dict[str, Any]:
    with _MEETING_JOB_LOCK:
        if any(j["status"] == "running" for j in _MEETING_JOBS.values()):
            raise HTTPException(409, "another meeting job is already running")  # 一次一個（n=1）
        _MEETING_JOBS[job_id] = {"status": "running", "stage": "intake", "error": "",
                                 "summary": None, "transcript": None, "write": None, "audio_path": req.audio_path,
                                 "cancel": False}
        _persist_job_state(job_id, _MEETING_JOBS[job_id])
    threading.Thread(target=_run_meeting_job, args=(job_id, req, vault_path), daemon=True).start()
    return {"ok": True, "job_id": job_id}


# whisper/faster-whisper 從中文 YouTube 字幕學到的罐頭幻覺（語言不符/靜音時冒出）——
# 這些片語極獨特、不會出現在真實會議語音，含任一即整行丟。語言鎖定後仍當防禦層。
_ASR_HALLUCINATION_SUBSTRINGS = (
    "請不吝點贊", "點贊", "明鏡與點點欄目", "點點欄目", "打賞支援明鏡",
    "字幕由Amara", "Amara.org", "字幕志愿者", "字幕志願者",
)


def _strip_asr_hallucinations(text: str) -> str:
    kept = [
        line for line in text.splitlines()
        if not any(h in line for h in _ASR_HALLUCINATION_SUBSTRINGS)
    ]
    return "\n".join(kept)


# 本機 LLM（Ollama）一鍵下載：沿用 local-asr-model 的 background+poll+lock 範式（不平行造）。
# 模型走 Ollama /api/pull 串流進度；Ollama 本體不在此代裝（精靈給安裝指引）。
_OLLAMA_RECOMMENDED_MODEL = "gemma3:4b"
_OLLAMA_PULLS: dict[str, dict[str, Any]] = {}
_OLLAMA_PULL_LOCK = threading.Lock()


def _pull_ollama_model(name: str) -> None:
    """Stream pull progress from Ollama into _OLLAMA_PULLS for the UI to poll.
    Ollama owns download/resume/integrity; we only relay bytes and errors."""
    state = _OLLAMA_PULLS[name]
    try:
        payload = json.dumps({"model": name}).encode("utf-8")
        request = urllib.request.Request(
            f"http://{providers.ollama_host()}/api/pull",
            data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3600) as resp:
            for raw in resp:
                line = json.loads(raw.decode("utf-8"))
                if line.get("error"):
                    raise ValueError(line["error"])
                # 多層 blob 各自帶 total/completed；主模型 blob 遠大於其餘 → 以最新層顯示即可
                if line.get("total"):
                    state["total"] = int(line["total"])
                    state["downloaded"] = int(line.get("completed") or 0)
        if name not in providers.ollama_tags()["models"]:
            raise ValueError("下載結束但模型未出現在 Ollama，請重試")
        state["status"] = "done"
    except Exception as exc:  # noqa: BLE001 — any failure must surface to the UI, not crash the thread
        state["status"] = "error"
        state["error"] = str(exc)
