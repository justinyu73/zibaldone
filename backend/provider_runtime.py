"""Provider runtime helpers for approved YT ASR/OCR execution."""
from __future__ import annotations

import base64
import binascii
import os
from typing import Any, Dict, List

from model_policy import load_model_policy, model_for_task
from runtime_usage import usage_from_response


MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_ASR_TASKS = {"asr", "asr_bulk", "asr_diarize"}
ALLOWED_AUDIO_MIME = {
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/wav",
    "audio/webm",
    "audio/ogg",
    "application/ogg",
    "video/mp4",
    "video/webm",
}
ALLOWED_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp"}


class ProviderRuntimeError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _task_config(task: str) -> Dict[str, Any]:
    policy = load_model_policy()
    config = policy.get("tasks", {}).get(task, {})
    return config if isinstance(config, dict) else {}


def runtime_status() -> Dict[str, Any]:
    policy = load_model_policy()
    tasks = policy.get("tasks", {}) if isinstance(policy.get("tasks"), dict) else {}
    return {
        "ok": True,
        "provider": policy.get("provider", "openai"),
        "runtime_boundary": policy.get("runtime_boundary", {}),
        "openai_api_key_present": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "enabled_runtime_tasks": sorted(
            task
            for task, config in tasks.items()
            if task in {"asr", "asr_bulk", "asr_diarize", "ocr_visual"} and isinstance(config, dict) and config.get("enabled") is True
        ),
        "blocked_scope": ["platform_media_download", "durable_source_note_write", "background_scheduler"],
    }


def decode_media(media_base64: str, max_bytes: int) -> bytes:
    raw = str(media_base64 or "").strip()
    if "," in raw and raw.lower().startswith("data:"):
        raw = raw.split(",", 1)[1]
    if not raw:
        raise ProviderRuntimeError(400, "media_base64 is required")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProviderRuntimeError(400, "media_base64 must be valid base64") from exc
    if not data:
        raise ProviderRuntimeError(400, "decoded media is empty")
    if len(data) > max_bytes:
        raise ProviderRuntimeError(413, f"media exceeds limit of {max_bytes} bytes")
    return data


def _require_real_runtime(task: str) -> str:
    config = _task_config(task)
    if config.get("enabled") is not True:
        raise ProviderRuntimeError(403, f"{task} provider runtime is not enabled in enabled_models.json")
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ProviderRuntimeError(400, "OPENAI_API_KEY is not configured")
    return api_key


def _dry_run_report(kind: str, task: str, model: str, filename: str, mime: str, byte_count: int) -> Dict[str, Any]:
    return {
        "ok": True,
        "status": "ready_for_real_provider_call",
        "execution_mode": "dry_run",
        "lane": kind,
        "task": task,
        "provider": "openai",
        "model": model,
        "input": {
            "filename": filename,
            "mime": mime,
            "bytes": byte_count,
            "surface": "operator_supplied_media_base64",
        },
        "provider_call_count": 0,
        "credential_reads": 0,
        "durable_writes": 0,
        "blocked_scope": ["platform_media_download", "durable_source_note_write"],
        "next_actions": ["set mode=real to call provider", "review report before durable writeback"],
    }


def _segment_dict(segment: Any, index: int) -> Dict[str, Any]:
    if isinstance(segment, dict):
        data = segment
    elif hasattr(segment, "model_dump"):
        data = segment.model_dump()
    else:
        data = {
            "start": getattr(segment, "start", None),
            "end": getattr(segment, "end", None),
            "text": getattr(segment, "text", ""),
        }
    return {
        "start": data.get("start"),
        "end": data.get("end"),
        "text": str(data.get("text") or "").strip(),
        "sources": ["asr"],
        "confidence": data.get("avg_logprob"),
        "warnings": [],
        "evidence_ref": f"provider:openai:asr:{index + 1}",
    }


def _transcription_segments(response: Any) -> List[Dict[str, Any]]:
    segments = getattr(response, "segments", None)
    if segments is None and isinstance(response, dict):
        segments = response.get("segments")
    if segments:
        return [_segment_dict(segment, index) for index, segment in enumerate(segments)]
    text = str(getattr(response, "text", "") or (response.get("text") if isinstance(response, dict) else "") or "").strip()
    return [
        {
            "start": None,
            "end": None,
            "text": text,
            "sources": ["asr"],
            "confidence": None,
            "warnings": ["no_segment_timestamps_returned"],
            "evidence_ref": "provider:openai:asr:1",
        }
    ] if text else []


def transcribe_audio(
    *,
    filename: str,
    media_base64: str,
    media_mime: str,
    task: str = "asr",
    mode: str = "dry_run",
    language: str = "",
    prompt: str = "",
) -> Dict[str, Any]:
    task = task if task in ALLOWED_ASR_TASKS else "asr"
    mime = media_mime or "audio/mpeg"
    if mime not in ALLOWED_AUDIO_MIME:
        raise ProviderRuntimeError(400, f"unsupported audio mime: {mime}")
    data = decode_media(media_base64, MAX_AUDIO_BYTES)
    model = model_for_task(task, "whisper-1")
    if mode != "real":
        return _dry_run_report("asr", task, model, filename, mime, len(data))

    api_key = _require_real_runtime(task)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ProviderRuntimeError(500, "Missing openai package. Run pip install -r requirements.txt.") from exc

    client = OpenAI(api_key=api_key, timeout=180.0)
    # whisper-1 才支援 verbose_json（含 segment 時間戳＝quote+timestamp distill 需要）；
    # gpt-4o-transcribe 等只支援 json（無 segments）→ 退回 json，時間戳由 _timestamped_transcript 略過不杜撰。
    response_format = "verbose_json" if str(model).startswith("whisper") else "json"
    options: Dict[str, Any] = {
        "file": (filename or "audio.bin", data, mime),
        "model": model,
        "response_format": response_format,
    }
    # whisper-1 verbose_json：顯式要 segment 級時間戳，否則某些情況只回單一整段
    # （高品質 tier 摘要全 [00:00] 的源頭）＝quote+timestamp distill 失效。
    if response_format == "verbose_json":
        options["timestamp_granularities"] = ["segment"]
    if language.strip():
        options["language"] = language.strip()
    if prompt.strip():
        options["prompt"] = prompt.strip()[:1200]
    try:
        response = client.audio.transcriptions.create(**options)
    except Exception as exc:
        raise ProviderRuntimeError(502, f"OpenAI ASR failed: {exc}") from exc

    segments = _transcription_segments(response)
    return {
        "ok": True,
        "status": "provider_completed",
        "execution_mode": "real",
        "lane": "asr",
        "task": task,
        "provider": "openai",
        "model": model,
        "segments": segments,
        "text": "\n".join(segment["text"] for segment in segments if segment["text"]),
        "provider_call_count": 1,
        "usage": usage_from_response(response),
        "credential_reads": 1,
        "durable_writes": 0,
        "write_mode": "report_only",
    }


def _response_text(response: Any) -> str:
    text = getattr(response, "output_text", "")
    if text:
        return str(text).strip()
    output = getattr(response, "output", None)
    return str(output or "").strip()


def analyze_frame(
    *,
    filename: str,
    image_base64: str,
    image_mime: str,
    mode: str = "dry_run",
    prompt: str = "",
) -> Dict[str, Any]:
    mime = image_mime or "image/png"
    if mime not in ALLOWED_IMAGE_MIME:
        raise ProviderRuntimeError(400, f"unsupported image mime: {mime}")
    data = decode_media(image_base64, MAX_IMAGE_BYTES)
    model = model_for_task("ocr_visual", "gpt-5.2")
    if mode != "real":
        return _dry_run_report("ocr_visual", "ocr_visual", model, filename, mime, len(data))

    api_key = _require_real_runtime("ocr_visual")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ProviderRuntimeError(500, "Missing openai package. Run pip install -r requirements.txt.") from exc

    client = OpenAI(api_key=api_key, timeout=180.0)
    instruction = (
        prompt.strip()
        or "Extract visible hard subtitles, screen text, products, people, brands, and concise visual context. Return compact JSON."
    )
    data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": instruction[:1600]},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
        )
    except Exception as exc:
        raise ProviderRuntimeError(502, f"OpenAI OCR/visual failed: {exc}") from exc

    text = _response_text(response)
    return {
        "ok": True,
        "status": "provider_completed",
        "execution_mode": "real",
        "lane": "ocr_visual",
        "task": "ocr_visual",
        "provider": "openai",
        "model": model,
        "segments": [
            {
                "start": None,
                "end": None,
                "text": text,
                "sources": ["ocr", "visual"],
                "confidence": None,
                "warnings": ["provider_visual_json_requires_review"],
                "evidence_ref": "provider:openai:ocr_visual:1",
            }
        ] if text else [],
        "provider_call_count": 1,
        "usage": usage_from_response(response),
        "credential_reads": 1,
        "durable_writes": 0,
        "write_mode": "report_only",
    }
