"""Meeting voice-note orchestrator (new product direction v1).

Operator-supplied meeting audio (a LOCAL file path) → ASR → meeting summary →
vault write. Meeting audio is operator-owned by nature, so this sidesteps the
platform_media_download / legal gate that blocked YouTube-no-CC and FB.

Pipeline:  audio file → (size guard) → ASR transcript → meeting summary
           (title / 摘要 / 重要整理 / 核心價值 / action_items / decisions /
            attendees / agenda) → write to the meetings dir (with rollback).

External effects (ASR / summarize / write) are injected, so orchestration —
file-exists + size guard, dry-run skips spend/write, live sequences the stages —
is testable with stubs (no audio, no provider, no spend).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

# Local engines (whisper.cpp / WhisperX) process long audio natively, so the
# meeting lane allows large files; the 25MB cap stays only on the cloud base64
# path (provider_runtime), where upload size genuinely matters.
MAX_AUDIO_BYTES = 500 * 1024 * 1024
# Relative to the user's vault ROOT (e.g. .../notes-vault/note_study). The old
# "note_study/..." prefix nested wrongly when vault_path already pointed inside
# note_study (audit bug B4).
MEETINGS_SUBFOLDER = "02_Sources/meetings"

MEETING_SUMMARY_FIELDS = (
    "title",
    "summary",
    "key_organization",
    "core_value",
    "action_items",
    "decisions",
    "attendees",
    "agenda",
)
_LIST_FIELDS = ("action_items", "decisions", "attendees", "agenda")

AsrFn = Callable[[Path], str]
SummarizeFn = Callable[[str], dict[str, Any]]
WriterFn = Callable[[dict[str, Any]], dict[str, Any]]


def _scalar(value: Any) -> str:
    """Render a scalar — or a dict the LLM returned where a string was expected
    (e.g. action_items[] of {item, owner, due_date}) — as one readable line,
    not a Python repr."""
    if isinstance(value, dict):
        parts = []
        for inner in value.values():
            if isinstance(inner, (list, tuple)):
                inner = "；".join(str(x).strip() for x in inner if str(x).strip())
            text = str(inner).strip()
            if text:
                parts.append(text)
        return " — ".join(parts)
    return str(value or "").strip()


def _lines(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [s for item in value if (s := _scalar(item))]
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _text(value: Any) -> str:
    """String field that the LLM sometimes returns as a list — flatten to a
    bulleted block instead of dumping the list literal."""
    if isinstance(value, (list, tuple)):
        return "\n".join(f"- {s}" for item in value if (s := _scalar(item)))
    return _scalar(value)


_TIMESTAMP_RE = re.compile(r"\s*\[(\d{1,2}:\d{2})\]")
_ALT_TIMESTAMP_RE = re.compile(r"[【（(]\s*(\d{1,2}:\d{2})\s*[】）)]")


def _canonicalize_timestamps(value: str) -> str:
    """Normalize common model variants so every valid timestamp reaches the UI as [mm:ss]."""
    return _ALT_TIMESTAMP_RE.sub(lambda m: f"[{m.group(1)}]", value)


def transcript_has_timestamps(transcript: str) -> bool:
    return bool(_TIMESTAMP_RE.search(transcript or ""))


def validate_summary_timestamps(summary: dict[str, Any], transcript: str) -> dict[str, Any]:
    """機械強制可驗證：摘要的 [mm:ss] 只保留對得回真實逐字稿 segment 的，模型杜撰／
    超出音檔長度的（雲端 GPT 對 36 秒音檔標 [00:45]、或逐字稿無時間戳卻硬塞 [00:00]）一律
    strip。可信筆記＝時間戳必指向真實可核對的片段；比信任 LLM 遵守 prompt 可靠
    （[[alignment-mechanical-not-instructed]]）。逐字稿無時間戳時 valid 為空＝全 strip。"""
    valid = set(_TIMESTAMP_RE.findall(_canonicalize_timestamps(transcript or "")))

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            canonical = _canonicalize_timestamps(value)
            return _TIMESTAMP_RE.sub(
                lambda m: f" [{m.group(1)}]" if m.group(1) in valid else "",
                canonical,
            ).strip()
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value
    return {key: clean(value) for key, value in summary.items()}


def normalize_meeting_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """Structure a raw meeting summary into the v1 fields + a quality verdict."""
    result: dict[str, Any] = {"schema_id": "meeting-note-summary-v1"}
    for field in MEETING_SUMMARY_FIELDS:
        if field in _LIST_FIELDS:
            result[field] = _lines(raw.get(field))
        else:
            result[field] = _text(raw.get(field))
    present = {
        field: bool(result[field])
        for field in MEETING_SUMMARY_FIELDS
    }
    warnings = [f"missing_{field}" for field in ("title", "summary", "core_value") if not present[field]]
    result["quality"] = {
        "completeness": round(sum(present.values()) / len(MEETING_SUMMARY_FIELDS), 3),
        "fields_present": present,
        "warnings": warnings,
        "review_recommended": bool(warnings),
    }
    return result


def _slug(text: str, max_len: int = 48) -> str:
    base = re.sub(r"[^\w一-鿿-]+", "-", str(text or "meeting").strip()).strip("-").lower()
    return (base or "meeting")[:max_len]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- （無）"


def build_meeting_markdown(summary: dict[str, Any], transcript: str, audio_path: str, *, today: str = "") -> str:
    today = today or datetime.now().strftime("%Y-%m-%d")
    # 音檔出處：note 保持純文字（不嵌音檔，git/Obsidian 不爆），但留可見連結 + 完整路徑
    # 以便日後從筆記查回原始錄音。路徑原樣不轉換（WSL / 掛載碟皆可）。
    audio_name = Path(audio_path).name
    audio_dir = Path(audio_path).parent.as_posix()
    audio_url = "file://" + quote(audio_path)
    return (
        f"---\n"
        f"type: source\n"
        f"source: meeting\n"
        f"title: {summary.get('title') or '會議筆記'}\n"
        f"attendees: [{', '.join(summary.get('attendees') or [])}]\n"
        f"created: {today}\n"
        f"audio_source: {audio_name}\n"
        f"audio_path: {audio_path}\n"
        f"tags: [type/source, source/meeting]\n"
        f"---\n\n"
        f"# {summary.get('title') or '會議筆記'}\n\n"
        f"## 音檔來源\n[{audio_name}]({audio_url})\n位置：{audio_dir}/\n\n"
        f"## 摘要\n{summary.get('summary') or ''}\n\n"
        f"## 重要整理\n{summary.get('key_organization') or ''}\n\n"
        f"## 核心價值\n{summary.get('core_value') or ''}\n\n"
        f"## 議程\n{_bullets(summary.get('agenda') or [])}\n\n"
        f"## 行動項目\n{_bullets(summary.get('action_items') or [])}\n\n"
        f"## 決議\n{_bullets(summary.get('decisions') or [])}\n\n"
        f"## 出席者\n{_bullets(summary.get('attendees') or [])}\n\n"
        f"## 逐字稿\n{transcript}\n"
    )


def meeting_note_metadata(content: str) -> dict[str, Any]:
    """Read the small provenance contract needed by the library playback UI."""
    source = re.search(r"(?m)^source:\s*([^\n]+)$", content or "")
    audio_path = re.search(r"(?m)^audio_path:\s*([^\n]+)$", content or "")
    path = (audio_path.group(1).strip() if audio_path else "").strip('"')
    return {
        "is_meeting": bool(source and source.group(1).strip().strip('"') == "meeting"),
        "audio_path": path,
        "audio_exists": bool(path and Path(path).expanduser().is_file()),
        "timestamps": list(dict.fromkeys(_TIMESTAMP_RE.findall(content or ""))),
    }


def replace_meeting_audio_provenance(content: str, audio_path: str) -> str:
    """Update only meeting audio provenance; preserve every other note byte."""
    metadata = meeting_note_metadata(content)
    if not metadata["is_meeting"]:
        raise ValueError("這不是 meeting note，不能修改音檔來源")
    path = Path(audio_path).expanduser()
    if not path.is_file():
        raise ValueError(f"找不到音檔：{path}")
    if path.suffix.lower() not in {".mp3", ".m4a", ".mp4", ".wav", ".webm", ".ogg"}:
        raise ValueError(f"不支援的音檔類型：{path.suffix}")

    name = path.name
    path_text = str(path)
    replacement = f"## 音檔來源\n[{name}](file://{quote(path_text)})\n位置：{path.parent.as_posix()}/\n"
    updated = re.sub(
        r"(?ms)^## 音檔來源\s*\n.*?(?=^##\s|\Z)",
        replacement + "\n",
        content,
        count=1,
    )
    if updated == content:
        raise ValueError("筆記缺少音檔來源區段")
    updated = re.sub(r"(?m)^audio_source:\s*.*$", f"audio_source: {name}", updated, count=1)
    updated = re.sub(r"(?m)^audio_path:\s*.*$", f"audio_path: {path_text}", updated, count=1)
    return updated


def write_meeting_note(vault_path: str, summary: dict[str, Any], transcript: str, audio_path: str) -> dict[str, Any]:
    from note_rollback import write_note_with_backup

    today = datetime.now().strftime("%Y-%m-%d")
    root = Path(vault_path).expanduser() / MEETINGS_SUBFOLDER
    note_path = root / f"{_slug(summary.get('title'))}_{today}.md"
    body = build_meeting_markdown(summary, transcript, audio_path, today=today)
    result = write_note_with_backup(note_path, body)
    result["relative_path"] = note_path.relative_to(Path(vault_path).expanduser()).as_posix()
    return result


def run_meeting_note(
    audio_path: str,
    *,
    asr_fn: AsrFn,
    summarizer_fn: SummarizeFn,
    writer_fn: WriterFn,
    dry_run: bool = True,
    max_audio_bytes: int = MAX_AUDIO_BYTES,
    preflight_fn: Callable[[Path], dict[str, Any]] | None = None,
    transcript: str | None = None,
    on_transcript: Callable[[str], None] | None = None,
    review_only: bool = False,
) -> dict[str, Any]:
    path = Path(audio_path).expanduser()
    if not audio_path or not path.is_file():
        return {"ok": False, "stage": "intake", "reason": "audio_file_not_found", "audio_path": str(path)}
    size = path.stat().st_size
    if size > max_audio_bytes:
        return {
            "ok": False,
            "stage": "intake",
            "reason": "audio_too_large",
            "bytes": size,
            "max_bytes": max_audio_bytes,
        }

    if dry_run:
        preflight = preflight_fn(path) if preflight_fn else None
        return {
            "ok": True,
            "dry_run": True,
            "stage": "preview",
            "audio_path": str(path),
            "bytes": size,
            "would_write_to": MEETINGS_SUBFOLDER,
            "provider_call_count": 0,
            "preflight": preflight,
        }

    # 階段 checkpoint：transcript 已給（retry 從磁碟讀回）就跳過 ASR——不重跑那段最貴的轉錄；
    # 首次轉錄成功後 on_transcript 把它落磁碟，故 ASR 後任何失敗都可從 transcript resume。
    if transcript is None:
        transcript = asr_fn(path)
        if on_transcript:
            on_transcript(transcript)
    summary = normalize_meeting_summary(summarizer_fn(transcript))
    # 只留對得回真實逐字稿 segment 的時間戳；雲端 GPT 杜撰/超出音檔長度的 strip。
    summary = validate_summary_timestamps(summary, transcript)
    if review_only:
        return {
            "ok": True,
            "dry_run": False,
            "stage": "review_ready",
            "summary": summary,
            "transcript": transcript,
            "write": None,
        }
    write = writer_fn({"transcript": transcript, "summary": summary, "audio_path": str(path)})
    return {
        "ok": True,
        "dry_run": False,
        "stage": "written",
        "summary": summary,
        "write": write,
    }
