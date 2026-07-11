"""Local whisper.cpp transcription (語音 lane 轉錄).

GLUE，不是重寫：把操作者的音檔轉成 16kHz mono wav（whisper.cpp 要求的格式），
丟給已 build 好的 whisper-cli，取回帶 timestamp 的 segments。runtime readiness
由呼叫端（main.py 既有 _local_asr_runtime_readiness）先 gate；本模組只在拿到
已解析的 binary/model 路徑後做事，runtime 缺則 ok=False，絕不假裝成功。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def _parse_whisper_json(data: dict[str, Any]) -> list[dict[str, Any]]:
    """whisper.cpp -oj 輸出 transcription[].offsets.{from,to}（毫秒）+ text。"""
    segments: list[dict[str, Any]] = []
    for item in data.get("transcription", []) or []:
        offsets = item.get("offsets") or {}
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        segments.append({
            "start": round(float(offsets.get("from", 0)) / 1000.0, 3),
            "end": round(float(offsets.get("to", 0)) / 1000.0, 3),
            "text": text,
        })
    return segments


def transcribe(
    audio_path: str,
    *,
    binary_path: str,
    model_path: str,
    language: str = "auto",
    timeout: int = 1800,
    threads: int | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    source = Path(audio_path).expanduser()
    binary = Path(binary_path).expanduser()
    model = Path(model_path).expanduser()
    if not source.is_file():
        return {"ok": False, "error_code": "audio_not_found", "message": f"找不到音檔：{source.as_posix()}"}
    if not binary.exists() or not model.exists():
        return {"ok": False, "error_code": "runtime_not_ready", "message": "whisper.cpp 執行檔或模型不存在"}
    import ffmpeg_runtime
    ffmpeg = ffmpeg_runtime.resolve("ffmpeg")
    if not ffmpeg:
        return {"ok": False, "error_code": "ffmpeg_unavailable", "message": "ffmpeg 尚未就緒（請先下載媒體工具）"}

    tmp_root = Path(tempfile.mkdtemp(prefix="yt_note_asr_"))
    wav_path = tmp_root / "input16k.wav"
    output_prefix = tmp_root / "transcript"
    try:
        convert = _run(
            [ffmpeg, "-hide_banner", "-y", "-i", source.as_posix(),
             "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", wav_path.as_posix()],
            timeout=600,
        )
        if convert.returncode != 0 or not wav_path.exists():
            tail = (convert.stderr or convert.stdout or "")[-800:]
            return {"ok": False, "error_code": "ffmpeg_convert_failed", "message": f"音檔轉 wav 失敗：{tail}"}

        command = [binary.as_posix(), "-m", model.as_posix(), "-f", wav_path.as_posix(),
                   "-l", language or "auto", "-oj", "-of", output_prefix.as_posix()]
        if threads:
            command += ["-t", str(threads)]
        if prompt:
            command += ["--prompt", prompt[-220:]]  # init-prompt 給上下文（whisper context 上限保守截尾）
        completed = _run(command, timeout=timeout)
        json_path = output_prefix.with_suffix(".json")
        if completed.returncode != 0 or not json_path.exists():
            tail = (completed.stderr or completed.stdout or f"exit {completed.returncode}")[-800:]
            return {"ok": False, "error_code": "whisper_failed", "message": f"轉錄失敗：{tail}"}

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {"ok": False, "error_code": "whisper_output_unparseable", "message": str(exc)}

        segments = _parse_whisper_json(data)
        detected = str((data.get("result") or {}).get("language") or language or "").strip()
        return {
            "ok": True,
            "language": detected or (language if language != "auto" else ""),
            "segments": segments,
            "text": "\n".join(s["text"] for s in segments).strip(),
            "segment_count": len(segments),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error_code": "timeout", "message": "轉錄逾時"}
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
