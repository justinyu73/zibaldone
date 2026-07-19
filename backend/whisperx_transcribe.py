"""WhisperX transcription — 語音 lane 品質引擎（make_vs_take 規格：VAD切片/word-timestamp ＝ TAKE WhisperX）.

管線：VAD 切片 + faster-whisper 轉錄 + wav2vec2 強制對齊 → 字級精準 timestamp
（餵 quote+timestamp distill 這個 value-add）。比 whisper.cpp 重（torch/faster-
whisper），故 lazy import；runtime 缺則 ok=False，不假裝成功。語者分離（pyannote）
依規格「待驗需求」未接（另需 HF token gate）。回傳契約對齊 whisper_transcribe.transcribe，
另加每段 words[] 與 word_count。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _round(value: Any) -> float | None:
    return round(float(value), 3) if value is not None else None


def transcribe(
    audio_path: str,
    *,
    model_size: str = "medium",
    language: str = "auto",
    device: str = "cpu",
    compute_type: str = "int8",
    batch_size: int = 8,
    align: bool = True,
) -> dict[str, Any]:
    source = Path(audio_path).expanduser()
    if not source.is_file():
        return {"ok": False, "error_code": "audio_not_found", "message": f"找不到音檔：{source.as_posix()}"}
    try:
        import whisperx  # lazy: heavy torch import only when this engine is actually used
    except ImportError as exc:
        return {"ok": False, "error_code": "whisperx_not_installed", "message": f"WhisperX 未安裝：{exc}"}

    requested = None if (not language or language == "auto") else language
    try:
        audio = whisperx.load_audio(source.as_posix())
        model = whisperx.load_model(model_size, device, compute_type=compute_type, language=requested)
        result = model.transcribe(audio, batch_size=batch_size)
        detected = str(result.get("language") or requested or "").strip()
        segments = result.get("segments") or []
        if align and detected:
            try:
                align_model, metadata = whisperx.load_align_model(language_code=detected, device=device)
                aligned = whisperx.align(segments, align_model, metadata, audio, device, return_char_alignments=False)
                segments = aligned.get("segments") or segments
            except (ValueError, KeyError):
                pass  # no align model for this language → keep transcript without word timestamps
    except Exception as exc:  # noqa: BLE001 — surface any pipeline failure, never fake success
        return {"ok": False, "error_code": "whisperx_failed", "message": str(exc)}

    out_segments: list[dict[str, Any]] = []
    words_total = 0
    for seg in segments:
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        words = [
            {"word": w_text, "start": _round(w.get("start")), "end": _round(w.get("end"))}
            for w in (seg.get("words") or [])
            if (w_text := str(w.get("word") or "").strip())
        ]
        words_total += len(words)
        out_segments.append({
            "start": _round(seg.get("start")) or 0.0,
            "end": _round(seg.get("end")) or 0.0,
            "text": text,
            "words": words,
        })
    return {
        "ok": True,
        "language": detected,
        "segments": out_segments,
        "text": "\n".join(s["text"] for s in out_segments).strip(),
        "segment_count": len(out_segments),
        "word_count": words_total,
        "aligned": words_total > 0,
    }
