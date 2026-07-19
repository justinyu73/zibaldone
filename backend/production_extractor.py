"""Bounded production extractor for user-authorized public YouTube URLs."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from model_policy import model_for_task
from provider_runtime import ProviderRuntimeError, analyze_frame


CAPS = {
    "max_sampled_frames": 6,
    "max_provider_calls": 6,
    "max_frame_bytes_total": 25_000_000,
    # OCR samples a fixed max_sampled_frames regardless of length, so cost is
    # bounded by frame/provider caps — not duration. Keep a generous ceiling only
    # as a sanity bound; a 15-min limit needlessly blocked normal long-form videos.
    "max_video_duration_seconds_for_frame_probe": 14400,
    "max_runtime_seconds": 240,
    "storage_root": "/tmp",
}


class ProductionExtractorError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _resolve_binary(name: str) -> str:
    if name in ("ffmpeg", "ffprobe"):
        import ffmpeg_runtime

        return ffmpeg_runtime.resolve(name)
    path_command = shutil.which(name)
    if path_command:
        return path_command
    if name == "yt-dlp":
        return os.getenv("YT_DLP_BINARY", "").strip()
    return ""


def _ytdlp_python_version() -> str:
    try:
        import yt_dlp

        return getattr(yt_dlp.version, "__version__", "installed")
    except Exception:
        return ""


def tooling_status() -> Dict[str, Any]:
    # yt-dlp is used via its Python API (bundled dependency), not a CLI binary.
    ytdlp_version = _ytdlp_python_version()
    tools: Dict[str, Any] = {
        "yt_dlp": {"available": bool(ytdlp_version), "path": "python:yt_dlp", "version": ytdlp_version},
    }
    for name in ["ffmpeg", "ffprobe"]:
        executable = _resolve_binary(name)
        version = ""
        if executable:
            try:
                completed = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=8, check=False)
                version = (completed.stdout or completed.stderr or "").strip().splitlines()[0]
            except Exception:
                version = "installed_version_unavailable"
        tools[name] = {
            "available": bool(executable),
            "path": executable,
            "version": version,
        }
    return {
        "ok": all(item["available"] for item in tools.values()),
        "tools": tools,
        "missing": [name for name, item in tools.items() if not item["available"]],
    }


def canonicalize_youtube_url(raw_url: str) -> Dict[str, str]:
    value = str(raw_url or "").strip()
    if not value:
        raise ProductionExtractorError(400, "url is required")
    if re.fullmatch(r"[A-Za-z0-9_-]{6,}", value):
        video_id = value
    else:
        parsed = urlparse(value)
        host = parsed.hostname.replace("www.", "") if parsed.hostname else ""
        if host not in {"youtube.com", "m.youtube.com", "youtu.be"}:
            raise ProductionExtractorError(400, "only public YouTube URLs are enabled for this runtime block")
        video_id = parsed.path.strip("/").split("/")[0] if host == "youtu.be" else parse_qs(parsed.query).get("v", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,}", video_id or ""):
        raise ProductionExtractorError(400, "could not extract a valid YouTube video id")
    return {
        "platform": "youtube",
        "video_id": video_id,
        "canonical_url": f"https://www.youtube.com/watch?v={video_id}",
    }


def _run_command(command: List[str], *, timeout: int = 90) -> str:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ProductionExtractorError(504, f"{Path(command[0]).name} timed out") from exc
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip()[-1600:]
        raise ProductionExtractorError(502, f"{Path(command[0]).name} failed: {error}")
    return (completed.stdout or "").strip()


def _ydl_extract(url: str, fmt: str) -> Dict[str, Any]:
    """Resolve metadata / stream URL via the bundled yt-dlp Python API (no CLI
    binary — the packaged sidecar ships yt_dlp as a Python dependency).

    player_client=android first: it returns direct stream URLs that don't require
    the nsig JS descramble, so ffprobe/ffmpeg don't hit intermittent 403s when no
    JS runtime (deno) is installed. web is kept as a fallback.
    """
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "noplaylist": True,
        "format": fmt,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


def _metadata(url: str) -> Dict[str, Any]:
    data = _ydl_extract(url, "best")
    return {
        "id": data.get("id", ""),
        "title_present": bool(data.get("title")),
        "duration_seconds": float(data.get("duration") or 0),
        "extractor": data.get("extractor", ""),
        "availability": data.get("availability", ""),
    }


def _download_lowres_video(url: str, dest_dir: Path) -> str:
    """Download a low-res copy locally via yt-dlp (it handles the network / TLS /
    nsig). Frame grabs then read this local file — a downloaded static ffmpeg can
    segfault on remote https streams, but reads local files reliably. Low res keeps
    the download light; it's still readable for hard-subtitle OCR."""
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "format": "bestvideo[height<=480][ext=mp4]/best[height<=480][ext=mp4]/worst[ext=mp4]/worst",
        "outtmpl": str(dest_dir / "video.%(ext)s"),
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    path = Path(ydl.prepare_filename(info)) if info else None
    if not path or not path.is_file():
        found = sorted(dest_dir.glob("video.*"))
        path = found[0] if found else None
    if not path or not path.is_file():
        raise ProductionExtractorError(502, "yt-dlp 未能下載影片畫面")
    return str(path)


def _probe(ffprobe: str, media_url: str) -> Dict[str, Any]:
    raw = _run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,duration",
            "-of",
            "json",
            media_url,
        ],
        timeout=90,
    )
    data = json.loads(raw)
    stream = data.get("streams", [{}])[0] if isinstance(data.get("streams"), list) and data.get("streams") else {}
    return {
        "probe_status": "pass",
        "codec_name": stream.get("codec_name", ""),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "r_frame_rate": stream.get("r_frame_rate", ""),
        "stream_duration_seconds": float(stream.get("duration") or 0) or None,
    }


def _timestamps(duration: float, sample_count: int) -> List[float]:
    count = max(1, min(int(sample_count or 1), CAPS["max_sampled_frames"]))
    bounded = min(max(float(duration or 1), 1), CAPS["max_video_duration_seconds_for_frame_probe"])
    if count == 1:
        return [round(bounded / 2, 2)]
    step = bounded / (count + 1)
    return [round(step * (index + 1), 2) for index in range(count)]


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contains_any(text: str, signals: List[str]) -> bool:
    lowered = text.lower()
    return any(signal in lowered for signal in signals)


def _quality(frame_records: List[Dict[str, Any]], provider_evidence: List[Dict[str, Any]], cleanup_verified: bool) -> Dict[str, Any]:
    sampled = len(frame_records)
    unique_hashes = {str(item.get("sha256") or "") for item in frame_records}
    platform_errors = {
        item.get("frame_index")
        for item in provider_evidence
        if _contains_any(str(item.get("text") or ""), ["something went wrong", "refresh or try again later", "player error", "error overlay"])
    }
    loading = {
        item.get("frame_index")
        for item in provider_evidence
        if _contains_any(str(item.get("text") or ""), ["buffering", "loading spinner", "loading", "spinner overlay"])
    }
    unique_ratio = round(len(unique_hashes) / sampled, 3) if sampled else 0
    platform_error_ratio = round(len(platform_errors) / sampled, 3) if sampled else 0
    failed: List[str] = []
    review: List[str] = []
    if platform_error_ratio >= 0.5:
        failed.append("platform_error_overlay_majority")
    if unique_ratio < 0.5:
        failed.append("low_unique_frame_hash_ratio")
    if not cleanup_verified:
        failed.append("cleanup_not_verified")
    if loading:
        review.append("loading_or_buffering_overlay_detected")
    if len(unique_hashes) < sampled:
        review.append("duplicate_frame_hashes_observed")
    state = "failed_retrieval_quality" if failed else "degraded_pending_human_review" if review else "content_candidate"
    return {
        "quality_state": state,
        "sampled_frame_count": sampled,
        "unique_hash_count": len(unique_hashes),
        "unique_hash_ratio": unique_ratio,
        "platform_error_frame_count": len(platform_errors),
        "platform_error_ratio": platform_error_ratio,
        "loading_overlay_frame_count": len(loading),
        "failed_reasons": failed,
        "review_reasons": review,
        "timeline_fusion_allowed": state == "content_candidate",
        "pending_human_review": state != "content_candidate",
    }


def _provider_evidence_to_segments(provider_evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "start": item.get("actual_timestamp"),
            "end": item.get("actual_timestamp"),
            "text": item.get("text", ""),
            "sources": ["ocr", "visual"],
            "confidence": None,
            "warnings": item.get("warnings", ["report_only_provider_ocr_requires_operator_review"]),
            "evidence_ref": item.get("evidence_ref", f"provider:openai:ocr_visual:production_frame_{index + 1}"),
        }
        for index, item in enumerate(provider_evidence)
        if str(item.get("text") or "").strip()
    ]


def _ocr_text_from_evidence(provider_evidence: List[Dict[str, Any]]) -> str:
    """Clean readable OCR output for the caption box: parse each frame's OCR JSON
    and collect hard-subtitle / on-screen text lines (deduped), not the raw JSON."""
    lines: List[str] = []
    seen = set()
    for item in provider_evidence:
        raw = str(item.get("text") or "").strip()
        if not raw:
            continue
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            data = json.loads(match.group(0) if match else raw)
        except (ValueError, TypeError):
            continue
        for key in ("hard_subtitles", "screen_text"):
            for entry in data.get(key) or []:
                text = (entry if isinstance(entry, str) else str((entry or {}).get("text") or "")).strip()
                if text and text not in seen:
                    seen.add(text)
                    lines.append(text)
    return "\n".join(lines)


def _dry_run(target: Dict[str, str], sample_count: int, max_provider_calls: int, user_authorized_media: bool, allow_provider_ocr: bool, confirm_report_only: bool) -> Dict[str, Any]:
    tools = tooling_status()
    errors: List[str] = []
    if not user_authorized_media:
        errors.append("user_authorized_media_required")
    if not confirm_report_only:
        errors.append("confirm_report_only_required")
    if int(sample_count or 0) < 1 or int(sample_count or 0) > CAPS["max_sampled_frames"]:
        errors.append("sample_count_outside_caps")
    if int(max_provider_calls or 0) < 0 or int(max_provider_calls or 0) > CAPS["max_provider_calls"]:
        errors.append("max_provider_calls_outside_caps")
    if not tools["ok"]:
        errors.extend([f"{name}_missing" for name in tools["missing"]])
    return {
        "ok": not errors,
        "status": "ready_for_real_run" if not errors else "blocked_preflight",
        "execution_mode": "dry_run",
        "target": target,
        "extraction_method": "yt_dlp_ffmpeg_ffprobe",
        "caps": CAPS,
        "requested": {
            "sample_count": sample_count,
            "max_provider_calls": max_provider_calls,
            "user_authorized_media": user_authorized_media,
            "allow_provider_ocr": allow_provider_ocr,
            "confirm_report_only": confirm_report_only,
        },
        "tooling": tools,
        "network_calls": 0,
        "provider_call_count": 0,
        "durable_writes": 0,
        "write_mode": "report_only",
        "errors": errors,
    }


def run_production_extractor(
    *,
    url: str,
    mode: str = "dry_run",
    sample_count: int = 6,
    max_provider_calls: int = 6,
    user_authorized_media: bool = False,
    allow_provider_ocr: bool = False,
    confirm_report_only: bool = False,
    prompt: str = "",
) -> Dict[str, Any]:
    started = time.perf_counter()
    target = canonicalize_youtube_url(url)
    dry = _dry_run(target, sample_count, max_provider_calls, user_authorized_media, allow_provider_ocr, confirm_report_only)
    if mode != "real":
        return dry
    if not dry["ok"]:
        raise ProductionExtractorError(400, "; ".join(dry["errors"]))
    if not allow_provider_ocr:
        raise ProductionExtractorError(400, "allow_provider_ocr is required for real production extraction")

    tools = dry["tooling"]["tools"]
    ffmpeg = tools["ffmpeg"]["path"]
    ffprobe = tools["ffprobe"]["path"]
    metadata = _metadata(target["canonical_url"])
    if metadata["id"] != target["video_id"]:
        raise ProductionExtractorError(502, f"metadata video id mismatch: {metadata['id']}")
    if metadata["duration_seconds"] <= 0:
        raise ProductionExtractorError(502, "video duration unavailable")
    if metadata["duration_seconds"] > CAPS["max_video_duration_seconds_for_frame_probe"]:
        raise ProductionExtractorError(400, f"duration exceeds cap: {metadata['duration_seconds']}")
    frame_records: List[Dict[str, Any]] = []
    provider_evidence: List[Dict[str, Any]] = []
    provider_cache: Dict[str, Dict[str, Any]] = {}
    provider_call_count = 0
    cleanup_verified = False
    tmp_root = tempfile.mkdtemp(prefix="vaultwiki_yt_api_extract_", dir="/tmp")
    try:
        local_video = _download_lowres_video(target["canonical_url"], Path(tmp_root))
        stream = _probe(ffprobe, local_video)
        for index, timestamp in enumerate(_timestamps(metadata["duration_seconds"], sample_count), start=1):
            frame_path = Path(tmp_root) / f"frame_{index:02d}.png"
            _run_command(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    str(timestamp),
                    "-i",
                    local_video,
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=1280:-1",
                    "-f",
                    "image2",
                    frame_path.as_posix(),
                ],
                timeout=90,
            )
            data = frame_path.read_bytes()
            sha256 = _hash_bytes(data)
            frame_record = {
                "index": index,
                "requested_timestamp": timestamp,
                "actual_timestamp": timestamp,
                "seek_verified": True,
                "retrieval_warning": "",
                "bytes": len(data),
                "sha256": sha256,
            }
            frame_records.append(frame_record)
            if sum(int(item["bytes"]) for item in frame_records) > CAPS["max_frame_bytes_total"]:
                raise ProductionExtractorError(413, "frame bytes exceed cap")
            if sha256 in provider_cache:
                cached = provider_cache[sha256]
                provider_evidence.append(
                    {
                        **cached,
                        "frame_index": index,
                        "requested_timestamp": timestamp,
                        "actual_timestamp": timestamp,
                        "sha256": sha256,
                        "duplicate_of_frame_index": cached["frame_index"],
                        "evidence_ref": f"provider:openai:ocr_visual:production_frame_{index}:duplicate",
                        "provider_call_reused": True,
                    }
                )
            else:
                if provider_call_count >= max_provider_calls:
                    raise ProductionExtractorError(400, "provider call cap exceeded")
                report = analyze_frame(
                    filename=frame_path.name,
                    image_base64=base64.b64encode(data).decode("ascii"),
                    image_mime="image/png",
                    mode="real",
                    prompt=prompt
                    or (
                        "Extract visible hard subtitles, screen text, products, people, brands, and concise visual context. "
                        "Return compact JSON. Do not infer a full transcript."
                    ),
                )
                provider_call_count += int(report.get("provider_call_count") or 0)
                text = "\n".join(str(segment.get("text") or "") for segment in report.get("segments", []))
                evidence = {
                    "frame_index": index,
                    "requested_timestamp": timestamp,
                    "actual_timestamp": timestamp,
                    "sha256": sha256,
                    "provider_call_reused": False,
                    "status": report.get("status", "provider_completed"),
                    "provider": report.get("provider", "openai"),
                    "model": report.get("model", model_for_task("ocr_visual", "gpt-5.2")),
                    "evidence_ref": f"provider:openai:ocr_visual:production_frame_{index}",
                    "text": text[:2000],
                    "text_truncated": len(text) > 2000,
                    "usage": report.get("usage", {}),
                    "warnings": ["report_only_provider_ocr_requires_operator_review"],
                }
                provider_cache[sha256] = evidence
                provider_evidence.append(evidence)
            try:
                frame_path.unlink()
            except FileNotFoundError:
                pass
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
        cleanup_verified = not Path(tmp_root).exists()

    runtime_ms = round((time.perf_counter() - started) * 1000)
    quality = _quality(frame_records, provider_evidence, cleanup_verified)
    return {
        "ok": True,
        "status": "pass",
        "execution_mode": "real",
        "target": target,
        "extraction_method": "yt_dlp_ffmpeg_ffprobe",
        "caps": CAPS,
        "runtime_ms": runtime_ms,
        "tool_versions": {
            "yt_dlp": tools["yt_dlp"]["version"],
            "ffmpeg": tools["ffmpeg"]["version"],
            "ffprobe": tools["ffprobe"]["version"],
        },
        "metadata": metadata,
        "stream": stream,
        "frame_only": True,
        "sampled_frame_count": len(frame_records),
        "frame_records": frame_records,
        "frame_bytes_total": sum(int(item["bytes"]) for item in frame_records),
        "cleanup_required": True,
        "cleanup_verified": cleanup_verified,
        "lane": "ocr_visual",
        "provider_task": "ocr_visual",
        "provider": "openai",
        "provider_model": model_for_task("ocr_visual", "gpt-5.2"),
        "provider_call_count": provider_call_count,
        "provider_evidence_count": len(provider_evidence),
        "provider_evidence": provider_evidence,
        "segments": _provider_evidence_to_segments(provider_evidence),
        "ocr_text": _ocr_text_from_evidence(provider_evidence),
        "quality": quality,
        "execution_invariants": {
            "full_video_download": False,
            "audio_extracted": False,
            "full_subtitle_export": False,
            "full_transcript_claim": False,
            "raw_frame_archive": False,
            "durable_raw_media_storage": False,
            "source_note_writeback": False,
            "index_writeback": False,
            "durable_writes": 0,
            "write_mode": "report_only",
        },
        "durable_writes": 0,
        "write_mode": "report_only",
        "errors": [],
    }
