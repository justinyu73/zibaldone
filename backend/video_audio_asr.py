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


def _download_bestaudio(url: str, dest_dir: Path) -> tuple[Path, float]:
    """Download the best audio-only track to a local file via yt-dlp. yt-dlp (not
    ffmpeg) does the network fetch — it handles YouTube's TLS/session/nsig, and it
    keeps ffmpeg off the network entirely (a downloaded static ffmpeg can segfault
    on remote https streams; it processes local files reliably)."""
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(dest_dir / "audio.%(ext)s"),
        # android client → direct URLs without the nsig JS descramble (no deno needed).
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    downloaded = Path(ydl.prepare_filename(info)) if info else None
    if not downloaded or not downloaded.is_file():
        found = sorted(dest_dir.glob("audio.*"))
        downloaded = found[0] if found else None
    if not downloaded or not downloaded.is_file():
        raise ValueError("yt-dlp 未能下載音訊（此來源可能無音訊或受限）")
    return downloaded, float((info or {}).get("duration") or 0)


def transcribe_youtube_audio(url: str, *, asr_model: str = "small", max_seconds: int = 7200) -> dict[str, Any]:
    """Download audio → 16 kHz mono wav → local whisper.cpp. `max_seconds` caps
    very long videos so a runaway transcription can't hang the app."""
    from services.meetings import _meeting_asr_local
    import ffmpeg_runtime

    ffmpeg = ffmpeg_runtime.resolve("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg 尚未就緒——請先下載媒體工具（ffmpeg）")

    tmp = Path(tempfile.mkdtemp(prefix="video_asr_"))
    wav = tmp / "audio.wav"
    try:
        audio_file, duration = _download_bestaudio(url, tmp)
        command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        if max_seconds and max_seconds > 0:
            command += ["-t", str(int(max_seconds))]
        command += ["-i", audio_file.as_posix(), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", wav.as_posix()]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0 or not wav.exists():
            raise ValueError(f"音訊抽取失敗：{(proc.stderr or '').strip()[-300:]}")
        transcript = _meeting_asr_local(wav, language="auto", asr_model=asr_model)
        if not transcript.strip():
            raise ValueError("轉錄結果為空（此來源可能無可辨識語音）")
        return {"transcript": transcript, "duration_seconds": duration, "asr_model": asr_model}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
