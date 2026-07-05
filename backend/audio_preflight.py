"""Audio quality pre-flight (語音 lane 薄層 BUILD).

Before transcribing, answer one question for the operator: 能不能用?
Garbage-in → garbage-out 的事前攔截，不是成本估算。ffprobe 取時長/取樣率，
ffmpeg volumedetect 取 mean/max 音量，據此給一句白話判定。純讀取，不改音檔。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

MIN_USABLE_SECONDS = 1.0
SILENCE_MEAN_DB = -50.0  # 整段平均比這還小 = 大概是靜音/沒收到聲
CLIP_MAX_DB = -0.5       # 峰值貼到 0 dBFS = 可能爆音削波（仍可用，警告）

_MEAN_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
_MAX_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def audio_preflight(audio_path: str) -> dict[str, Any]:
    path = Path(audio_path).expanduser()
    if not audio_path.strip():
        return {"ok": False, "usable": False, "reason": "未提供音檔路徑"}
    if not path.is_file():
        return {"ok": False, "usable": False, "reason": f"找不到音檔：{path.as_posix()}"}

    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        return {"ok": False, "usable": False, "reason": "ffmpeg/ffprobe 不可用，無法檢查音檔"}

    probe = _run(
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path.as_posix()],
        timeout=60,
    )
    if probe.returncode != 0:
        return {"ok": False, "usable": False, "reason": "ffprobe 讀不出此檔（可能不是音訊檔或已損毀）"}
    try:
        meta = json.loads(probe.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "usable": False, "reason": "ffprobe 輸出無法解析"}

    audio_streams = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio_streams:
        return {"ok": False, "usable": False, "reason": "此檔沒有音訊軌"}
    stream = audio_streams[0]
    duration = float(meta.get("format", {}).get("duration") or stream.get("duration") or 0.0)
    sample_rate = int(stream.get("sample_rate") or 0)
    channels = int(stream.get("channels") or 0)

    vol = _run(
        [ffmpeg, "-hide_banner", "-i", path.as_posix(), "-af", "volumedetect", "-f", "null", "-"],
        timeout=120,
    )
    mean_match = _MEAN_RE.search(vol.stderr or "")
    max_match = _MAX_RE.search(vol.stderr or "")
    mean_db = float(mean_match.group(1)) if mean_match else None
    max_db = float(max_match.group(1)) if max_match else None

    warnings: list[str] = []
    usable = True
    reason = "可用"
    if duration < MIN_USABLE_SECONDS:
        usable = False
        reason = f"音檔過短（{duration:.1f}s），可能不是有效錄音"
    elif mean_db is not None and mean_db <= SILENCE_MEAN_DB:
        usable = False
        reason = f"整段近乎靜音（平均 {mean_db:.0f} dB），可能沒收到聲音"
    else:
        if max_db is not None and max_db >= CLIP_MAX_DB:
            warnings.append(f"峰值貼近 0 dB（{max_db:.1f} dB），可能有爆音削波")
        reason = f"可用（{duration:.0f}s、{sample_rate} Hz、{channels} 聲道）"

    return {
        "ok": True,
        "usable": usable,
        "reason": reason,
        "duration_seconds": round(duration, 2),
        "sample_rate": sample_rate,
        "channels": channels,
        "mean_volume_db": mean_db,
        "max_volume_db": max_db,
        "warnings": warnings,
    }
