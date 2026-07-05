"""Fetch YouTube metadata and transcripts."""
from __future__ import annotations

import os
import re
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

EN_CODES = ["en", "en-US", "en-GB"]
ZH_CODES = ["zh-TW", "zh-Hant", "zh", "zh-CN", "zh-Hans"]


@dataclass
class TranscriptSegment:
    text: str
    start: float
    duration: float


@dataclass
class VideoMeta:
    video_id: str
    title: str
    channel: str
    published: Optional[str]
    duration: Optional[str]
    thumbnail: Optional[str]


def extract_video_id(url: str) -> Optional[str]:
    if not url:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
        return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None

    if "youtube" in host:
        query = parse_qs(parsed.query)
        if query.get("v"):
            video_id = query["v"][0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return video_id
        match = re.match(r"^/(shorts|embed|live)/([A-Za-z0-9_-]{11})", parsed.path)
        if match:
            return match.group(2)
    return None


def fetch_meta(video_id: str) -> VideoMeta:
    title = ""
    channel = ""
    thumbnail = None
    try:
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=10,
        )
        if response.ok:
            data = response.json()
            title = data.get("title", "") or ""
            channel = data.get("author_name", "") or ""
            thumbnail = data.get("thumbnail_url")
    except requests.RequestException:
        pass

    return VideoMeta(
        video_id=video_id,
        title=title or f"YouTube {video_id}",
        channel=channel,
        published=None,
        duration=None,
        thumbnail=thumbnail or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    )


def fetch_duration_seconds(video_id: str) -> int:
    """Fast duration lookup from the watch page (no transcript fetch)."""
    try:
        response = requests.get(
            f"https://www.youtube.com/watch?v={video_id}",
            timeout=4,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        match = re.search(r'"lengthSeconds":"(\d+)"', response.text)
        return int(match.group(1)) if match else 0
    except requests.RequestException:
        return 0


def _pick_transcript(transcripts, language_codes):
    try:
        return transcripts.find_manually_created_transcript(language_codes)
    except NoTranscriptFound:
        pass
    try:
        return transcripts.find_generated_transcript(language_codes)
    except NoTranscriptFound:
        return None


def _segments(transcript) -> list[dict]:
    fetched = transcript.fetch()
    raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
    return [asdict(TranscriptSegment(**segment)) for segment in raw]


def _list_transcripts(video_id: str):
    api = YouTubeTranscriptApi()
    if hasattr(api, "list"):
        return api.list(video_id)
    return YouTubeTranscriptApi.list_transcripts(video_id)


def _parse_vtt_timestamp(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
    except ValueError:
        return 0.0
    return 0.0


def _parse_vtt(text: str) -> list[dict]:
    segments = []
    current_start = 0.0
    current_duration = 0.0
    buffer = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or line.startswith(("Kind:", "Language:", "NOTE")):
            if buffer:
                value = re.sub(r"<[^>]+>", "", " ".join(buffer)).strip()
                if value:
                    segments.append({"text": value, "start": current_start, "duration": current_duration})
                buffer = []
            continue
        if "-->" in line:
            if buffer:
                value = re.sub(r"<[^>]+>", "", " ".join(buffer)).strip()
                if value:
                    segments.append({"text": value, "start": current_start, "duration": current_duration})
                buffer = []
            start_raw, end_raw = [part.strip().split()[0] for part in line.split("-->", 1)]
            current_start = _parse_vtt_timestamp(start_raw)
            end = _parse_vtt_timestamp(end_raw)
            current_duration = max(0.0, end - current_start)
            continue
        if re.fullmatch(r"\d+", line):
            continue
        buffer.append(line)
    if buffer:
        value = re.sub(r"<[^>]+>", "", " ".join(buffer)).strip()
        if value:
            segments.append({"text": value, "start": current_start, "duration": current_duration})
    return segments


def _parse_json3(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    segments = []
    for event in data.get("events", []):
        parts = event.get("segs") or []
        value = "".join(part.get("utf8", "") for part in parts).replace("\n", " ").strip()
        if not value:
            continue
        start = float(event.get("tStartMs") or 0) / 1000
        duration = float(event.get("dDurationMs") or 0) / 1000
        segments.append({"text": value, "start": start, "duration": duration})
    return segments


def _parse_generic_json(text: str) -> list[dict]:
    # whisper/whisperx 匯出常見：{"segments":[{"start","text"}]} 或 [{...}]。
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = data.get("segments") if isinstance(data, dict) else data
    segments = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("text") or "").strip()
        if not value:
            continue
        start = float(item.get("start") or 0)
        end = item.get("end")
        duration = max(0.0, float(end) - start) if end is not None else 0.0
        segments.append({"text": value, "start": start, "duration": duration})
    return segments


def parse_imported_transcript(text: str, filename: str = "") -> list[dict]:
    """匯入既有逐字稿（make_vs_take GLUE）→ {text,start,duration} segments。
    SRT 與 VTT 同走 _parse_vtt（時碼 , 與數字 index 已被既有解析吃）；JSON 走 json3 或
    whisper 通用格式；純 TXT 無時碼 → 回 []，呼叫端退回純文字（distill 自然略過 [mm:ss]）。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    head = text.lstrip()[:1]
    if ext in {"vtt", "srt"} or "-->" in text[:4000]:
        return _parse_vtt(text)
    if ext in {"json", "json3"} or head in "{[":
        return _parse_json3(text) or _parse_generic_json(text)
    return []


def _choose_subtitle_track(tracks: dict, language_codes: list[str]) -> tuple[str, list[dict]] | tuple[None, None]:
    for code in language_codes:
        if code in tracks:
            return code, tracks[code]
    for code, entries in tracks.items():
        if any(code.lower().startswith(prefix.lower()) for prefix in language_codes for prefix in [prefix.split("-")[0]]):
            return code, entries
    return None, None


def _fetch_subtitle_entries(entries: list[dict]) -> list[dict]:
    for entry in entries or []:
        ext = entry.get("ext")
        if ext not in {"json3", "vtt", "srv3", "srv2", "srv1", "ttml"}:
            continue
        url = entry.get("url")
        if not url:
            continue
        try:
            response = requests.get(url, timeout=20)
            if response.ok and response.text.strip():
                parsed = _parse_json3(response.text) if ext == "json3" else _parse_vtt(response.text)
                if parsed:
                    return parsed
        except requests.RequestException:
            continue
    return []


def _fetch_transcript_with_ytdlp(video_id: str) -> dict:
    result = {"en": None, "zh": None, "available_langs": [], "error": None}
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        result["error"] = f"yt-dlp fallback unavailable: {exc}"
        return result

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with YoutubeDL({"quiet": True, "skip_download": True, "writesubtitles": True, "writeautomaticsub": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"yt-dlp 抓取字幕失敗：{exc}"
        return result

    subtitles = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    all_tracks = {**auto, **subtitles}
    result["available_langs"] = list(all_tracks.keys())

    en_code, en_entries = _choose_subtitle_track(all_tracks, EN_CODES)
    zh_code, zh_entries = _choose_subtitle_track(all_tracks, ZH_CODES)
    if en_entries:
        result["en"] = _fetch_subtitle_entries(en_entries)
        if en_code and not result.get("fallback_lang"):
            result["fallback_lang"] = en_code
    if zh_entries:
        result["zh"] = _fetch_subtitle_entries(zh_entries)
        if zh_code:
            result["zh_lang"] = zh_code
    if not result.get("en") and not result.get("zh"):
        result["error"] = "yt-dlp 找到字幕軌但無法下載字幕內容" if all_tracks else "yt-dlp 找不到可用字幕"
    return result


def _resolve_ytdlp_binary() -> str:
    override = os.getenv("YT_DLP_BINARY", "").strip()
    if override:
        return override
    return shutil.which("yt-dlp") or ""


def _run_ytdlp_subtitle_metadata(video_id: str, *, timeout: int = 60) -> dict:
    executable = _resolve_ytdlp_binary()
    if not executable:
        raise RuntimeError("yt-dlp binary is not available")
    url = f"https://www.youtube.com/watch?v={video_id}"
    command = [
        executable,
        "--no-playlist",
        "--skip-download",
        "--dump-json",
        "--no-warnings",
        url,
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("yt-dlp subtitle metadata probe timed out") from exc
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()[-1200:]
        raise RuntimeError(f"yt-dlp subtitle metadata probe failed: {error}")
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("yt-dlp subtitle metadata probe returned invalid JSON") from exc


def fetch_ytdlp_subtitle_fallback_only(
    video_id: str,
    language_codes: list[str] | None = None,
    *,
    preview_limit: int = 5,
) -> dict:
    requested_languages = language_codes or [*ZH_CODES, *EN_CODES]
    result = {
        "ok": False,
        "provider": "yt_dlp",
        "mode": "skip_download_subtitles_only_no_cookies_no_media_stream",
        "requested_languages": requested_languages,
        "available_languages": [],
        "selected_language": "",
        "segment_count": 0,
        "segment_preview": [],
        "error_code": "",
        "message": "",
        "route_state": "ytdlp_subtitle_unavailable_review_required",
        "yt_dlp_fallback_used": False,
        "media_downloaded": False,
        "credential_read": False,
        "persisted": False,
    }
    try:
        if not _resolve_ytdlp_binary():
            result["error_code"] = "ytdlp_binary_unavailable"
            result["message"] = "yt-dlp binary is not available"
            result["route_state"] = "ytdlp_subtitle_fallback_blocked_or_retry_later"
            return result
        result["yt_dlp_fallback_used"] = True
        info = _run_ytdlp_subtitle_metadata(video_id)
        subtitles = info.get("subtitles") or {}
        automatic = info.get("automatic_captions") or {}
        all_tracks = {**automatic, **subtitles}
        result["available_languages"] = list(all_tracks.keys())
        selected_language, entries = _choose_subtitle_track(all_tracks, requested_languages)
        if not entries:
            result["error_code"] = "ytdlp_subtitle_unavailable"
            result["message"] = "yt-dlp found no reviewable subtitle tracks"
            return result

        segments = _fetch_subtitle_entries(entries)
        if not segments:
            result["selected_language"] = selected_language or ""
            result["error_code"] = "ytdlp_subtitle_fetch_failed"
            result["message"] = "yt-dlp found subtitle tracks but could not fetch reviewable text"
            return result

        result.update(
            {
                "ok": True,
                "selected_language": selected_language or "",
                "segment_count": len(segments),
                "segment_preview": segments[: max(1, preview_limit)],
                "error_code": "",
                "message": "",
                "route_state": "ytdlp_subtitle_segments_reviewable",
            }
        )
        return result
    except Exception as exc:  # noqa: BLE001
        result["error_code"] = "ytdlp_subtitle_probe_failed"
        result["message"] = str(exc)
        result["route_state"] = "ytdlp_subtitle_fallback_blocked_or_retry_later"
        return result


def fetch_transcript(video_id: str) -> dict:
    result = {"en": None, "zh": None, "available_langs": [], "error": None}
    try:
        transcripts = _list_transcripts(video_id)
        result["available_langs"] = [item.language_code for item in transcripts]

        en_transcript = _pick_transcript(transcripts, EN_CODES)
        zh_transcript = _pick_transcript(transcripts, ZH_CODES)

        if en_transcript:
            result["en"] = _segments(en_transcript)
        if zh_transcript:
            result["zh"] = _segments(zh_transcript)
            result["zh_lang"] = zh_transcript.language_code

        if not en_transcript and not zh_transcript:
            fallback = next(iter(transcripts), None)
            if fallback:
                result["en"] = _segments(fallback)
                result["fallback_lang"] = fallback.language_code

    except TranscriptsDisabled:
        result["error"] = "此影片已停用字幕"
    except VideoUnavailable:
        result["error"] = "此影片無法使用或不存在"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"抓取字幕失敗：{exc}"
    if result.get("error") or (not result.get("en") and not result.get("zh")):
        fallback = _fetch_transcript_with_ytdlp(video_id)
        if fallback.get("en") or fallback.get("zh"):
            return fallback
        if fallback.get("available_langs") and not result.get("available_langs"):
            result["available_langs"] = fallback["available_langs"]
        if fallback.get("error"):
            result["error"] = f"{result.get('error') or '主要字幕 API 無結果'}；fallback: {fallback['error']}"
    return result


def _classify_native_caption_error(error: Exception) -> tuple[str, str]:
    lowered = str(error).lower()
    if any(
        token in lowered
        for token in [
            "429",
            "too many",
            "rate",
            "forbidden",
            "403",
            "blocked",
            "nameresolutionerror",
            "failed to resolve",
            "connection",
            "max retries",
            "timeout",
        ]
    ):
        return "rate_limited_or_blocked", "blocked_or_retry_later"
    if any(token in lowered for token in ["parse", "json", "xml", "vtt", "decode"]):
        return "parser_failure", "blocked_or_retry_later"
    return "parser_failure", "blocked_or_retry_later"


def fetch_native_caption_api_only(
    video_id: str,
    language_codes: list[str] | None = None,
    *,
    preview_limit: int = 5,
) -> dict:
    requested_languages = language_codes or [*ZH_CODES, *EN_CODES]
    result = {
        "ok": False,
        "provider": "youtube_transcript_api",
        "requested_languages": requested_languages,
        "available_languages": [],
        "selected_language": "",
        "segment_count": 0,
        "segment_preview": [],
        "error_code": "",
        "message": "",
        "route_state": "native_caption_unavailable",
        "yt_dlp_fallback_used": False,
        "media_downloaded": False,
        "credential_read": False,
        "persisted": False,
    }
    try:
        transcripts = _list_transcripts(video_id)
        result["available_languages"] = [item.language_code for item in transcripts]
        selected = _pick_transcript(transcripts, requested_languages)
        if not selected:
            result["error_code"] = "native_caption_unavailable"
            result["message"] = "No native captions matched the requested languages"
            return result

        segments = _segments(selected)
        if not segments:
            result["error_code"] = "native_caption_unavailable"
            result["message"] = "Native caption track returned no segments"
            return result

        result.update(
            {
                "ok": True,
                "selected_language": selected.language_code,
                "segment_count": len(segments),
                "segment_preview": segments[: max(1, preview_limit)],
                "error_code": "",
                "message": "",
                "route_state": "native_caption_available",
            }
        )
        return result
    except TranscriptsDisabled:
        result["error_code"] = "transcript_disabled"
        result["message"] = "This video has disabled captions"
        return result
    except VideoUnavailable:
        result["error_code"] = "video_unavailable"
        result["message"] = "This video is unavailable"
        result["route_state"] = "blocked_or_retry_later"
        return result
    except NoTranscriptFound:
        result["error_code"] = "native_caption_unavailable"
        result["message"] = "No native captions were found"
        return result
    except Exception as exc:  # noqa: BLE001
        error_code, route_state = _classify_native_caption_error(exc)
        result["error_code"] = error_code
        result["message"] = f"Native caption API probe failed: {exc}"
        result["route_state"] = route_state
        return result


def segments_to_plain_text(segments: list[dict]) -> str:
    if not segments:
        return ""
    return " ".join(segment["text"].replace("\n", " ").strip() for segment in segments if segment.get("text"))


def segments_to_timestamped(segments: list[dict]) -> str:
    if not segments:
        return ""
    lines = []
    for segment in segments:
        start = int(segment.get("start", 0))
        minutes, seconds = divmod(start, 60)
        hours, minutes = divmod(minutes, 60)
        timestamp = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
        lines.append(f"[{timestamp}] {segment.get('text', '').strip()}")
    return "\n".join(lines)
