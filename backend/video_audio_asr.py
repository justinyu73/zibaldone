"""ASR rung of the CC → ASR → OCR ladder: a captionless video's audio is
downloaded (yt-dlp) and transcribed with local whisper.cpp (keyless, offline).

Operator-gated: this is only invoked by an explicit user action in the video
lane when no captions exist. The transcript flows into the same
translate → summarize → save path as native captions.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _bestaudio_stream(url: str) -> tuple[str, float]:
    """Resolve the best audio-only stream URL via the yt-dlp Python API (bundled),
    without downloading the media file itself. Returns (stream_url, duration_s)."""
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    stream = info.get("url") or ""
    if not stream:
        formats = info.get("requested_formats") or []
        stream = (formats[0].get("url") if formats else "") or ""
    if not stream:
        raise ValueError("yt-dlp 未回傳可用音訊串流（此來源可能無音訊或受限）")
    return stream, float(info.get("duration") or 0)


def transcribe_youtube_audio(url: str, *, asr_model: str = "small", max_seconds: int = 7200) -> dict[str, Any]:
    """Download audio → 16 kHz mono wav → local whisper.cpp. `max_seconds` caps
    very long videos so a runaway transcription can't hang the app."""
    from services.meetings import _meeting_asr_local

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg 不可用——本機語音轉錄需要 ffmpeg")

    stream_url, duration = _bestaudio_stream(url)
    tmp = Path(tempfile.mkdtemp(prefix="video_asr_"))
    wav = tmp / "audio.wav"
    try:
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        if max_seconds and max_seconds > 0:
            command += ["-t", str(int(max_seconds))]
        command += ["-i", stream_url, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", wav.as_posix()]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0 or not wav.exists():
            raise ValueError(f"音訊抽取失敗：{(proc.stderr or '').strip()[-300:]}")
        transcript = _meeting_asr_local(wav, language="auto", asr_model=asr_model)
        if not transcript.strip():
            raise ValueError("轉錄結果為空（此來源可能無可辨識語音）")
        return {"transcript": transcript, "duration_seconds": duration, "asr_model": asr_model}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
